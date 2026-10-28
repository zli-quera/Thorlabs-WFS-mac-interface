"""Transfer local instrument assets between hosts; firmware stays out of Git."""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import zipfile
from factory_memory import decode

ROOT=Path(__file__).resolve().parents[1]
FILES=('native/recipe.json.gz','runtime/factory_memory.bin')
MAX_FILE=16*1024*1024


def validate_assets(files):
    with gzip.GzipFile(fileobj=io.BytesIO(files[FILES[0]])) as f:
        raw=f.read(24*1024*1024+1)
    if len(raw)>24*1024*1024:raise ValueError('Startup recipe is too large')
    recipe=json.loads(raw)
    if recipe.get('serial')!='4110057336' or recipe.get('usb_id')!='1409:3370':
        raise ValueError('Asset bundle is not for the supported instrument 4110057336')
    for key in ('boot','initialize','capture'):
        if not isinstance(recipe.get(key),list) or not recipe[key]:raise ValueError('Incomplete startup recipe')
        for packet in recipe[key]:bytes.fromhex(packet)
    bytes.fromhex(recipe['end_capture'])
    if len(recipe.get('initialize_status',[]))!=len(recipe['initialize']):raise ValueError('Missing command status recipe')
    factory=decode(files[FILES[1]])
    return recipe,factory


def export_assets(destination,root=ROOT):
    root=Path(root);destination=Path(destination)
    files={name:(root/name).read_bytes() for name in FILES}
    recipe,factory=validate_assets(files)
    manifest=dict(schema=1,camera_serial=recipe['serial'],model=factory['model'],
                  thorlabs_serial=factory['thorlabs_serial'],
                  sha256={name:hashlib.sha256(data).hexdigest() for name,data in files.items()})
    destination.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(destination,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('manifest.json',json.dumps(manifest,indent=2)+'\n')
        for name,data in files.items():archive.writestr(name,data)
    return manifest


def import_assets(source,root=ROOT):
    root=Path(root)
    with zipfile.ZipFile(source) as archive:
        if sorted(archive.namelist())!=sorted(('manifest.json',*FILES)):
            raise ValueError('Unexpected or duplicate bundle entries')
        if any(info.file_size>MAX_FILE for info in archive.infolist()):raise ValueError('Oversized bundle entry')
        manifest=json.loads(archive.read('manifest.json'))
        if manifest.get('schema')!=1:raise ValueError('Unsupported asset bundle schema')
        files={name:archive.read(name) for name in FILES}
    for name,data in files.items():
        if hashlib.sha256(data).hexdigest()!=manifest.get('sha256',{}).get(name):
            raise ValueError(f'Checksum mismatch: {name}')
    recipe,factory=validate_assets(files)
    if manifest.get('camera_serial')!=recipe['serial'] or manifest.get('thorlabs_serial')!=factory['thorlabs_serial']:
        raise ValueError('Bundle identity mismatch')
    # Only the fixed allowlist is written; archive paths never select destinations.
    for name,data in files.items():
        target=root/name;target.parent.mkdir(parents=True,exist_ok=True)
        temporary=None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent,delete=False) as f:
                temporary=Path(f.name);f.write(data)
            os.replace(temporary,target)
        finally:
            if temporary is not None:temporary.unlink(missing_ok=True)
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('export','import'))
    parser.add_argument('bundle',type=Path,help='Local .instrument.zip path; not for Git')
    args=parser.parse_args()
    try:
        manifest=export_assets(args.bundle) if args.action=='export' else import_assets(args.bundle)
    except (OSError,EOFError,ValueError,KeyError,TypeError,zipfile.BadZipFile) as error:parser.exit(1,str(error)+'\n')
    print(json.dumps(manifest,indent=2))
    print('Local instrument assets '+('exported' if args.action=='export' else 'imported')+'. Do not add firmware bundles to Git.')

if __name__=='__main__':main()
