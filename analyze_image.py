"""Analyze saved monochrome PNG/PGM frames without a sensor or running GUI."""
import argparse
import json
from pathlib import Path
import sys
import numpy as np
from PIL import Image
sys.path[:0]=[str(Path(__file__).resolve().parent/'gui'),str(Path(__file__).resolve().parent/'native')]
from analysis import analyze, detect_spots, make_reference
from factory_memory import decode
from factory_reference import reference_from_factory


def load_image(path):
    with Image.open(path) as image:
        if image.mode != 'L':
            raise ValueError('Expected a raw 8-bit monochrome image (PNG or PGM)')
        return np.array(image)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image',type=Path)
    parser.add_argument('--factory-memory',type=Path,help='Native 512-byte factory-memory dump; supplies focal length and reference grid')
    parser.add_argument('--reference',type=Path,help='Known flat-wavefront image')
    parser.add_argument('--focal-mm',type=float)
    parser.add_argument('--pixel-um',type=float,default=5.5)
    parser.add_argument('--threshold-dn',type=float,default=20)
    parser.add_argument('--min-spots',type=int,default=20)
    parser.add_argument('--tilt-limit-urad',type=float,default=100)
    parser.add_argument('--keep-tilt',action='store_true')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if not np.isfinite(args.pixel_um) or args.pixel_um<=0:parser.error('pixel size must be positive and finite')
    if not np.isfinite(args.tilt_limit_urad) or args.tilt_limit_urad<0:parser.error('tilt cutoff must be non-negative and finite')
    config=dict(threshold_dn=args.threshold_dn,min_spots=args.min_spots,focal_mm=args.focal_mm,
                remove_tilt=not args.keep_tilt,tilt_limit_urad=args.tilt_limit_urad)
    reference=None
    image=load_image(args.image)
    if args.factory_memory:
        if args.reference:parser.error('Choose measured reference or factory memory, not both')
        profile=decode(args.factory_memory.read_bytes())
        reference=reference_from_factory(detect_spots(image,args.threshold_dn),image.shape,profile)
        config['focal_mm']=reference['focal_mm']
    if args.reference:
        flat=load_image(args.reference);spots=detect_spots(flat,args.threshold_dn)
        if spots.saturated_fraction>.02 or len(spots.xy)<args.min_spots:
            parser.error('Reference image is saturated or has too few usable spots')
        reference=make_reference(spots,flat.shape,args.pixel_um)
    result,_=analyze(image,config,reference)
    data=json.dumps(dict(image=str(args.image),reference=str(args.reference) if args.reference else None,
                         factory_memory=str(args.factory_memory) if args.factory_memory else None,config=config,analysis=result),indent=2,allow_nan=False)+'\n'
    if args.output:args.output.write_text(data)
    else:print(data,end='')

if __name__=='__main__':main()
