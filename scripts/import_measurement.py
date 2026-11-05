"""Import one completed measurement and refresh the shared site."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

from catalog import ROOT, rebuild

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('device', choices=['go2','starling2'])
    parser.add_argument('recording', type=Path)
    parser.add_argument('id', nargs='?', help='YYYY-MM-DD_HHMMSS_測定名')
    parser.add_argument('--title')
    parser.add_argument('--bag', type=Path)
    parser.add_argument('--step', type=int, default=15)
    args = parser.parse_args()
    if args.device == 'starling2' and args.id is None and not args.title and not args.bag and args.step == 15:
        from starling2_experiment import import_experiment
        import_experiment(args.recording)
        return
    conditions = None
    if args.device == 'go2' and args.id is None:
        experiment = args.recording.resolve()
        args.id = experiment.name
        args.title = args.title or experiment.name
        recordings = list((experiment/'raw').rglob('external-lidar.jsonl'))
        if len(recordings) != 1:
            parser.error('実験フォルダのraw以下に1件のL2録画が必要です')
        args.recording = recordings[0].parent
        if (args.recording/'rgbd.jsonl').exists() or 'rgbd' in json.loads((args.recording/'manifest.json').read_text())['sources']:
            conditions = experiment/'config/l2-color.json'
            if not conditions.is_file():
                parser.error('検証した校正値と静止条件 config/l2-color.json が必要です')
    if not args.id or not args.title:
        parser.error('個別録画の取り込みには測定IDと --title が必要です')
    if not re.fullmatch(r'\d{4}-\d\d-\d\d_[\w-]+', args.id) or args.step < 1:
        parser.error('測定IDまたはstepが不正です')
    if args.device == 'go2':
        command = [sys.executable, str(ROOT/'scripts/go2/import_recording.py'), str(args.recording),
                   str(ROOT/'go2/measurements'/args.id), '--title', args.title]
        if conditions:
            from datetime import datetime
            audit = experiment/'analysis'/datetime.now().astimezone().strftime('%Y%m%dT%H%M%S%z_l2-color')
            command += ['--conditions',str(conditions),'--audit',str(audit)]
        if args.bag:
            command += ['--bag',str(args.bag)]
    else:
        if args.bag:
            parser.error('--bag はGo2用です')
        command = [sys.executable, str(ROOT/'scripts/import_realsense.py'), str(args.recording),
                   args.id, '--title',args.title, '--step',str(args.step)]
    subprocess.run(command, check=True)
    rebuild()

if __name__ == '__main__':
    main()
