"""Native macOS userspace USB backend for instrument 4110057336.

No Linux process or vendor host SDK. Uses macOS libusb (IOKit underneath).
Initial implementation uses this instrument's observed startup recipe.
"""
import ctypes as c
import gzip
import json
from pathlib import Path
import struct
import threading
import time

from controls import validate as validate_controls, exposure_packet, gain_packet, exposure_value

class USBError(RuntimeError):
    def __init__(self, operation, code):
        self.code=code
        super().__init__(f'{operation}: libusb {code}')

class USB:
    def __init__(self):
        self.lib=c.CDLL('/opt/homebrew/lib/libusb-1.0.dylib')
        signatures={
            'libusb_init':([c.POINTER(c.c_void_p)],c.c_int),
            'libusb_exit':([c.c_void_p],None),
            'libusb_open_device_with_vid_pid':([c.c_void_p,c.c_uint16,c.c_uint16],c.c_void_p),
            'libusb_close':([c.c_void_p],None),
            'libusb_set_configuration':([c.c_void_p,c.c_int],c.c_int),
            'libusb_claim_interface':([c.c_void_p,c.c_int],c.c_int),
            'libusb_set_interface_alt_setting':([c.c_void_p,c.c_int,c.c_int],c.c_int),
            'libusb_release_interface':([c.c_void_p,c.c_int],c.c_int),
            'libusb_clear_halt':([c.c_void_p,c.c_ubyte],c.c_int),
            'libusb_control_transfer':([c.c_void_p,c.c_uint8,c.c_uint8,c.c_uint16,c.c_uint16,c.c_void_p,c.c_uint16,c.c_uint],c.c_int),
            'libusb_bulk_transfer':([c.c_void_p,c.c_ubyte,c.c_void_p,c.c_int,c.POINTER(c.c_int),c.c_uint],c.c_int)}
        for name,(args,result) in signatures.items():
            fn=getattr(self.lib,name);fn.argtypes=args;fn.restype=result
        self.context=c.c_void_p();self.handle=None;self.claimed=False
        self.check(self.lib.libusb_init(c.byref(self.context)),'USB initialization')
    def check(self,result,name):
        if result<0:raise USBError(name,result)
        return result
    def open(self):
        self.handle=self.lib.libusb_open_device_with_vid_pid(self.context,0x1409,0x3370)
        if not self.handle:raise RuntimeError('Sensor not connected or USB access unavailable')
        identity=self.control(0xc0,0xb1,0,0,40)
        if b'4110057336' not in identity:
            self.close_handle();raise RuntimeError('Startup recipe is specific to sensor 4110057336')
        descriptor=self.control(0x80,6,0x200,0,9)
        self.check(self.lib.libusb_set_configuration(self.handle,1),'Set USB configuration')
        for feature in (48,49):
            self.control(0,1,feature,0,0)
        return struct.unpack_from('<H',descriptor,2)[0]>18
    def claim(self):
        self.check(self.lib.libusb_claim_interface(self.handle,0),'Claim interface')
        self.claimed=True
        self.check(self.lib.libusb_set_interface_alt_setting(self.handle,0,0),'Select interface alternate')
        for feature in (48,49):self.control(0,1,feature,0,0)
        for ep in (1,0x81):self.check(self.lib.libusb_clear_halt(self.handle,ep),'Clear endpoint')
    def control(self,bm,request,value,index,data,timeout=3000):
        length=data if isinstance(data,int) else len(data)
        buffer=c.create_string_buffer(length or 1)
        if not isinstance(data,int):buffer[:length]=data
        n=self.check(self.lib.libusb_control_transfer(self.handle,bm,request,value,index,buffer,length,timeout),'Control transfer')
        return buffer.raw[:n]
    def write(self,data):
        buffer=c.create_string_buffer(data);actual=c.c_int()
        self.check(self.lib.libusb_bulk_transfer(self.handle,1,buffer,len(data),c.byref(actual),5000),'Command write')
        if actual.value!=len(data):raise RuntimeError('Incomplete command write')
    def read(self,ep,length,timeout=5000):
        buffer=c.create_string_buffer(length);actual=c.c_int()
        result=self.lib.libusb_bulk_transfer(self.handle,ep,buffer,length,c.byref(actual),timeout)
        self.check(result,f'Endpoint {ep:02x} read')
        return buffer.raw[:actual.value]
    def close_handle(self):
        if self.handle:
            if self.claimed:self.lib.libusb_release_interface(self.handle,0)
            self.lib.libusb_close(self.handle);self.handle=None;self.claimed=False
    def close(self):
        self.close_handle()
        if self.context:self.lib.libusb_exit(self.context);self.context=None

