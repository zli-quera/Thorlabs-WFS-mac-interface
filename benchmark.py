"""Compare existing native and QEMU backends on one physical sensor.
Uses full-resolution frame publication, not browser or wavefront analysis timing.
"""
import argparse
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time
import urllib.request

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'gui'))
from native_bridge import CameraBridge as NativeBridge
from bridge import CameraBridge as VMBridge


def api(action):
    req=urllib.request.Request('http://127.0.0.1:8864/api/camera/'+action,data=b'{}',headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=5) as response:return json.load(response)


def cpu_seconds(text):
    parts=text.strip().split(':')
    return sum(float(v)*60**i for i,v in enumerate(reversed(parts)))


def resources(bridge):
    pids=[__import__('os').getpid()]
    if getattr(bridge,'process',None) and bridge.process.poll() is None:pids.append(bridge.process.pid)
    cpu=0.;rss=0
    for pid in pids:
        result=subprocess.run(['ps','-p',str(pid),'-o','time=','-o','rss='],text=True,capture_output=True)
        if result.returncode:continue
        parts=result.stdout.split()
        cpu+=cpu_seconds(parts[0]);rss+=int(parts[1])*1024
    return dict(cpu_seconds=cpu,rss_bytes=rss)


def run_backend(name,frames):
    cls=NativeBridge if name=='native' else VMBridge
    bridge=cls(ROOT);bridge.controls(10,0)
    config=ROOT/'runtime/live/benchmark.json'
    config.write_text(json.dumps({'frames':frames+4}))
    before=time.perf_counter();bridge.start();last=None;samples=[];first=None;resource_start=None;rss=[]
    try:
        deadline=before+180
        while time.perf_counter()<deadline:
            if bridge.stage=='error':raise RuntimeError(bridge.message)
            capture=bridge.read()
            if capture:
                meta,pixels=capture
                key=meta['time']
                if key!=last:
                    last=key
                    if len(pixels)!=2048*2048:raise RuntimeError('Incomplete benchmark frame')
                    now=time.perf_counter()
                    if first is None:
                        first=now
                        print(name,'first frame',round(first-before,3),'s',flush=True)
                    samples.append(dict(observed=now,metadata=meta))
                    if len(samples)==4:
                        resource_start=resources(bridge);measurement_start=now
                    if len(samples)>4:rss.append(resources(bridge)['rss_bytes'])
                    if len(samples)>=frames+4:break
            if bridge.thread and not bridge.thread.is_alive() and not bridge.stopping.is_set():
                raise RuntimeError(bridge.message)
            time.sleep(.005)
        else:raise RuntimeError(f'{name} benchmark timed out: {bridge.message}')
        ending=resources(bridge);elapsed=samples[-1]['observed']-measurement_start
        measured=samples[4:]
        latencies=[s['metadata']['capture_seconds'] for s in measured]
        result=dict(backend=name,startup_seconds=first-before,frames=len(measured),elapsed_seconds=elapsed,
                    delivered_fps=len(measured)/elapsed,capture_median_ms=statistics.median(latencies)*1000,
                    capture_p95_ms=sorted(latencies)[max(0,__import__('math').ceil(.95*len(latencies))-1)]*1000,
                    cpu_percent_one_core=(ending['cpu_seconds']-resource_start['cpu_seconds'])/elapsed*100,
                    resident_mib=statistics.median(rss)/1024**2,
                    samples=measured)
        print(json.dumps({k:v for k,v in result.items() if k!='samples'}),flush=True)
        return result
    finally:
        bridge.stop()
        if bridge.thread:bridge.thread.join(timeout=35)
        config.unlink(missing_ok=True)
        if bridge.thread and bridge.thread.is_alive():raise RuntimeError('Backend did not release sensor')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--frames',type=int,default=30);parser.add_argument('--backends',nargs='+',default=['native','vm']);args=parser.parse_args()
    output=ROOT/'diagnostics/speed_comparison.json'
    results=[]
    api('stop');time.sleep(1)
    try:
        for name in args.backends:
            results.append(run_backend(name,args.frames))
            output.write_text(json.dumps(dict(settings={'width':2048,'height':2048,'bits':8,'exposure_ms':10,'gain_percent':0,'gui_throttle_disabled':True,'warmup_frames':4,'analysis_included':False,'cpu_unit':'100% is one CPU core','rss_scope':'benchmark host plus QEMU when present'},results=results),indent=2)+'\n')
    finally:
        api('start')
        recovery_deadline=time.monotonic()+45
        while time.monotonic()<recovery_deadline:
            with urllib.request.urlopen('http://127.0.0.1:8864/api/state',timeout=5) as response:
                restored=json.load(response)
            if restored.get('fresh'):
                print('Native viewer restored',flush=True)
                break
            if restored.get('stage')=='error':
                print('Viewer recovery needs USB reconnect: '+restored['message'],flush=True)
                break
            time.sleep(.5)
        else:print('Viewer did not become ready within 45 seconds',flush=True)
