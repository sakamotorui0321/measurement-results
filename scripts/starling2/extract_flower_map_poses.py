#!/usr/bin/env python3
"""Read saved ROS bag odometry for offline flower mapping; no ROS node starts."""
import argparse
import json
from pathlib import Path

from detect_recorded_flowers import sha256


def main():
    import rosbag2_py
    from rclpy.serialization import deserialize_message
    from rosidl_runtime_py.convert import message_to_ordereddict
    from rosidl_runtime_py.utilities import get_message

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bag', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--vehicle-id', default='uav_01')
    args = parser.parse_args()
    reader = rosbag2_py.SequentialReader()
    reader.open(rosbag2_py.StorageOptions(uri=str(args.bag), storage_id='mcap'), rosbag2_py.ConverterOptions('', ''))
    types = {t.name: t.type for t in reader.get_all_topics_and_types()}
    topic = f'/{args.vehicle_id}/fmu/out/vehicle_odometry'
    sync_topic = f'/{args.vehicle_id}/fmu/out/timesync_status'
    expected = {topic: 'px4_msgs/msg/VehicleOdometry', sync_topic: 'px4_msgs/msg/TimesyncStatus'}
    if any(types.get(name) != kind for name, kind in expected.items()):
        raise ValueError('Required PX4 odometry/timesync topic types missing')
    data = {'odometry': [], 'timesync': []}
    while reader.has_next():
        name, payload, stamp = reader.read_next()
        if name in expected:
            msg = message_to_ordereddict(deserialize_message(payload, get_message(types[name])))
            data['odometry' if name == topic else 'timesync'].append(dict(bag_ns=stamp, message=msg))
    if not data['odometry'] or not data['timesync']:
        raise ValueError('No odometry or timesync samples')
    data['source'] = dict(path=str(args.bag), topics=expected,
                          files={p.name: dict(bytes=p.stat().st_size, sha256=sha256(p))
                                 for p in sorted(args.bag.iterdir()) if p.is_file()})
    with args.output.open('x') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
    print({key: len(data[key]) for key in ['odometry', 'timesync']})


if __name__ == '__main__':
    main()
