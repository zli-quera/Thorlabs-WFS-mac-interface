"""Relative Shack–Hartmann reconstruction from measured reference centroids.

Spot displacement / lenslet focal length gives local wavefront slope.
Coordinates and OPD are in micrometres; piston is unobservable and omitted.
No factory reference or lenslet focal length is assumed.
"""
from dataclasses import dataclass
from functools import lru_cache
from math import comb, factorial, sqrt

import numpy as np
from scipy import ndimage
from scipy.spatial import cKDTree, Delaunay, QhullError


MODES = [(1, 1, "Tilt X"), (1, -1, "Tilt Y"), (2, 0, "Defocus"),
         (2, -2, "Astigmatism 45°"), (2, 2, "Astigmatism 0°"),
         (3, -1, "Coma Y"), (3, 1, "Coma X"), (3, -3, "Trefoil Y"),
         (3, 3, "Trefoil X"), (4, 0, "Spherical"),
         (4, 2, "Secondary astigmatism X"), (4, -2, "Secondary astigmatism Y"),
         (4, 4, "Tetrafoil X"), (4, -4, "Tetrafoil Y")]


@dataclass
class Spots:
    xy: np.ndarray
    flux: np.ndarray
    peaks: np.ndarray
    background: float
    noise: float
    peak: float
    saturated_fraction: float


def detect_spots(frame, threshold=20):
    image = np.asarray(frame, dtype=np.float32)
    background = float(np.percentile(image[::4, ::4], 30))
    low = image[::4, ::4]
    low = low[low <= np.percentile(low, 60)]
    noise = max(.5, float(np.median(np.abs(low - np.median(low))) * 1.4826))
    peak = float(image.max())
    saturated = float(np.mean(image >= 254))
    empty = Spots(np.empty((0, 2)), np.empty(0), np.empty(0), background, noise, peak, saturated)
    cutoff = background + max(float(threshold), 5 * noise)
    if peak < cutoff:
        return empty
    labels, count = ndimage.label(image >= cutoff)
    if not count or count > 25000:
        return empty
    indices = np.arange(1, count + 1)
    sizes = np.bincount(labels.ravel(), minlength=count + 1)[1:]
    peaks = ndimage.maximum(image, labels, indices)
    good = (sizes >= 3) & (sizes <= 400) & (peaks < 254)
    indices, peaks = indices[good], np.asarray(peaks)[good]
    if not len(indices):
        return empty
    weights = np.maximum(image - background, 0) * (labels > 0)
    centers = np.asarray(ndimage.center_of_mass(weights, labels, indices))[:, ::-1]
    flux = np.asarray(ndimage.sum(weights, labels, indices))
    snr = flux / np.sqrt(np.maximum(flux + sizes[good] * noise**2, 1))
    good = np.isfinite(centers).all(axis=1) & (snr >= 8)
    return Spots(centers[good], flux[good], peaks[good], background, noise, peak, saturated)


def make_reference(spots, shape, pixel_um):
    if len(spots.xy) < 8:
        raise ValueError("Too few usable spots for a reference.")
    distances = cKDTree(spots.xy).query(spots.xy, k=2)[0][:, 1]
    pitch = float(np.median(distances))
    if not np.isfinite(pitch) or pitch < 5:
        raise ValueError("The spots are too close together to identify lenslets.")
    center = (np.max(spots.xy, axis=0) + np.min(spots.xy, axis=0)) / 2
    radius = float(np.max(np.linalg.norm(spots.xy - center, axis=1)) + pitch * .25)
    return {"xy": spots.xy.tolist(), "shape": list(shape), "pixel_um": float(pixel_um),
            "pitch_px": pitch, "center": center.tolist(), "radius_px": radius,
            "kind": "measured_relative_reference"}


