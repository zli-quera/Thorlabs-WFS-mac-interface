import unittest
import numpy as np
from analysis import Spots,detect_spots
from beam_profile import beam_profile

class BeamProfileTests(unittest.TestCase):
    def envelope(self,shape=(1024,1024),center=(510,490),sigmas=(110,65),angle=.4):
        xx,yy=np.meshgrid(np.arange(15,shape[1],27.),np.arange(15,shape[0],27.))
        xy=np.column_stack((xx.ravel(),yy.ravel()))
        p=xy-center;c,s=np.cos(angle),np.sin(angle)
        rotated=p@np.array([[c,-s],[s,c]])
        flux=3000*np.exp(-.5*np.sum((rotated/sigmas)**2,axis=1))
        good=flux>100
        return Spots(xy[good],flux[good],np.ones(good.sum()),3.,.5,180.,0.)

    def test_rotated_gaussian_with_missing_tails(self):
        spots=self.envelope()
        # A few grossly brighter sites should not dominate the envelope fit.
        spots.flux[::19]*=3
        result=beam_profile(spots,(1024,1024),5.5)
        self.assertTrue(result['visible'],result['reason'])
        np.testing.assert_allclose([result['diameter_major_mm'],result['diameter_minor_mm']],[2.42,1.43],rtol=.03)
        np.testing.assert_allclose(result['center_px'],[510,490],atol=2)
        self.assertAlmostEqual(result['angle_deg'],np.degrees(.4),delta=2)

    def test_raw_gaussian_spot_image(self):
        shape=(1024,1024);spots=self.envelope()
        image=np.full(shape,3.)
        for (x,y),flux in zip(spots.xy,spots.flux):
            x,y=int(x),int(y);yy,xx=np.mgrid[y-7:y+8,x-7:x+8]
            image[y-7:y+8,x-7:x+8]+=180*flux/3000*np.exp(-((xx-x)**2+(yy-y)**2)/(2*1.5**2))
        result=beam_profile(detect_spots(np.rint(image).astype(np.uint8)),shape,5.5)
        self.assertTrue(result['visible'],result['reason'])
        np.testing.assert_allclose([result['diameter_major_mm'],result['diameter_minor_mm']],[2.42,1.43],rtol=.04)

    def test_clipped_saturated_and_invalid_frames(self):
        result=beam_profile(self.envelope(center=(45,500)),(1024,1024),5.5,saturated=True)
        self.assertTrue(result['visible'])
        self.assertTrue(any('clipped' in w for w in result['warnings']))
        self.assertTrue(any('Saturated' in w for w in result['warnings']))
        self.assertFalse(result['reliable'])
        spots=self.envelope();spots.flux[:]=1
        self.assertFalse(beam_profile(spots,(1024,1024),5.5)['visible'])
        self.assertFalse(beam_profile(detect_spots(np.zeros((128,128),np.uint8)),(128,128),5.5)['visible'])
        self.assertFalse(beam_profile(spots,(1024,1024),None)['visible'])
        self.assertFalse(beam_profile(spots,(1024,1024),5.5,diagnostic=True)['visible'])

if __name__=='__main__':unittest.main()
