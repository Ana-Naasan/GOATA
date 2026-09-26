"""One local recording to a native GVHMR handoff, without preview rendering."""

import argparse
from bisect import bisect_left
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import sys
import time
from uuid import UUID

from .native import MAX_FRAMES, UPSTREAM_COMMIT, _array, load_json
from .timing import map_selected_frames

MAX_INFERENCE_FRAMES = 600
MAX_MEDIA_BYTES = 512 * 1024 * 1024


def write_json(path, value):
    path.write_text(json.dumps(value, allow_nan=False, indent=2) + '\n', encoding='utf-8')


def digest(path):
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest() if hasattr(hashlib, 'file_digest') else _hash(stream)


def _hash(stream):
    value = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
        value.update(chunk)
    return value.hexdigest()


def _required(value, fields, name):
    if type(value) is not dict or not set(fields).issubset(value):
        raise ValueError(f'{name} requires fields {fields}')


def plan_input(doc, allow_estimated_intrinsics=False):
    _required(doc, ('schema_version', 'take_id', 'frames', 'adapter', 'image', 'camera', 'clock', 'capture'), 'sidecar')
    if doc['schema_version'] != '1.0':
        raise ValueError('sidecar schema_version must be 1.0')
    if type(doc['take_id']) is not str:
        raise ValueError('take_id must be a UUID string')
    UUID(doc['take_id'])
    for section, fields in {
        'adapter': ('name', 'version'),
        'image': ('width_px', 'height_px', 'rotation_degrees', 'mirrored'),
        'camera': ('id', 'calibration_status', 'distortion_model', 'distortion_coefficients'),
        'clock': ('id', 'unit', 'origin_pts_ns'),
        'capture': ('view', 'condition', 'side', 'interrupted'),
    }.items():
        _required(doc[section], fields, section)
    for value in (doc['adapter']['name'], doc['adapter']['version'], doc['camera']['id'], doc['clock']['id']):
        if type(value) is not str or not 1 <= len(value) <= 256:
            raise ValueError('adapter and clock/camera identifiers must be nonempty bounded strings')
    origin = doc['clock']['origin_pts_ns']
    if type(origin) is not str or not origin.lstrip('-').isascii() or not origin.lstrip('-').isdigit():
        raise ValueError('clock origin_pts_ns must be an ASCII integer string')
    int(origin)
    frames = doc['frames']
    if type(frames) is not list or not 2 <= len(frames) <= MAX_FRAMES:
        raise ValueError('require 2 to 3600 source frames')
    map_selected_frames(frames, [0])
    if any(not f['image_valid'] for f in frames):
        raise ValueError('invalid images: supply a separate contiguous eligible take; no gap filling')
    capture = doc['capture']
    if capture.get('interrupted') is not False or capture.get('gaps'):
        raise ValueError('interrupted takes or explicit gaps are not supported')
    if doc['clock']['unit'] != 'nanoseconds':
        raise ValueError('source clock must use nanoseconds')
    image = doc['image']
    width, height = image['width_px'], image['height_px']
    if (type(width) is not int or type(height) is not int or min(width, height) < 32
            or width % 2 or height % 2 or width * height > 1920 * 1080):
        raise ValueError('require even image dimensions, at least 32px, at most 2073600 pixels')
    if type(image['rotation_degrees']) is not int or image['rotation_degrees'] != 0 or image['mirrored'] is not False:
        raise ValueError('require an upright, unmirrored encoded image; no implicit transforms')
    camera = doc['camera']
    if camera.get('distortion_model') != 'none' or camera.get('distortion_coefficients') != []:
        raise ValueError('require rectified pinhole images with distortion_model none')
    status = camera['calibration_status']
    if status in ('calibrated', 'estimated'):
        k = camera.get('intrinsics')
        _required(k, ('fx', 'fy', 'cx', 'cy'), 'camera intrinsics')
        if set(k) != {'fx', 'fy', 'cx', 'cy'}:
            raise ValueError('intrinsics supports fx, fy, cx, cy only, no implicit skew')
        values = [k[name] for name in ('fx', 'fy', 'cx', 'cy')]
        _array(values, (4,), 'intrinsics')
        fx, fy, cx, cy = values
        if fx <= 0 or fy != fx:
            raise ValueError('this GVHMR path supports positive shared focal length only; rectify first')
    elif status == 'unavailable' and allow_estimated_intrinsics:
        fx = math.hypot(width, height)
        cx, cy = width / 2, height / 2
        status = 'estimated'
    else:
        raise ValueError('intrinsics unavailable; opt in with --allow-estimated-intrinsics')
    times = [int(f['pts_ns']) for f in frames]
    if any(b - a > 100_000_000 for a, b in zip(times, times[1:])):
        raise ValueError('source gap exceeds 100ms; do not concatenate across missing observations')
    duration = times[-1] - times[0]
    count = duration * 30 // 1_000_000_000 + 1
    # Rounded capture clocks can put the final 30Hz sample less than 1ns past the endpoint.
    if abs(Fraction(count, 30) * 1_000_000_000 - duration) <= 1:
        count += 1
    if not 2 <= count <= MAX_INFERENCE_FRAMES:
        raise ValueError('supported inference length is 2 to 600 frames at 30Hz; no automatic trimming')
    selected = []
    for index in range(count):
        target = times[0] + Fraction(index * 1_000_000_000, 30)
        right = bisect_left(times, target)
        choices = [i for i in (right - 1, right) if 0 <= i < len(times)]
        selected.append(min(choices, key=lambda i: (abs(times[i] - target), i)))
    mapping = map_selected_frames(frames, selected)
    for index, row in enumerate(mapping):
        row['inference_time_s'] = index / 30
        row['selection_error_ns'] = str(Fraction(int(row['source_pts_ns']) - times[0]) - Fraction(index * 10**9, 30))
    return {'schema_version': 'native-selection-1', 'take_id': doc['take_id'],
            'selected_indices': selected, 'frame_mapping': mapping,
            'source_frames': frames, 'K': [[fx, 0, cx], [0, fx, cy], [0, 0, 1]],
            'intrinsics_status': status, 'width': width, 'height': height,
            'resampling': 'nearest original image at 30Hz, earlier source wins ties',
            'gap_policy': 'reject invalid images, interruptions and intervals over 100ms'}


