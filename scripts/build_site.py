#!/usr/bin/env python3
"""Refresh all analyzed flower viewers and the measurement library."""
from catalog import MEASUREMENTS, ROOT, rebuild

template = (ROOT / 'src/viewer.html').read_text(encoding='utf-8')
assert template.count('__DATA__') == 1
html = template.replace('const DATA=__DATA__;', 'const DATA=window.FLOWER_DATA;')
html = html.replace('<script>\nconst DATA=', '<script src="data.js"></script>\n<script>\nconst DATA=')
html = html.replace('<div id="status"></div>', '<div id="status">点群・画像を読み込み中…</div>')
html = html.replace('<header>', '<header><a style="color:inherit" href="../../">← 測定一覧</a>')
for payload in MEASUREMENTS.glob('*/data.js'):
    (payload.parent / 'index.html').write_text(html, encoding='utf-8')
rebuild()
