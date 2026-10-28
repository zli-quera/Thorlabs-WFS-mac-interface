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
from collections import deque
import numpy as np
from PIL import Image
from flask import Flask, jsonify, request, Response
from native_bridge import CameraBridge
from libusb_loader import platform_label
from analysis import analyze, make_reference, detect_spots
from factory_reference import reference_from_factory
from factory_memory import decode as decode_factory
from simulation import Simulator, DEFAULTS, LIMITS, FPS
from preview import camera_preview

ROOT = Path(__file__).resolve().parents[1]
app = Flask(__name__, static_folder='static', static_url_path='')
bridge = CameraBridge(ROOT)
lock = threading.RLock()
config = dict(threshold_dn=20, min_spots=20, focal_mm=None, remove_tilt=True, tilt_limit_urad=500., exposure_ms=10., gain=0)
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
simulator = None
simulation_parameters = dict(DEFAULTS)
simulation_rate = 0.
analysis_rate = 0.
app.config['MAX_CONTENT_LENGTH'] = 32*1024*1024


def process():
    global state, frame, metadata, preview, factory_profile, factory_error, revision, simulation_rate, analysis_rate
    previous = None
    next_frame=time.monotonic()
    last_processed=None
    analysis_times=deque(maxlen=30)
    rate_source=None
    while True:
        started=time.monotonic()
        with lock:
            sim=simulator
            parameters=dict(simulation_parameters)
            capture = None if sim else offline_capture if offline_capture is not None else bridge.read()
            if offline_capture is None and capture and capture[0].get('factory_calibration'):
                incoming=capture[0]['factory_calibration']
                if factory_profile is None or incoming['sha256']!=factory_profile['sha256']:
                    factory_profile=incoming;factory_error=None
                    if len(incoming['arrays'])==1:config['focal_mm']=incoming['arrays'][0]['focal_mm']
                    revision+=1
            settings, ref, version = dict(config), None if sim else reference, revision
        if sim:
            try:capture=sim.capture(parameters)
            except Exception as error:
                with lock:state=dict(visible=False,reason=str(error),wavefront=None)
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
                                result,_=analyze(image,settings,spots=spots)
                                result['reason']=str(error)
                            else:result,_=analyze(image,settings,active_ref,spots=spots)
                        else:result,_=analyze(image,settings,spots=spots)
                    else:result,_=analyze(image, settings, active_ref, meta.get('diagnostic', False))
                    result['reference_kind']=active_ref.get('kind') if active_ref else None
                    rendered_preview=camera_preview(image)
                    with lock:
                        if version == revision:
                            frame, metadata, state, preview = image, meta, result, rendered_preview
                    now=time.monotonic()
                    source=meta.get('source','native')
                    if source!=rate_source:
                        analysis_times.clear();rate_source=source
                    if last_processed is not None and now-last_processed>3:analysis_times.clear()
                    analysis_times.append(now)
                    analysis_rate=((len(analysis_times)-1)/(now-analysis_times[0]) if len(analysis_times)>1 else 0.)
                    if sim and last_processed is not None:
                        simulation_rate=.9*simulation_rate+.1/(now-last_processed) if simulation_rate else 1/(now-last_processed)
                    last_processed=now
                    previous = key
                except Exception as error:
                    with lock:
                        state = dict(visible=False, reason=str(error), wavefront=None)
        if sim:
            next_frame=max(next_frame+1/FPS,started)
            time.sleep(max(0,next_frame-time.monotonic()))
        else:
            next_frame=time.monotonic()
            time.sleep(.02)


@app.get('/')
def index():
    return app.send_static_file('index.html')