def bind_pts(frames, decoded, offset_ns):
    """Match rounded decoder PTS to source PTS, never by equal frame counts."""
    lookup = {int(frame['pts_ns']): i for i, frame in enumerate(frames)}
    positions = []
    for index, pts_seconds in decoded:
        timestamp = round(pts_seconds * 1_000_000_000) + offset_ns
        if timestamp not in lookup or index != len(positions):
            raise ValueError('decoder PTS cannot be bound to sidecar source PTS')
        positions.append(lookup[timestamp])
    if positions != list(range(len(frames))):
        raise ValueError('decoded PTS are missing, repeated, extra or reordered')
    return positions


def prepare_video(video, destination, plan, offset_ns):
    import av
    # Decode twice: first establish timestamp identity, then encode selected images.
    decoded = []
    with av.open(str(video)) as container:
        if len(container.streams.video) != 1:
            raise ValueError('require exactly one video stream')
        stream = container.streams.video[0]
        if stream.metadata.get('rotate', '0') != '0':
            raise ValueError('container rotation is unsupported')
        for index, frame in enumerate(container.decode(stream)):
            if index >= MAX_FRAMES or frame.pts is None:
                raise ValueError('missing decoder PTS or excessive decoded frames')
            if (frame.width, frame.height) != (plan['width'], plan['height']):
                raise ValueError('decoded image dimensions differ from sidecar')
            if any('DISPLAYMATRIX' in str(s.type) for s in frame.side_data):
                raise ValueError('display transforms are unsupported')
            decoded.append((index, Fraction(frame.pts) * frame.time_base))
    bind_pts(plan['source_frames'], decoded, offset_ns)
    plan['decoder_binding'] = {'offset_ns': str(offset_ns), 'rule': 'round(decoded_pts_seconds * 1e9) + offset_ns == source_pts_ns',
                               'decoded_pts_seconds': [str(pts) for _, pts in decoded]}
    selections = plan['selected_indices']
    cursor = 0
    decoded_count = 0
    with av.open(str(video)) as source, av.open(str(destination), 'w') as output:
        stream = output.add_stream('libx264', rate=30)
        stream.width, stream.height = plan['width'], plan['height']
        stream.pix_fmt = 'yuv420p'
        stream.options = {'crf': '0', 'preset': 'ultrafast', 'bf': '0'}
        for index, frame in enumerate(source.decode(video=0)):
            decoded_count += 1
            if (index >= len(decoded) or frame.pts is None
                    or Fraction(frame.pts) * frame.time_base != decoded[index][1]):
                raise ValueError('decoder changed between passes')
            while cursor < len(selections) and selections[cursor] == index:
                selected = av.VideoFrame.from_ndarray(frame.to_ndarray(format='rgb24'), format='rgb24')
                selected.pts, selected.time_base = cursor, Fraction(1, 30)
                for packet in stream.encode(selected):
                    output.mux(packet)
                cursor += 1
            if destination.exists() and destination.stat().st_size > MAX_MEDIA_BYTES:
                raise ValueError('prepared video exceeds 512MiB')
        for packet in stream.encode():
            output.mux(packet)
    if decoded_count != len(decoded) or cursor != len(selections) or destination.stat().st_size > MAX_MEDIA_BYTES:
        raise ValueError('incomplete or oversized prepared video')
    with av.open(str(destination)) as check:
        actual = [Fraction(f.pts) * f.time_base for f in check.decode(video=0)]
    if actual != [Fraction(i, 30) for i in range(len(selections))]:
        raise ValueError('prepared video PTS do not match the selected 30Hz sequence')


