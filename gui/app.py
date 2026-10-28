"""Local camera viewer and threshold-gated relative wavefront display."""
import atexit
import argparse
import io
import sys
import json
from pathlib import Path
import threading
import signal
import time
import numpy as np
from PIL import Image
from flask import Flask, jsonify, request, Response
from native_bridge import CameraBridge
from analysis import analyze, make_reference, detect_spots
from factory_reference import reference_from_factory
from factory_memory import decode as decode_factory

ROOT = Path(__file__).resolve().parents[1]
app = Flask(__name__, static_folder='static', static_url_path='')
bridge = CameraBridge(ROOT)
lock = threading.RLock()
config = dict(threshold_dn=20, min_spots=20, focal_mm=None, remove_tilt=True, tilt_limit_urad=100., exposure_ms=10., gain=0)
reference = None
factory_profile = None
factory_error = None
try:
    factory_profile=decode_factory((ROOT/'runtime/factory_memory.bin').read_bytes())
    if len(factory_profile['arrays'])==1:
        config['focal_mm']=factory_profile['arrays'][0]['focal_mm']
except FileNotFoundError:
    pass
except ValueError as error:
    factory_error=str(error)
state = dict(visible=False, reason='Starting camera', wavefront=None)
frame = None
metadata = {}
preview = b''
revision = 0
offline_capture = None
app.config['MAX_CONTENT_LENGTH'] = 32*1024*1024


def process():
    global state, frame, metadata, preview, factory_profile, factory_error, revision
    previous = None
    while True:
        with lock:
            capture = offline_capture if offline_capture is not None else bridge.read()
            if offline_capture is None and capture and capture[0].get('factory_calibration'):
                incoming=capture[0]['factory_calibration']
                if factory_profile is None or incoming['sha256']!=factory_profile['sha256']:
                    factory_profile=incoming;factory_error=None
                    if len(incoming['arrays'])==1:config['focal_mm']=incoming['arrays'][0]['focal_mm']
                    revision+=1
            settings, ref, version = dict(config), reference, revision
        if capture:
            meta, pixels = capture
            key = (meta['time'], version)
            if key != previous:
                try:
                    image = np.frombuffer(pixels, np.uint8).reshape(meta['height'], meta['width']).copy()
                    active_ref=ref
                    if active_ref is None and factory_profile is not None and not meta.get('diagnostic',False):
                        spots=detect_spots(image,settings['threshold_dn'])
                        if len(spots.xy)>=settings['min_spots'] and spots.saturated_fraction<=.02:
                            try:active_ref=reference_from_factory(spots,image.shape,factory_profile)
                            except ValueError as error:
                                result,_=analyze(image,settings)
                                result['reason']=str(error)
                            else:result,_=analyze(image,settings,active_ref)
                        else:result,_=analyze(image,settings)
                    else:result,_=analyze(image, settings, active_ref, meta.get('diagnostic', False))
                    result['reference_kind']=active_ref.get('kind') if active_ref else None
                    buf = io.BytesIO()
                    thumbnail = Image.fromarray(image)
                    thumbnail.thumbnail((1024,1024))
                    thumbnail.save(buf, format='PNG')
                    with lock:
                        if version == revision:
                            frame, metadata, state, preview = image, meta, result, buf.getvalue()
                    previous = key
                except Exception as error:
                    with lock:
                        state = dict(visible=False, reason=str(error), wavefront=None)
        time.sleep(.15)


@app.get('/')
def index():
    return app.send_static_file('index.html')


@app.get('/api/state')
def status():
    with lock:
        offline = offline_capture is not None
        fresh = bool(metadata) and ((offline and metadata.get('time')==offline_capture[0]['time']) or (not offline and time.time() - metadata.get('time', 0) < 3 and not bridge.stopping.is_set()))
        result = dict(state) if fresh else dict(visible=False, wavefront=None, reason=bridge.message)
        return jsonify(analysis=result, camera=metadata, fresh=fresh, stage='offline' if offline else bridge.stage,
                       message='Saved image · offline' if offline else bridge.message, config=config, reference=reference is not None, backend=bridge.backend, factory_calibration=factory_profile, factory_error=factory_error)


@app.get('/api/frame')
def get_frame():
    with lock:
        return Response(preview, mimetype='image/png', headers={'Cache-Control':'no-store'}) if preview else ('',204)


