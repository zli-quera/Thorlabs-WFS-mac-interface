import unittest
import numpy as np
from analysis import analyze,detect_spots
from factory_reference import corrected_grid,reference_from_factory

class FactoryGridTests(unittest.TestCase):
    def setUp(self):
        self.cal=dict(index=0,name='synthetic',pixel_um=5.5,lenslet_pitch_um=150.,focal_mm=5.,
                      spot_offset_x_px=-12.,spot_offset_y_px=-13.,grid_correction_0_ppm=0.,
                      grid_correction_45_ppm=0.,grid_rotation_mdeg=0.,grid_pitch_ppm=0.,
                      trefoil_y_ppb=0.,trefoil_x_ppb=0.,coma_y_ppb=0.,coma_x_ppb=0.)
        self.profile=dict(arrays=[self.cal],model='WFS40-7AR',thorlabs_serial='test',sha256='synthetic')
    def test_origin_and_signed_linear_corrections(self):
        xy=corrected_grid(np.array([0.,100.]),np.array([0.,200.]),self.cal)
        np.testing.assert_allclose(xy,[[-12,-13],[88,187]])
        xy=corrected_grid(np.array([100.]),np.array([200.]),{**self.cal,'grid_correction_0_ppm':1000.,'grid_pitch_ppm':-1000.})
        np.testing.assert_allclose(xy,[[100*1.001*.999-12,200*.999*.999-13]])
    def test_factory_grid_is_not_fitted_to_measured_tilt(self):
        image=np.zeros((2048,2048),dtype=float)
        pitch=150/5.5;shift=np.array([-12.,-12.])
        for i in range(-6,7):
            for j in range(-6,7):
                x,y=np.array([1024+i*pitch-12,1024+j*pitch-13])+shift
                cx,cy=round(x),round(y);yy,xx=np.mgrid[cy-6:cy+7,cx-6:cx+7]
                image[cy-6:cy+7,cx-6:cx+7]+=180*np.exp(-((xx-x)**2+(yy-y)**2)/(2*1.7**2))
        image=np.rint(image).astype(np.uint8);spots=detect_spots(image)
        ref=reference_from_factory(spots,image.shape,self.profile)
        result,_=analyze(image,dict(focal_mm=5.,tilt_limit_urad=100),ref)
        self.assertTrue(result['visible'],result['reason'])
        self.assertEqual(result['matched_count'],169)
        self.assertFalse(result['reliable'])
        self.assertTrue(any('Too tilted' in w for w in result['warnings']))
        self.assertIsNone(ref['match_distance_limit_px'])
        self.assertFalse(result['tilt']['removed'])
        expected=np.arctan(shift*5.5/5000)*1e6
        np.testing.assert_allclose([result['tilt']['x_urad'],result['tilt']['y_urad']],expected,atol=8)
        self.assertEqual(ref['kind'],'factory_calibrated_grid')
        with self.assertRaisesRegex(ValueError,'2048'):reference_from_factory(spots,(1024,1024),self.profile)

if __name__=='__main__':unittest.main()
