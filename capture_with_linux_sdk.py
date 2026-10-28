import ctypes as c, ctypes.util, json, pathlib, time, sys, struct
lib=c.CDLL(ctypes.util.find_library('ueye_api') or '/usr/lib/libueye_api.so')
class Sensor(c.Structure):
 _fields_=[('id',c.c_uint16),('name',c.c_char*32),('color',c.c_char),('width',c.c_uint32),('height',c.c_uint32),('master_gain',c.c_int),('r_gain',c.c_int),('g_gain',c.c_int),('b_gain',c.c_int),('global_shutter',c.c_int),('pixel_size',c.c_uint16),('bayer',c.c_char),('reserved',c.c_char*13)]
class Rect(c.Structure):_fields_=[('x',c.c_int),('y',c.c_int),('width',c.c_int),('height',c.c_int)]
def call(name,*args,required=True):
 r=getattr(lib,name)(*args);print(name,r,flush=True)
 if r and required:raise RuntimeError(f'{name} returned {r}')
 return r
n=c.c_int()
for attempt in range(20):
 call('is_GetNumberOfCameras',c.byref(n))
 if n.value:break
 time.sleep(1)
print('Camera count',n.value,flush=True)
if not n.value:sys.exit(2)
class CameraInfo(c.Structure):
 _fields_=[('camera_id',c.c_uint32),('device_id',c.c_uint32),('sensor_id',c.c_uint32),('in_use',c.c_uint32),('serial',c.c_char*16),('model',c.c_char*16),('status',c.c_uint32),('reserved',c.c_uint32*2),('full_model',c.c_char*32),('reserved2',c.c_uint32*5)]
class CameraList(c.Structure):_fields_=[('count',c.c_uint32),('info',CameraInfo*16)]
listing=CameraList();listing.count=16;call('is_GetCameraList',c.byref(listing))
for ci in listing.info[:listing.count]:print('Camera list entry',ci.camera_id,ci.device_id,ci.sensor_id,ci.in_use,ci.serial,ci.model,hex(ci.status),flush=True)
h=c.c_int(listing.info[0].device_id|0x8000);call('is_InitCamera',c.byref(h),None)
try:
 s=Sensor();call('is_GetSensorInfo',h,c.byref(s));print('Sensor',s.name,s.width,s.height,'pixel_um',s.pixel_size/100,flush=True)
 info=c.create_string_buffer(64);call('is_GetCameraInfo',h,info,required=False);print('Camera info',repr(info.raw),flush=True)
 call('is_SetDisplayMode',h,1);call('is_SetColorMode',h,6);call('is_SetExternalTrigger',h,0)
 fps=c.c_double();call('is_SetFrameRate',h,c.c_double(2),c.byref(fps),required=False)
 rect=Rect();call('is_AOI',h,2,c.byref(rect),c.sizeof(rect));print('AOI',rect.width,rect.height,flush=True)
 memory=c.c_void_p();mid=c.c_int();call('is_AllocImageMem',h,rect.width,rect.height,8,c.byref(memory),c.byref(mid));call('is_SetImageMem',h,memory,mid)
 pitch=c.c_int();call('is_GetImageMemPitch',h,c.byref(pitch))
 out=pathlib.Path(sys.argv[1] if len(sys.argv)>1 else '/mnt/host');out.mkdir(parents=True,exist_ok=True);meta={'sensor':s.name.decode(),'width':rect.width,'height':rect.height,'pixel_um':s.pixel_size/100,'fps':fps.value,'captures':[]}
 supported=c.c_int();call('is_GetSupportedTestImages',h,c.byref(supported),required=False)
 print('Supported test images',hex(supported.value&0xffffffff),flush=True)
 pattern=next((value for value in (0x10000000,4,0x200) if supported.value&value),0)
 cases=[('frame_1ms',1.0,0),('frame_10ms',10.0,0),('frame_50ms',50.0,0)]
 if pattern and '--verify' in sys.argv:cases.append(('diagnostic_pattern',10.0,pattern))
 for label,exposure,testmode in cases:
  call('is_SetSensorTestImage',h,c.c_int(testmode),0,required=False)
  e=c.c_double(exposure);call('is_Exposure',h,12,c.byref(e),c.sizeof(e),required=False)
  c.memset(memory,0xa5,pitch.value*rect.height)
  started=time.monotonic();call('is_FreezeVideo',h,1);elapsed=time.monotonic()-started
  imageinfo=c.create_string_buffer(96);info_status=call('is_GetImageInfo',h,mid,imageinfo,96,required=False)
  raw=c.string_at(memory,pitch.value*rect.height)
  pixels=b''.join(raw[y*pitch.value:y*pitch.value+rect.width] for y in range(rect.height))
  filename=f'wfs_{label}.pgm';(out/filename).write_bytes(f'P5\n{rect.width} {rect.height}\n255\n'.encode()+pixels)
  item={'file':filename,'kind':'camera_test_pattern' if testmode else 'optical_frame','test_mode':testmode,'exposure_ms':e.value,'min':min(pixels),'max':max(pixels),'mean':sum(pixels)/len(pixels),'unchanged_sentinel_pixels':pixels.count(0xa5),'capture_elapsed_seconds':elapsed,'image_info_status':info_status,'frame_number':struct.unpack_from('<Q',imageinfo.raw,48)[0] if info_status==0 else None,'device_timestamp':struct.unpack_from('<Q',imageinfo.raw,8)[0] if info_status==0 else None};meta['captures'].append(item);print(item,flush=True)
 call('is_SetSensorTestImage',h,0,0,required=False)
 (out/'capture.json').write_text(json.dumps(meta,indent=2))
 call('is_FreeImageMem',h,memory,mid,required=False)
finally:
 call('is_SetSensorTestImage',h,0,0,required=False)
 call('is_ExitCamera',h,required=False)
