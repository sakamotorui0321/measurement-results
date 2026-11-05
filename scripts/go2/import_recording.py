"""Package a stopped Go2 Recorder session for the static measurement library."""
import argparse
from datetime import datetime
import json
import math
from pathlib import Path
import sqlite3
import struct
import tempfile

from build import build


def rows(path):
    with path.open(encoding='utf-8') as f:
        for line in f:
            yield json.loads(line)


def measurement(source, data, title):
    meta = json.loads((source/'manifest.json').read_text())
    if meta['state'] != 'stopped':
        raise ValueError('正常停止した録画を指定してください')
    origin = datetime.fromisoformat(meta['started_utc']).timestamp()
    trajectory, seen = [], set()
    low, high = [math.inf]*3, [-math.inf]*3
    session = None
    with (data/'points.bin').open('wb') as out:
        for row in rows(source/'external-lidar.jsonl'):
            pose = row.get('pose')
            if not pose or row['frame'] != 'unilidar_lidar':
                continue
            if session is not None and session != pose['session']:
                raise ValueError('自己位置のリセットを検出。区間別に解析してください')
            session = pose['session']
            t = max(0, row['received_unix']-origin)
            if trajectory and t < trajectory[-1][0]:
                raise ValueError('点群の時計が逆行しました')
            trajectory.append([t]+pose['xyz'])
            qx,qy,qz,qw = pose['quaternion']
            for x,y,z in row['points']:
                # Same nominal external L2 mounting offsets as CloudMap.defaultMount.
                x += .20
                z += .11
                tx,ty,tz = 2*(qy*z-qz*y),2*(qz*x-qx*z),2*(qx*y-qy*x)
                delta = (x+qw*tx+qy*tz-qz*ty,y+qw*ty+qz*tx-qx*tz,z+qw*tz+qx*ty-qy*tx)
                world = [d+p for d,p in zip(delta,pose['xyz'])]
                key = tuple(math.floor(v/.02) for v in world)
                if key in seen:
                    continue
                seen.add(key)
                out.write(struct.pack('<4f', *world,t))
                low = list(map(min,low,world))
                high = list(map(max,high,world))
    if not seen:
        raise ValueError('同期姿勢付き外付けLiDAR点群がありません')
    frames = []
    duration = trajectory[-1][0]
    with (data/'rgb.mjpeg').open('wb') as video:
        # Recordings may have been copied into a differently named directory.
        filename = 'rgb_'+meta['id']+'.mjpeg'
        if Path(filename).name != filename:
            raise ValueError('invalid recording ID')
        with (source/filename).open('rb') as raw:
            for row in rows(source/'rgb.jsonl'):
                if row['file'] != filename or row['offset'] < 0 or row['bytes'] < 4:
                    raise ValueError('invalid RGB index')
                raw.seek(row['offset'])
                frame = raw.read(row['bytes'])
                if len(frame) != row['bytes']:
                    raise ValueError('incomplete RGB frame')
                t = datetime.fromisoformat(row['saved_utc']).timestamp()-origin
                frames.append(dict(t=t, offset=video.tell(), bytes=len(frame)))
                video.write(frame)
                duration = max(duration,t)
    if not frames:
        raise ValueError('RGB記録がありません')
    run = dict(id=1,title=title,count=len(seen),duration=duration,bounds=[low,high],
               trajectory=trajectory,file='data/points.bin')
    (data/'manifest.json').write_text(json.dumps({'runs':[run]}))
    (data/'rgb.json').write_text(json.dumps({'1':dict(file='data/rgb.mjpeg', maxAge=.75,frames=frames)}))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('recording',type=Path)
    p.add_argument('output',type=Path)
    p.add_argument('--title',required=True)
    p.add_argument('--bag',type=Path,help='同時収録したbagセッション（data/*.db3）')
    a = p.parse_args()
    if a.output.exists():
        p.error('出力先は新しい測定フォルダにしてください')
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=a.output.parent,prefix='.import-') as temp:
        temp = Path(temp)
        data,site = temp/'data',temp/'site'
        data.mkdir()
        measurement(a.recording,data,a.title)
        build(data,site,'hosted')
        (site/'title.txt').write_text(a.title+'\n',encoding='utf-8')
        index = site/'index.html'
        page = index.read_text(encoding='utf-8').replace('<header>', '<header><a href="../../" style="color:inherit">← 測定一覧</a>')
        if a.bag:
            from contextlib import closing
            import html
            bag_meta = json.loads((a.bag/'session.json').read_text())
            totals = dict.fromkeys(bag_meta.get('topics', []), 0)
            files = sorted((a.bag/'data').glob('*.db3'))
            if not files or not (a.bag/'data/metadata.yaml').is_file():
                p.error('確定済みのbagを指定してください')
            for db in files:
                with closing(sqlite3.connect(db.resolve().as_uri()+'?mode=ro',uri=True)) as con:
                    for name,n in con.execute('SELECT t.name,count(m.id) FROM topics t LEFT JOIN messages m ON m.topic_id=t.id GROUP BY t.id'):
                        totals[name] = totals.get(name,0)+n
            summary = '<details><summary>ROSトピック受信件数</summary><ul>'+''.join(
                f'<li>{html.escape(k)} · {v} 件</li>' for k,v in sorted(totals.items()))+'</ul></details>'
            page = page.replace('</aside>',summary+'</aside>')
        index.write_text(page,encoding='utf-8')
        site.rename(a.output)


if __name__ == '__main__':
    main()
