import base64
import json
from pathlib import Path
import struct
import tempfile
import unittest

from build import build, read_assets, write_hosted_assets


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / 'data'
        self.data.mkdir()
        self.manifest = {'runs': [{'id': 3, 'count': 1, 'file': 'data/run3.bin', 'source': 'private-path'}]}
        (self.data / 'manifest.json').write_text(json.dumps(self.manifest))
        (self.data / 'run3.bin').write_bytes(struct.pack('<4f', 1, 2, 3, 0))
        (self.data / 'rgb3.mjpeg').write_bytes(b'\xff\xd8\xff\xd9')
        rgb = {'3': {'file': 'data/rgb3.mjpeg', 'source': 'private-path', 'maxAge': .75,
                     'frames': [{'t': 0, 'offset': 0, 'bytes': 4}]}}
        (self.data / 'rgb.json').write_text(json.dumps(rgb))

    def test_portable_roundtrip_and_privacy(self):
        out = self.root / 'portable'
        build(self.data, out)
        for file in (out / 'assets').glob('*.js'):
            ref, text = json.loads('[' + file.read_text()[len('window.__portableData('):-2] + ']')
            raw = base64.b64decode(text)
            if ref.endswith('.json'):
                self.assertNotIn(b'private-path', raw)
            else:
                self.assertEqual(raw, (self.data / ref.split('/')[1]).read_bytes())
        html = (out / 'ビューアーを開く.html').read_text(encoding='utf-8')
        self.assertIn('src="start.js"', html)
        self.assertNotIn('importmap', html)
        with self.assertRaises(FileExistsError):
            build(self.data, out)

    def test_web_build(self):
        out = self.root / 'web'
        build(self.data, out, 'web')
        self.assertTrue((out / 'index.html').exists())
        self.assertEqual((out / 'data/run3.bin').read_bytes(), (self.data / 'run3.bin').read_bytes())

    def test_hosted_chunk_roundtrip(self):
        out = self.root / 'hosted'
        (out / 'data').mkdir(parents=True)
        (out / 'app.js').write_text("fetch('data/run3.bin')")
        (out / 'index.html').write_text(' このPC内で表示', encoding='utf-8')
        raw = bytes(range(31))
        write_hosted_assets(out, {'data/run3.bin': raw}, chunk_size=8)
        files = sorted((out / 'data').glob('run3.bin.part*'))
        self.assertEqual(b''.join(f.read_bytes() for f in files), raw)
        self.assertTrue(all(f.stat().st_size <= 8 for f in files))
        self.assertFalse((out / 'data/run3.bin').exists())
        self.assertIn('assetFetch(', (out / 'app.js').read_text(encoding='utf-8'))

    def test_reject_bad_size_before_writing_output(self):
        (self.data / 'run3.bin').write_bytes(b'bad')
        out = self.root / 'bad'
        with self.assertRaises(ValueError):
            build(self.data, out)
        self.assertFalse(out.exists())

    def test_reject_external_asset_path(self):
        self.manifest['runs'][0]['file'] = 'data/../../secret'
        (self.data / 'manifest.json').write_text(json.dumps(self.manifest))
        with self.assertRaises(ValueError):
            read_assets(self.data)


if __name__ == '__main__':
    unittest.main()
