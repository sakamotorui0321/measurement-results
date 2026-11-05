"""Import a complete Starling2 experiment into the local measurement viewer."""
from datetime import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from zoneinfo import ZoneInfo

from build_site import VIDEOS, render
from catalog import ROOT, MEASUREMENTS, rebuild

STAGES = ROOT/'scripts/starling2'
WS = Path(os.environ.get('STARLING2_WS', Path.home()/'agricultural_support_ws'))
WEIGHTS = Path(os.environ.get('STARLING2_WEIGHTS', Path.home()/'.local/share/measurement-results/tomato_flower_yolov8n.pt'))
YOLO = Path(os.environ.get('STARLING2_YOLO_PYTHON', Path.home()/'.venvs/go2-processor/bin/python'))
PYTHON = '/usr/bin/python3'

def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))

def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()

def one(paths, label):
    paths = list(paths)
    if len(paths) != 1:
        raise ValueError(f'{label} を1件に特定できません（{len(paths)}件）')
    return paths[0]

def inputs(exp):
    cameras = exp/'raw/voxl/recordings/realsense'
    bags = exp/'raw/pi'
    info = exp/'raw/pc/FLIGHT_RESULT.json'
    recording = read(info).get('recording',{}) if info.exists() else {}
    raw = one((p for p in cameras.glob('*/status.json') if not recording.get('voxl')
               or p.parent.name == Path(recording['voxl']).name),'RealSense録画').parent
    bag = one((p for p in bags.rglob('metadata.yaml') if not recording.get('pi')
               or Path(recording['pi']).name in p.relative_to(bags).parts),'ROS bag').parent
    if not re.fullmatch(r'\d{4}-\d\d-\d\d_\d{6}_[\w-]+',raw.name):
        raise ValueError(f'録画IDに日時がありません: {raw.name}')
    return raw,bag

def calibration_for(exp, raw):
    status = read(raw/'status.json')
    native = raw/'calibration.json'
    if native.is_file():
        if sha(native) == status.get('calibration_sha256') and read(native)['device']['serial'] == status.get('camera_serial'):
            return native
        raise ValueError('録画の工場校正のハッシュまたはカメラ番号が一致しません')
    # Older recordings may have a validated factory calibration in the experiment archive.
    verified = {}
    for cal in (exp/'analysis').glob('*/config/factory_bound.json'):
        manifest = cal.parents[1]/'manifest.json'
        if not manifest.is_file():
            continue
        record = read(manifest)
        binding = record.get('calibration',{})
        sources = record.get('input_files',{})
        if (binding.get('same_device_no_recalibration_confirmed') is True
                and sources.get('status.json',{}).get('sha256') == sha(raw/'status.json')
                and sources.get('color.yuyv',{}).get('sha256') == status.get('sha256_color')
                and sources.get('depth.z16',{}).get('sha256') == status.get('sha256_depth')
                and binding.get('sha256') == sha(cal)):
            verified[sha(cal)] = cal
    return one(verified.values(),'録画に対応付けて検証済みの工場校正')

def analyze(exp, raw, bag, work, site):
    scripts = STAGES
    env = dict(os.environ,PYTHONNOUSERSITE='1',OPENBLAS_NUM_THREADS='3',OMP_NUM_THREADS='4')
    def run(*args):
        subprocess.run(list(map(str,args)),env=env,check=True)
    cal = calibration_for(exp, raw)
    mount = exp/'config/mount.json'
    shutil.copyfile(mount if mount.is_file() else STAGES/'mount.json',work/'mount.json')
    run('bash','-c','set -e; source /opt/ros/jazzy/setup.bash; source "$1/install/local_setup.bash"; shift; exec "$@"',
        'extract',WS,PYTHON,scripts/'extract_flower_map_poses.py','--bag',bag,'--output',work/'poses.json')
    run(YOLO,scripts/'detect_recorded_flowers.py','--weights',WEIGHTS,'--recording',raw,'--output',work/'detect')
    run(PYTHON,scripts/'localize_recorded_flowers.py','--recording',raw,'--detections',work/'detect/detections.csv',
        '--calibration',cal,'--same-device-confirmed','--output',work/'positions')
    if read(work/'positions/manifest.json')['statuses'].get('estimated',0):
        run(PYTHON,scripts/'map_recorded_flowers.py','--positions',work/'positions/positions.csv',
            '--clock',raw/'clock.jsonl','--poses',work/'poses.json','--mount',work/'mount.json','--output',work/'world')
    else:
        run(PYTHON,STAGES/'empty_world.py',raw,work,scripts)
    run(PYTHON,STAGES/'make_cloud.py',raw,work,scripts,cal)
    run(PYTHON,STAGES/'make_payload.py',raw,work,scripts)
    (site/'videos').mkdir()
    run(PYTHON,STAGES/'videos.py',raw,work,site/'videos')
    shutil.copyfile(work/'data.js',site/'data.js')
    stats = read(work/'viewer_stats.json')
    if sha(site/'data.js') != stats['data_sha256']:
        raise OSError('点群データのコピー検証に失敗しました')
    return stats

