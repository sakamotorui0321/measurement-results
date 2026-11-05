"""Create a lightweight synchronized frame browser from a stopped VOXL recording."""
import argparse
import html
import json
import re
import tempfile
from bisect import bisect_left
from pathlib import Path

from catalog import MEASUREMENTS, rebuild


def convert(source, folder, step):
    import cv2
    import numpy as np

    status = json.loads((source / 'status.json').read_text())
    if status['state'] != 'stopped' or status.get('error'):
        raise ValueError('正常停止した録画を指定してください')
    match = re.fullmatch(r'(\d+)x(\d+) (\d+(?:\.\d+)?)fps depth=Z16_LE color=YUYV', status['format'])
    if not match:
        raise ValueError('未対応の撮影形式: ' + status['format'])
    w, h = map(int, match.groups()[:2])
    fps = float(match[3])
    streams = {'depth': [], 'color': []}
    with (source / 'frames.jsonl').open() as rows:
        for line in rows:
            row = json.loads(line)
            streams[row['stream']].append((row['timestamp_monotonic'], row['offset'], row['bytes']))
    depth, color = (sorted(streams[k]) for k in ('depth', 'color'))
    times = [r[0] for r in depth]
    if not color:
        raise ValueError('カラー画像がありません')
    def read(file, row, dtype, shape):
        if row[1] < 0 or row[2] != w*h*2:
            raise ValueError('不正なフレーム索引')
        file.seek(row[1])
        return np.frombuffer(file.read(row[2]), dtype=dtype).reshape(shape)

    frames = []
    with (source / 'color.yuyv').open('rb') as rgb, (source / 'depth.z16').open('rb') as z:
        for i, row in enumerate(color[::step]):
            yuv = read(rgb, row, 'u1', (h,w,2))
            picture = cv2.cvtColor(yuv, cv2.COLOR_YUV2BGR_YUY2)
            idx = bisect_left(times, row[0])
            near = min(depth[max(0,idx-1):idx+1], key=lambda r: abs(r[0]-row[0]), default=None)
            delta = None
            if near and abs(near[0]-row[0]) <= 1/fps:
                raw = read(z, near, '<u2', (h,w))
                gray = (np.minimum(raw, 4000) * (255.0/4000)).astype('uint8')
                image = cv2.applyColorMap(gray, cv2.COLORMAP_TURBO)
                image[raw == 0] = 0
                delta = round((near[0]-row[0])*1000, 1)
            else:
                image = np.zeros_like(picture)
            if not cv2.imwrite(str(folder / f'{i}.jpg'), np.hstack([picture,image])):
                raise OSError('画像の書き込みに失敗')
            frames.append([round(row[0]-color[0][0],3),delta])
    return frames


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('recording', type=Path)
    p.add_argument('id', help='YYYY-MM-DD_HHMMSS_測定名')
    p.add_argument('--title', required=True)
    p.add_argument('--step', type=int, default=15, help='カラー何フレームごとに収録するか')
    a = p.parse_args()
    if not re.fullmatch(r'\d{4}-\d\d-\d\d_[\w-]+', a.id) or a.step < 1:
        p.error('測定IDまたはstepが不正です')
    dest = MEASUREMENTS / a.id
    if dest.exists():
        p.error('同じ測定IDが存在します')
    with tempfile.TemporaryDirectory(dir=MEASUREMENTS, prefix='.import-') as temp:
        folder = Path(temp) / 'result'
        folder.mkdir()
        frames = convert(a.recording, folder, a.step)
        title = html.escape(a.title)
        page = f'''<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>{title}</title>
<style>body{{max-width:1100px;margin:4vh auto;padding:0 1rem;font:16px/1.5 system-ui;color:#18352e}}img,input{{width:100%}}</style>
<a href="../../">← 測定一覧</a><h1>{title}</h1><p>左はカラー、右は深度です。深度は生の値0を黒、1〜4000を寒色から暖色で表示します。</p>
<img id="picture" src="0.jpg" alt="カラーと深度の対応画像"><label>撮影時刻 <input id="slider" type="range" min="0" max="{len(frames)-1}" value="0"></label><output id="stamp"></output>
<script>const frames={json.dumps(frames)};function show(){{const [t,d]=frames[slider.value];picture.src=slider.value+'.jpg';stamp.textContent=t+' 秒 / '+(d===null?'対応する深度なし':'深度との時差 '+d+' ms');}}slider.oninput=show;show()</script></html>'''
        (folder/'index.html').write_text(page,encoding='utf-8')
        (folder/'title.txt').write_text(a.title+'\n',encoding='utf-8')
        folder.rename(dest)
    rebuild()


if __name__ == '__main__':
    main()