@app.get('/api/state')
def status():
    with lock:
        offline = offline_capture is not None
        testing=simulator is not None
        fresh = bool(metadata) and ((offline and metadata.get('time')==offline_capture[0]['time']) or (not offline and time.time() - metadata.get('time', 0) < 3 and (testing or not bridge.stopping.is_set())))
        result = dict(state) if fresh else dict(visible=False, wavefront=None, reason=bridge.message)
        return jsonify(analysis=result, camera=metadata, analysis_fps=analysis_rate if fresh and not offline else 0., camera_fps=(simulation_rate if testing else metadata.get('camera_fps',0.)) if fresh and not offline else 0., fresh=fresh, stage='simulation' if testing else 'offline' if offline else bridge.stage,
                       message='Test mode · 14 FPS target' if testing else 'Saved image · offline' if offline else bridge.message, simulation=dict(enabled=testing,parameters=simulation_parameters,target_fps=FPS,analysis_fps=simulation_rate), config=config, reference=reference is not None, backend=bridge.backend, factory_calibration=factory_profile, factory_error=factory_error, platform_label=platform_label(), controls_supported=True, control_error=bridge.control_error)


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
        for key, lo, hi in [('tilt_limit_urad',0,1000000),('threshold_dn',1,250),('min_spots',8,1000),('exposure_ms',.04,150),('gain',0,100),('focal_mm',.05,1000)]:
            if key in data:
                if key == 'focal_mm' and data[key] in ('',None):
                    changed[key] = None
                else:
                    value = float(data[key])
                    if not np.isfinite(value) or not lo <= value <= hi or (key=='gain' and value!=int(value)):
                        raise ValueError(f'{key} must be between {lo} and {hi}')
                    changed[key] = int(value) if key in ('min_spots','gain') else value
        if 'remove_tilt' in data:
            changed['remove_tilt'] = bool(data['remove_tilt'])
        with lock:
            bridge.controls(changed.get('exposure_ms',config['exposure_ms']),changed.get('gain',config['gain']))
            config.update(changed)
            revision += 1
            state = dict(visible=False,reason='Updating settings',wavefront=None)
        return jsonify(ok=True)
    except (ValueError,TypeError) as error:
        return jsonify(error=str(error)),400


@app.post('/api/reference')
def set_reference():
    global reference, revision, state
    with lock:
        if offline_capture is not None and metadata.get('time')!=offline_capture[0]['time']:
            return jsonify(error='Wait for saved image analysis'),400
        if simulator is not None:return jsonify(error='Test mode always uses the factory reference'),400
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
    global offline_capture, revision, state, simulator
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
            simulator=None
            offline_capture=(dict(time=time.time(),width=width,height=height,pixel_um=5.5,
                                  source='saved image',filename=Path(upload.filename or 'image').name,
                                  diagnostic=False),pixels)
            revision+=1
            state=dict(visible=False,reason='Analyzing saved image',wavefront=None)
        return jsonify(ok=True)
    except (OSError,ValueError) as error:return jsonify(error=str(error)),400


@app.post('/api/simulation')
def testing_mode():
    global simulator, offline_capture, revision, state, simulation_rate
    data=request.get_json() or {}
    try:
        changed={}
        for name,(lo,hi) in LIMITS.items():
            if name in data:
                value=float(data[name])
                if not np.isfinite(value) or not lo<=value<=hi:raise ValueError(f'{name} must be between {lo} and {hi}')
                changed[name]=value
        if data.get('enabled') and factory_profile is None:raise ValueError('Read factory calibration before starting test mode')
        if data.get('enabled'):bridge.stop()
        with lock:
            if data.get('reset'):simulation_parameters.update(DEFAULTS)
            simulation_parameters.update(changed)
            if data.get('enabled') and simulator is None:
                simulator=Simulator(factory_profile)
                config['focal_mm']=factory_profile['arrays'][0]['focal_mm']
                simulation_rate=0.
                offline_capture=None
            elif data.get('enabled') is False:
                simulator=None
            revision+=1
            state=dict(visible=False,reason='Updating test scene',wavefront=None)
        return jsonify(ok=True)
    except (ValueError,TypeError) as error:return jsonify(error=str(error)),400


@app.post('/api/camera/<action>')
def camera(action):
    global offline_capture, revision, state, simulator
    with lock:
        offline_capture=None
        simulator=None
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
