"""Checks decoding against a recorded real instrument frame, without hardware."""
import hashlib
from pathlib import Path
import unittest
from camera import Camera
from trace import records

class FrameProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packets=[]
        path=Path(__file__).with_name('usb_trace_initial.bin')
        if not path.exists():raise unittest.SkipTest('Instrument trace fixture unavailable')
        for r in records(path):
            if r['event']==1 and r['ep']==0x82 and r['seq']>=6402:
                cls.packets.append(r['data'])
                if r['data'][:4]==b'U3VT':break
        cls.expected=b''.join(cls.packets[1:-2])
    def camera_with_packets(self,packets):
        class RecordedUSB:
            def __init__(self):self.packets=iter(packets)
            def read(self,endpoint,length):
                if endpoint!=0x82:raise AssertionError('Wrong image endpoint')
                data=next(self.packets)
                if len(data)>length:raise AssertionError('Request too small for packet')
                return data
        cam=Camera.__new__(Camera);cam.usb=RecordedUSB()
        return cam
    def test_real_sensor_frame(self):
        cam=self.camera_with_packets(self.packets)
        pixels,leader,metadata,trailer=cam._read_image()
        self.assertEqual(len(pixels),2048*2048)
        self.assertEqual(hashlib.sha256(pixels).digest(),hashlib.sha256(self.expected).digest())
        self.assertEqual(len(metadata),60)
    def test_incomplete_frame_never_accepted(self):
        packets=list(self.packets);packets[-1]=b'broken trailer'
        with self.assertRaisesRegex(RuntimeError,'trailer'):
            self.camera_with_packets(packets)._read_image()
        packets=list(self.packets);packets[0]=b'X'+packets[0][1:]
        with self.assertRaisesRegex(RuntimeError,'leader'):
            self.camera_with_packets(packets)._read_image()

if __name__=='__main__':unittest.main()
