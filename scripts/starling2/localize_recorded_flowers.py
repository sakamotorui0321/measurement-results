#!/usr/bin/env python3
"""Localize existing offline flower candidates using factory RGB-D calibration."""
import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys

import cv2
import numpy as np

from detect_recorded_flowers import WIDTH, HEIGHT, FPS, FRAME_BYTES, inspect_recording, read_color, sha256
from flower_depth_geometry import DepthProjector, estimate_position


def load_detections(path, streams, hashes):
    """Bind candidates to exactly the validated source frames, not another video."""
    manifest = json.loads((path.parent / 'manifest.json').read_text())
    for name, value in hashes.items():
        if manifest['input_files'][name] != value:
            raise ValueError(f'Detections refer to different recording: {name}')
    if sha256(path) != manifest['outputs'][path.name]['sha256']:
        raise ValueError('Detection CSV hash mismatch')
    frames_path = path.parent / 'frames.csv'
    if sha256(frames_path) != manifest['outputs']['frames.csv']['sha256']:
        raise ValueError('Detection frame CSV hash mismatch')
    frames = list(csv.DictReader(frames_path.open()))
    by_frame = defaultdict(list)
    for row in csv.DictReader(path.open()):
        index = int(row['frame_index'])
        if not 0 <= index < len(streams['color']):
            raise ValueError('Detection frame index out of range')
        source = streams['color'][index]
        if int(row['sequence']) != source['sequence'] or abs(float(row['timestamp_monotonic'])-source['timestamp_monotonic']) > 1e-6:
            raise ValueError('Detection frame timestamp or sequence mismatch')
        bbox = [float(row[k]) for k in ('x1_px', 'y1_px', 'x2_px', 'y2_px')]
        if not np.isfinite(bbox).all() or not (0 <= bbox[0] < bbox[2] <= WIDTH and 0 <= bbox[1] < bbox[3] <= HEIGHT):
            raise ValueError('Invalid detection bounds')
        confidence = float(row['confidence'])
        if not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise ValueError('Invalid detection confidence')
        by_frame[index].append(row)
    indices = []
    for row in frames:
        index = int(row['frame_index'])
        if not 0 <= index < len(streams['color']):
            raise ValueError('Frame CSV index out of range')
        source = streams['color'][index]
        if int(row['sequence']) != source['sequence'] or abs(float(row['timestamp_monotonic'])-source['timestamp_monotonic']) > 1e-6:
            raise ValueError('Frame CSV timestamp or sequence mismatch')
        if int(row['detections']) != len(by_frame[index]):
            raise ValueError('Detection/frame CSV counts disagree')
        indices.append(index)
    if indices != sorted(set(indices)) or not indices or not set(by_frame).issubset(indices):
        raise ValueError('Frame CSV must contain ordered unique frame indices covering all detections')
    if len(indices) != manifest['processed_frames'] or sum(map(len, by_frame.values())) != manifest['candidate_boxes']:
        raise ValueError('Detection manifest counts disagree')
    return indices, by_frame, manifest


