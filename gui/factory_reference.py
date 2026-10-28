"""Factory reference for full-resolution WFS40 frames.

The order/scales of corrections follow the WFS 6.3 reference-grid calculation.
No grid position, rotation or pitch is fitted to the measured image.
"""
import numpy as np
from scipy.spatial import cKDTree
from analysis import make_reference, Spots, MATCH_WARNING_FRACTION


def corrected_grid(x,y,calibration):
    x=np.asarray(x,dtype=float).copy();y=np.asarray(y,dtype=float).copy();c=calibration
    x+=x*c['grid_correction_0_ppm']*1e-6
    y-=y*c['grid_correction_0_ppm']*1e-6
    x+=y*c['grid_correction_45_ppm']*1e-6
    y+=x*c['grid_correction_45_ppm']*1e-6
    x+=x*c['grid_pitch_ppm']*1e-6
    y+=y*c['grid_pitch_ppm']*1e-6
    angle=-c['grid_rotation_mdeg']*.001*.017453292
    x,y=x*np.cos(angle)-y*np.sin(angle),x*np.sin(angle)+y*np.cos(angle)
    k=c['trefoil_y_ppb']*1e-9
    x+=2*x*y*k
    y+=(x*x-y*y)*k
    k=c['trefoil_x_ppb']*1e-9
    x+=(x*x-y*y)*k
    y-=2*x*y*k
    k=c['coma_y_ppb']*1e-9
    x+=2*x*y*k
    y+=(x*x+3*y*y)*k
    k=c['coma_x_ppb']*1e-9
    x+=(3*x*x+y*y)*k
    y+=2*x*y*k
    return np.column_stack((x+c['spot_offset_x_px'],y+c['spot_offset_y_px']))


def reference_from_factory(spots,shape,profile,array_index=None):
    if tuple(shape)!=(2048,2048):
        raise ValueError('Factory reference currently supports full 2048 × 2048 WFS40 frames only')
    arrays=profile['arrays']
    if array_index is None:
        if len(arrays)!=1:raise ValueError('Select the physically installed MLA from the factory array records')
        cal=arrays[0]
    else:cal=next(a for a in arrays if a['index']==array_index)
    pitch=cal['lenslet_pitch_um']/cal['pixel_um']
    limit=int(np.ceil(max(shape)/pitch/2))+2
    ix,iy=np.meshgrid(np.arange(-limit,limit+1),np.arange(-limit,limit+1))
    grid=corrected_grid(ix.ravel()*pitch,iy.ravel()*pitch,cal)+np.array([shape[1]/2,shape[0]/2])
    inside=(grid[:,0]>=0)&(grid[:,0]<shape[1])&(grid[:,1]>=0)&(grid[:,1]<shape[0])
    grid=grid[inside]
    if len(spots.xy)<8:raise ValueError('Too few usable spots for a factory-reference fit')
    distances,indices=cKDTree(grid).query(spots.xy)
    selected=np.unique(indices)
    if len(selected)<8:
        raise ValueError('Too few distinct lenslets to fit a wavefront')
    warnings=[]
    if np.any(distances>MATCH_WARNING_FRACTION*pitch):
        warnings.append('Too tilted — lenslet assignment may be unreliable; absolute tilt can wrap by a lenslet pitch')
    if len(selected)<.5*len(spots.xy):
        warnings.append('Many spots map to the same lenslet — assignment may be unreliable')
    # Restrict the pupil to illuminated lenslets, but retain their factory
    # coordinates unchanged. This does not use the measured image as a flat.
    xy=grid[selected]
    refspots=Spots(xy,np.ones(len(xy)),np.ones(len(xy)),0.,0.,0.,0.)
    ref=make_reference(refspots,shape,cal['pixel_um'])
    ref.update(kind='factory_calibrated_grid',factory_sha256=profile['sha256'],
               sensor_model=profile['model'],thorlabs_serial=profile['thorlabs_serial'],
               array_name=cal['name'],array_index=cal['index'],focal_mm=cal['focal_mm'],
               pitch_px=pitch,illuminated_lenslets=len(selected),
               factory_grid_lenslets=len(grid),warnings=warnings,match_distance_limit_px=None,unmatched_measured_spots=0)
    return ref
