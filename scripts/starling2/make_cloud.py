"""Build Starling2 flower-viewer data from one calibrated flight."""
from pathlib import Path
import csv, json, sys, base64, hashlib
import numpy as np
import cv2
from scipy.spatial import cKDTree

raw, root, scripts = map(Path, sys.argv[1:4])
previous = root / 'world'
sys.path.insert(0, str(scripts))
from map_recorded_flowers import image_unix,interpolate_poses,optical_to_enu
from flower_depth_geometry import DepthProjector
calpath=Path(sys.argv[4]) if len(sys.argv)>4 else raw/'calibration.json'
cal=json.loads(calpath.read_text()); projector=DepthProjector(cal)
clock=[json.loads(x) for x in (raw/'clock.jsonl').read_text().splitlines()]
poses=json.loads((root/'poses.json').read_text())
mount=json.loads((root/'mount.json').read_text())
world_manifest=json.loads((previous/'manifest.json').read_text())
origin=np.array(world_manifest['origin_enu_m']); axes=np.array(world_manifest['enu_to_display_rotation'])
frames=[json.loads(x) for x in (raw/'frames.jsonl').read_text().splitlines()]
depth=[f for f in frames if f['stream']=='depth']; color=[f for f in frames if f['stream']=='color']
selected=depth[::15]
times=image_unix(clock,[f['timestamp_monotonic'] for f in selected])
positions,rotations,gaps=interpolate_poses(poses['odometry'],times)
color_times=np.array([f['timestamp_monotonic'] for f in color])
groups=list(csv.DictReader((previous/'flower_groups.csv').open()))
flowers=np.array([[float(g[k]) for k in ['along_m','left_m','relative_up_m']] for g in groups])
repeated=np.array([g['status']=='repeated' for g in groups])
points_all=[]; colors_all=[]; paired=[]; skipped=[]
v,u=np.mgrid[0:480:2,0:640:2]
idx=(v*640+u).ravel()
depth_file=(raw/'depth.z16').open('rb'); color_file=(raw/'color.yuyv').open('rb')
for n,record in enumerate(selected):
    ci=int(np.argmin(abs(color_times-record['timestamp_monotonic'])))
    delta=abs(color_times[ci]-record['timestamp_monotonic'])
    if delta>.01:
        skipped.append(dict(sequence=record['sequence'],reason='No color within 10ms',nearest_color_delta_ms=delta*1000))
        continue
    depth_file.seek(record['offset']); z=np.frombuffer(depth_file.read(record['bytes']),dtype='<u2').reshape(-1)[idx]*cal['depth_scale_m']
    good=(z>=.15)&(z<=4)
    optical=projector.rays[idx[good]]*z[good,None]
    optical=optical@projector.rotation.T+projector.translation
    c=cal['color']; uu=np.rint(c['fx']*optical[:,0]/optical[:,2]+c['ppx']).astype(int); vv=np.rint(c['fy']*optical[:,1]/optical[:,2]+c['ppy']).astype(int)
    inside=(uu>=0)&(uu<640)&(vv>=0)&(vv<480)&(optical[:,2]>0)
    optical=optical[inside]; uu=uu[inside]; vv=vv[inside]
    # Per-frame color-view z-buffer avoids painting hidden rear samples.
    pixel=vv*640+uu
    order=np.argsort(optical[:,2],kind='stable')
    _,first=np.unique(pixel[order],return_index=True)
    keep=order[first]
    optical=optical[keep]; uu=uu[keep]; vv=vv[keep]
    color_file.seek(color[ci]['offset'])
    rgb=cv2.cvtColor(np.frombuffer(color_file.read(color[ci]['bytes']),np.uint8).reshape(480,640,2),cv2.COLOR_YUV2RGB_YUY2)
    world=optical_to_enu(optical,positions[n:n+1],rotations[n],mount['translation_body_flu_m'])
    local_xyz=(world-origin)@axes.T
    # Average once per voxel per frame, so close-range dense samples do not dominate.
    keys=np.floor(local_xyz/.01).astype(np.int32)
    unique,inv,count=np.unique(keys,axis=0,return_inverse=True,return_counts=True)
    pts=np.column_stack([np.bincount(inv,weights=local_xyz[:,j])/count for j in range(3)])
    clr=np.column_stack([np.bincount(inv,weights=rgb[vv,uu,j])/count for j in range(3)])
    points_all.append(pts); colors_all.append(clr)
    paired.append(dict(depth_sequence=record['sequence'],color_sequence=color[ci]['sequence'],monotonic=record['timestamp_monotonic'],unix_sec=float(times[n]),delta_ms=delta*1000,voxel_samples=len(pts)))
    if n%15==0: print(f'Frames {n+1}/{len(selected)}',flush=True)
depth_file.close();color_file.close()
points=np.vstack(points_all); colors=np.vstack(colors_all)
keys,inv,count=np.unique(np.floor(points/.01).astype(np.int32),axis=0,return_inverse=True,return_counts=True)
points=np.column_stack([np.bincount(inv,weights=points[:,j])/count for j in range(3)])
colors=np.clip(np.column_stack([np.bincount(inv,weights=colors[:,j])/count for j in range(3)]),0,255).astype(np.uint8)
if len(flowers):
    distance,nearest=cKDTree(flowers).query(points)
else:
    distance=np.full(len(points),np.inf)
    nearest=np.full(len(points),-1)
red=distance<=.03
assert np.isfinite(points).all() and len(points)==len(colors)==len(red)
# Check rigid-transform round trip and geometry of red mask.
np.testing.assert_allclose(((points@axes)+origin-origin)@axes.T,points,atol=1e-12)
assert (distance[red]<=.03).all() and (distance[~red]>.03).all()
np.savez_compressed(root/'cloud.npz',xyz_m=points,rgb=colors,frame_support=count,red=red,nearest_group_id=nearest+1,distance_to_group_m=distance)

(root/'cloud_frames.json').write_text(json.dumps(dict(paired=paired,skipped=skipped)))
