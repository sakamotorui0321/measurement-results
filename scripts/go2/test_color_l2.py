import json
from pathlib import Path
import tempfile
import unittest

try:
    import cv2
    import numpy as np
    import scipy
except ImportError:
    np = None

from import_recording import static_measurement
from build import build


@unittest.skipIf(np is None, 'color tests require NumPy, SciPy, OpenCV')
class VisibilityTest(unittest.TestCase):
    def test_static_depth_and_legacy_packaging(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data, audit = root/'data', root/'audit'
            data.mkdir()
            def save(name,value):
                (root/name).write_text(json.dumps(value))
            v,u = np.mgrid[:12,:16]
            rays = np.stack(((u-8)/10,(v-6)/10),axis=-1).astype('f4')
            np.save(root/'intrinsics-a.npy',rays)
            save('intrinsics-a.json',dict(session='a',serial='s',color_format='bgr8',
                 aligned_to='color',intrinsics=dict(width=16,height=12),depth_scale=.001,
                 color_to_depth_rotation_column_major=np.eye(3).ravel().tolist(),
                 color_to_depth_translation_m=[0,0,.1]))
            depth = np.full((12,16),1100,np.uint16)
            depth[3,3]=0
            color = np.zeros((12,16,3),np.uint8)
            color[6,8]=[17,80,155]
            np.savez(root/'sample.npz',color=color,depth=depth)
            save('rgbd.jsonl',dict(session='a',received_unix=1.,color_clock='hardware',
                 depth_clock='hardware',color_timestamp_ms=5,depth_timestamp_ms=5,file='sample.npz'))
            save('manifest.json',dict(state='stopped',started_utc='1970-01-01T00:00:00+00:00'))
            rows = [dict(sequence=1,points=[[0,0,1],[0,0,3],[-.5,-.3,1],[4,0,1],[0,0,-1]],
                         header_unix=1.,received_unix=1.01,frame='unilidar_lidar'),
                    dict(sequence=2,points=[[0,0,1]],header_unix=2.,received_unix=2.,frame='unilidar_lidar')]
            (root/'external-lidar.jsonl').write_text('\n'.join(map(json.dumps,rows)))
            config = dict(T_rgb_from_l2=np.eye(4).tolist(),motion='stationary',validation_reference='fixture',
                          max_time_s=.05,max_depth_m=.02,camera_serial='s',tolerance_basis='synthetic fixture')
            static_measurement(root,data,'fixture',config,audit)
            report = json.loads((audit/'summary.json').read_text())
            self.assertEqual([report[k] for k in ('outside','depth_missing','depth_mismatch','time_mismatch','colored')],[2,1,1,1,1])
            self.assertEqual((report['colored_fraction_all'],report['colored_fraction_in_view']),(1/6,1/4))
            self.assertEqual((data/'colors.bin').read_bytes(),bytes([155,80,17])+bytes([128])*15)
            self.assertEqual((data/'points.bin').stat().st_size,6*16)
            self.assertTrue((audit/'occlusion-0-overlay.png').is_file())
            build(data,root/'site','hosted')
            self.assertEqual((root/'site/data/colors.bin').read_bytes(),(data/'colors.bin').read_bytes())
