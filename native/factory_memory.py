"""Read-only decoder for the WFS40 factory EEPROM records.

Layout and signed-byte checksum verified against WFS 6.3's EEPROM decoder.
Numeric record fields match WFS_GetMlaData. Offset/correction application to
reference centroids is deliberately separate from this memory decoder.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import struct


def checksum_valid(record):
    if len(record)!=64:return False
    signed_sum=sum(x if x<128 else x-256 for x in record[:62])
    return (1234+signed_sum)&65535 == struct.unpack_from('<H',record,62)[0]


def text(data):
    return bytes((value+32)&255 for value in data).split(b'\0')[0].decode('ascii').rstrip()


def decode(data):
    if len(data)!=512:raise ValueError('Expected a complete 512-byte factory memory region')
    header=data[:64]
    if not checksum_valid(header):raise ValueError('Factory identity checksum failed')
    model,serial=text(header[:16]),text(header[16:32])
    if not model.startswith('WFS40'):raise ValueError('Unsupported factory record model')
    arrays=[]
    for index,start in enumerate(range(64,512,64)):
        record=data[start:start+64]
        if record in (bytes(64),b'\xff'*64):continue
        if not checksum_valid(record):raise ValueError(f'MLA {index} checksum failed')
        name=text(record[:16])
        pixel_um,pitch_um=struct.unpack_from('<dd',record,16)
        x,y,focal_um,correction0,correction45=struct.unpack_from('<5f',record,32)
        if not(3<=pixel_um<=20 and 100<=pitch_um<=500 and 1000<=focal_um<=30000):
            raise ValueError('Factory optical parameters outside supported ranges')
        arrays.append(dict(index=index,name=name,pixel_um=pixel_um,lenslet_pitch_um=pitch_um,
                           focal_um=focal_um,focal_mm=focal_um/1000,
                           stored_spot_offset_x=x,stored_spot_offset_y=y,
                           stored_grid_correction_0=correction0,stored_grid_correction_45=correction45,
                           spot_offset_x_px=x,spot_offset_y_px=y,
                           grid_correction_0_ppm=correction0,grid_correction_45_ppm=correction45,
                           grid_rotation_mdeg=max(-50,min(50,struct.unpack_from('<h',record,52)[0])),
                           grid_pitch_ppm=struct.unpack_from('<h',record,54)[0],
                           trefoil_y_ppb=struct.unpack_from('<b',record,56)[0],
                           trefoil_x_ppb=struct.unpack_from('<b',record,57)[0],
                           coma_y_ppb=struct.unpack_from('<b',record,58)[0],
                           coma_x_ppb=struct.unpack_from('<b',record,59)[0],
                           remaining_record_bytes_hex=record[52:62].hex(),checksum_valid=True))
    if not arrays:raise ValueError('No valid MLA records')
    return dict(model=model,thorlabs_serial=serial,arrays=arrays,identity_checksum_valid=True,
                byte_count=len(data),sha256=sha256(data).hexdigest(),
                reference_mapping_implemented=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('memory',type=Path);parser.add_argument('--output',type=Path)
    args=parser.parse_args();value=json.dumps(decode(args.memory.read_bytes()),indent=2)+'\n'
    if args.output:args.output.write_text(value)
    else:print(value,end='')
