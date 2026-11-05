#!/usr/bin/env python3
"""Offline 2D flower inference on finalized Starling2 YUYV recordings.

Uses the same Ultralytics predict interface as Go2 rs_map_mjpeg.py. No ROS,
camera access, robot commands, spatial depth alignment or world coordinates.
"""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import platform
import sys

WIDTH, HEIGHT, FPS = 640, 480, 15
FRAME_BYTES = WIDTH * HEIGHT * 2
FORMAT = '640x480 15fps depth=Z16_LE color=YUYV'


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_recording(path):
    """Reject unfinished, mismatched, truncated or ambiguous recordings."""
    path = Path(path)
    status = json.loads((path / 'status.json').read_text())
    if status.get('finalized') is not True or status.get('error') is not None:
        raise ValueError('Recording must be finalized without capture errors')
    if status.get('format') != FORMAT:
        raise ValueError(f'Unsupported format: {status.get("format")}')
    records = [json.loads(line) for line in (path / 'frames.jsonl').read_text().splitlines() if line.strip()]
    streams = {}
    hashes = {}
    for kind, filename in [('color', 'color.yuyv'), ('depth', 'depth.z16')]:
        rows = [row for row in records if row['stream'] == kind]
        if not rows or len(rows) != status.get('frames_' + kind):
            raise ValueError(f'{kind}: frame count mismatch')
        previous = -math.inf
        for index, row in enumerate(rows):
            stamp = row['timestamp_monotonic']
            if not math.isfinite(stamp) or stamp <= previous:
                raise ValueError(f'{kind}: timestamps must increase')
            if row['offset'] != index * FRAME_BYTES or row['bytes'] != FRAME_BYTES:
                raise ValueError(f'{kind}: invalid frame offset/size')
            previous = stamp
        file = path / filename
        if file.stat().st_size != len(rows) * FRAME_BYTES:
            raise ValueError(f'{kind}: raw file size mismatch')
        digest = sha256(file)
        if digest != status.get('sha256_' + kind):
            raise ValueError(f'{kind}: SHA-256 mismatch')
        streams[kind] = rows
        hashes[filename] = {'bytes': file.stat().st_size, 'sha256': digest}
    for name in ['frames.jsonl', 'status.json']:
        hashes[name] = {'bytes': (path / name).stat().st_size, 'sha256': sha256(path / name)}
    return streams, hashes


def read_color(stream, row):
    import cv2
    import numpy as np
    stream.seek(row['offset'])
    data = stream.read(FRAME_BYTES)
    if len(data) != FRAME_BYTES:
        raise ValueError('Truncated color frame')
    return cv2.cvtColor(np.frombuffer(data, np.uint8).reshape(HEIGHT, WIDTH, 2), cv2.COLOR_YUV2BGR_YUY2)


