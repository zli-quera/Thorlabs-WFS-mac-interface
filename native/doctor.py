"""Read-only host readiness report. USB listing never claims or initializes the sensor."""
import argparse
import contextlib
import importlib.metadata
import json
from pathlib import Path
import platform
import struct
import sys
from libusb_loader import load_libusb,platform_label
from instrument_assets import FILES,ROOT,validate_assets


def report(offline=False,list_usb=False):
    result=dict(platform=platform_label(),os=platform.platform(),python=sys.version.split()[0],
                python_executable=sys.executable,python_bits=struct.calcsize('P')*8,
                offline=offline,checks=[],ready=True)
    def check(name,ok,detail,required=True):
        result['checks'].append(dict(name=name,ok=ok,detail=detail,required=required))
        if required and not ok:result['ready']=False
    for name in ('Flask','numpy','scipy','Pillow'):
        try:check(name,True,importlib.metadata.version(name))
        except importlib.metadata.PackageNotFoundError:check(name,False,'Install requirements.txt with this Python')
    try:
        recipe,factory=validate_assets({name:(ROOT/name).read_bytes() for name in FILES})
        check('instrument assets',True,f"{recipe['serial']} / {factory['model']} / {factory['thorlabs_serial']}")
    except (OSError,EOFError,ValueError,KeyError,TypeError) as error:
        check('instrument assets',False,str(error)+'; use native/instrument_assets.py import',required=not offline)
    if not offline:
        try:
            lib=load_libusb();check('libusb',True,str(lib._name))
            if list_usb:
                from usb_transport import USB
                with contextlib.closing(USB(library=lib)) as usb:
                    with contextlib.closing(usb.devices()) as devices:
                        count=sum((d.idVendor,d.idProduct)==(0x1409,0x3370) for _,d in devices)
                check('USB enumeration',count>0,f'{count} matching device(s). Device access/WinUSB binding is not verified by enumeration.')
        except (OSError,RuntimeError) as error:check('libusb / USB',False,str(error))
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--offline',action='store_true',help='No USB library required and no USB calls')
    mode.add_argument('--usb',action='store_true',help='List descriptors only; do not open or claim the sensor')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args();result=report(args.offline,args.usb)
    text=json.dumps(result,indent=2)+'\n'
    if args.output:args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(text)
    print(text,end='')
    return 0 if result['ready'] else 1

if __name__=='__main__':raise SystemExit(main())
