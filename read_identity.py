"""Read the connected IDS camera's identity directly on macOS with libusb.

The B1 request was observed in the vendor driver's USB initialization traffic.
This reads identity bytes only; it does not acquire an image or wavefront.
"""
import ctypes as c
import json
import re
from pathlib import Path


class Descriptor(c.Structure):
    _fields_ = [("length", c.c_uint8), ("type", c.c_uint8),
                ("usb", c.c_uint16), ("device_class", c.c_uint8),
                ("subclass", c.c_uint8), ("protocol", c.c_uint8),
                ("packet", c.c_uint8), ("vendor", c.c_uint16),
                ("product", c.c_uint16), ("version", c.c_uint16),
                ("manufacturer", c.c_uint8), ("name", c.c_uint8),
                ("serial", c.c_uint8), ("configurations", c.c_uint8)]


def main():
    usb = c.CDLL("/opt/homebrew/lib/libusb-1.0.dylib")
    usb.libusb_init.argtypes = [c.POINTER(c.c_void_p)]
    usb.libusb_get_device_list.argtypes = [c.c_void_p, c.POINTER(c.POINTER(c.c_void_p))]
    usb.libusb_get_device_list.restype = c.c_ssize_t
    usb.libusb_get_device_descriptor.argtypes = [c.c_void_p, c.POINTER(Descriptor)]
    usb.libusb_open.argtypes = [c.c_void_p, c.POINTER(c.c_void_p)]
    usb.libusb_control_transfer.argtypes = [c.c_void_p, c.c_uint8, c.c_uint8,
                                          c.c_uint16, c.c_uint16, c.c_void_p,
                                          c.c_uint16, c.c_uint]
    usb.libusb_close.argtypes = [c.c_void_p]
    usb.libusb_free_device_list.argtypes = [c.POINTER(c.c_void_p), c.c_int]
    usb.libusb_exit.argtypes = [c.c_void_p]
    context = c.c_void_p()
    result = usb.libusb_init(c.byref(context))
    if result:
        raise RuntimeError(f"libusb initialization failed: {result}")
    devices = c.POINTER(c.c_void_p)()
    try:
        count = usb.libusb_get_device_list(context, c.byref(devices))
        if count < 0:
            raise RuntimeError(f"USB enumeration failed: {count}")
        for index in range(count):
            descriptor = Descriptor()
            if usb.libusb_get_device_descriptor(devices[index], c.byref(descriptor)):
                continue
            if (descriptor.vendor, descriptor.product) != (0x1409, 0x3370):
                continue
            handle = c.c_void_p()
            result = usb.libusb_open(devices[index], c.byref(handle))
            if result:
                raise RuntimeError(f"Opening sensor failed: {result}")
            try:
                buffer = c.create_string_buffer(40)
                result = usb.libusb_control_transfer(handle, 0xC0, 0xB1, 0, 0,
                                                    buffer, 40, 2000)
                if result < 0:
                    raise RuntimeError(f"Identity request failed: {result}")
                raw = buffer.raw[:result]
                serial = re.search(rb"\d{10}", raw)
                reading = {"usb_id": "1409:3370", "bytes_read": result,
                           "serial": serial.group().decode() if serial else None,
                           "identity_hex": raw.hex(), "image_acquired": False,
                           "wavefront_acquired": False}
                output = Path(__file__).with_name("identity.json")
                output.write_text(json.dumps(reading, indent=2) + "\n")
                print(json.dumps(reading, indent=2))
                return
            finally:
                usb.libusb_close(handle)
        raise RuntimeError("Sensor not visible to libusb; run with device access outside the app sandbox.")
    finally:
        if devices:
            usb.libusb_free_device_list(devices, 1)
        usb.libusb_exit(context)


if __name__ == "__main__":
    main()
