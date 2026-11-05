#!/usr/bin/env python3
"""Refresh analyzed flower viewers and the measurement library."""
from catalog import MEASUREMENTS, ROOT, rebuild

VIDEOS = {'rgb':'RGB', 'depth':'Depth', 'paired':'RGB・Depth左右比較', 'flowers':'花検出'}

def render(folder):
    template = (ROOT/'src/viewer.html').read_text(encoding='utf-8')
    assert template.count('__DATA__') == 1
    html = template.replace('const DATA=__DATA__;', 'const DATA=window.FLOWER_DATA;')
    html = html.replace('<script>\nconst DATA=', '<script src="data.js"></script>\n<script>\nconst DATA=')
    html = html.replace('<div id="status"></div>', '<div id="status">点群・画像を読み込み中…</div>')
    nav = '<a style="color:inherit" href="../../">← 測定一覧</a>'
    for key, title in VIDEOS.items():
        if (folder/'videos'/f'{key}.mp4').is_file():
            nav += f' <a style="color:inherit" href="videos/{key}.mp4">{title}動画</a>'
    (folder/'index.html').write_text(html.replace('<header>', '<header>'+nav),encoding='utf-8')

if __name__ == '__main__':
    for payload in MEASUREMENTS.glob('*/data.js'):
        if not payload.parent.name.startswith('.'):
            render(payload.parent)
    rebuild()
