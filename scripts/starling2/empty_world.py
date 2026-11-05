"""Retain the cloud and trajectory when there are zero localized flowers."""
import json
from pathlib import Path
import sys
import numpy as np

raw, work, scripts = map(Path,sys.argv[1:])
sys.path.insert(0,str(scripts))
from map_recorded_flowers import image_unix, interpolate_poses
frames = [json.loads(line) for line in (raw/'frames.jsonl').read_text().splitlines()]
clock = [json.loads(line) for line in (raw/'clock.jsonl').read_text().splitlines()]
times = image_unix(clock,[f['timestamp_monotonic'] for f in frames if f['stream']=='color'])
poses = json.loads((work/'poses.json').read_text())['odometry']
ned, _, _ = interpolate_poses(poses, np.linspace(times[0],times[-1],600))
enu = ned[:,[1,0,2]] * [1,1,-1]
out = work/'world'
out.mkdir()
(out/'manifest.json').write_text(json.dumps(dict(origin_enu_m=enu[0].tolist(),
    enu_to_display_rotation=np.eye(3).tolist(), axes='east,north,relative up', mapped_observations=0)))
np.savez(out/'map_arrays.npz',trajectory=enu-enu[0])
(out/'flower_groups.csv').write_text('cluster_id,status\n')
(out/'observations_world.csv').write_text('cluster_id,frame_index\n')
