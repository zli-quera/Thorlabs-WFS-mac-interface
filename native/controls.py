"""Volatile controls for the recorded UI337xCP-M full-resolution configuration.

CMV4000: 40 MHz master clock, FOT register 73 = 20. The SDK quantizes
integration to four sequencer ticks (12.9 us), with a 27.735 us offset.
Exposure retains the recorded frame blanking; it does not change ROI/clock.
Master gain is the camera's FPGA digital multiplier (1x to 4x), not sensor PGA.
"""
import math
import struct

MIN_EXPOSURE_MS=.04
MAX_EXPOSURE_MS=150.
TICK_MS=129/40000
FOT_TICKS=.43*20


def validate(exposure_ms,gain):
    exposure_ms=float(exposure_ms);gain=float(gain)
    if not math.isfinite(exposure_ms) or not MIN_EXPOSURE_MS<=exposure_ms<=MAX_EXPOSURE_MS:
        raise ValueError(f'Exposure must be {MIN_EXPOSURE_MS}–{MAX_EXPOSURE_MS} ms')
    if not math.isfinite(gain) or not 0<=gain<=100 or gain!=int(gain):
        raise ValueError('Gain must be a whole percentage between 0 and 100')
    return exposure_ms,int(gain)


def exposure_value(exposure_ms):
    exposure_ms,_=validate(exposure_ms,0)
    ticks=max(1,int(exposure_ms/TICK_MS-FOT_TICKS+1e-7)//4*4)
    return ticks,(ticks+FOT_TICKS)*TICK_MS


def gain_value(gain):
    _,gain=validate(10,gain)
    fixed=int((1+3*gain/100)*256)
    return fixed,fixed/256


def exposure_packet(recipe,exposure_ms):
    ticks,actual=exposure_value(exposure_ms)
    templates=[bytes.fromhex(p) for p in recipe['initialize']
               if len(p)==432 and p.startswith('40d3')]
    if not templates:raise ValueError('Startup recipe has no full-resolution exposure template')
    packet=bytearray(templates[-1])
    # Keep the recorded clock, frame blanking, row/readout configuration,
    # and all unrelated sensor registers. Only update integration and its tag.
    if packet[52:56]!=bytes.fromhex('020e0000'):
        raise ValueError('Unsupported exposure timing tag')
    struct.pack_into('<I',packet,56,round(exposure_ms*1e6))
    for first in (42,56):
        for i in range(3):
            marker=bytes.fromhex('140b00000107010800')+bytes([first+i])
            if packet.count(marker)!=1:raise ValueError('Unsupported exposure register template')
            packet[packet.index(marker)+len(marker)]=(ticks>>(8*i))&255
    return bytes(packet),actual


def gain_packet(recipe,gain):
    fixed,factor=gain_value(gain)
    for item in reversed(recipe['initialize']):
        packet=bytearray.fromhex(item)
        if len(packet)==56 and packet[1]==0xe6 and packet[28:44]==struct.pack('<4I',2,16,16,1):
            struct.pack_into('<3I',packet,44,fixed,fixed,fixed)
            return bytes(packet),factor
    raise ValueError('Startup recipe has no digital gain template')
