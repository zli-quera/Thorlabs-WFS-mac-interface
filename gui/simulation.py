"""Ideal collimator ray model -> factory-referenced, quantized WFS camera frames.

Distances in mm, angles in mrad. The lens is a zero-thickness, aberration-free
125 mm collimator rotated about its optical center. It subtracts the spherical
wave of an on-axis point at its front focal point in lens-local coordinates.
This is an alignment simulator, not an AC254 prescription / wavelength model.
"""
from functools import lru_cache
import time
import numpy as np
from scipy.interpolate import LinearNDInterpolator
from factory_reference import corrected_grid

DEFAULTS=dict(x_um=0.,y_um=0.,z_mm=0.,tip_mrad=0.,tilt_mrad=0.)
LIMITS=dict(x_um=(-500,500),y_um=(-500,500),z_mm=(-5,5),tip_mrad=(-30,30),tilt_mrad=(-30,30))
FPS=14.
F=125.
DISTANCE=100.
PUPIL_MM=1.75


def rotation(tip,tilt):
    # Tip: rotation about camera X. Tilt: rotation about camera Y.
    a,b=tip/1000,tilt/1000
    cx,sx=np.cos(a),np.sin(a);cy,sy=np.cos(b),np.sin(b)
    return np.array([[cy,sy*sx,sy*cx],[0,cx,-sx],[-sy,cy*sx,cy*cx]])


def trace(parameters,xy):
    """Trace lens samples to the WFS, return intercepts and physical slopes."""
    r=rotation(parameters['tip_mrad'],parameters['tilt_mrad'])
    source=np.array([parameters['x_um']/1000,parameters['y_um']/1000,-F-parameters['z_mm']])
    local_source=source@r
    points=np.column_stack((xy,np.zeros(len(xy))))
    incoming=points-local_source
    incoming/=np.linalg.norm(incoming,axis=1)[:,None]
    # Ideal focusing phase: exactly flat at centered nominal focus.
    tangents=incoming[:,:2]-xy/np.sqrt(F*F+np.sum(xy*xy,axis=1))[:,None]
    outgoing=np.column_stack((tangents,np.sqrt(1-np.sum(tangents*tangents,axis=1))))@r.T
    points=points@r.T
    slopes=outgoing[:,:2]/outgoing[:,2,None]
    intercept=points[:,:2]+(DISTANCE-points[:,2,None])*slopes
    return intercept,slopes


class Simulator:
    def __init__(self,profile):
        if len(profile['arrays'])!=1:raise ValueError('Test mode requires one selected factory MLA')
        self.profile=profile;self.cal=profile['arrays'][0];self.sequence=0
        pitch=self.cal['lenslet_pitch_um']/self.cal['pixel_um']
        ix,iy=np.meshgrid(np.arange(-16,17),np.arange(-16,17))
        ideal=np.column_stack((ix.ravel()*pitch,iy.ravel()*pitch))
        self.reference=corrected_grid(ideal[:,0],ideal[:,1],self.cal)+1024
        a=np.linspace(-3,3,45);xx,yy=np.meshgrid(a,a)
        self.lens_samples=np.column_stack((xx.ravel(),yy.ravel()))
        self.started=time.monotonic()

    @lru_cache(maxsize=2)
    def render(self,values):
        parameters=dict(zip(DEFAULTS,values))
        intercept,slopes=trace(parameters,self.lens_samples)
        # Pupil follows the fiber's central ray at the WFS; no true slope
        # or reference coordinates are supplied to the reconstruction.
        center,_=trace(parameters,np.zeros((1,2)))
        sensor_xy=(self.reference-1024)*self.cal['pixel_um']/1000
        selected=np.linalg.norm(sensor_xy-center[0],axis=1)<=PUPIL_MM
        xy=self.reference[selected]
        gradients=LinearNDInterpolator(intercept,slopes)(sensor_xy[selected])
        if not np.isfinite(gradients).all():raise ValueError('Simulated beam left the modeled aperture')
        xy=xy+gradients*self.cal['focal_mm']*1000/self.cal['pixel_um']
        image=np.full((2048,2048),3.,dtype=np.float32)
        for x,y in xy:
            cx,cy=int(round(x)),int(round(y))
            if cx<9 or cy<9 or cx>=2039 or cy>=2039:continue
            yy,xx=np.mgrid[cy-8:cy+9,cx-8:cx+9]
            image[cy-8:cy+9,cx-8:cx+9]+=180*np.exp(-((xx-x)**2+(yy-y)**2)/(2*1.7**2))
        # Quantization is retained; random noise is disabled for reproducible tests.
        return np.rint(np.clip(image,0,255)).astype(np.uint8).tobytes()

    def capture(self,parameters):
        pixels=self.render(tuple(parameters[k] for k in DEFAULTS))
        self.sequence+=1
        return dict(time=time.time(),width=2048,height=2048,pixel_um=self.cal['pixel_um'],
                    source='simulation',sensor=self.profile['model'],serial=self.profile['thorlabs_serial'],
                    sequence=self.sequence,target_fps=FPS,simulation=dict(parameters)),pixels
