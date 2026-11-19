"""Rough elliptical Gaussian envelope fit to integrated lenslet-spot flux.

I = I0 exp(-2 r^2 / w^2), so a principal-axis 1/e^2 diameter is 4 sigma.
This estimates the illuminated envelope, not an individual focal-spot width.
"""
import numpy as np
from scipy.optimize import least_squares
from scipy.spatial import cKDTree


def beam_profile(spots, shape, pixel_um, *, saturated=False, diagnostic=False):
    missing=dict(visible=False,reason='Too few spots for a beam profile',warnings=[])
    if diagnostic:return {**missing,'reason':'Diagnostic image'}
    if pixel_um is None or not np.isfinite(pixel_um) or pixel_um<=0:
        return {**missing,'reason':'Sensor pixel size is unavailable'}
    xy=np.asarray(spots.xy);flux=np.asarray(spots.flux)
    good=np.isfinite(xy).all(axis=1)&np.isfinite(flux)&(flux>0)
    xy,flux=xy[good],flux[good]
    if len(xy)<20:return missing
    if np.percentile(flux,90)/np.percentile(flux,10)<1.3:
        return {**missing,'reason':'Envelope is too flat to estimate a Gaussian diameter'}
    origin=np.mean(xy,axis=0)
    scale=np.max(np.ptp(xy,axis=0))
    if scale<=0:return missing
    p=(xy-origin)/scale;x,y=p.T
    matrix=np.column_stack((np.ones(len(x)),x,y,x*x,x*y,y*y))
    if np.linalg.matrix_rank(matrix)<6:
        return {**missing,'reason':'Insufficient spatial coverage for a beam profile'}
    logflux=np.log(flux)
    initial=np.linalg.lstsq(matrix,logflux,rcond=None)[0]
    fit=least_squares(lambda c:matrix@c-logflux,initial,jac=lambda c:matrix,
                      loss='soft_l1',f_scale=.15,max_nfev=50)
    c=fit.x
    precision=-np.array([[2*c[3],c[4]],[c[4],2*c[5]]])
    eigenvalues,vectors=np.linalg.eigh(precision)
    if not fit.success or np.min(eigenvalues)<=0:
        return {**missing,'reason':'Envelope does not support a Gaussian diameter fit'}
    sigma=scale/np.sqrt(eigenvalues)
    center=origin+scale*np.linalg.solve(precision,c[1:3])
    diameters=4*sigma*pixel_um/1000
    if np.max(diameters)>4*max(shape)*pixel_um/1000:
        return {**missing,'reason':'Gaussian diameter is poorly constrained by the visible envelope'}
    residual=float(np.median(np.abs(matrix@c-logflux)))
    pitch=float(np.median(cKDTree(xy).query(xy,k=2)[0][:,1]))
    warnings=[]
    if saturated:warnings.append('Saturated spots omitted; diameter may be biased. Lower exposure.')
    covariance=vectors@np.diag(sigma*sigma)@vectors.T
    radii=2*np.sqrt(np.diag(covariance))
    sensor_size=np.array(shape[::-1])
    if np.any(center-radii<pitch/2) or np.any(center+radii>sensor_size-1-pitch/2):
        warnings.append('Fitted 1/e² envelope reaches the sensor edge; beam may be clipped.')
    if np.any(xy.min(axis=0)<pitch/2) or np.any(xy.max(axis=0)>sensor_size-1-pitch/2):
        if not any('clipped' in w for w in warnings):warnings.append('Detected light reaches the sensor edge; beam may be clipped.')
    if residual>.2:warnings.append('Envelope differs substantially from a Gaussian; treat diameter as indicative only.')
    if np.min(sigma)<pitch:warnings.append('Beam spans too few lenslets for a well sampled diameter.')
    peak_log=c[0]+.5*c[1:3]@np.linalg.solve(precision,c[1:3])
    if np.min(logflux)>peak_log-1.5:
        warnings.append('Detected spots do not reach the 1/e² intensity level; diameter is extrapolated.')
    axis=vectors[:,0]
    angle=float((np.degrees(np.arctan2(axis[1],axis[0]))+90)%180-90)
    return dict(visible=True,reason='',method='elliptical Gaussian fit to integrated spot flux',
                diameter_major_mm=float(diameters[0]),diameter_minor_mm=float(diameters[1]),
                angle_deg=angle,center_px=center.tolist(),spot_count=len(xy),
                log_fit_residual=residual,warnings=warnings,reliable=not warnings)
