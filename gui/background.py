"""Estimate smooth background between spots and interpolate beneath them."""
import numpy as np
from scipy import ndimage
from PIL import Image


def subtract_background(image,enabled=False):
    if not enabled:return image,0.
    # Sparse sampling and a robust local percentile suppress bright spot cores.
    # Smooth interpolation supplies an estimate under those cores as well.
    small=np.asarray(image[::16,::16],dtype=np.float32)
    low=ndimage.percentile_filter(small,30,size=3,mode='nearest')
    low=ndimage.gaussian_filter(low,1,mode='nearest')
    background=np.asarray(Image.fromarray(low).resize((image.shape[1],image.shape[0]),Image.Resampling.BILINEAR))
    corrected=np.rint(np.clip(image.astype(np.float32)-background,0,255)).astype(np.uint8)
    return corrected,float(np.median(background))
