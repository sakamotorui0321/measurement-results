"""Write full-rate 640x480 RGB, depth, paired RGB-D, and detection videos."""
from contextlib import ExitStack
import json
from pathlib import Path
import shutil
import sys

import cv2
import numpy as np

def depth_image(raw, offset):
    samples = np.frombuffer(raw, dtype='<u2', count=640*480, offset=offset).reshape(480, 640)
    gray = np.rint(np.clip(samples / 2000., 0, 1) * 255).astype(np.uint8)
    result = cv2.applyColorMap(255-gray, cv2.COLORMAP_TURBO)
    result[samples == 0] = 0
    cv2.rectangle(result, (0,448), (639,479), (0,0,0), -1)
    cv2.putText(result, 'Depth: 0-2000 raw units | black: invalid', (8,469),
                cv2.FONT_HERSHEY_SIMPLEX, .48, (255,255,255), 1, cv2.LINE_AA)
    return result

def convert(raw, work, out):
    cv2.setNumThreads(2)
    records = [json.loads(line) for line in (raw/'frames.jsonl').read_text().splitlines()]
    rgb, depth = ([row for row in records if row['stream'] == kind] for kind in ('color','depth'))
    times = np.array([row['timestamp_monotonic'] for row in depth])
    color_data = np.memmap(raw/'color.yuyv', mode='r', dtype='u1')
    depth_data = np.memmap(raw/'depth.z16', mode='r', dtype='u1')
    with ExitStack() as stack:
        def writer(name, width):
            video = cv2.VideoWriter(str(out/name), cv2.VideoWriter_fourcc(*'avc1'), 15, (width,480))
            if not video.isOpened():
                raise RuntimeError(f'H.264 encoder unavailable: {name}')
            stack.callback(video.release)
            return video
        single, metric, pair = writer('rgb.mp4',640), writer('depth.mp4',640), writer('paired.mp4',1280)
        for row in depth:
            metric.write(depth_image(depth_data, row['offset']))
        for row in rgb:
            pixels = np.frombuffer(color_data, dtype='u1', count=640*480*2, offset=row['offset'])
            color = cv2.cvtColor(pixels.reshape(480,640,2), cv2.COLOR_YUV2BGR_YUY2)
            single.write(color)
            t = row['timestamp_monotonic']
            after = int(np.searchsorted(times,t))
            nearest = min({max(0,after-1),min(len(depth)-1,after)}, key=lambda i:(abs(times[i]-t),i))
            image = np.hstack([color,depth_image(depth_data, depth[nearest]['offset'])])
            cv2.rectangle(image,(0,0),(1279,28),(0,0,0),-1)
            for label,x in [('RGB',10),('Depth',650)]:
                cv2.putText(image,label,(x,21),cv2.FONT_HERSHEY_SIMPLEX,.6,(255,255,255),1,cv2.LINE_AA)
            pair.write(image)
    shutil.copyfile(work/'detect/detections.mp4',out/'flowers.mp4')
    for name, count in [('rgb',len(rgb)),('depth',len(depth)),('paired',len(rgb)),('flowers',len(rgb))]:
        cap = cv2.VideoCapture(str(out/f'{name}.mp4'))
        try:
            actual = 0
            while cap.grab():
                if not cap.retrieve()[0]:
                    raise ValueError(f'{name}: frame decoding failed')
                actual += 1
            if count != actual or cap.get(cv2.CAP_PROP_FPS) != 15:
                raise ValueError(f'{name}: expected {count} frames at 15 fps, decoded {actual}')
        finally:
            cap.release()

if __name__ == '__main__':
    convert(*map(Path,sys.argv[1:]))
