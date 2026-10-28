"""Display-only saturation overlay; raw pixels remain unchanged."""
import io
import numpy as np
from PIL import Image


def camera_preview(image):
    gray=Image.fromarray(image)
    gray.thumbnail((1024,1024))
    # Pool before painting so even a single clipped source pixel remains
    # visible when the preview is downsampled.
    mask=Image.fromarray(np.where(image>=254,255,0).astype(np.uint8))
    mask=mask.resize(gray.size,Image.Resampling.BOX)
    rgb=np.asarray(gray.convert('RGB')).copy()
    rgb[np.asarray(mask)>0]=[255,32,32]
    output=io.BytesIO();Image.fromarray(rgb).save(output,format='PNG')
    return output.getvalue()
