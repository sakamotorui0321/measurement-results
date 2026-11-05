"""Locate a verified local flower model and prepare a private CPU inference environment."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
MODEL = 'tomato_flower_yolov8n.pt'
DIGEST = '923bea0c52ffeefff3779a6bcadbe94c54bb939339ac55e21ead959faa6166b9'

def weights_for(exp):
    override = os.environ.get('STARLING2_WEIGHTS')
    if override:
        path = Path(override).expanduser()
        if not path.is_file():
            raise FileNotFoundError(path)
        return path
    candidates = [
        exp/'config'/MODEL,
        Path.home()/'.local/share/measurement-results'/MODEL,
        *sorted(exp.parent.glob(f'*/analysis/*/config/go2_original/{MODEL}')),
    ]
    for path in candidates:
        if path.is_file():
            with path.open('rb') as stream:
                if hashlib.file_digest(stream,'sha256').hexdigest() == DIGEST:
                    return path
    raise FileNotFoundError(f'共有実験データの10月22日花検出モデル、または実験の config/{MODEL} を同期してください。')

def yolo_python():
    override = os.environ.get('STARLING2_YOLO_PYTHON')
    if override:
        return str(Path(override).expanduser())
    for folder in [ROOT/'.venv', Path.home()/'.venvs/go2-processor']:
        python = folder/'bin/python'
        if python.exists() and subprocess.run(
            [str(python),'-s',str(ROOT/'scripts/check_starling2_runtime.py')],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        ).returncode == 0:
            return str(python)
    subprocess.run(['bash',str(ROOT/'scripts/setup_starling2.sh')],check=True)
    return str(ROOT/'.venv/bin/python')
