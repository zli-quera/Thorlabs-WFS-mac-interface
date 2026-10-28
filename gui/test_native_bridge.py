import tempfile,time,unittest
from unittest.mock import patch
from native_bridge import CameraBridge

class BridgeTests(unittest.TestCase):
    def test_viewer_handoff_does_not_open_frame_file(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge=CameraBridge(directory);meta={'time':time.time()};pixels=b'test pixels'
            bridge.capture=(meta,pixels)
            with patch('pathlib.Path.open',side_effect=AssertionError('Viewer must not hold a frame file open')):
                self.assertEqual(bridge.read(),(meta,pixels))
            bridge.stop();self.assertIsNone(bridge.read())
            bridge.stopping.clear();meta['time']=time.time()-4
            self.assertIsNone(bridge.read())

if __name__=='__main__':unittest.main()
