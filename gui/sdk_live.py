"""Runs inside the local driver helper. Uses only Python's standard library."""
import ctypes as c
import ctypes.util
import json
import os
from pathlib import Path
import struct
import sys
import time


class Sensor(c.Structure):
    _fields_ = [("id", c.c_uint16), ("name", c.c_char*32), ("color", c.c_char),
                ("width", c.c_uint32), ("height", c.c_uint32),
                ("gains", c.c_int*4), ("global_shutter", c.c_int),
                ("pixel_size", c.c_uint16), ("bayer", c.c_char), ("reserved", c.c_char*13)]


class CameraInfo(c.Structure):
    _fields_ = [("camera_id", c.c_uint32), ("device_id", c.c_uint32),
                ("sensor_id", c.c_uint32), ("in_use", c.c_uint32),
                ("serial", c.c_char*16), ("model", c.c_char*16),
                ("status", c.c_uint32), ("reserved", c.c_uint32*2),
                ("full_model", c.c_char*32), ("reserved2", c.c_uint32*5)]


class CameraList(c.Structure):
    _fields_ = [("count", c.c_uint32), ("info", CameraInfo*16)]


class Rect(c.Structure):
    _fields_ = [("x", c.c_int), ("y", c.c_int), ("width", c.c_int), ("height", c.c_int)]


def atomic(path, data):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def run(root):
    root.mkdir(parents=True, exist_ok=True)
    stop = root / "stop"
    lib = c.CDLL(ctypes.util.find_library("ueye_api"))
    signatures = {
        "is_GetNumberOfCameras": [c.POINTER(c.c_int)],
        "is_GetCameraList": [c.POINTER(CameraList)],
        "is_InitCamera": [c.POINTER(c.c_uint32), c.c_void_p],
        "is_ExitCamera": [c.c_uint32],
        "is_GetSensorInfo": [c.c_uint32, c.POINTER(Sensor)],
        "is_SetDisplayMode": [c.c_uint32, c.c_int],
        "is_SetColorMode": [c.c_uint32, c.c_int],
        "is_SetExternalTrigger": [c.c_uint32, c.c_int],
        "is_SetFrameRate": [c.c_uint32, c.c_double, c.POINTER(c.c_double)],
        "is_AOI": [c.c_uint32, c.c_uint32, c.c_void_p, c.c_uint32],
        "is_AllocImageMem": [c.c_uint32, c.c_int, c.c_int, c.c_int, c.POINTER(c.c_void_p), c.POINTER(c.c_int)],
        "is_SetImageMem": [c.c_uint32, c.c_void_p, c.c_int],
        "is_FreeImageMem": [c.c_uint32, c.c_void_p, c.c_int],
        "is_GetImageMemPitch": [c.c_uint32, c.POINTER(c.c_int)],
        "is_SetSensorTestImage": [c.c_uint32, c.c_int, c.c_int],
        "is_SetHardwareGain": [c.c_uint32, c.c_int, c.c_int, c.c_int, c.c_int],
        "is_Exposure": [c.c_uint32, c.c_uint32, c.c_void_p, c.c_uint32],
        "is_FreezeVideo": [c.c_uint32, c.c_int],
        "is_GetImageInfo": [c.c_uint32, c.c_int, c.c_void_p, c.c_int],
    }
    for name, arguments in signatures.items():
        getattr(lib, name).argtypes = arguments
        getattr(lib, name).restype = c.c_int

    def call(name, *args):
        result = getattr(lib, name)(*args)
        if result:
            raise RuntimeError(f"{name}: {result}")

    def status(stage, message):
        atomic(root / "status.json", json.dumps({"stage": stage, "message": message, "time": time.time()}).encode())

    while not stop.exists():
        handle = c.c_uint32()
        memory = c.c_void_p()
        memory_id = c.c_int()
        opened = False
        try:
            status("connecting", "Waiting for camera")
            listing = CameraList()
            listing.count = 16
            call("is_GetCameraList", c.byref(listing))
            if not listing.count:
                time.sleep(1)
                continue
            entry = next((item for item in listing.info[:listing.count] if not item.in_use and not item.status), None)
            if entry is None:
                time.sleep(1)
                continue
            handle.value = entry.device_id | 0x8000
            call("is_InitCamera", c.byref(handle), None)
            opened = True
            sensor = Sensor()
            call("is_GetSensorInfo", handle, c.byref(sensor))
            call("is_SetDisplayMode", handle, 1)
            call("is_SetColorMode", handle, 6)
            call("is_SetExternalTrigger", handle, 0)
            call("is_SetSensorTestImage", handle, 0, 0)
            fps = c.c_double()
            call("is_SetFrameRate", handle, 5., c.byref(fps))
            rect = Rect()
            call("is_AOI", handle, 2, c.byref(rect), c.sizeof(rect))
            call("is_AllocImageMem", handle, rect.width, rect.height, 8, c.byref(memory), c.byref(memory_id))
            call("is_SetImageMem", handle, memory, memory_id)
            pitch = c.c_int()
            call("is_GetImageMemPitch", handle, c.byref(pitch))
            last_controls = None
            sequence = 0
            print("WFS_LIVE_READY", flush=True)
            status("streaming", "Camera online")
            while not stop.exists():
                started = time.monotonic()
                try:
                    controls = json.loads((root / "controls.json").read_text())
                except (OSError, ValueError):
                    controls = {"exposure_ms": 10., "gain": 0}
                pair = (float(controls.get("exposure_ms", 10)), int(controls.get("gain", 0)))
                if pair != last_controls:
                    exposure = c.c_double(pair[0])
                    call("is_Exposure", handle, 12, c.byref(exposure), c.sizeof(exposure))
                    call("is_SetHardwareGain", handle, pair[1], -1, -1, -1)
                    last_controls = pair
                capture_started=time.monotonic()
                call("is_FreezeVideo", handle, 1)
                raw = c.string_at(memory, pitch.value * rect.height)
                pixels = (raw if pitch.value == rect.width else
                          b"".join(raw[y*pitch.value:y*pitch.value+rect.width] for y in range(rect.height)))
                imageinfo = c.create_string_buffer(96)
                call("is_GetImageInfo", handle, memory_id, imageinfo, 96)
                capture_elapsed=time.monotonic()-capture_started
                sequence += 1
                # Data and metadata travel in one atomic file; readers cannot mix frames.
                metadata = {"sequence": sequence, "time": time.time(), "sensor": sensor.name.decode(),
                            "serial": entry.serial.decode(), "width": rect.width, "height": rect.height,
                            "pixel_um": sensor.pixel_size / 100, "exposure_ms": exposure.value,
                            "gain": pair[1], "frame_number": struct.unpack_from("<Q", imageinfo.raw, 48)[0],
                            "device_timestamp": struct.unpack_from("<Q", imageinfo.raw, 8)[0],
                            "diagnostic": False,"capture_seconds":capture_elapsed,"configured_fps":fps.value}
                header = json.dumps(metadata).encode() + b"\n"
                atomic(root / "frame.bin", header + pixels)
                interval=0 if (root/'benchmark.json').exists() else .5
                time.sleep(max(0, interval - (time.monotonic() - started)))
        except Exception as error:
            print(str(error), flush=True)
            status("connecting", str(error))
            time.sleep(1)
        finally:
            if opened:
                lib.is_SetSensorTestImage(handle, 0, 0)
                if memory.value:
                    lib.is_FreeImageMem(handle, memory, memory_id)
                lib.is_ExitCamera(handle)
    status("stopped", "Camera stopped")


if __name__ == "__main__":
    run(Path(sys.argv[1]))
