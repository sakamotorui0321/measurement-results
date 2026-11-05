"""Fit a candidate L2-to-RGB transform from indexed targets in static recordings."""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from color_l2 import Camera, local_file, read_json


def scene(spec, root):
    recording = (root / spec['recording']).resolve()
    row = json.loads((recording/'external-lidar.jsonl').read_text().splitlines()[spec['scan']])
    frame = json.loads((recording/'rgbd.jsonl').read_text().splitlines()[spec['frame']])
    if row['frame'] != 'unilidar_lidar':
        raise ValueError('Unexpected L2 frame')
    camera = Camera(recording, frame['session'])
    cloud = np.asarray(row['points'],dtype=float)
    pixels = np.asarray(spec['rgb_pixels'],dtype=int)
    points = cloud[spec['l2_indices']]
    if (len(points) != len(pixels) or pixels.shape != (len(points),2)
            or (pixels < 0).any() or (pixels >= [camera.w,camera.h]).any()):
        raise ValueError('Invalid target correspondences')
    u,v = pixels.T
    return dict(recording=recording,frame=frame,camera=camera,cloud=cloud,
                points=points,pixels=pixels,rays=camera.rays[v,u])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('annotations',type=Path)
    parser.add_argument('output',type=Path)
    args = parser.parse_args()
    annotations = read_json(args.annotations)
    train, held = ([scene(s,args.annotations.parent) for s in annotations[key]]
                   for key in ('fit','held_out'))
    if not train or not held or {s['recording'] for s in train} & {s['recording'] for s in held}:
        raise ValueError('Use distinct static recordings for fit and held-out scenes')
    if len({s['camera'].meta['serial'] for s in train+held}) != 1:
        raise ValueError('Multiple cameras')
    pts = np.concatenate([s['points'] for s in train])
    rays = np.concatenate([s['rays'] for s in train]).astype(float)
    if len(pts)<8 or np.linalg.matrix_rank(pts-pts.mean(axis=0),tol=.02)<3:
        raise ValueError('Use at least eight targets distributed across multiple planes')
    ok,r,t = cv2.solvePnP(pts,rays,np.eye(3),None,flags=cv2.SOLVEPNP_ITERATIVE)
    if not ok:
        raise ValueError('PnP failed')
    rot = cv2.Rodrigues(r)[0]
    transform = np.eye(4)
    transform[:3,:3],transform[:3,3] = rot,t.ravel()
    args.output.mkdir(parents=True,exist_ok=False)
    report = dict(camera_serial=train[0]['camera'].meta['serial'],T_rgb_from_l2=transform.tolist(),scenes=[])
    (args.output/'annotations.json').write_text(json.dumps(annotations,ensure_ascii=False,indent=2))
    for role,scenes in [('fit',train),('held_out',held)]:
        for i,s in enumerate(scenes):
            indices,uv = s['camera'].project(s['points'] @ rot.T+t.ravel())
            if not len(indices) or len(indices)!=len(s['pixels']):
                raise ValueError('Some marked correspondences project outside the image')
            errors = np.linalg.norm(uv.T-s['pixels'][indices],axis=1)
            with np.load(local_file(s['recording'],s['frame']['file'])) as packet:
                overlay = packet['color'].copy()
            full,coords = s['camera'].project(s['cloud'] @ rot.T+t.ravel())
            for x,y in coords.T:
                cv2.circle(overlay,(int(x),int(y)),1,(255,160,0),-1)
            for predicted,actual in zip(uv.T,s['pixels'][indices]):
                cv2.line(overlay,tuple(predicted),tuple(actual),(0,0,255),2)
                cv2.circle(overlay,tuple(actual),4,(0,255,0),1)
            file = '%s-%d.png' % (role,i)
            if not cv2.imwrite(str(args.output/file),overlay):
                raise OSError('Cannot save overlay')
            report['scenes'].append(dict(role=role,overlay=file,recording=str(s['recording']),
                median_px=float(np.median(errors)),max_px=float(errors.max()),residual_px=errors.tolist(),
                in_view=len(full),all_points=len(s['cloud']),uv_min=coords.min(axis=1).tolist(),
                uv_max=coords.max(axis=1).tolist()))
    (args.output/'candidate.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
