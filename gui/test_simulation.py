import unittest
import numpy as np
from analysis import analyze,detect_spots
from factory_reference import reference_from_factory
from simulation import Simulator,DEFAULTS,trace,F,DISTANCE
import test_factory_reference as fixtures

class SimulationTests(unittest.TestCase):
    def setUp(self):
        fixture=fixtures.FactoryGridTests();fixture.setUp()
        self.profile=fixture.profile
        self.profile['arrays'][0].update(grid_pitch_ppm=-140,grid_correction_0_ppm=-20,
                                         grid_correction_45_ppm=-20,trefoil_y_ppb=-15,coma_y_ppb=-25)
        self.sim=Simulator(self.profile)
    def fit(self,**changes):
        meta,pixels=self.sim.capture({**DEFAULTS,**changes})
        image=np.frombuffer(pixels,np.uint8).reshape(2048,2048)
        spots=detect_spots(image)
        ref=reference_from_factory(spots,image.shape,self.profile)
        result,_=analyze(image,dict(focal_mm=5.,tilt_limit_urad=500),ref,spots=spots)
        self.assertTrue(result['visible'],result['reason'])
        return result,ref
    def test_factory_offsets_cancel_at_nominal_alignment(self):
        r,_=self.fit()
        self.assertLess(abs(r['tilt']['x_urad']),1)
        self.assertLess(abs(r['tilt']['y_urad']),1)
        self.assertLess(r['raw_rms_um'],.001)
        self.assertGreater(r['matched_count'],350)
    def test_xy_and_defocus_recovered_from_quantized_camera(self):
        r,_=self.fit(x_um=50,y_um=-40)
        np.testing.assert_allclose([r['tilt']['x_urad'],r['tilt']['y_urad']],[-400,320],atol=3)
        self.assertTrue(r['tilt']['removed'])
        r,ref=self.fit(z_mm=1)
        radius=ref['radius_px']*5.5/1000
        k=-1/(F*(F+1))
        expected=k/(1+DISTANCE*k)*radius**2/(4*np.sqrt(3))*1000
        self.assertAlmostEqual(r['coefficients'][2]['um'],expected,delta=.001)
        r,_=self.fit(x_um=100)
        self.assertFalse(r['tilt']['removed'])
    def test_lens_rotation_is_not_mirror_steering(self):
        flat,_=self.fit()
        for axis in ('tip_mrad','tilt_mrad'):
            r,_=self.fit(**{axis:20})
            self.assertLess(r['tilt']['magnitude_urad'],100)
            self.assertGreater(max(abs(c['um']) for c in r['coefficients'][2:]),.0003)
        a=self.sim.capture(DEFAULTS);b=self.sim.capture(DEFAULTS)
        self.assertEqual(a[1],b[1]);self.assertGreater(b[0]['sequence'],a[0]['sequence'])

if __name__=='__main__':unittest.main()
