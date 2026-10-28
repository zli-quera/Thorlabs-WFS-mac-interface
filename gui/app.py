"""Local camera viewer and threshold-gated relative wavefront display."""
import atexit
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
from analysis import analyze, make_reference

ROOT = Path(__file__).resolve().parents[1]
app = Flask(__name__, static_folder='static', static_url_path='')
bridge = CameraBridge(ROOT)
lock = threading.RLock()
config = dict(threshold_dn=20, min_spots=20, focal_mm=None, remove_tilt=True, exposure_ms=10., gain=0)
reference = None
state = dict(visible=False, reason='Starting camera', wavefront=None)
frame = None
metadata = {}
preview = b''
revision = 0


def process():
    global state, frame, metadata, preview
    previous = None
    while True:
        capture = bridge.read()
        if capture:
            meta, pixels = capture
            with lock:
                settings, ref, version = dict(config), reference, revision
            key = (meta['time'], version)
            if key != previous:
                try:
                    image = np.frombuffer(pixels, np.uint8).reshape(meta['height'], meta['width']).copy()
                    result, _ = analyze(image, settings, ref, meta.get('diagnostic', False))
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
        fresh = bool(metadata) and time.time() - metadata.get('time', 0) < 3 and not bridge.stopping.is_set()
        result = dict(state) if fresh else dict(visible=False, wavefront=None, reason=bridge.message)
        return jsonify(analysis=result, camera=metadata, fresh=fresh, stage=bridge.stage,
                       message=bridge.message, config=config, reference=reference is not None, backend=bridge.backend)


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
        for key, lo, hi in [('threshold_dn',1,250),('min_spots',8,1000),('exposure_ms',.1,150),('gain',0,100),('focal_mm',.05,1000)]:
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
        if frame is None or time.time()-metadata.get('time',0)>3:
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


@app.post('/api/camera/<action>')
def camera(action):
    if action=='start':
        bridge.start()
    elif action=='stop':
        bridge.stop()
    else:
        return jsonify(error='Unknown action'),400
    return jsonify(ok=True)


if __name__=='__main__':
    bridge.controls(config['exposure_ms'],config['gain'])
    bridge.start()
    def shutdown():
        bridge.stop()
        if bridge.thread:
            bridge.thread.join(timeout=12)
    atexit.register(shutdown)
    signal.signal(signal.SIGTERM,lambda *_: sys.exit(0))
    threading.Thread(target=process,daemon=True).start()
    app.run(host='127.0.0.1',port=8864,threaded=True,use_reloader=False)
