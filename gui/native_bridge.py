"""Native macOS camera worker; publishes the same atomic frames as the viewer."""
import json
import os
from pathlib import Path
import sys
import threading
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'native'))
from camera import Camera
from controls import validate as validate_controls

class CameraBridge:
    backend='macos-libusb'
    def __init__(self,root):
        self.root=Path(root);self.live=self.root/'runtime/live';self.live.mkdir(parents=True,exist_ok=True)
        self.stopping=threading.Event();self.thread=None;self.stage='stopped';self.message='Camera stopped'
        self.exposure_ms=10.;self.gain=0
        self.control_lock=threading.Lock();self.control_error=None
    def start(self):
        if self.thread and self.thread.is_alive():return
        self.stopping.clear()
        (self.live/'frame.bin').unlink(missing_ok=True)
        self.thread=threading.Thread(target=self._run,daemon=True);self.thread.start()
    def controls(self,exposure_ms,gain):
        exposure_ms,gain=validate_controls(exposure_ms,gain)
        with self.control_lock:
            self.exposure_ms,self.gain=exposure_ms,gain
            self.control_error=None
    def _apply_controls(self,camera):
        with self.control_lock:exposure,gain=self.exposure_ms,self.gain
        camera.set_controls(exposure,gain)
    def _progress(self,message):self.message=message
    def _run(self):
        camera=None
        try:
            self.stage='starting';self.message='Starting native camera'
            camera=Camera(progress=self._progress,stop=self.stopping)
            camera.initialize()
            self.stage='streaming';self.message='Camera online · native macOS'
            while not self.stopping.is_set():
                self._apply_controls(camera)
                start=time.monotonic()
                meta,pixels=camera.capture()
                meta["capture_seconds"]=time.monotonic()-start
                header=json.dumps(meta).encode()+b'\n'
                temporary=self.live/'frame.tmp'
                temporary.write_bytes(header+pixels)
                os.replace(temporary,self.live/'frame.bin')
                interval=0 if (self.live/'benchmark.json').exists() else .5
                self.stopping.wait(max(0,interval-(time.monotonic()-start)))
        except Exception as error:
            if not self.stopping.is_set():
                self.control_error=str(error);self.stage='error';self.message=str(error)
        finally:
            if camera:camera.close()
            if self.stopping.is_set():self.stage='stopped';self.message='Camera stopped'
    def stop(self):
        self.stopping.set();self.stage='stopping';self.message='Stopping camera'
    def read(self):
        try:
            with (self.live/'frame.bin').open('rb') as stream:
                meta=json.loads(stream.readline());pixels=stream.read()
            if time.time()-meta['time']>3 or self.stopping.is_set():return None
            return meta,pixels
        except (OSError,ValueError,KeyError):return None
