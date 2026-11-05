"""Import one completed measurement and refresh the shared site."""
import argparse
from pathlib import Path
import re
import subprocess
import sys

from catalog import ROOT, rebuild

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('device', choices=['go2','starling2'])
    parser.add_argument('recording', type=Path)
    parser.add_argument('id', help='YYYY-MM-DD_HHMMSS_測定名')
    parser.add_argument('--title', required=True)
    parser.add_argument('--bag', type=Path)
    parser.add_argument('--step', type=int, default=15)
    args = parser.parse_args()
    if not re.fullmatch(r'\d{4}-\d\d-\d\d_[\w-]+', args.id) or args.step < 1:
        parser.error('測定IDまたはstepが不正です')
    if args.device == 'go2':
        command = [sys.executable, str(ROOT/'scripts/go2/import_recording.py'), str(args.recording),
                   str(ROOT/'go2/measurements'/args.id), '--title', args.title]
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
