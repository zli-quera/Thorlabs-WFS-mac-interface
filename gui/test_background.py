import io,unittest
import numpy as np
from PIL import Image
from background import subtract_background
from analysis import detect_spots
from preview import camera_preview

class BackgroundTests(unittest.TestCase):
    def test_automatic_subtraction_preserves_spots_and_raw(self):
        yy,xx=np.mgrid[:256,:256]
        background=30+.03*xx+.02*yy
        signal=np.zeros_like(background)
        for x in range(32,240,32):
            for y in range(32,240,32):signal+=150*np.exp(-((xx-x)**2+(yy-y)**2)/(2*1.7**2))
        raw=np.rint(background+signal).astype(np.uint8);original=raw.copy()
        image,level=subtract_background(raw,True)
        np.testing.assert_array_equal(raw,original)
        self.assertGreater(level,30);self.assertLess(np.median(image),3)
        spots=detect_spots(image)
        self.assertEqual(len(spots.xy),49)
        expected=np.array([(x,y) for y in range(32,240,32) for x in range(32,240,32)])
        from scipy.spatial import cKDTree
        self.assertLess(cKDTree(spots.xy).query(expected)[0].max(),.15)
        unchanged,level=subtract_background(raw,False)
        np.testing.assert_array_equal(unchanged,raw);self.assertEqual(level,0)
    def test_subtraction_cannot_hide_raw_clipping(self):
        yy,xx=np.mgrid[:64,:64]
        raw=np.rint(40+230*np.exp(-((xx-32)**2+(yy-32)**2)/8)).clip(0,255).astype(np.uint8)
        image,_=subtract_background(raw,True)
        self.assertLess(image.max(),254)
        spots=detect_spots(image,saturation_source=raw)
        self.assertEqual(len(spots.xy),0);self.assertGreater(spots.saturated_fraction,0)
        preview=np.array(Image.open(io.BytesIO(camera_preview(image,saturation_source=raw))))
        np.testing.assert_array_equal(preview[32,32],[255,32,32])

if __name__=='__main__':unittest.main()