def verify_reuse(exp,raw,bag,site,manifest):
    work = Path(manifest['analysis'])
    detect = read(work/'detect/manifest.json')
    pose_source = read(work/'poses.json')['source']
    calibration = calibration_for(exp,raw)
    mount = exp/'config/mount.json'
    checks = {raw/name:meta['sha256'] for name,meta in detect['input_files'].items()}
    checks.update({bag/name:meta['sha256'] for name,meta in pose_source['files'].items()})
    checks[WEIGHTS] = detect['weights']['sha256']
    checks[calibration] = read(work/'positions/manifest.json')['calibration']['sha256']
    checks[mount if mount.is_file() else STAGES/'mount.json'] = sha(work/'mount.json')
    world = read(work/'world/manifest.json')
    if 'inputs' in world:
        checks[raw/'clock.jsonl'] = world['inputs']['clock']['sha256']
    checks[site/'data.js'] = manifest['stats']['data_sha256']
    checks.update({site/'videos'/f'{key}.mp4':digest for key,digest in manifest['videos'].items()})
    for path,expected in checks.items():
        if not path.is_file() or sha(path) != expected:
            raise ValueError(f'登録済み結果とファイルが一致しません: {path}')

def deliver(site, progress, stem, manifest):
    progress.mkdir(parents=True,exist_ok=True)
    for key,label in VIDEOS.items():
        src = site/'videos'/f'{key}.mp4'
        dst = progress/f'{stem}_{label}.mp4'
        expected = manifest['videos'][key]
        if dst.exists():
            if sha(dst) != expected:
                raise FileExistsError(f'異なる既存動画を保持しました: {dst}')
            continue
        with tempfile.NamedTemporaryFile(dir=progress,suffix='.tmp',delete=False) as stream:
            tmp = Path(stream.name)
        try:
            shutil.copyfile(src,tmp)
            if sha(tmp) != expected:
                raise OSError(f'動画のコピー検証に失敗しました: {dst}')
            os.link(tmp,dst)
        finally:
            tmp.unlink(missing_ok=True)

def append_link(path, label, target):
    if not path.is_file():
        return
    relative = os.path.relpath(target,path.parent)
    entry = f'- [{label}](<{relative}>)'
    with path.open('r+',encoding='utf-8') as stream:
        fcntl.flock(stream,fcntl.LOCK_EX)
        if entry not in stream.read():
            stream.write('\n'+entry+'\n')

def record_result(exp, site, progress, manifest):
    work = Path(manifest['analysis'])
    report = work/'README.md'
    stats = manifest['stats']
    if not report.exists():
        videos = os.path.relpath(progress,work)
        with report.open('x',encoding='utf-8') as stream:
            stream.write(f"# {exp.name} 統合ビューアー用変換\n\n"
                         f"対象録画 {manifest['recording']}。点群 {stats['cloud_points']:,} 点、"
                         f"深度付き花候補 {stats['observations']:,} 観測、{stats['flower_groups']} 群。"
                         f"元RGB画像 {stats['rgb_frames']:,} 枚に照合。\n\n"
                         f"[動画4本](<{videos}>)。全フレームのデコードと保存先SHA-256を照合。"
                         "クラウド同期は未確認。校正・推定条件・位置精度の限界は "
                         "positions/manifest.json、world/manifest.json、mount.json を参照。\n")
    summary = work/'viewer_result.json'
    if not summary.exists():
        shutil.copyfile(site/'result.json',summary)
    append_link(exp/'README.md','統合ビューアー・3Dと動画4本',report)
    if exp.parent.parent.name=='実験データ':
        append_link(exp.parent.parent/'INDEX.md',f'{exp.name} 統合ビューアー・動画4本',report)

def import_experiment(experiment):
    exp = experiment.resolve()
    raw, bag = inputs(exp)
    timestamp = raw.name[:17]
    name = re.sub(r'^\d{4}-\d\d-\d\d_\d{6}_','',exp.name)
    stem = f'{timestamp}_{name}'
    site = MEASUREMENTS/(raw.name+'_results')
    default_root = (exp.parents[2]/'進捗/動画/実機/Starling2' if exp.parent.parent.name=='実験データ'
                    else exp/'exports')
    progress = Path(os.environ.get('STARLING2_VIDEO_ROOT', default_root))/(timestamp[:10]+'_'+name)
    with (MEASUREMENTS/('.'+site.name+'.lock')).open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        reuse = site.exists()
        if not reuse:
            date = datetime.now(ZoneInfo('Asia/Tokyo')).strftime('%Y-%m-%d_%H%M%S')
            work = exp/'analysis'/(date+'_統合ビューアー')
            work.mkdir(parents=True)
            with tempfile.TemporaryDirectory(dir=MEASUREMENTS,prefix='.import-') as temporary:
                staging = Path(temporary)/site.name
                staging.mkdir()
                stats = analyze(exp,raw,bag,work,staging)
                manifest = dict(recording=raw.name,experiment=str(exp),analysis=str(work),
                                source_status=sha(raw/'status.json'),stats=stats,
                                videos={key:sha(staging/'videos'/f'{key}.mp4') for key in VIDEOS})
                (staging/'result.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
                (staging/'title.txt').write_text(f'{name} · 3D点群・花候補・動画4本\n')
                render(staging)
                staging.rename(site)
        manifest = read(site/'result.json')
        if manifest['source_status'] != sha(raw/'status.json') or manifest['experiment'] != str(exp):
            raise ValueError('同じ録画IDに異なる実験が登録されています')
        if reuse:
            verify_reuse(exp,raw,bag,site,manifest)
        deliver(site,progress,stem,manifest)
        rebuild()
        record_result(exp,site,progress,manifest)
        print(f'統合ビューアー: {site}\n動画: {progress}')
