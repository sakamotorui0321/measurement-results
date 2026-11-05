"""Build the shared home page and both measurement lists."""
import html
import os
from pathlib import Path
import tempfile
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
MEASUREMENTS = ROOT / 'starling2/measurements'
DEVICES = {'go2': 'Go2 ・ 走行計測', 'starling2': 'Starling2 ・ RealSense'}
STYLE = """*{box-sizing:border-box}body{margin:0;background:#f4f7f5;color:#18352e;font:16px/1.65 system-ui,sans-serif}main{max-width:900px;margin:auto;padding:7vh 5vw}small{letter-spacing:.06em;color:#536b61}h1{margin:.25em 0}ul{list-style:none;padding:0}li a{display:block;background:white;border:1px solid #c7d7cd;border-left:5px solid #237350;border-radius:8px;padding:1rem 1.4rem;margin:1rem 0;text-decoration:none}strong{display:block;font-size:1.25rem;color:#19372d}a{color:#12694a}a:hover strong{text-decoration:underline}nav{display:flex;gap:1.4rem;flex-wrap:wrap}"""

def write_page(path, title, content):
    page = f"""<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title><style>{STYLE}</style><main><small>実機実験 / 測定アーカイブ</small><h1>{html.escape(title)}</h1>{content}</main></html>"""
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as out:
        out.write(page)
    os.replace(out.name, path)

def rebuild():
    sections = []
    for device, name in DEVICES.items():
        links = []
        for folder in sorted((ROOT/device/'measurements').iterdir(), reverse=True):
            if folder.name.startswith('.') or not (folder/'index.html').is_file():
                continue
            title_file = folder/'title.txt'
            title = title_file.read_text(encoding='utf-8').strip() if title_file.exists() else folder.name
            links.append(f'<li><a href="measurements/{quote(folder.name)}/"><small>{html.escape(folder.name)}</small><strong>{html.escape(title)}</strong>ビューアーを開く →</a></li>')
        body = '<ul>'+''.join(links)+'</ul>'
        nav = '<nav><a href="../">すべての測定</a>'+''.join(f'<a href="../{key}/">{value}</a>' for key,value in DEVICES.items() if key != device)+'</nav>'
        write_page(ROOT/device/'index.html', name, nav+body)
        sections.append(f'<section><h2>{name}</h2>'+body.replace('href="measurements/',f'href="{device}/measurements/')+'</section>')
    write_page(ROOT/'index.html', 'Go2・Starling2 測定結果', '<p>機体と測定を選んで、映像・点群・解析結果を確認できます。</p>'+''.join(sections))

if __name__ == '__main__':
    rebuild()