@lru_cache(maxsize=None)
def polynomial(n, signed_m):
    m = abs(signed_m)
    angular = {}
    for k in range(m + 1):
        coefficient = comb(m, k) * (1j**k)
        coefficient = coefficient.imag if signed_m < 0 else coefficient.real
        if coefficient:
            angular[(m - k, k)] = coefficient
    if m == 0:
        angular = {(0, 0): 1.}
    result = {}
    normalization = sqrt(n + 1) * (sqrt(2) if m else 1)
    for s in range((n - m) // 2 + 1):
        radial = ((-1)**s * factorial(n - s) /
                  (factorial(s) * factorial((n + m)//2 - s) * factorial((n - m)//2 - s)))
        q = (n - 2*s - m) // 2
        for j in range(q + 1):
            for (a, b), coefficient in angular.items():
                key = (a + 2*(q-j), b + 2*j)
                result[key] = result.get(key, 0.) + normalization * radial * comb(q, j) * coefficient
    return result


def basis(x, y, derivative=None):
    columns = []
    for n, m, _ in MODES:
        values = np.zeros_like(x, dtype=float)
        for (a, b), coefficient in polynomial(n, m).items():
            if derivative == "x":
                if a:
                    values += coefficient * a * x**(a-1) * y**b
            elif derivative == "y":
                if b:
                    values += coefficient * b * x**a * y**(b-1)
            else:
                values += coefficient * x**a * y**b
        columns.append(values)
    return np.stack(columns, axis=-1)


def analyze(frame, config, reference=None, diagnostic=False):
    spots = detect_spots(frame, config.get("threshold_dn", 20))
    minimum = int(config.get("min_spots", 20))
    result = {"visible": False, "reason": "Signal below threshold", "spot_count": len(spots.xy),
              "spots": spots.xy.tolist(), "peak_dn": spots.peak,
              "background_dn": spots.background, "noise_dn": spots.noise,
              "saturated_fraction": spots.saturated_fraction, "wavefront": None,
              "matched_count": 0, "reference_count": len(reference["xy"]) if reference else 0}
    if diagnostic:
        result["reason"] = "Diagnostic image · wavefront hidden"
        return result, spots
    if len(spots.xy) < minimum:
        result["reason"] = f"Signal below threshold · {len(spots.xy)}/{minimum} usable spots"
        return result, spots
    if spots.saturated_fraction > .02:
        result["reason"] = "Image is saturated · reduce exposure"
        return result, spots
    if not reference:
        result["reason"] = "Set a flat-wavefront reference"
        return result, spots
    if list(frame.shape) != reference["shape"]:
        result["reason"] = "Image size changed · replace the reference"
        return result, spots
    focal_mm = config.get("focal_mm")
    if focal_mm is None or not .05 <= float(focal_mm) <= 1000:
        result["reason"] = "Enter the lenslet focal length"
        return result, spots
    ref = np.asarray(reference["xy"])
    distances, matches = cKDTree(spots.xy).query(ref)
    good = distances < .4 * reference["pitch_px"]
    # Each measured spot can be assigned to only one lenslet.
    selected = []
    used = set()
    for index in np.argsort(distances):
        if good[index] and int(matches[index]) not in used:
            selected.append(index)
            used.add(int(matches[index]))
    selected = np.asarray(selected, dtype=int)
    result["matched_count"] = len(selected)
    if len(selected) < minimum or len(selected) < .5 * len(ref):
        result["reason"] = "Too few reference spots matched"
        return result, spots
    reference_xy = ref[selected]
    current_xy = spots.xy[matches[selected]]
    normalized = (reference_xy - np.asarray(reference["center"])) / reference["radius_px"]
    x, y = normalized.T
    pixel_um = reference["pixel_um"]
    radius_um = reference["radius_px"] * pixel_um
    slopes = (current_xy - reference_xy) * pixel_um / (float(focal_mm) * 1000)
    matrix = np.vstack((basis(x, y, "x"), basis(x, y, "y")))
    target = np.concatenate((slopes[:, 0], slopes[:, 1])) * radius_um
    weights = np.sqrt(np.clip(spots.flux[matches[selected]] / np.median(spots.flux[matches[selected]]), .2, 5))
    weights = np.concatenate((weights, weights))
    weighted = matrix * weights[:, None]
    if np.linalg.cond(weighted) > 1e6:
        result["reason"] = "Spot coverage is insufficient for reconstruction"
        return result, spots
    coefficients = np.linalg.lstsq(weighted, target * weights, rcond=None)[0]
    residual = matrix @ coefficients - target
    residual_px = float(np.sqrt(np.mean(residual**2)) / radius_um * float(focal_mm) * 1000 / pixel_um)
    if residual_px > .15 * reference["pitch_px"]:
        result["reason"] = "Spot displacement is inconsistent · check the reference"
        return result, spots
    display_coefficients = coefficients.copy()
    if config.get("remove_tilt", True):
        display_coefficients[:2] = 0
    axis = np.linspace(-1, 1, 81)
    gx, gy = np.meshgrid(axis, axis)
    mask = gx**2 + gy**2 <= 1
    try:
        mask &= Delaunay(normalized).find_simplex(np.column_stack((gx.ravel(), gy.ravel()))).reshape(gx.shape) >= 0
    except QhullError:
        result["reason"] = "Spot coverage is insufficient for reconstruction"
        return result, spots
    surface = basis(gx, gy) @ display_coefficients
    surface -= np.mean(surface[mask])
    values = surface[mask]
    grid = [[float(v) if ok else None for v, ok in zip(row, valid)] for row, valid in zip(surface, mask)]
    result.update(visible=True, reason="Signal accepted", wavefront=grid,
                  rms_um=float(np.sqrt(np.mean(values**2))), pv_um=float(np.ptp(values)),
                  fit_residual_px=residual_px, pupil_radius_mm=radius_um/1000,
                  coefficients=[{"name": name, "um": float(value)} for (_, _, name), value in zip(MODES, coefficients)])
    return result, spots