@app.post('/api/config')
def configure():
    global revision, state
    data = request.get_json() or {}
    try:
        changed = {}
        for key, lo, hi in [('tilt_limit_urad',0,1000000),('threshold_dn',1,250),('min_spots',8,1000),('exposure_ms',.1,150),('gain',0,100),('focal_mm',.05,1000)]:
            if key in data:
                if key == 'focal_mm' and data[key] in ('',None):
                    changed[key] = None
                else:
                    value = float(data[key])
                    if not np.isfinite(value) or not lo <= value <= hi:
                        raise ValueError(f'{key} must be between {lo} and {hi}')
                    changed[key] = int(value) if key in ('min_spots','gain') else value
        if 'remove_tilt' in data:
            changed['remove_tilt'] = bool(data['remove_tilt'])
        with lock:
            bridge.controls(changed.get('exposure_ms',config['exposure_ms']),changed.get('gain',config['gain']))
            config.update(changed)
            revision += 1
            state = dict(visible=False,reason='Updating settings',wavefront=None)
            bridge.controls(config['exposure_ms'],config['gain'])
        return jsonify(ok=True)
    except (ValueError,TypeError) as error:
        return jsonify(error=str(error)),400


@app.post('/api/reference')
def set_reference():
    global reference, revision, state
    with lock:
        if offline_capture is not None and metadata.get('time')!=offline_capture[0]['time']:
            return jsonify(error='Wait for saved image analysis'),400
        if frame is None or (offline_capture is None and (bridge.stopping.is_set() or time.time()-metadata.get('time',0)>3)):
            return jsonify(error='Wait for a live image'),400
        result, spots = analyze(frame,config)
        if len(spots.xy)<config['min_spots'] or spots.saturated_fraction>.02 or metadata.get('diagnostic'):
            return jsonify(error='Reference requires an illuminated, unsaturated spot field above threshold'),400
        try:
            reference = make_reference(spots,frame.shape,metadata['pixel_um'])
        except ValueError as error:
            return jsonify(error=str(error)),400
        (ROOT/'runtime/reference.json').write_text(json.dumps(reference))
        revision += 1
        state = dict(visible=False,reason='Updating reference',wavefront=None)
    return jsonify(ok=True)


@app.post('/api/image')
def saved_image():
    global offline_capture, revision, state
    upload=request.files.get('image')
    if not upload:return jsonify(error='Choose a monochrome PNG or PGM image'),400
    try:
        with Image.open(upload.stream) as image:
            if image.format not in ('PNG','PPM') or image.mode!='L':
                raise ValueError('Use a raw 8-bit monochrome PNG or PGM')
            width,height=image.size
            if min(width,height)<16 or max(width,height)>4096:
                raise ValueError('Image dimensions must be between 16 and 4096 pixels')
            pixels=image.tobytes()
        bridge.stop()
        with lock:
            offline_capture=(dict(time=time.time(),width=width,height=height,pixel_um=5.5,
                                  source='saved image',filename=Path(upload.filename or 'image').name,
                                  diagnostic=False),pixels)
            revision+=1
            state=dict(visible=False,reason='Analyzing saved image',wavefront=None)
        return jsonify(ok=True)
    except (OSError,ValueError) as error:return jsonify(error=str(error)),400


@app.post('/api/camera/<action>')
def camera(action):
    global offline_capture, revision, state
    with lock:
        offline_capture=None
        revision+=1
        state=dict(visible=False,reason='Changing source',wavefront=None)
    if action=='start':
        bridge.start()
    elif action=='stop':
        bridge.stop()
    else:
        return jsonify(error='Unknown action'),400
    return jsonify(ok=True)


if __name__=='__main__':
    bridge.controls(config['exposure_ms'],config['gain'])
    parser=argparse.ArgumentParser()
    parser.add_argument('--offline',action='store_true',help='Start without opening the USB camera')
    args=parser.parse_args()
    if args.offline:
        bridge.message='Load a saved image';bridge.stage='stopped'
    else:
        bridge.start()
    def shutdown():
        bridge.stop()
        if bridge.thread:
            bridge.thread.join(timeout=12)
    atexit.register(shutdown)
    signal.signal(signal.SIGTERM,lambda *_: sys.exit(0))
    threading.Thread(target=process,daemon=True).start()
    app.run(host='127.0.0.1',port=8864,threaded=True,use_reloader=False)
