import json
from pathlib import Path
import sqlite3
import struct
import subprocess
import sys
import tempfile
import unittest

from import_recording import measurement


class RecordingTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.record = self.root/'original'
        self.record.mkdir()
        def save(file, value):
            (self.record/file).write_text(json.dumps(value))
        save('manifest.json', dict(state='stopped', id='record1', started_utc='2026-11-01T00:00:00+00:00'))
        save('external-lidar.jsonl', dict(received_unix=1793491201,frame='unilidar_lidar',
             pose=dict(session='A',xyz=[1,2,3],quaternion=[0,0,0,1]),points=[[1,0,0],[1,0,0]]))
        save('rgb.jsonl',dict(saved_utc='2026-11-01T00:00:01+00:00',file='rgb_record1.mjpeg',offset=0,bytes=4))
        (self.record/'rgb_record1.mjpeg').write_bytes(b'\xff\xd8\xff\xd9')

    def test_hosted_with_bag(self):
        bag = self.root/'bag'
        (bag/'data').mkdir(parents=True)
        (bag/'data/metadata.yaml').touch()
        (bag/'session.json').write_text('{"topics":["/tf","/camera/image/raw"]}')
        with sqlite3.connect(bag/'data/part.db3') as db:
            db.executescript("create table topics(id,name);create table messages(id,topic_id);insert into topics values(1,'/tf');insert into messages values(1,1);")
        dest = self.root/'new'
        cmd = [sys.executable,str(Path(__file__).with_name('import_recording.py')),str(self.record),str(dest),'--title','走行A','--bag',str(bag)]
        subprocess.run(cmd,check=True)
        self.assertIn('/camera/image/raw · 0 件', (dest/'index.html').read_text())
        self.assertIn('/tf · 1 件', (dest/'index.html').read_text())
        self.assertEqual((dest/'title.txt').read_text().strip(),'走行A')
        values = struct.unpack('<4f',(dest/'data/points.bin').read_bytes())
        for got,want in zip(values,(2.2,2,3.11,1)):
            self.assertAlmostEqual(got,want,places=5)
        self.assertNotEqual(subprocess.run(cmd,capture_output=True).returncode,0)

    def test_missing_pose(self):
        (self.record/'external-lidar.jsonl').write_text('{"pose":null}')
        out = self.root/'data'
        out.mkdir()
        with self.assertRaisesRegex(ValueError,'同期姿勢'):
            measurement(self.record,out,'測定')
