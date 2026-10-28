"""Diagnostic: use only persistent-memory GET_SIZE/READ commands, never WRITE."""
import ctypes as c
import ctypes.util,json,time,sys
from pathlib import Path
from sdk_live import CameraList

root=Path(sys.argv[1]);root.mkdir(parents=True,exist_ok=True)
lib=c.CDLL(ctypes.util.find_library('ueye_api'))
lib.is_GetCameraList.argtypes=[c.POINTER(CameraList)]
lib.is_InitCamera.argtypes=[c.POINTER(c.c_uint32),c.c_void_p]
lib.is_ExitCamera.argtypes=[c.c_uint32]
lib.is_PersistentMemory.argtypes=[c.c_uint32,c.c_uint32,c.c_void_p,c.c_uint32]
class Memory(c.Structure):
 _fields_=[('offset',c.c_uint32),('count',c.c_uint32),('option',c.c_int32),('data',c.c_void_p)]
manifest={'method':'Vendor SDK persistent-memory GET_SIZE and READ only','regions':[]}
handle=c.c_uint32();opened=False
try:
 for attempt in range(100):
  listing=CameraList();listing.count=16;status=lib.is_GetCameraList(c.byref(listing))
  entry=next((x for x in listing.info[:min(listing.count,16)] if not x.in_use and not x.status),None) if not status else None
  if entry is not None:break
  time.sleep(1)
 else:raise RuntimeError('No camera available to reference driver')
 handle.value=entry.device_id|0x8000
 status=lib.is_InitCamera(c.byref(handle),None)
 if status:raise RuntimeError(f'is_InitCamera: {status}')
 opened=True;manifest['serial']=entry.serial.decode()
 for name,get_size,read in [('user',6,4),('extended',3,1),('protected',9,7)]:
  size=c.c_uint32();status=lib.is_PersistentMemory(handle,get_size,c.byref(size),4)
  item={'name':name,'size_status':status,'size':size.value};manifest['regions'].append(item)
  print(item,flush=True)
  if status or not size.value or size.value>2*1024*1024:continue
  content=bytearray()
  for offset in range(0,size.value,256):
   length=min(256,size.value-offset);buffer=c.create_string_buffer(length)
   request=Memory(offset,length,0x75457965 if name=='protected' else 0,c.cast(buffer,c.c_void_p))
   status=lib.is_PersistentMemory(handle,read,c.byref(request),c.sizeof(request))
   if status:item['read_error']={'offset':offset,'status':status};break
   content.extend(buffer.raw)
  item['bytes_read']=len(content)
  (root/(name+'.bin')).write_bytes(content)
except Exception as error:
 manifest['error']=str(error);print(str(error),flush=True)
finally:
 if opened:lib.is_ExitCamera(handle)
 (root/'memory_manifest.json').write_text(json.dumps(manifest,indent=2))
 print('WFS_MEMORY_READ_DONE',flush=True)
