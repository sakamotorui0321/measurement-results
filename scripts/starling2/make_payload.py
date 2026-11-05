"""Build Starling2 flower-viewer data from one calibrated flight."""
from pathlib import Path
import csv, json, sys, base64, hashlib
import numpy as np
import cv2
from scipy.spatial import cKDTree

raw, root, scripts = map(Path, sys.argv[1:])
previous = root / 'world'
sys.path.insert(0, str(scripts))
cloud=np.load(root/'cloud.npz');points=cloud['xyz_m'];groups=list(csv.DictReader((previous/'flower_groups.csv').open()))
observations=list(csv.DictReader((previous/'observations_world.csv').open()))
frames=[json.loads(s) for s in (raw/'frames.jsonl').read_text().splitlines()];colors=[f for f in frames if f['stream']=='color']
data_groups={}
for g in groups:
    gid=int(g['cluster_id']);items=[r for r in observations if int(r['cluster_id'])==gid];items.sort(key=lambda r:float(r['timestamp_monotonic']))
    assert len(items)==int(g['support_frames'])
    converted=[]
    for r in items:
        index=int(r['frame_index']);f=colors[index]
        assert int(r['sequence'])==f['sequence'] and abs(float(r['timestamp_monotonic'])-f['timestamp_monotonic'])<1e-6
        box=[float(r[k]) for k in ['x1_px','y1_px','x2_px','y2_px']];assert 0<=box[0]<box[2]<=640 and 0<=box[1]<box[3]<=480
        converted.append(dict(frame=index,sequence=f['sequence'],candidate=int(r['candidate_id']),elapsed=float(r['elapsed_sec']),conf=float(r['confidence']),range=float(r['range_m']),box=box))
    data_groups[gid]=dict(xyz=[float(g[k]) for k in ['along_m','left_m','relative_up_m']],obs=converted,best=int(np.argmax([o['conf'] for o in converted])))
images={}
with (raw/'color.yuyv').open('rb') as f:
    for index in sorted({int(r['frame_index']) for r in observations}):
        entry=colors[index];f.seek(entry['offset']);payload=f.read(entry['bytes']);assert len(payload)==640*480*2
        bgr=cv2.cvtColor(np.frombuffer(payload,np.uint8).reshape(480,640,2),cv2.COLOR_YUV2BGR_YUY2)
        ok,jpg=cv2.imencode('.jpg',bgr,[cv2.IMWRITE_JPEG_QUALITY,88]);assert ok
        decoded=cv2.imdecode(jpg,cv2.IMREAD_COLOR);assert decoded.shape==(480,640,3)
        images[index]=base64.b64encode(jpg).decode()
def enc(a,dtype):return base64.b64encode(np.asarray(a,dtype=dtype).tobytes()).decode()
path=np.load(previous/'map_arrays.npz')['trajectory'];extent=np.vstack([points,path]);center=(extent.min(axis=0)+extent.max(axis=0))/2;radius=float(np.linalg.norm(extent-center,axis=1).max())
data=dict(xyz=enc(points,'<f4'),rgb=enc(cloud['rgb'],'u1'),red=enc(cloud['red'],'u1'),nearest=enc(cloud['nearest_group_id'],'<u2'),path=enc(path,'<f4'),groups=data_groups,images=images,center=center.tolist(),radius=radius)

assert len(data_groups)==len(groups) and sum(len(g['obs']) for g in data_groups.values())==len(observations)
assert np.isfinite(points).all() and all(o['frame'] in images for g in data_groups.values() for o in g['obs'])
assert set(cloud['nearest_group_id'][cloud['red']]).issubset(data_groups)
payload=root/'data.js'
with payload.open('w') as f:
    f.write('window.FLOWER_DATA=')
    json.dump(data,f,separators=(',',':'))
    f.write(';\n')
stats=dict(cloud_points=len(points),red_points=int(cloud['red'].sum()),flower_groups=len(groups),repeated_groups=sum(g['status']=='repeated' for g in groups),observations=len(observations),rgb_frames=len(images),depth_frames=len(json.loads((root/'cloud_frames.json').read_text())['paired']),data_sha256=hashlib.sha256(payload.read_bytes()).hexdigest())
(root/'viewer_stats.json').write_text(json.dumps(stats,indent=2))
print(stats)