class Camera:
    def __init__(self,progress=print,stop=None):
        self.progress=progress;self.stop=stop or threading.Event()
        with gzip.open(Path(__file__).with_name('recipe.json.gz'),'rt') as f:self.recipe=json.load(f)
        self.exposure_ms=exposure_value(10.)[1];self.requested_exposure_ms=10.;self.gain=0;self.gain_factor=1.
        self.usb=USB();self.sequence=0;self.frame_number=0;self.factory_calibration=None
        self.protocol_log=Path(__file__).parents[1]/"diagnostics/native_protocol.jsonl"
        self.protocol_log.parent.mkdir(parents=True,exist_ok=True)
    def initialize(self):
        self.progress('Opening sensor directly on macOS')
        runtime=self.usb.open()
        if not runtime:
            self.progress('Loading volatile camera firmware')
            previous_write=None
            boot=self.recipe['boot']
            for i,value in enumerate(boot):
                if self.stop.is_set():raise RuntimeError('Stopped')
                data=bytes.fromhex(value);bm,request,val,index,length=struct.unpack('<BBHHH',data[:8])
                try:
                    reply=self.usb.control(bm,request,val,index,length if bm&0x80 else data[8:])
                except USBError as error:
                    if i!=len(boot)-1:raise
                if request==0xa0 and not bm&0x80 and length:
                    previous_write=(val,index,data[8:])
                elif request==0xa0 and bm&0x80 and previous_write and previous_write[:2]==(val,index):
                    if reply!=previous_write[2]:raise RuntimeError('Firmware RAM readback mismatch')
            self.usb.close_handle()
            for _ in range(100):
                if self.stop.wait(.1):raise RuntimeError('Stopped')
                try:
                    if self.usb.open():break
                    self.usb.close_handle()
                except (USBError,RuntimeError):self.usb.close_handle()
            else:raise RuntimeError('Camera did not enumerate after firmware startup')
        self.usb.claim()
        time.sleep(2)
        commands=self.recipe['initialize']
        reuse_fpga=False
        factory_read_pending=False
        for i,packet in enumerate(commands):
            if i==12 and getattr(self,'fpga_state',None)==0:
                identity=self.command(bytes.fromhex(commands[687]))
                if identity!=b'\xaa':
                    raise RuntimeError('FPGA configuration is incomplete; reconnect the sensor USB cable')
                reuse_fpga=True
                self.progress('Reusing verified FPGA configuration')
            if reuse_fpga and 12<=i<687:continue
            if self.stop.is_set():raise RuntimeError('Stopped')
            wire=bytes.fromhex(packet)
            response=self.command(wire,expected_status=self.recipe['initialize_status'][i])
            if factory_read_pending and wire[1]==0xd4:
                if len(response)!=564:raise RuntimeError('Incomplete factory-memory response')
                self.factory_memory=response[52:]
                cache=self.protocol_log.parents[1]/'runtime'
                cache.mkdir(parents=True,exist_ok=True)
                (cache/'factory_memory.bin').write_bytes(self.factory_memory)
                from factory_memory import decode
                try:
                    factory=decode(self.factory_memory)
                    self.factory_calibration=factory
                    (cache/'factory_calibration.json').write_text(json.dumps(factory,indent=2)+'\n')
                except ValueError as error:
                    self.progress('Factory record validation failed: '+str(error))
                factory_read_pending=False
            if wire[1]==0xd3 and len(wire)==580 and wire[61:65]==b'\x1c\x05\x00\x00':
                factory_read_pending=True
            if i==11:
                if len(response)!=9:raise RuntimeError('Invalid FPGA status response')
                self.fpga_state=response[-1]
                if self.fpga_state not in (0,0x2c):raise RuntimeError(f'Unexpected FPGA state {self.fpga_state:02x}')
            if i%200==0:self.progress(f'Configuring sensor {i+1}/{len(commands)}')
        self.progress('Native camera ready')
    def command(self,packet,expected_status=0):
        packet=bytearray(packet)
        old=struct.unpack_from('<H',packet,12)[0]
        self.sequence=self.sequence%65535+1
        struct.pack_into('<H',packet,12,self.sequence)
        if packet[1]==0xe6 and struct.unpack_from('<H',packet,4)[0]==old:
            struct.pack_into('<H',packet,4,self.sequence)
        response_box=[]
        read_errors=[]
        def receive_ack():
            try:response_box.append(self.usb.read(0x81,4096))
            except Exception as error:read_errors.append(error)
        receiver=threading.Thread(target=receive_ack,daemon=True)
        receiver.start()
        time.sleep(.002)
        self.usb.write(bytes(packet))
        receiver.join(6)
        if read_errors:raise read_errors[0]
        if receiver.is_alive():raise RuntimeError('Acknowledgement transfer stuck')
        for attempt in range(50):
            response=response_box[0] if attempt==0 else self.usb.read(0x81,4096)
            if len(response)<8:raise RuntimeError('Short command response')
            status,code,token,length=struct.unpack_from('<4H',response)
            with self.protocol_log.open('a') as log:
                log.write(json.dumps({'time':time.monotonic(),'sequence':self.sequence,'command':packet[:80].hex(),'response':response[:96].hex()})+'\n')
            if token==self.sequence and code==packet[10]:
                if status!=expected_status:raise RuntimeError(f'Camera command {code:02x} token {token} status {status:04x}; response={response[:96].hex()} packet={packet[:80].hex()}')
                if len(response)!=8+length:raise RuntimeError('Command response length mismatch')
                return response[8:]
        raise RuntimeError('No matching camera acknowledgement')
    def set_controls(self,exposure_ms,gain):
        # Called by the capture owner between completed frames, never from
        # the HTTP thread. Store applied values only after checked ACKs.
        exposure_ms,gain=validate_controls(exposure_ms,gain)
        if exposure_ms!=self.requested_exposure_ms:
            packet,actual=exposure_packet(self.recipe,exposure_ms)
            self.command(packet)
            self.exposure_ms=actual;self.requested_exposure_ms=exposure_ms
        if gain!=self.gain:
            packet,factor=gain_packet(self.recipe,gain)
            self.command(packet)
            self.gain=gain;self.gain_factor=factor
        return dict(exposure_ms=self.exposure_ms,requested_exposure_ms=self.requested_exposure_ms,
                    gain=self.gain,gain_factor=self.gain_factor)

    def _read_image(self):
        leader=self.usb.read(0x82,56)
        if len(leader)!=56 or leader[:4]!=b'U3VL':raise RuntimeError('Invalid image leader')
        width,height=struct.unpack_from('<II',leader,32)
        if (width,height)!=(2048,2048):raise RuntimeError(f'Unexpected image dimensions {width}x{height}')
        chunks=[];remaining=width*height
        while remaining:
            block=self.usb.read(0x82,min(524288,remaining))
            if not block:raise RuntimeError('Empty image payload')
            chunks.append(block);remaining-=len(block)
        chunk_metadata=self.usb.read(0x82,60)
        trailer=self.usb.read(0x82,32)
        if len(chunk_metadata)!=60 or len(trailer)!=32 or trailer[:4]!=b'U3VT':raise RuntimeError('Incomplete image trailer')
        return b''.join(chunks),leader,chunk_metadata,trailer
    def capture(self):
        result=[];errors=[]
        def receive():
            try:result.append(self._read_image())
            except Exception as error:errors.append(error)
        reader=threading.Thread(target=receive,daemon=True);reader.start()
        try:
            for value in self.recipe['capture']:
                packet=bytearray.fromhex(value)
                if packet[16:18]==b'@1':struct.pack_into('<I',packet,len(packet)-4,self.frame_number+1)
                self.command(packet)
            reader.join(10)
            if reader.is_alive():raise RuntimeError('Image transfer did not finish')
            if errors:raise errors[0]
            pixels,leader,chunk,trailer=result[0]
        finally:
            self.command(bytes.fromhex(self.recipe['end_capture']))
        self.frame_number+=1
        meta={'sequence':self.frame_number,'frame_number':self.frame_number,'time':time.time(),
              'width':2048,'height':2048,'pixel_um':5.5,'serial':self.recipe['serial'],
              'sensor':'UI337xCP-M','device_timestamp':struct.unpack_from('<Q',chunk,4)[0],
              'stream_timestamp_ns':struct.unpack_from('<Q',leader,20)[0],
              'sensor_counter':struct.unpack_from('<I',chunk,24)[0],
              'diagnostic':False,'backend':'macos-libusb','factory_calibration':self.factory_calibration,'exposure_ms':self.exposure_ms,'requested_exposure_ms':self.requested_exposure_ms,'gain':self.gain,'gain_factor':self.gain_factor,
              'leader_hex':leader.hex(),'chunk_hex':chunk.hex(),'trailer_hex':trailer.hex()}
        return meta,pixels
    def close(self):self.usb.close()

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--frames',type=int,default=3);args=parser.parse_args()
    output=Path(__file__).parents[1]/'captures/native';output.mkdir(parents=True,exist_ok=True)
    camera=Camera(progress=lambda s:print(s,flush=True))
    try:
        camera.initialize()
        for i in range(args.frames):
            meta,pixels=camera.capture();stem=output/f'frame_{i+1:03d}'
            stem.with_suffix('.pgm').write_bytes(b'P5\n2048 2048\n255\n'+pixels)
            meta.update(min_dn=min(pixels),max_dn=max(pixels),mean_dn=sum(pixels)/len(pixels))
            stem.with_suffix('.json').write_text(json.dumps(meta,indent=2))
            print(json.dumps(meta),flush=True)
    finally:camera.close()
