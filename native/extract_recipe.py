"""Extract this instrument's observed, volatile startup/capture exchanges.
Firmware bytes stay local to the instrument's workspace; not a distributable SDK.
"""
import gzip,json,hashlib
from pathlib import Path
from trace import records
root=Path(__file__).parent
rows=list(records(root/'usb_trace_initial.bin'))
sends={r['seq']:r for r in rows if r['event']==0}
def packet(seq):return sends[seq]['data'].hex()
recipe={'trace_sha256':hashlib.sha256((root/'usb_trace_initial.bin').read_bytes()).hexdigest(),
        'usb_id':'1409:3370','serial':'4110057336','width':2048,'height':2048,'pixel_um':5.5,
        'boot':[packet(n) for n in range(14,146)],
        'initialize':[r['data'].hex() for r in rows if r['event']==0 and r['ep']==1 and 159<=r['seq']<=6400],
        'capture':[packet(n) for n in (6426,6428,6430,6433,6435,6437,6439,6441)],
        'end_capture':packet(6453)}
responses={}
for r in rows:
    if r['event']==1 and r['ep']==0x81 and len(r['data'])>=8:
        status,code,token,length=__import__('struct').unpack_from('<4H',r['data'])
        responses.setdefault((code,token),status)
recipe['initialize_status']=[responses[(__import__('struct').unpack_from('<H',bytes.fromhex(p),10)[0],__import__('struct').unpack_from('<H',bytes.fromhex(p),12)[0])] for p in recipe['initialize']]
with gzip.open(root/'recipe.json.gz','wt') as f:json.dump(recipe,f)
print('Expected optional probe errors',[(i,hex(s)) for i,s in enumerate(recipe['initialize_status']) if s])
print('Boot controls',len(recipe['boot']),'init commands',len(recipe['initialize']))
