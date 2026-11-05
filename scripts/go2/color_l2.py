"""Static L2 scans in the RGB optical frame. Units are metres and seconds."""
from bisect import bisect_left
import json
from pathlib import Path

import cv2
import numpy as np
from scipy.spatial import cKDTree

LABELS = ('outside', 'depth_missing', 'depth_mismatch', 'time_mismatch', 'colored')


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def local_file(root, name):
    path = (root / name).resolve()
    if path.parent != root.resolve():
        raise ValueError('Invalid recording asset path')
    return path


class Camera:
    def __init__(self, source, session):
        prefix = 'intrinsics-' + session
        self.meta = read_json(local_file(source, prefix + '.json'))
        self.rays = np.load(local_file(source, prefix + '.npy'), allow_pickle=False)
        intr = self.meta['intrinsics']
        if (self.meta['session'] != session or self.meta['aligned_to'] != 'color'
                or self.meta['color_format'] != 'bgr8'
                or self.rays.shape != (intr['height'], intr['width'], 2)):
            raise ValueError('RGB calibration or resolution mismatch')
        self.h, self.w = self.rays.shape[:2]
        self.tree = cKDTree(self.rays.reshape(-1, 2))

    def project(self, xyz):
        # Invert the recorded SDK distortion-aware rays. The local Jacobian
        # distinguishes a genuine edge pixel from a point beyond the image.
        front = np.flatnonzero(xyz[:, 2] > 0)
        norm = xyz[front, :2] / xyz[front, 2, None]
        _, idx = self.tree.query(norm)
        v, u = np.divmod(idx, self.w)
        r = self.rays[v, u]
        du = np.where(u + 1 < self.w, 1, -1)
        dv = np.where(v + 1 < self.h, 1, -1)
        jac = np.stack(((self.rays[v, u+du]-r)*du[:, None],
                        (self.rays[v+dv, u]-r)*dv[:, None]), axis=-1)
        pixel = np.stack((u,v), axis=1) + np.linalg.solve(jac, (norm-r)[..., None])[..., 0]
        inside = ((pixel >= -.5) & (pixel < [self.w-.5, self.h-.5])).all(axis=1)
        return front[inside], np.floor(pixel[inside]+.5).astype(int).T


