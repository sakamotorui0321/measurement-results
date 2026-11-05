"""Build a web or file:// distribution from separately stored experiment assets."""
import argparse
import base64
import json
from pathlib import Path
import re
import shutil
import zipfile

ROOT = Path(__file__).resolve().parent


def write_hosted_assets(output, assets, chunk_size=8 * 1024 * 1024):
    """Bound individual hosting assets without changing decoded sensor data."""
    parts = {}
    for ref, raw in assets.items():
        if len(raw) <= chunk_size:
            (output / ref).write_bytes(raw)
            continue
        parts[ref] = []
        for index, start in enumerate(range(0, len(raw), chunk_size)):
            name = ref + f'.part{index:03d}'
            (output / name).write_bytes(raw[start:start + chunk_size])
            parts[ref].append(name)
    app = output / 'app.js'
    source = app.read_text(encoding='utf-8').replace('fetch(', 'assetFetch(')
    loader = 'const assetParts=' + json.dumps(parts) + ';\n'
    loader += '''async function assetFetch(url){
 if(!assetParts[url])return fetch(url);
 const buffers=[];
 for(const part of assetParts[url]){const response=await fetch(part);if(!response.ok)throw new Error('データの取得失敗：'+part);buffers.push(await response.arrayBuffer());}
 return new Response(new Blob(buffers));
}
'''
    app.write_text(loader + source, encoding='utf-8')
    html = output / 'index.html'
    html.write_text(html.read_text(encoding='utf-8').replace(' このPC内で表示', ' 公開ビューアー'), encoding='utf-8')


def public_metadata(value):
    if isinstance(value, dict):
        return {k: public_metadata(v) for k, v in value.items() if k != 'source'}
    if isinstance(value, list):
        return [public_metadata(v) for v in value]
    return value


def read_assets(data_dir):
    """Read only referenced assets; reject paths outside the supplied directory."""
    data_dir = data_dir.resolve()
    manifest = json.loads((data_dir / 'manifest.json').read_text(encoding='utf-8'))
    rgb = json.loads((data_dir / 'rgb.json').read_text(encoding='utf-8'))
    refs = {r['file'] for r in manifest['runs']} | {r['file'] for r in rgb.values()}
    assets = {}
    for ref in sorted(refs):
        parts = ref.split('/')
        if len(parts) != 2 or parts[0] != 'data' or parts[1] in ('', '.', '..') or '\\' in ref:
            raise ValueError('Invalid asset path: ' + ref)
        path = (data_dir / parts[1]).resolve()
        if path.parent != data_dir:
            raise ValueError('Asset outside data directory: ' + ref)
        assets[ref] = path.read_bytes()
    for run in manifest['runs']:
        if len(assets[run['file']]) != run['count'] * 16:
            raise ValueError('Point-cloud byte count mismatch')
    for recording in rgb.values():
        raw = assets[recording['file']]
        previous = float('-inf')
        for frame in recording['frames']:
            offset, size = frame['offset'], frame['bytes']
            if offset < 0 or size < 4 or offset + size > len(raw) or frame['t'] < previous:
                raise ValueError('Invalid RGB frame index')
            if raw[offset:offset+2] != b'\xff\xd8' or raw[offset+size-2:offset+size] != b'\xff\xd9':
                raise ValueError('Invalid JPEG frame boundary')
            previous = frame['t']
    for name, value in [('manifest.json', manifest), ('rgb.json', rgb)]:
        assets['data/' + name] = json.dumps(public_metadata(value), ensure_ascii=False).encode('utf-8')
    return assets


def build(data_dir, output, mode='portable'):
    assets = read_assets(data_dir)
    # Never overwrite a previous delivery or an input dataset.
    output.mkdir(parents=True, exist_ok=False)
    web = ROOT / 'web'
    if mode in ('web', 'hosted'):
        shutil.copytree(web, output, dirs_exist_ok=True, ignore=shutil.ignore_patterns('data'))
        (output / 'data').mkdir()
        if mode == 'hosted':
            write_hosted_assets(output, assets)
        else:
            for ref, raw in assets.items():
                (output / ref).write_bytes(raw)
        return
    (output / 'assets').mkdir()
    mapping = {}
    for ref, raw in assets.items():
        name = ref.split('/')[1] + '.js'
        mapping[ref] = 'assets/' + name
        (output / 'assets' / name).write_text(
            'window.__portableData(' + json.dumps(ref) + ',' + json.dumps(base64.b64encode(raw).decode()) + ');',
            encoding='utf-8')
    three = (web / 'vendor/three.module.js').read_text(encoding='utf-8')
    orbit = (web / 'vendor/OrbitControls.js').read_text(encoding='utf-8')
    app = (web / 'app.js').read_text(encoding='utf-8').replace('fetch(', 'window.portableFetch(')
    # Serialize each source separately: replacing placeholders after insertion can
    # accidentally replace matching words inside the bundled library sources.
    start = 'const assetFiles=' + json.dumps(mapping) + ';\n'
    start += (ROOT / 'portable-loader.js').read_text(encoding='utf-8')
    start += 'const threeUrl=moduleUrl(' + json.dumps(three) + ');\n'
    start += 'const orbitSource=' + json.dumps(orbit) + ';\n'
    start += "const orbitUrl=moduleUrl(orbitSource.replace(\"from 'three'\",'from '+JSON.stringify(threeUrl)));\n"
    start += 'const originalApp=' + json.dumps(app) + ';\n'
    start += "const appSource=originalApp.replace(\"from 'three'\",'from '+JSON.stringify(threeUrl)).replace(\"from './vendor/OrbitControls.js'\",'from '+JSON.stringify(orbitUrl));\n"
    start += "import(moduleUrl(appSource)).catch(e=>{document.getElementById('loadState').textContent='起動できません：'+e.message;});\n"
    (output / 'start.js').write_text(start, encoding='utf-8')
    html = (web / 'index.html').read_text(encoding='utf-8')
    html = re.sub(r'<script type="importmap">.*?</script>', '', html)
    html = html.replace('<script type="module" src="app.js"></script>', '<script src="start.js"></script>')
    html = html.replace(' このPC内で表示', ' オフライン版')
    (output / 'ビューアーを開く.html').write_text(html, encoding='utf-8')
    shutil.copy2(web / 'style.css', output / 'style.css')
    shutil.copy2(web / 'vendor/THREE-LICENSE.txt', output / 'THREE-LICENSE.txt')
    shutil.copy2(ROOT / '配布先向け説明.txt', output / '最初にお読みください.txt')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path, help='New directory; existing paths are rejected')
    parser.add_argument('--mode', choices=['portable', 'web', 'hosted'], default='portable')
    parser.add_argument('--zip', action='store_true', help='Also create output-directory-name.zip')
    args = parser.parse_args()
    archive = args.output.with_name(args.output.name + '.zip')
    if args.zip and archive.exists():
        parser.error('ZIP already exists: ' + str(archive))
    build(args.data_dir, args.output, args.mode)
    if args.zip:
        with zipfile.ZipFile(archive, 'x', zipfile.ZIP_DEFLATED) as z:
            for file in sorted(args.output.rglob('*')):
                if file.is_file():
                    z.write(file, file.relative_to(args.output.parent))
        with zipfile.ZipFile(archive) as z:
            if z.testzip() is not None:
                raise RuntimeError('ZIP integrity check failed')
        print(archive)
    print(args.output)


if __name__ == '__main__':
    main()
