"""Read bounded USB request/completion records from the macOS capture tracer."""
import struct
from pathlib import Path

def records(path):
    with Path(path).open('rb') as stream:
        while True:
            header=stream.read(32)
            if len(header)<32:return
            magic,event,seq,ep,kind,status,length,size=struct.unpack('<8I',header)
            timestamp=None
            if magic==0x32534657:
                extra=stream.read(8)
                if len(extra)<8:return
                timestamp=struct.unpack('<Q',extra)[0]/1e9
            elif magic!=0x31534657: raise ValueError('Bad trace header')
            data=stream.read(size)
            if len(data)!=size:return
            yield dict(time=timestamp,event=event,seq=seq,ep=ep,kind=kind,status=status,length=length,data=data)

if __name__=='__main__':
    import sys
    from collections import Counter
    rows=list(records(sys.argv[1]));print('Records',len(rows))
    print(Counter((r['event'],hex(r['ep']),r['kind'],r['status'],r['length'],len(r['data'])) for r in rows).most_common(20))
    for r in rows:
        if r['event']==0 and r['ep'] in (0,1):
            print('SEND',r['seq'],hex(r['ep']),r['length'],r['data'][:80].hex())
        elif r['event'] and r['data']:
            print('RECV',r['seq'],hex(r['ep']),r['length'],len(r['data']),r['status'],r['data'][:80].hex())