def select_track(history):
    """Reject ambiguous identities and missing boxes instead of interpolating."""
    boxes, identity = [], None
    for frame in history:
        if len(frame) != 1:
            raise ValueError('require exactly one tracked person in every inference image')
        item = frame[0]
        if identity is None:
            identity = item['id']
        if item['id'] != identity:
            raise ValueError('person track changed; recapture or explicitly isolate the participant')
        box = list(item['bbx_xyxy'])
        # NumPy scalars from upstream are converted before the JSON-style check.
        box = [float(v) for v in box]
        validate_rows([box], 1, 4)
        if box[2] <= box[0] or box[3] <= box[1]:
            raise ValueError('invalid detected bounding box')
        boxes.append(box)
    if not boxes:
        raise ValueError('no person track')
    return boxes


def validate_rows(rows, count, width):
    _array(rows, (count, width), 'output rows')


def geometry_metadata(names, parents, vertices, triangles):
    if (len(names) != len(parents) or not names or len(set(names)) != len(names)
            or parents[0] != -1 or any(type(p) is not int or not 0 <= p < i for i, p in enumerate(parents[1:], 1))
            or type(vertices) is not int or vertices < 3 or type(triangles) is not int or triangles < 1):
        raise ValueError('invalid geometry topology or joint hierarchy')
    return {'coordinate_system': 'gvhmr_global_ay', 'handedness': 'right', 'up_axis': '+Y',
            'horizontal_axes': 'native GV0 gauge; not registered to Quest world or participant facing',
            'units': 'model_metres', 'scale_status': 'estimated', 'unity_conversion_applied': False,
            'root_translation': 'preserved, no per-frame recentering',
            'body_model': 'SMPL-X neutral, upstream supermotion configuration',
            'joint_definition': 'first 22 SMPL-X posed kinematic joints from the same body-model forward call',
            'joint_names': names, 'joint_parents': parents,
            'vertex_count': vertices, 'triangle_count': triangles,
            'joint_validity': 'finite fitted estimates, not observed landmarks or calibrated confidence',
            'unfitted_parts': 'hands, face and expression use body-model defaults; not measurements'}


def infer(video, plan, output):
    from .gvhmr import infer_native
    return infer_native(video, plan, output)


def run(video, sidecar, output, offset_ns, allow_estimated_intrinsics):
    started = time.monotonic()
    if not video.is_file() or not 0 < video.stat().st_size <= MAX_MEDIA_BYTES:
        raise ValueError('video must be a local file of 1 byte to 512MiB')
    sidecar_digest = digest(sidecar)
    doc = load_json(sidecar)
    plan = plan_input(doc, allow_estimated_intrinsics)
    output.mkdir(parents=False, exist_ok=False)
    original_digest = digest(video)
    write_json(output / 'source-sidecar.json', doc)
    write_json(output / 'selection.json', plan)
    prepared = output / 'inference.mp4'
    prepare_video(video, prepared, plan, offset_ns)
    if digest(video) != original_digest or digest(sidecar) != sidecar_digest:
        raise ValueError('source video or sidecar changed during preparation')
    write_json(output / 'selection.json', plan)
    preparation_s = time.monotonic() - started
    result = infer(prepared, plan, output)
    result.update({'schema_version': 'gvhmr-native-1', 'take_id': doc['take_id'],
                   'upstream_commit': UPSTREAM_COMMIT, 'source_video_sha256': original_digest,
                   'source_sidecar_sha256': sidecar_digest, 'selection': 'selection.json',
                   'adapter_sha256': {name: digest(Path(__file__).with_name(name))
                                      for name in ('runtime.py', 'gvhmr.py', 'native.py', 'timing.py')},
                   'intrinsics_status': plan['intrinsics_status'],
                   'camera_motion': 'moving camera, SIFT/pycolmap relative rotation; no Quest-pose fusion',
                   'preparation_s': preparation_s, 'local_elapsed_s': time.monotonic() - started,
                   'whole_capture_to_loaded_latency': 'not measured by this local CLI',
                   'validation_status': 'research_demo_unvalidated'})
    write_json(output / 'handoff.partial.json', result)
    (output / 'handoff.partial.json').replace(output / 'handoff.json')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video', type=Path, required=True)
    parser.add_argument('--sidecar', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='new directory beneath an existing writable parent')
    parser.add_argument('--pts-offset-ns', type=int, required=True, help='verified source-clock minus decoded MP4 clock offset')
    parser.add_argument('--allow-estimated-intrinsics', action='store_true')
    args = parser.parse_args(argv)
    try:
        run(args.video.resolve(), args.sidecar.resolve(), args.output.resolve(), args.pts_offset_ns,
            args.allow_estimated_intrinsics)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, ImportError) as error:
        print(f'Reconstruction failed: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
