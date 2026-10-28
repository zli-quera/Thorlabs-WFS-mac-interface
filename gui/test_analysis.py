import unittest
import numpy as np
from analysis import analyze, detect_spots, make_reference, basis

class ReconstructionTests(unittest.TestCase):
    def setUp(self):
        coords=np.arange(80,450,32)
        self.xy=np.array([(x,y) for y in coords for x in coords if (x-256)**2+(y-256)**2<175**2],float)
        self.cfg=dict(threshold_dn=20,min_spots=20,focal_mm=5.2,remove_tilt=True)
        self.flat=self.render(self.xy)
        self.ref=make_reference(detect_spots(self.flat),self.flat.shape,5.5)

    def render(self,xy):
        yy,xx=np.mgrid[:512,:512]
        im=np.zeros((512,512))
        for x,y in xy:
            im+=200*np.exp(-((xx-x)**2+(yy-y)**2)/(2*1.7**2))
        return np.rint(im).astype(np.uint8)

    def test_known_defocus_and_dark_gate(self):
        refxy=np.array(self.ref['xy']); r=self.ref['radius_px']
        x,y=((refxy-self.ref['center'])/r).T
        coeff=np.zeros(14);coeff[2]=.15
        displacement=np.column_stack((basis(x,y,'x')@coeff,basis(x,y,'y')@coeff))/(r*5.5)*5200/5.5
        result,_=analyze(self.render(refxy+displacement),self.cfg,self.ref)
        self.assertTrue(result['visible'],result['reason'])
        self.assertAlmostEqual(result['coefficients'][2]['um'],.15,delta=.012)
        dark,_=analyze(np.zeros_like(self.flat),self.cfg,self.ref)
        self.assertFalse(dark['visible']);self.assertIsNone(dark['wavefront'])

    def test_requires_calibration_and_rejects_uniform_and_diagnostic(self):
        for image,cfg,ref,diag in [(self.flat,self.cfg,None,False),(self.flat,{**self.cfg,'focal_mm':None},self.ref,False),(np.full_like(self.flat,100),self.cfg,self.ref,False),(self.flat,self.cfg,self.ref,True)]:
            result,_=analyze(image,cfg,ref,diag)
            self.assertFalse(result['visible']);self.assertIsNone(result['wavefront'])

if __name__=='__main__': unittest.main()
