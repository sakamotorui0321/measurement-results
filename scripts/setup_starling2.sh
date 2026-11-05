#!/usr/bin/env bash
# Ubuntu 24.04: leave apt and the flight workspace untouched.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
export PYTHONNOUSERSITE=1
cd "$root"
exec 9>".starling2-setup.lock"
flock 9
if [[ -x .venv/bin/python ]] && .venv/bin/python scripts/check_starling2_runtime.py >/dev/null 2>&1; then
    exit 0
fi
/usr/bin/python3 -c 'import cv2,numpy,scipy,matplotlib,PIL,psutil,yaml,requests' || {
    echo 'Ubuntuの前提パッケージはREADMEの「ノートPC」に記載しています。' >&2
    exit 1
}
/usr/bin/python3 -m venv --system-site-packages .venv
.venv/bin/python -m pip install --index-url https://download.pytorch.org/whl/cpu 'torch==2.14.1' 'torchvision==0.29.1'
# The Ubuntu OpenCV build supplies the H.264 encoder; avoid the conflicting PyPI wheel.
.venv/bin/python -m pip install 'mcap-ros2-support==0.5.7'
.venv/bin/python -m pip install --no-deps 'ultralytics==8.4.86'
.venv/bin/python scripts/check_starling2_runtime.py
