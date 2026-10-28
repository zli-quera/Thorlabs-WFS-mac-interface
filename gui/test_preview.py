import io,unittest
import numpy as np
from PIL import Image
from preview import camera_preview

class PreviewTests(unittest.TestCase):
    def test_single_saturated_pixel_survives_downsampling_without_changing_raw(self):
        image=np.full((2048,2048),80,dtype=np.uint8);image[100,100]=255
        image[200,200]=254
        original=image.copy()
        preview=np.array(Image.open(io.BytesIO(camera_preview(image))))
        np.testing.assert_array_equal(image,original)
        self.assertEqual(preview.shape,(1024,1024,3))
        np.testing.assert_array_equal(preview[50,50],[255,32,32])
        np.testing.assert_array_equal(preview[100,100],[255,32,32])
        np.testing.assert_array_equal(preview[0,0],[80,80,80])

if __name__=='__main__':unittest.main()
