"""libusb transport with platform-specific setup and shared wire transfers."""
import ctypes as c
import contextlib
import struct
import sys
from libusb_loader import load_libusb

ERROR_NAMES={-1:'IO',-2:'INVALID_PARAM',-3:'ACCESS',-4:'NO_DEVICE',-5:'NOT_FOUND',
             -6:'BUSY',-7:'TIMEOUT',-8:'OVERFLOW',-9:'PIPE',-10:'INTERRUPTED',-11:'NO_MEM',-12:'NOT_SUPPORTED'}

class DeviceDescriptor(c.Structure):
    _fields_=[('bLength',c.c_uint8),('bDescriptorType',c.c_uint8),('bcdUSB',c.c_uint16),
              ('bDeviceClass',c.c_uint8),('bDeviceSubClass',c.c_uint8),('bDeviceProtocol',c.c_uint8),
              ('bMaxPacketSize0',c.c_uint8),('idVendor',c.c_uint16),('idProduct',c.c_uint16),
              ('bcdDevice',c.c_uint16),('iManufacturer',c.c_uint8),('iProduct',c.c_uint8),
              ('iSerialNumber',c.c_uint8),('bNumConfigurations',c.c_uint8)]

class USBError(RuntimeError):
    def __init__(self, operation, code):
        self.code=code
        super().__init__(f'{operation}: LIBUSB_ERROR_{ERROR_NAMES.get(code, str(code))} ({code})')

class USB:
    def __init__(self,library=None,system=None):
        self.system=sys.platform if system is None else system
        self.lib=load_libusb(self.system) if library is None else library
        signatures={
            'libusb_init':([c.POINTER(c.c_void_p)],c.c_int),
            'libusb_exit':([c.c_void_p],None),
            'libusb_get_device_list':([c.c_void_p,c.POINTER(c.POINTER(c.c_void_p))],c.c_ssize_t),
            'libusb_free_device_list':([c.POINTER(c.c_void_p),c.c_int],None),
            'libusb_get_device_descriptor':([c.c_void_p,c.POINTER(DeviceDescriptor)],c.c_int),
            'libusb_open':([c.c_void_p,c.POINTER(c.c_void_p)],c.c_int),
            'libusb_get_configuration':([c.c_void_p,c.POINTER(c.c_int)],c.c_int),
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
    def devices(self):
        listing=c.POINTER(c.c_void_p)()
        count=self.check(self.lib.libusb_get_device_list(self.context,c.byref(listing)),'Enumerate USB devices')
        try:
            for i in range(count):
                descriptor=DeviceDescriptor()
                if self.lib.libusb_get_device_descriptor(listing[i],c.byref(descriptor))==0:
                    yield listing[i],descriptor
        finally:self.lib.libusb_free_device_list(listing,1)
    def open(self):
        # Keep the device list alive until libusb_open owns a reference.
        with contextlib.closing(self.devices()) as devices:
            for device,descriptor in devices:
                if (descriptor.idVendor,descriptor.idProduct)!=(0x1409,0x3370):continue
                handle=c.c_void_p()
                result=self.lib.libusb_open(device,c.byref(handle))
                if result<0:
                    hint=(' Install WinUSB for this sensor and close other camera applications; '
                          'see docs/windows_setup.md.' if self.system=='win32' else '')
                    raise USBError('Open sensor 1409:3370.'+hint,result)
                self.handle=handle
                break
            else:
                raise RuntimeError('Sensor 1409:3370 is not connected or not enumerated')
        identity=self.control(0xc0,0xb1,0,0,40)
        if b'4110057336' not in identity:
            self.close_handle();raise RuntimeError('Startup recipe is specific to sensor 4110057336')
        descriptor=self.control(0x80,6,0x200,0,9)
        self.configure()
        self.disable_link_power_management()
        return struct.unpack_from('<H',descriptor,2)[0]>18
    def configure(self):
        if self.system=='win32':
            current=c.c_int()
            self.check(self.lib.libusb_get_configuration(self.handle,c.byref(current)),'Get USB configuration')
            # WinUSB cannot reset/select arbitrary configurations. This device
            # uses the first configuration; do not re-set it when already active.
            if current.value==1:return
            if current.value!=0:raise RuntimeError(f'Unexpected Windows USB configuration {current.value}; expected 1')
        self.check(self.lib.libusb_set_configuration(self.handle,1),'Set USB configuration')
    def disable_link_power_management(self):
        # The U1/U2 workaround is specific to the tested macOS host/hub path.
        # Windows leaves USB link power management to WinUSB/the host driver.
        if self.system=='darwin':
            for feature in (48,49):self.control(0,1,feature,0,0)
    def claim(self):
        self.check(self.lib.libusb_claim_interface(self.handle,0),'Claim interface')
        self.claimed=True
        self.check(self.lib.libusb_set_interface_alt_setting(self.handle,0,0),'Select interface alternate')
        self.disable_link_power_management()
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
