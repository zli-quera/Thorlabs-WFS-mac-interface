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


class TiltTests(unittest.TestCase):
    setUp=ReconstructionTests.setUp
    render=ReconstructionTests.render
    def test_uniform_translation_has_correct_angle_and_conditional_removal(self):
        shift=np.array([.25,-.4])
        image=self.render(np.array(self.ref['xy'])+shift)
        expected=np.arctan(shift*5.5/5200)*1e6
        removed,_=analyze(image,{**self.cfg,'tilt_limit_urad':1000},self.ref)
        self.assertTrue(removed['visible'],removed['reason'])
        self.assertTrue(removed['tilt']['removed'])
        at_boundary,_=analyze(image,{**self.cfg,'tilt_limit_urad':removed['tilt']['magnitude_urad']},self.ref)
        self.assertTrue(at_boundary['tilt']['removed'])
        np.testing.assert_allclose([removed['tilt']['x_urad'],removed['tilt']['y_urad']],expected,atol=8)
        self.assertLess(removed['rms_um'],removed['raw_rms_um']*.1)
        self.assertTrue(all(c['display_um']==0 for c in removed['coefficients'][:2]))
        retained,_=analyze(image,{**self.cfg,'tilt_limit_urad':100},self.ref)
        self.assertTrue(retained['visible'])
        self.assertFalse(retained['tilt']['removed'])
        self.assertAlmostEqual(retained['rms_um'],retained['raw_rms_um'])
        disabled,_=analyze(image,{**self.cfg,'tilt_limit_urad':1000,'remove_tilt':False},self.ref)
        self.assertFalse(disabled['tilt']['removed'])
        self.assertEqual(disabled['coefficients'],retained['coefficients'])
        dark,_=analyze(np.zeros_like(image),self.cfg,self.ref)
        self.assertIsNone(dark['tilt'])

    def test_mixed_aberrations_survive_tilt_removal(self):
        xy=np.array(self.ref['xy']);r=self.ref['radius_px'];x,y=((xy-self.ref['center'])/r).T
        # Analytic physical gradients of normalized defocus and 0-degree astigmatism.
        defocus,astig=.15,.04
        gradients=np.column_stack(((4*np.sqrt(3)*defocus+2*np.sqrt(6)*astig)*x,
                                   (4*np.sqrt(3)*defocus-2*np.sqrt(6)*astig)*y))/(r*5.5)
        image=self.render(xy+gradients*5200/5.5+np.array([.2,-.1]))
        result,_=analyze(image,{**self.cfg,'tilt_limit_urad':1000},self.ref)
        self.assertTrue(result['visible'],result['reason'])
        self.assertTrue(result['tilt']['removed'])
        self.assertAlmostEqual(result['coefficients'][2]['um'],defocus,delta=.012)
        self.assertAlmostEqual(result['coefficients'][4]['um'],astig,delta=.012)
        self.assertGreater(result['rms_um'],.05)
        for coefficient in result['coefficients'][2:]:
            self.assertEqual(coefficient['um'],coefficient['display_um'])

if __name__=='__main__': unittest.main()