class Colorizer:
    def __init__(self, source, config, audit):
        self.source, self.config, self.audit = source, config, audit
        if config['motion'] != 'stationary' or not config['validation_reference']:
            raise ValueError('Static recording and reviewed held-out calibration required')
        self.T = np.asarray(config['T_rgb_from_l2'], dtype=float)
        r = self.T[:3,:3]
        if (self.T.shape != (4,4) or not np.isfinite(self.T).all()
                or not np.allclose(self.T[3], [0,0,0,1]) or not np.allclose(r.T @ r, np.eye(3), atol=1e-5)
                or not np.isclose(np.linalg.det(r), 1)):
            raise ValueError('Invalid rigid transform')
        self.dt, self.dz = config['max_time_s'], config['max_depth_m']
        if not (0 < self.dt and 0 < self.dz and np.isfinite([self.dt,self.dz]).all() and config['tolerance_basis']):
            raise ValueError('Document positive finite tolerances and their basis')
        self.frames = [json.loads(line) for line in (source/'rgbd.jsonl').read_text().splitlines()]
        if not self.frames or len({f['session'] for f in self.frames}) != 1:
            raise ValueError('Expected a single calibrated RGB-D session')
        self.camera = Camera(source, self.frames[0]['session'])
        if config['camera_serial'] != self.camera.meta['serial']:
            raise ValueError('Camera serial differs from calibration')
        # Use device exposure times only when the SDK identifies the Go2 host
        # time domain. Hardware-clock recordings use receipt pairing, static only.
        def capture_time(frame):
            if frame['color_clock'].split('.')[-1] in ('system_time','global_time'):
                return frame['color_timestamp_ms']/1000
            return frame['received_unix']
        self.times = [capture_time(f) for f in self.frames]
        if not np.isfinite(self.times).all() or np.any(np.diff(self.times) < 0):
            raise ValueError('RGB-D receipt clock discontinuity')
        self.counts = np.zeros(5, dtype=np.int64)
        self.in_view = 0
        self.uv_min, self.uv_max = np.array([self.camera.w,self.camera.h]), np.array([-1,-1])
        self.examples = set()
        audit.mkdir()
        (audit/'conditions.json').write_text(json.dumps(config, ensure_ascii=False, indent=2))
        (audit/'camera.json').write_text(json.dumps(self.camera.meta, indent=2))

    def scan(self, row, number, log):
        if row['frame'] != 'unilidar_lidar':
            raise ValueError('Unexpected L2 coordinate frame')
        pts = np.asarray(row['points'], dtype=float).reshape(-1,3)
        xyz = pts @ self.T[:3,:3].T + self.T[:3,3]
        idx, (u,v) = self.camera.project(xyz)
        self.in_view += len(idx)
        if len(idx):
            self.uv_min = np.minimum(self.uv_min,[u.min(),v.min()])
            self.uv_max = np.maximum(self.uv_max,[u.max(),v.max()])
        rgb = np.full((len(pts),3), 128, dtype=np.uint8)
        labels = np.zeros(len(pts), dtype=np.uint8)
        labels[idx] = 3
        stamp = row['header_unix']
        j = bisect_left(self.times, stamp)
        i = min({max(0,j-1),min(j,len(self.times)-1)}, key=lambda k: abs(self.times[k]-stamp))
        frame = self.frames[i]
        gap = self.times[i]-stamp
        pair_gap = (frame['depth_timestamp_ms']-frame['color_timestamp_ms'])/1000
        counts_info = dict(scan=number, lidar_sequence=row['sequence'], lidar_header_unix=stamp,
                           camera_file=frame['file'], camera_received_unix=frame['received_unix'],
                           matching_time_unix=self.times[i], color_clock=frame['color_clock'],
                           match_minus_header_s=gap, depth_minus_color_s=pair_gap)
        if (abs(gap) <= self.dt and 0 <= row['received_unix']-stamp <= .25
                and frame['depth_clock']==frame['color_clock'] and abs(pair_gap)<=self.dt
                and abs(gap+pair_gap)<=self.dt):
            with np.load(local_file(self.source,frame['file']), allow_pickle=False) as packet:
                bgr, depth = packet['color'], packet['depth']
            cam = self.camera
            if depth.shape != (cam.h,cam.w) or bgr.shape != (cam.h,cam.w,3) or depth.dtype != np.uint16 or bgr.dtype != np.uint8:
                raise ValueError('Invalid RGB-D frame')
            # Aligned Z16 stores native depth-camera Z on the RGB pixel grid.
            rotation = np.array(cam.meta['color_to_depth_rotation_column_major']).reshape(3,3,order='F')
            direction = cam.rays[v,u] @ rotation[2,:2] + rotation[2,2]
            measured = (depth[v,u]*cam.meta['depth_scale']-cam.meta['color_to_depth_translation_m'][2])/direction
            valid = (depth[v,u]>0) & (measured>0) & np.isfinite(measured)
            # Reject uncertain silhouettes. A small RGB↔L2 registration shift
            # must not assign a foreground leaf's colour to a rear surface.
            good = valid & (np.abs(measured-xyz[idx,2])<=self.dz)
            for dy,dx in ((0,-1),(0,1),(-1,0),(1,0)):
                yn,xn = np.clip(v+dy,0,cam.h-1),np.clip(u+dx,0,cam.w-1)
                zn = depth[yn,xn]*cam.meta['depth_scale']
                dn = cam.rays[yn,xn] @ rotation[2,:2]+rotation[2,2]
                adjacent = (zn-cam.meta['color_to_depth_translation_m'][2])/dn
                valid &= zn>0
                good &= (zn>0) & (np.abs(adjacent-xyz[idx,2])<=self.dz)
            labels[idx] = np.where(good,4,np.where(valid,2,1))
            rgb[idx[good]] = bgr[v[good],u[good],::-1]
            behind = valid & (xyz[idx,2]-measured>self.dz)
            tag = 'occlusion' if behind.any() else 'projection'
            if len(idx) and tag not in self.examples:
                self.examples.add(tag)
                base = self.audit / (tag+'-'+str(number))
                cv2.imwrite(str(base)+'-rgb.png', bgr)
                cv2.imwrite(str(base)+'-z16.png', depth)
                overlay = bgr.copy()
                for x,y,ok in zip(u,v,good):
                    cv2.circle(overlay,(int(x),int(y)),2,(0,220,0) if ok else (0,0,255),1)
                cv2.imwrite(str(base)+'-overlay.png',overlay)
                np.savez_compressed(str(base)+'-points.npz',point_index=idx,u=u,v=v,
                                    lidar_z=xyz[idx,2],camera_z=measured,reason=labels[idx])
        counts = np.bincount(labels,minlength=5)
        self.counts += counts
        log.write(json.dumps(dict(counts_info,counts=dict(zip(LABELS,counts.tolist()))))+'\n')
        return rgb

    def finish(self):
        n = int(self.counts.sum())
        c = int(self.counts[-1])
        summary = dict(zip(LABELS,self.counts.tolist()))
        summary.update(recorded_l2_points=n, in_view=self.in_view,
                       in_view_pixel_bounds=[self.uv_min.tolist(),self.uv_max.tolist()] if self.in_view else None,
                       colored_fraction_all=c/n if n else None,
                       colored_fraction_in_view=c/self.in_view if self.in_view else None)
        (self.audit/'summary.json').write_text(json.dumps(summary,indent=2))
