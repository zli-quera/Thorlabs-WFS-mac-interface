import gzip,json,unittest
from pathlib import Path
from unittest.mock import Mock
from controls import exposure_value,gain_value,validate,exposure_packet,gain_packet
from camera import Camera

class ControlMathTests(unittest.TestCase):
    def test_recorded_exposures_and_vendor_quantization(self):
        # SDK machine-code comparison: 0.04/.1/.29/1/10/150 ms requests.
        for requested,ticks,actual in [(.04,1,.03096),(.1,20,.092235),(.29,80,.285735),
                                      (1,300,.995235),(10,3092,9.999435),(150,46500,149.990235)]:
            got=exposure_value(requested)
            self.assertEqual(got[0],ticks);self.assertAlmostEqual(got[1],actual,places=10)
        self.assertEqual(gain_value(0),(256,1.))
        self.assertEqual(gain_value(50),(640,2.5))
        self.assertEqual(gain_value(100),(1024,4.))
    def test_invalid_values(self):
        for exposure,gain in [(0,0),(151,0),(float('nan'),0),(10,-1),(10,101),(10,1.5),(10,float('inf'))]:
            with self.assertRaises(ValueError):validate(exposure,gain)

class ControlPacketTests(unittest.TestCase):
    def setUp(self):
        p=Path(__file__).with_name('recipe.json.gz')
        if not p.exists():self.skipTest('Local instrument startup recipe unavailable')
        self.recipe=json.load(gzip.open(p,'rt'))
    def test_default_commands_match_recorded_sdk_commands(self):
        p,_=exposure_packet(self.recipe,10.)
        self.assertIn(p.hex(),self.recipe['initialize'])
        p,_=gain_packet(self.recipe,0)
        self.assertIn(p.hex(),self.recipe['initialize'])
    def test_only_integration_registers_and_tag_change(self):
        base,_=exposure_packet(self.recipe,10);short,_=exposure_packet(self.recipe,.1)
        changes={i for i,(a,b) in enumerate(zip(base,short)) if a!=b}
        allowed=set(range(56,60))
        for reg in (42,43,44,56,57,58):
            marker=bytes.fromhex('140b00000107010800')+bytes([reg])
            allowed.add(base.index(marker)+len(marker))
        self.assertTrue(changes);self.assertTrue(changes<=allowed)
    def test_failed_ack_preserves_applied_metadata(self):
        camera=Camera.__new__(Camera);camera.recipe=self.recipe
        camera.requested_exposure_ms=10.;camera.exposure_ms=9.999435;camera.gain=0;camera.gain_factor=1.
        camera.command=Mock(side_effect=RuntimeError('ACK failed'))
        with self.assertRaisesRegex(RuntimeError,'ACK failed'):camera.set_controls(.1,50)
        self.assertEqual(camera.requested_exposure_ms,10.)
        self.assertEqual(camera.exposure_ms,9.999435);self.assertEqual(camera.gain,0)
        camera.command=Mock();camera.set_controls(.1,50)
        self.assertEqual(camera.command.call_count,2)
        self.assertAlmostEqual(camera.exposure_ms,.092235)
        self.assertEqual(camera.gain_factor,2.5)
        camera.command.reset_mock();camera.set_controls(.1,50);camera.command.assert_not_called()

if __name__=='__main__':unittest.main()