def run(args):
    if not args.same_device_confirmed:
        raise ValueError('Explicit confirmation of same device and no recalibration is required')
    streams, hashes = inspect_recording(args.recording)
    calibration = json.loads(args.calibration.read_text(encoding='utf-8-sig'))
    projector = DepthProjector(calibration)
    indices, detections, source_manifest = load_detections(args.detections, streams, hashes)
    # Preserve sampling cadence from the source inference run.
    stride = int(source_manifest['parameters']['stride'])
    if stride < 1 or any(b-a != stride for a, b in zip(indices, indices[1:])):
        raise ValueError('Nonuniform detection sampling is unsupported')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    started = datetime.now(timezone.utc).isoformat()
    max_boxes = max(map(len, detections.values()), default=0)
    video_height = max(HEIGHT, 100 + 26*max_boxes)
    video_height += video_height % 2
    video_width = WIDTH + 480
    video = output / 'flowers_3d.mp4'
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*'avc1'), FPS/stride, (video_width, video_height))
    if not writer.isOpened():
        raise RuntimeError('H.264 video encoder unavailable')
    depth_times = np.array([row['timestamp_monotonic'] for row in streams['depth']])
    statuses = Counter()
    ranges, deltas = [], []
    previews = set(indices[int(i)] for i in np.linspace(0, len(indices)-1, 6))
    original_fields = list(next(csv.DictReader(args.detections.open())).keys()) if source_manifest['candidate_boxes'] else list(csv.DictReader(args.detections.open()).fieldnames)
    extra = ['candidate_id', 'depth_index', 'depth_minus_color_ms', 'valid_pixels', 'patch_pixels',
             'valid_fraction', 'depth_mad_m', 'depth_p90_p10_m', 'x_m', 'y_m', 'z_m', 'range_m']
    fields = original_fields + extra
    first_time = streams['color'][0]['timestamp_monotonic']
    frame_rows = []
    try:
        with (args.recording/'color.yuyv').open('rb') as color_file, \
                (args.recording/'depth.z16').open('rb') as depth_file, \
                (output/'positions.csv').open('w', newline='') as positions:
            table = csv.DictWriter(positions, fields)
            table.writeheader()
            for number, index in enumerate(indices):
                frame = streams['color'][index]
                stamp = frame['timestamp_monotonic']
                di = int(np.argmin(np.abs(depth_times-stamp)))
                delta = float((depth_times[di]-stamp)*1000)
                deltas.append(abs(delta))
                aligned = np.full((HEIGHT, WIDTH), np.nan)
                candidates = detections[index]
                # Also align preview frames without detections to expose missing depth.
                if abs(delta) <= 20 and (candidates or index in previews):
                    depth_file.seek(streams['depth'][di]['offset'])
                    data = depth_file.read(FRAME_BYTES)
                    if len(data) != FRAME_BYTES:
                        raise ValueError('Truncated depth frame')
                    aligned = projector.align(np.frombuffer(data, dtype='<u2').reshape(HEIGHT, WIDTH))
                color = read_color(color_file, frame)
                canvas = np.zeros((video_height, video_width, 3), np.uint8)
                canvas[:HEIGHT, :WIDTH] = color
                def text(value, y, color=(240, 240, 240)):
                    cv2.putText(canvas, value, (WIDTH+12, y), cv2.FONT_HERSHEY_SIMPLEX, .52, color, 1, cv2.LINE_AA)
                text(f't={stamp-first_time:.2f}s  frame={index}', 25)
                text('conf: YOLO score | r: camera range [m]', 48)
                text('r = sqrt(X*X+Y*Y+Z*Z); estimate only', 70, (0, 220, 255))
                valid_count = 0
                for ident, row in enumerate(candidates, 1):
                    bbox = [float(row[k]) for k in ('x1_px', 'y1_px', 'x2_px', 'y2_px')]
                    result = estimate_position(aligned, bbox, calibration['color'])
                    if abs(delta) > 20:
                        result['position_status'] = 'time_mismatch'
                    status = result['position_status']
                    statuses[status] += 1
                    if status == 'estimated':
                        valid_count += 1
                        ranges.append(result['range_m'])
                        label = f'#{ident:02d} conf={float(row["confidence"]):.2f}  r={result["range_m"]:.2f}m'
                        tint = (170, 255, 170)
                    else:
                        label = f'#{ident:02d} conf={float(row["confidence"]):.2f}  r=N/A ({status.split("_")[0]})'
                        tint = (0, 200, 255)
                    text(label, 100+26*(ident-1), tint)
                    x1, y1, x2, y2 = map(int, bbox)
                    cv2.rectangle(canvas, (x1, y1), (x2, y2), (0, 0, 255), 2)
                    cv2.putText(canvas, f'#{ident}', (x1, max(14, y1-4)), cv2.FONT_HERSHEY_SIMPLEX, .45, (0, 0, 255), 1)
                    table.writerow(dict(row, **result, candidate_id=ident, depth_index=di, depth_minus_color_ms=delta))
                if not candidates:
                    text('No flower candidates in this frame', 110)
                writer.write(canvas)
                frame_rows.append(dict(frame_index=index, candidates=len(candidates), positions=valid_count,
                                       depth_index=di, depth_minus_color_ms=delta))
                if index in previews:
                    if not cv2.imwrite(str(output/f'frame_{index:04d}.jpg'), canvas):
                        raise RuntimeError('Preview write failed')
                    normalized = np.nan_to_num(aligned, nan=0)
                    display = cv2.applyColorMap(np.uint8(np.clip(normalized/2, 0, 1)*255), cv2.COLORMAP_TURBO)
                    display[~np.isfinite(aligned)] = 0
                    if not cv2.imwrite(str(output/f'alignment_{index:04d}.jpg'), np.hstack([color, display])):
                        raise RuntimeError('Alignment preview write failed')
                    np.save(output/f'aligned_z_{index:04d}.npy', aligned)
                if number % 120 == 0:
                    print(f'{number+1}/{len(indices)} frames; {dict(statuses)}', flush=True)
    finally:
        writer.release()
    cap = cv2.VideoCapture(str(video))
    count = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if frame.shape[:2] != (video_height, video_width):
            raise RuntimeError('Incorrect output video dimensions')
        count += 1
    cap.release()
    if count != len(indices):
        raise RuntimeError('Video frame count mismatch')
    with (output/'frames_3d.csv').open('w', newline='') as stream:
        table = csv.DictWriter(stream, list(frame_rows[0]))
        table.writeheader()
        table.writerows(frame_rows)
    manifest = dict(started_utc=started, finished_utc=datetime.now(timezone.utc).isoformat(), command=sys.argv,
                    recording=str(args.recording), input_files=hashes,
                    detections=dict(path=str(args.detections), sha256=sha256(args.detections),
                                    manifest_sha256=sha256(args.detections.parent/'manifest.json')),
                    calibration=dict(path=str(args.calibration), sha256=sha256(args.calibration),
                                     device=calibration['device'], same_device_no_recalibration_confirmed=True),
                    processed_frames=count, candidate_boxes=sum(statuses.values()), statuses=dict(statuses),
                    frames_with_positions=sum(r['positions']>0 for r in frame_rows),
                    range_m=dict(min=min(ranges), median=float(np.median(ranges)), max=max(ranges)) if ranges else None,
                    max_pair_delta_ms=max(deltas), video_decoded_frames=count,
                    coordinate_frame='color_optical: X right, Y down, Z forward; meters',
                    range_definition='Euclidean distance from color camera optical center; distinct from axial Z',
                    geometry='Zero-distortion pinhole; depth-to-color column-major rotation, translation in meters; sample-center splat, nearest Z wins; NaN holes, no fill',
                    quality=dict(max_pair_delta_ms=20, min_z_m=.15, max_z_m=4., min_valid_pixels=5,
                                 min_valid_fraction=.25, region='central third of bbox',
                                 mad_limit='max(0.01m, 0.03*medianZ)', p90_p10_limit='max(0.03m, 0.10*medianZ)'),
                    limitations=['Estimated bbox-center ray at median Z, not a measured flower organ.',
                                 'Consistent leaf/background depth can pass quality gates.',
                                 'No world coordinates, tracking, or metric ground truth evaluation.'],
                    versions=dict(python=sys.version, numpy=np.__version__, opencv=cv2.__version__))
    manifest['outputs'] = {p.name: dict(bytes=p.stat().st_size, sha256=sha256(p)) for p in sorted(output.iterdir()) if p.is_file()}
    (output/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(json.dumps({k: manifest[k] for k in ('statuses', 'frames_with_positions', 'range_m')}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recording', type=Path, required=True)
    parser.add_argument('--detections', type=Path, required=True, help='CSV with adjacent frames.csv and manifest.json')
    parser.add_argument('--calibration', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--same-device-confirmed', action='store_true', help='Same physical camera, no replacement or recalibration')
    run(parser.parse_args())


if __name__ == '__main__':
    main()
