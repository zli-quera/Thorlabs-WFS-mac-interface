import ctypes as c
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
import libusb_loader as loader
from usb_transport import USB,USBError,DeviceDescriptor

class LoaderTests(unittest.TestCase):
    def test_explicit_missing_path_does_not_fall_back(self):
        with tempfile.TemporaryDirectory() as directory,patch.dict(loader.os.environ,{'WFS_LIBUSB_PATH':str(Path(directory)/'absent.dll')},clear=True):
            with self.assertRaisesRegex(RuntimeError,'does not name a file'):loader.library_candidates('win32')
    def test_windows_uses_qualified_dll_and_reports_architecture_error(self):
        with patch.dict(loader.os.environ,{},clear=True):
            candidates=loader.library_candidates('win32')
            self.assertEqual(len(candidates),1);self.assertTrue(Path(candidates[0]).is_absolute())
            self.assertEqual(Path(candidates[0]).name,'libusb-1.0.dll')
        with patch.object(loader.platform,'machine',return_value='AMD64'),patch.object(loader.struct,'calcsize',return_value=8),patch.object(loader.c,'CDLL',side_effect=OSError('wrong DLL architecture')),patch.dict(loader.os.environ,{},clear=True):
            with self.assertRaisesRegex(RuntimeError,'x64 libusb-1.0.dll'):loader.load_libusb('win32')
        with patch.object(loader.struct,'calcsize',return_value=4):
            with self.assertRaisesRegex(RuntimeError,'requires x64 Python'):loader.load_libusb('win32')
    def test_macos_library_discovery_and_platform_labels(self):
        with patch.dict(loader.os.environ,{},clear=True),patch.object(loader,'find_library',return_value='/test/libusb.dylib'):
            self.assertEqual(loader.library_candidates('darwin')[0],'/test/libusb.dylib')
        self.assertEqual(loader.backend_name('win32'),'windows-libusb')
        self.assertEqual(loader.platform_label('win32'),'Windows')

class TransportTests(unittest.TestCase):
    def library(self,configuration=1,open_status=0):
        lib=SimpleNamespace()
        for name in ('init','exit','get_device_list','free_device_list','get_device_descriptor','open','get_configuration','close','set_configuration','claim_interface','set_interface_alt_setting','release_interface','clear_halt','control_transfer','bulk_transfer'):
            setattr(lib,'libusb_'+name,Mock(return_value=0))
        lib.array=(c.c_void_p*1)(22)
        def initialize(pointer):c.cast(pointer,c.POINTER(c.c_void_p))[0]=c.c_void_p(11);return 0
        def listing(ctx,pointer):c.cast(pointer,c.POINTER(c.POINTER(c.c_void_p)))[0]=c.cast(lib.array,c.POINTER(c.c_void_p));return 1
        def descriptor(device,pointer):
            d=c.cast(pointer,c.POINTER(DeviceDescriptor)).contents
            d.idVendor=0x1409;d.idProduct=0x3370;return 0
        def open_device(device,pointer):c.cast(pointer,c.POINTER(c.c_void_p))[0]=c.c_void_p(33);return open_status
        def get_configuration(handle,pointer):c.cast(pointer,c.POINTER(c.c_int))[0]=configuration;return 0
        lib.libusb_init.side_effect=initialize;lib.libusb_get_device_list.side_effect=listing
        lib.libusb_get_device_descriptor.side_effect=descriptor;lib.libusb_open.side_effect=open_device
        lib.libusb_get_configuration.side_effect=get_configuration
        return lib
    def test_windows_avoids_configuration_reset_and_macos_workaround(self):
        lib=self.library();usb=USB(library=lib,system='win32')
        usb.control=Mock(side_effect=[b'4110057336',bytes.fromhex('090220000101008032')])
        self.assertTrue(usb.open());usb.claim()
        self.assertEqual(usb.control.call_count,2)
        lib.libusb_set_configuration.assert_not_called()
        lib.libusb_claim_interface.assert_called_once()
        lib.libusb_free_device_list.assert_called_once()
        usb.close();lib.libusb_release_interface.assert_called_once();lib.libusb_exit.assert_called_once()
    def test_macos_keeps_link_power_workaround(self):
        lib=self.library();usb=USB(library=lib,system='darwin');usb.control=Mock()
        usb.configure();usb.disable_link_power_management()
        lib.libusb_set_configuration.assert_called_once()
        self.assertEqual([call.args[2] for call in usb.control.call_args_list],[48,49])
        usb.close()
    def test_windows_open_error_explains_binding_and_frees_list(self):
        lib=self.library(open_status=-12);usb=USB(library=lib,system='win32')
        with self.assertRaisesRegex(USBError,'WinUSB.*NOT_SUPPORTED'):usb.open()
        lib.libusb_free_device_list.assert_called_once();usb.close()
    def test_unexpected_configuration_is_not_changed(self):
        lib=self.library(configuration=2);usb=USB(library=lib,system='win32')
        with self.assertRaisesRegex(RuntimeError,'Unexpected Windows USB configuration'):usb.configure()
        lib.libusb_set_configuration.assert_not_called();usb.close()
        self.assertEqual(c.sizeof(DeviceDescriptor),18)

if __name__=='__main__':unittest.main()
