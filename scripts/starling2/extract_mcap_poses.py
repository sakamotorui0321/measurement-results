"""Extract the recorded PX4 poses using embedded ROS 2 definitions, without a ROS installation."""
from pathlib import Path
import json
import sys

from mcap_ros2.reader import read_ros2_messages
import yaml

from detect_recorded_flowers import sha256

def extract(bag, output):
    metadata = yaml.safe_load((bag/'metadata.yaml').read_text())['rosbag2_bagfile_information']
    topics = {'/uav_01/fmu/out/vehicle_odometry': ('odometry','px4_msgs/msg/VehicleOdometry'),
              '/uav_01/fmu/out/timesync_status': ('timesync','px4_msgs/msg/TimesyncStatus')}
    records = {'odometry': [], 'timesync': []}
    for filename in metadata['relative_file_paths']:
        path = (bag/filename).resolve()
        if path.parent != bag.resolve() or path.suffix != '.mcap':
            raise ValueError(f'Invalid MCAP part: {filename}')
        for row in read_ros2_messages(path, topics=list(topics)):
            key, kind = topics[row.channel.topic]
            if row.schema.name != kind:
                raise ValueError(f'Unexpected schema: {row.schema.name}')
            msg = row.ros_msg
            records[key].append(dict(bag_ns=row.log_time_ns,message={k:getattr(msg,k) for k in msg.__slots__}))
    counts = {r['topic_metadata']['name']:r['message_count'] for r in metadata['topics_with_message_count']}
    for topic,(key,_) in topics.items():
        if not records[key] or len(records[key]) != counts.get(topic):
            raise ValueError(f'Incomplete topic {topic}: {len(records[key])} messages')
        records[key].sort(key=lambda r:r['bag_ns'])
    records['source'] = dict(path=str(bag),topics={k:v[1] for k,v in topics.items()},
                             files={p.name:dict(bytes=p.stat().st_size,sha256=sha256(p))
                                    for p in bag.iterdir() if p.is_file()})
    with output.open('x') as stream:
        json.dump(records,stream,ensure_ascii=False,allow_nan=True)
if __name__ == '__main__':
    extract(*map(Path,sys.argv[1:]))
