"""Check inference imports, matching CPU operators, and the actual MP4 encoder."""
from importlib.metadata import version
from pathlib import Path
import tempfile
import cv2
import numpy as np
import torch
from torchvision.ops import nms
from ultralytics import YOLO
from mcap_ros2.reader import read_ros2_messages

if version('ultralytics') != '8.4.86':
    raise RuntimeError('ultralytics==8.4.86 が必要です')
nms(torch.tensor([[0.,0.,1.,1.]]),torch.tensor([0.9]),0.5)
with tempfile.TemporaryDirectory() as tmp:
    path = str(Path(tmp)/'probe.mp4')
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*'avc1'),15,(64,64))
    if not writer.isOpened():
        raise RuntimeError('UbuntuのH.264対応 python3-opencv が必要です')
    writer.write(np.zeros((64,64,3),np.uint8))
    writer.release()
    capture = cv2.VideoCapture(path)
    try:
        if not capture.read()[0]:
            raise RuntimeError('H.264 MP4を読み戻せません')
    finally:
        capture.release()
