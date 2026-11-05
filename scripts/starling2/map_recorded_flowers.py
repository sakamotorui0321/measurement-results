#!/usr/bin/env python3
"""Map saved optical flower points with epoch-stamped PX4 NED poses (offline)."""
import argparse
import csv
import json
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment
from scipy.spatial.distance import pdist
from scipy.spatial.transform import Rotation, Slerp

from detect_recorded_flowers import sha256


def image_unix(clock, mono):
    if len(clock) < 2 or len({c['boot_id'] for c in clock}) != 1:
        raise ValueError('Clock requires one boot and at least two anchors')
    if any(c.get('discontinuity') or not c['time_sync']['ready'] for c in clock):
        raise ValueError('Discontinuous or unsynchronized clock')
    x = np.array([c['monotonic_sec'] for c in clock])
    offset = np.array([c['unix_sec'] - c['monotonic_sec'] for c in clock])
    if np.any(np.diff(x) <= 0) or np.ptp(offset) > .01:
        raise ValueError('Non-monotonic clock or offset jump >10 ms')
    mono = np.asarray(mono)
    if np.any(mono < x[0]) or np.any(mono > x[-1]):
        raise ValueError('Image outside clock coverage; no extrapolation')
    return mono + np.interp(mono, x, offset)


def interpolate_poses(records, times, max_gap=.15):
    messages = [r['message'] for r in records]
    t = np.array([m['timestamp_sample'] / 1e6 for m in messages])
    if np.any(np.diff(t) <= 0):
        raise ValueError('Pose sample timestamps must strictly increase')
    if any(m['pose_frame'] != 1 for m in messages):
        raise ValueError('Only PX4 NED poses supported')
    if len({m['reset_counter'] for m in messages}) != 1:
        raise ValueError('Pose reset detected; split recording before mapping')
    p = np.array([m['position'] for m in messages])
    q = np.array([m['q'] for m in messages])
    if not np.all(np.isfinite(p)) or not np.all(np.isfinite(q)) or np.any(abs(np.linalg.norm(q, axis=1) - 1) > .01):
        raise ValueError('Invalid pose or quaternion')
    times = np.asarray(times)
    if np.any(times < t[0]) or np.any(times > t[-1]):
        raise ValueError('Image outside pose coverage; no extrapolation')
    hi = np.clip(np.searchsorted(t, times, side='right'), 1, len(t)-1)
    lo = hi-1
    span = t[hi]-t[lo]
    if np.any(span > max_gap):
        raise ValueError('Pose interpolation crosses excessive sample gap')
    a = (times-t[lo])/span
    positions = p[lo]*(1-a[:, None])+p[hi]*a[:, None]
    rotations = Slerp(t-t[0], Rotation.from_quat(q[:, [1, 2, 3, 0]]))(times-t[0])
    return positions, rotations, span


def optical_to_enu(points, positions_ned, rotations, mount_flu):
    """Forward-level optical -> FLU -> FRD -> NED -> ENU."""
    points = np.asarray(points)
    flu = points[:, [2, 0, 1]] * [1, -1, -1] + np.asarray(mount_flu)
    ned = positions_ned + rotations.apply(flu * [1, -1, -1])
    return ned[:, [1, 0, 2]] * [1, 1, -1]


def group_points(points, frames, classes, radius):
    """Chronological one-to-one matches, bounded full cluster diameter."""
    if radius <= 0:
        raise ValueError('radius must be positive')
    clusters = []
    labels = np.full(len(points), -1, dtype=int)
    points = np.asarray(points)
    frames = np.asarray(frames)
    for frame in sorted(set(frames)):
        indices = np.flatnonzero(frames == frame)
        costs = np.full((len(indices), len(clusters)), 1e6)
        for i, index in enumerate(indices):
            for j, members in enumerate(clusters):
                if classes[index] == classes[members[0]]:
                    d = np.linalg.norm(points[members]-points[index], axis=1).max()
                    if d <= radius:
                        costs[i, j] = d
        row, col = linear_sum_assignment(costs)
        for i, j in zip(row, col):
            if costs[i, j] <= radius:
                index = indices[i]
                clusters[j].append(int(index))
                labels[index] = j
        for index in indices:
            if labels[index] < 0:
                labels[index] = len(clusters)
                clusters.append([int(index)])
    return labels, clusters


