"""Resolve libusb without importing or opening a USB device at module import."""
import ctypes as c
from ctypes.util import find_library
import os
from pathlib import Path
import platform
import struct
import sys

ROOT=Path(__file__).resolve().parents[1]


def platform_label(system=None):
    system=sys.platform if system is None else system
    return {'win32':'Windows','darwin':'macOS','linux':'Linux'}.get(system,system)


def backend_name(system=None):
    system=sys.platform if system is None else system
    return {'win32':'windows','darwin':'macos','linux':'linux'}.get(system,system)+'-libusb'


def library_candidates(system=None):
    system=sys.platform if system is None else system
    override=os.environ.get('WFS_LIBUSB_PATH')
    if override:
        path=Path(override).expanduser().resolve()
        if not path.is_file():raise RuntimeError(f'WFS_LIBUSB_PATH does not name a file: {path}')
        return [str(path)]
    if system=='win32':
        # Do not search the current directory/PATH for an unqualified DLL.
        return [str(ROOT/'native/vendor/libusb-1.0.dll')]
    found=find_library('usb-1.0')
    paths=([found] if found else [])
    if system=='darwin':paths+=['/opt/homebrew/lib/libusb-1.0.dylib','/usr/local/lib/libusb-1.0.dylib']
    elif system.startswith('linux'):paths+=['libusb-1.0.so.0']
    else:raise RuntimeError(f'Unsupported USB host platform: {system}')
    return list(dict.fromkeys(paths))


def load_libusb(system=None):
    system=sys.platform if system is None else system
    if system=='win32' and (struct.calcsize('P')!=8 or platform.machine().lower() not in ('amd64','x86_64')):
        raise RuntimeError('Windows USB support currently requires x64 Python on x64 Windows')
    errors=[]
    for path in library_candidates(system):
        try:
            # x64 Windows has one calling convention; CDLL is also used on macOS.
            return c.CDLL(path)
        except OSError as error:errors.append(f'{path}: {error}')
    hint=('Install the x64 libusb-1.0.dll at native/vendor/libusb-1.0.dll or set '
          'WFS_LIBUSB_PATH to its full path. See docs/windows_setup.md.' if system=='win32'
          else 'Install libusb, or set WFS_LIBUSB_PATH to its full path.')
    raise RuntimeError('Could not load libusb. '+hint+' Details: '+'; '.join(errors))