def run(args):
    import cv2
    import numpy as np
    import torch
    import ultralytics
    from ultralytics import YOLO

    recording = args.recording.resolve()
    weights = args.weights.resolve(strict=True)  # Require local weights; no model-name download.
    if not weights.is_file():
        raise ValueError('Weights must be a local file')
    streams, inputs = inspect_recording(recording)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    started = datetime.now(timezone.utc).isoformat()
    torch.set_num_threads(args.threads)
    cv2.setNumThreads(args.threads)
    model = YOLO(str(weights))
    indices = list(range(0, len(streams['color']), args.stride))
    if args.limit:
        indices = indices[:args.limit]
    first_time = streams['color'][0]['timestamp_monotonic']
    depths = np.array([row['timestamp_monotonic'] for row in streams['depth']])
    fields = ['frame_index', 'sequence', 'timestamp_monotonic', 'elapsed_sec',
              'class_id', 'class_name', 'confidence', 'x1_px', 'y1_px', 'x2_px', 'y2_px',
              'center_u_px', 'center_v_px', 'position_status']
    frame_fields = ['frame_index', 'sequence', 'timestamp_monotonic', 'elapsed_sec',
                    'detections', 'nearest_depth_index', 'depth_minus_color_ms']
    video = output / 'detections.mp4'
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*'avc1'), FPS / args.stride, (WIDTH, HEIGHT))
    if not writer.isOpened():
        raise RuntimeError('H.264 writer unavailable; use an OpenCV build with an H.264 encoder')
    total, positive, max_delta = 0, 0, 0.0
    best = []
    preview_indices = {indices[0], indices[len(indices) // 2], indices[-1]}
    try:
        with (recording / 'color.yuyv').open('rb') as raw, \
                (output / 'detections.csv').open('w', newline='') as det_file, \
                (output / 'frames.csv').open('w', newline='') as frame_file:
            det_csv, frame_csv = csv.DictWriter(det_file, fields), csv.DictWriter(frame_file, frame_fields)
            det_csv.writeheader()
            frame_csv.writeheader()
            for number, index in enumerate(indices):
                row = streams['color'][index]
                stamp = row['timestamp_monotonic']
                elapsed = stamp - first_time
                image = read_color(raw, row)
                result = model.predict(source=image, conf=args.conf, imgsz=args.imgsz,
                                       device='cpu', verbose=False, save=False)[0]
                boxes = result.boxes
                count = len(boxes)
                total += count
                positive += int(count > 0)
                common = dict(frame_index=index, sequence=row['sequence'],
                              timestamp_monotonic=stamp, elapsed_sec=elapsed)
                annotated = image.copy()
                score = 0.0
                for box in boxes:
                    x1, y1, x2, y2 = [float(v) for v in box.xyxy[0].tolist()]
                    confidence, cls = float(box.conf[0]), int(box.cls[0])
                    name = str(result.names[cls])
                    det_csv.writerow(dict(common, class_id=cls, class_name=name, confidence=confidence,
                                          x1_px=x1, y1_px=y1, x2_px=x2, y2_px=y2,
                                          center_u_px=(x1+x2)/2, center_v_px=(y1+y2)/2,
                                          position_status='2d_only_uncalibrated_depth'))
                    cv2.rectangle(annotated, (int(x1), int(y1)), (int(x2), int(y2)), (0, 0, 255), 2)
                    cv2.putText(annotated, f'{name} {confidence:.2f}', (int(x1), max(15, int(y1)-5)),
                                cv2.FONT_HERSHEY_SIMPLEX, .45, (0, 0, 255), 1)
                    score = max(score, confidence)
                nearest = int(np.abs(depths - stamp).argmin())
                delta = float((depths[nearest] - stamp) * 1000)
                max_delta = max(max_delta, abs(delta))
                frame_csv.writerow(dict(common, detections=count, nearest_depth_index=nearest,
                                        depth_minus_color_ms=delta))
                cv2.rectangle(annotated, (0, 0), (WIDTH-1, 28), (0, 0, 0), -1)
                cv2.putText(annotated, f'2D ONLY | t={elapsed:.2f}s frame={index} candidates={count}',
                            (6, 20), cv2.FONT_HERSHEY_SIMPLEX, .5, (255, 255, 255), 1)
                writer.write(annotated)
                if index in preview_indices:
                    if not cv2.imwrite(str(output / f'frame_{index:04d}.jpg'), annotated):
                        raise RuntimeError('Preview write failed')
                if count:
                    best.append((score, index, annotated))
                    best = sorted(best, key=lambda entry: entry[0], reverse=True)[:6]
                if number % 60 == 0:
                    print(f'{number+1}/{len(indices)} frames; {total} candidate boxes', flush=True)
    finally:
        writer.release()
    if best:
        montage = np.vstack([np.hstack([entry[2] for entry in best[start:start+2]])
                             for start in range(0, len(best)-1, 2)]) if len(best) > 1 else best[0][2]
        if not cv2.imwrite(str(output / 'highest_confidence.jpg'), montage):
            raise RuntimeError('Montage write failed')
    cap = cv2.VideoCapture(str(video))
    decoded = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if frame.shape[:2] != (HEIGHT, WIDTH):
            raise RuntimeError('Video dimensions changed')
        decoded += 1
    cap.release()
    if decoded != len(indices):
        raise RuntimeError(f'Video decode mismatch: {decoded} != {len(indices)}')
    summary = dict(started_utc=started, finished_utc=datetime.now(timezone.utc).isoformat(),
                   command=sys.argv, recording=str(recording), input_files=inputs,
                   weights=dict(path=str(weights), sha256=sha256(weights), classes=model.names),
                   parameters=dict(conf=args.conf, imgsz=args.imgsz, stride=args.stride,
                                   limit=args.limit, threads=args.threads, device='cpu'),
                   source_frames=len(streams['color']), processed_frames=len(indices),
                   frames_with_candidates=positive, candidate_boxes=total,
                   highest_confidence_frames=[dict(frame_index=i, confidence=s) for s, i, _ in best],
                   max_nearest_depth_delta_ms=max_delta, video_decoded_frames=decoded,
                   position_status='2d_only_uncalibrated_depth',
                   limitations=['Boxes are candidates, not verified flowers or unique flower counts.',
                                'Depth pairing is temporal only; no spatial alignment or metric coordinates.',
                                'Video playback is constant FPS; CSV preserves source monotonic timestamps.'],
                   versions=dict(python=platform.python_version(), opencv=cv2.__version__,
                                 numpy=np.__version__, torch=torch.__version__, ultralytics=ultralytics.__version__))
    summary['outputs'] = {p.name: dict(bytes=p.stat().st_size, sha256=sha256(p))
                          for p in sorted(output.iterdir()) if p.is_file()}
    (output / 'manifest.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps({k: summary[k] for k in ['processed_frames', 'frames_with_candidates', 'candidate_boxes']}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recording', type=Path, required=True)
    parser.add_argument('--weights', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='New directory; existing paths are rejected')
    parser.add_argument('--conf', type=float, default=.25)
    parser.add_argument('--imgsz', type=int, default=640)
    parser.add_argument('--stride', type=int, default=1)
    parser.add_argument('--limit', type=int, default=0, help='0 means all frames')
    parser.add_argument('--threads', type=int, default=4)
    args = parser.parse_args()
    if not 0 < args.conf <= 1 or args.imgsz <= 0 or args.stride < 1 or args.limit < 0 or args.threads < 1:
        parser.error('Invalid confidence, image size, stride, limit or thread count')
    run(args)


if __name__ == '__main__':
    main()