def write_csv(path, rows):
    with path.open('x', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ['positions', 'clock', 'poses', 'mount', 'output']:
        parser.add_argument('--'+key, type=Path, required=True)
    parser.add_argument('--radius', type=float, default=.06)
    parser.add_argument('--min-frames', type=int, default=3)
    args = parser.parse_args()
    if args.min_frames < 2:
        raise ValueError('min-frames must be at least two')
    args.output.mkdir(parents=True, exist_ok=False)
    rows = list(csv.DictReader(args.positions.open(encoding='utf-8-sig')))
    valid = [r for r in rows if r['position_status'] == 'estimated']
    if not valid:
        raise ValueError('No estimated positions')
    clock = [json.loads(line) for line in args.clock.read_text().splitlines()]
    poses = json.loads(args.poses.read_text())
    mount = json.loads(args.mount.read_text())
    if mount['reference_frame'] != 'color_optical' or not mount['orientation_confirmed'] or mount['orientation'] != 'forward level; optical to body FLU = [z,-x,-y]':
        raise ValueError('Only confirmed forward-level color optical mount supported')
    times = image_unix(clock, [float(r['timestamp_monotonic']) for r in valid])
    p, rotation, span = interpolate_poses(poses['odometry'], times)
    optical = np.array([[float(r[k]) for k in ['x_m', 'y_m', 'z_m']] for r in valid])
    if not np.all(np.isfinite(optical)):
        raise ValueError('Invalid optical point')
    world = optical_to_enu(optical, p, rotation, mount['translation_body_flu_m'])
    # Display frame uses endpoints of the interval containing 2D detections.
    endpoints = image_unix(clock, [min(float(r['timestamp_monotonic']) for r in rows), max(float(r['timestamp_monotonic']) for r in rows)])
    path_times = np.linspace(*endpoints, 600)
    path_p, path_r, _ = interpolate_poses(poses['odometry'], path_times)
    path_enu = path_p[:, [1, 0, 2]] * [1, 1, -1]
    origin = path_enu[0]
    along = path_enu[-1]-origin
    along[2] = 0
    if np.linalg.norm(along) < .1:
        # A short or stationary observation interval cannot define a row direction.
        along = np.array([1., 0., 0.])
    along /= np.linalg.norm(along)
    axes = np.array([along, [-along[1], along[0], 0], [0, 0, 1]])
    local = (world-origin) @ axes.T
    path_local = (path_enu-origin) @ axes.T
    cameras = optical_to_enu(np.zeros_like(path_p), path_p, path_r, mount['translation_body_flu_m'])
    forward = optical_to_enu(np.tile([0, 0, .3], (len(path_p), 1)), path_p, path_r, mount['translation_body_flu_m'])
    frames = [int(r['frame_index']) for r in valid]
    classes = [r['class_id'] for r in valid]
    labels, clusters = group_points(world, frames, classes, args.radius)
    mapped = []
    for i, r in enumerate(valid):
        mapped.append(dict(r, unix_sec=times[i], pose_bracket_sec=span[i], cluster_id=int(labels[i])+1,
                           east_m=world[i, 0], north_m=world[i, 1], up_m=world[i, 2],
                           along_m=local[i, 0], left_m=local[i, 1], relative_up_m=local[i, 2]))
    groups = []
    for i, members in enumerate(clusters):
        xyz = np.median(world[members], axis=0)
        loc = (xyz-origin) @ axes.T
        groups.append(dict(cluster_id=i+1, support_frames=len(members), status='repeated' if len(members) >= args.min_frames else 'low_support',
                           east_m=xyz[0], north_m=xyz[1], up_m=xyz[2], along_m=loc[0], left_m=loc[1], relative_up_m=loc[2],
                           diameter_m=float(pdist(world[members]).max()) if len(members)>1 else 0,
                           mean_confidence=float(np.mean([float(valid[j]['confidence']) for j in members])),
                           first_unix_sec=float(min(times[members])), last_unix_sec=float(max(times[members]))))
    sensitivity = []
    for radius in sorted({.03, .06, .10, args.radius}):
        _, c = group_points(world, frames, classes, radius)
        sensitivity.append(dict(radius_m=radius, groups=len(c), repeated=sum(len(m)>=args.min_frames for m in c)))
    write_csv(args.output/'observations_world.csv', mapped)
    write_csv(args.output/'flower_groups.csv', groups)
    write_csv(args.output/'trajectory.csv', [dict(unix_sec=t, east_m=e[0], north_m=e[1], up_m=e[2], along_m=l[0], left_m=l[1], relative_up_m=l[2]) for t,e,l in zip(path_times,path_enu,path_local)])
    np.savez_compressed(args.output/'map_arrays.npz', observations=local, trajectory=path_local,
                        camera=(cameras-origin)@axes.T, forward=(forward-origin)@axes.T)
    manifest = dict(input_rows=len(rows), mapped_observations=len(mapped), groups=len(groups),
                    repeated_groups=sum(g['status']=='repeated' for g in groups), radius_m=args.radius, min_frames=args.min_frames,
                    sensitivity=sensitivity, origin_enu_m=origin.tolist(), enu_to_display_rotation=axes.tolist(),
                    mount=mount, image_unix_range=[float(times.min()), float(times.max())],
                    trajectory_interval='First to last 2D detection (including depth-rejected detections)',
                    max_pose_bracket_sec=float(span.max()),
                    clock_offset_span_sec=float(np.ptp([c['unix_sec']-c['monotonic_sec'] for c in clock])),
                    max_clock_error_bound_sec=max(c['time_sync']['estimated_error_bound_sec'] for c in clock),
                    clock_method='VOXL monotonic to Unix via recorded clock anchors; PX4 timestamp_sample already epoch on DDS; no second timesync offset',
                    grouping='Chronological one-to-one per frame, same class, maximum distance to every member <= radius. Median representative. Not verified biological identity.',
                    limits=['Approximate mount, no extrinsic calibration uncertainty', 'VIO local ENU, not surveyed geography', 'Up is relative to initial body height, not ground', 'Depth/background and YOLO false positives remain', 'No plant surface or row boundary measured'],
                    inputs={k: dict(path=str(getattr(args,k)), sha256=sha256(getattr(args,k))) for k in ['positions','clock','poses','mount']})
    (args.output/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
