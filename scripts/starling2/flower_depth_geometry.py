"""Pinhole RGB-D projection and conservative bbox-center depth estimates.

Only calibrated zero-distortion profiles are supported. No hole filling.
"""
import math
import numpy as np


def validate_calibration(calibration, width=640, height=480):
    if calibration.get('schema_version') != 1 or not calibration.get('device', {}).get('serial'):
        raise ValueError('Missing calibration version or device serial')
    for kind, fmt in [('depth', 'Z16'), ('color', 'YUYV')]:
        p = calibration[kind]
        if (p['width'], p['height'], p['fps'], p['format']) != (width, height, 15, fmt):
            raise ValueError('Calibration profile does not match recording')
        values = [p[k] for k in ('fx', 'fy', 'ppx', 'ppy')] + list(p['coeffs'])
        if not np.isfinite(values).all() or p['fx'] <= 0 or p['fy'] <= 0:
            raise ValueError('Invalid camera intrinsics')
        if p['model'] not in (0, 1, 2, 3, 4, 5) or len(p['coeffs']) != 5 or np.any(np.array(p['coeffs']) != 0):
            raise ValueError('Only known models with zero distortion coefficients are supported')
    scale = calibration['depth_scale_m']
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError('Invalid depth scale')
    transform = calibration['depth_to_color']
    rotation = np.array(transform['rotation_column_major'], dtype=float).reshape(3, 3, order='F')
    translation = np.array(transform['translation_m'], dtype=float)
    if translation.shape != (3,) or not np.isfinite(rotation).all() or not np.isfinite(translation).all():
        raise ValueError('Invalid depth-to-color transform')
    if not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-5) or not np.isclose(np.linalg.det(rotation), 1, atol=1e-5):
        raise ValueError('Calibration rotation is not a proper rotation')
    return rotation, translation


class DepthProjector:
    def __init__(self, calibration, width=640, height=480):
        self.rotation, self.translation = validate_calibration(calibration, width, height)
        self.calibration = calibration
        self.width, self.height = width, height
        v, u = np.mgrid[:height, :width]
        d = calibration['depth']
        self.rays = np.stack(((u-d['ppx'])/d['fx'], (v-d['ppy'])/d['fy'], np.ones_like(u)), axis=-1).reshape(-1, 3)

    def align(self, raw):
        if raw.shape != (self.height, self.width) or raw.dtype != np.dtype('uint16'):
            raise ValueError('Expected Z16 image with calibrated dimensions')
        values = raw.reshape(-1)
        valid = (values > 0) & (values < 65535)
        points = self.rays[valid] * (values[valid, None] * self.calibration['depth_scale_m'])
        points = points @ self.rotation.T + self.translation
        points = points[points[:, 2] > 0]
        c = self.calibration['color']
        # Project sample centers, then z-buffer: nearest surface wins collisions.
        u = np.floor(c['fx']*points[:, 0]/points[:, 2]+c['ppx']+.5).astype(np.int64)
        v = np.floor(c['fy']*points[:, 1]/points[:, 2]+c['ppy']+.5).astype(np.int64)
        inside = (u >= 0) & (u < self.width) & (v >= 0) & (v < self.height)
        aligned = np.full(self.width*self.height, np.inf)
        np.minimum.at(aligned, v[inside]*self.width+u[inside], points[inside, 2])
        aligned[~np.isfinite(aligned)] = np.nan
        return aligned.reshape(self.height, self.width)


def estimate_position(aligned, bbox, intrinsics):
    """Estimate bbox-center ray at central-third median color-camera Z.

These quality gates reject sparse/mixed depth, but cannot prove flower identity.
"""
    x1, y1, x2, y2 = bbox
    height, width = aligned.shape
    if not np.isfinite(bbox).all() or not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
        raise ValueError('Invalid bounding box')
    left, right = int(math.floor(x1+(x2-x1)/3)), int(math.ceil(x2-(x2-x1)/3))
    top, bottom = int(math.floor(y1+(y2-y1)/3)), int(math.ceil(y2-(y2-y1)/3))
    patch = aligned[top:bottom, left:right]
    valid = patch[np.isfinite(patch) & (patch >= .15) & (patch <= 4.)]
    result = dict(position_status='sparse_depth', valid_pixels=int(valid.size),
                  patch_pixels=int(patch.size), valid_fraction=float(valid.size/patch.size),
                  depth_mad_m=None, depth_p90_p10_m=None,
                  x_m=None, y_m=None, z_m=None, range_m=None)
    if valid.size < 5 or result['valid_fraction'] < .25:
        return result
    z = float(np.median(valid))
    mad = float(np.median(np.abs(valid-z)))
    spread = float(np.percentile(valid, 90)-np.percentile(valid, 10))
    result.update(depth_mad_m=mad, depth_p90_p10_m=spread)
    if mad > max(.01, .03*z) or spread > max(.03, .1*z):
        result['position_status'] = 'mixed_depth'
        return result
    u, v = (x1+x2)/2, (y1+y2)/2
    x = (u-intrinsics['ppx'])*z/intrinsics['fx']
    y = (v-intrinsics['ppy'])*z/intrinsics['fy']
    result.update(position_status='estimated', x_m=x, y_m=y, z_m=z,
                  range_m=math.sqrt(x*x+y*y+z*z))
    return result
