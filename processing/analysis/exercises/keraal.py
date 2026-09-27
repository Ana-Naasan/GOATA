"""Offline KERAAL ELK Error1 research mechanics, not a validated detector.

See protocol.json for pinned provenance, label definitions and input gates.
Only stdlib is required. No downloads, trackers, pickle, or service side effects.
"""
import json
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from statistics import fmean, pstdev

UPSTREAM_REVISION = '8e111d5c3e95d4776d74832a897228137f409d94'
FEATURE_VERSION = 'elk-image-arm-projections-v1'
MAX_BYTES = 16 * 1024 * 1024
MAX_FRAMES = 3600
JOINTS = tuple(f'{side}_{joint}' for side in ('Left', 'Right')
               for joint in ('shoulder', 'hip', 'elbow', 'wrist'))
SCHEMA = {
    'Global evaluation': {'evaluation': {'Correct', 'Incorrect', 'Incomplete', 'Motionless'}},
    'Global error': {'type': {'none', 'Error1', 'Error2', 'Error3', 'Other'},
                     'Evaluation': {'SmallError', 'LargeError'},
                     'bodyPart': {'LeftArm', 'RightArm', 'BothArms', 'Spine'}},
    'Temporal error': {'type': {'Error1', 'Error2', 'Error3', 'Other'},
                       'Evaluation': {'SmallError', 'LargeError'},
                       'bodyPart': {'LeftArm', 'RightArm', 'BothArms', 'Spine'}},
}


@dataclass(frozen=True)
class Annotation:
    annotator: str
    track: str
    start_s: float
    end_s: float
    attributes: dict


@dataclass(frozen=True)
class Frame:
    frame_id: int
    time_s: float
    joints: dict


@dataclass(frozen=True)
class Sequence:
    participant_id: str
    take_id: str
    exercise: str
    tracker_version: str
    frames: tuple
    annotations: tuple
    mapping_provenance: str = 'caller-supplied source frames'
    view: str = 'unverified'
    capture_complete: bool = False


@dataclass(frozen=True)
class Model:
    mean: tuple
    scale: tuple
    centroids: tuple
    participants: frozenset
    take_ids: frozenset
    tracker_version: str
    feature_version: str = FEATURE_VERSION


def _text(value):
    if type(value) is not str or not value.strip() or len(value) > 256:
        raise ValueError('expected nonempty identifier/provenance, at most 256 characters')
    return value


def _number(value):
    try:
        valid = type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError('expected finite number, not boolean')
    return value


def _bounded(raw):
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_BYTES:
        raise ValueError('expected nonempty bytes, at most 16 MiB')


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def _constant(value):
    raise ValueError('nonfinite JSON constant')


def parse_annotations(raw, annotator):
    """Preserve each ANVIL element and reviewer; never expand global to temporal.

    No referenced video/specification paths are opened. Defaults in the source
    schema are not labels, so absent attributes are not filled in.
    """
    _bounded(raw)
    _text(annotator)
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper() or b'\x00' in raw:
        raise ValueError('DTD/entities and non-ASCII-compatible XML encoding prohibited')
    try:
        root = ET.fromstring(raw)
    except (ET.ParseError, RecursionError) as error:
        raise ValueError('malformed annotation XML') from error
    if root.tag != 'annotation' or len(root.findall('body')) != 1:
        raise ValueError('expected one annotation body')
    result = []
    for track in root.find('body'):
        name = track.get('name')
        if track.tag != 'track' or name not in SCHEMA:
            raise ValueError('unsupported annotation track')
        indices = set()
        for element in track:
            if element.tag != 'el' or element.get('index') in indices:
                raise ValueError('invalid or duplicate annotation element')
            index = element.get('index')
            if index is None or not index.isascii() or not index.isdigit():
                raise ValueError('annotation index must be a nonnegative integer')
            indices.add(index)
            try:
                start, end = float(element.attrib['start']), float(element.attrib['end'])
            except (KeyError, ValueError) as error:
                raise ValueError('missing or invalid annotation times') from error
            _number(start)
            _number(end)
            if not 0 <= start <= end:
                raise ValueError('invalid annotation interval')
            attributes = {}
            for attr in element:
                key = attr.get('name')
                value = attr.text
                if (attr.tag != 'attribute' or key in attributes or key not in SCHEMA[name]
                        or value not in SCHEMA[name][key] or len(attr)):
                    raise ValueError('unknown, duplicate or malformed annotation attribute')
                attributes[key] = value
            if not attributes:
                raise ValueError('empty annotation element')
            result.append(Annotation(annotator, name, start, end, attributes))
    return tuple(result)


def ingest_blazepose(raw, *, participant_id, take_id, exercise, tracker_version,
                     width, height, source_map, mapping_provenance,
                     anatomical_sides_verified, view, capture_complete, annotations=()):
    """Read released positions JSON with externally verified timing and validity.

    source_map keys match positions keys exactly. Values contain frame_id,
    time_s and valid_joints. These are caller-established evidence, not defaults.
    BlazePose image x/y are converted to pixels; z is NOT metric depth.
    Do not pass Kinect, SMPL or world landmarks as these image landmarks.
    """
    _bounded(raw)
    for value in (participant_id, take_id, tracker_version, mapping_provenance):
        _text(value)
    if exercise not in ('elk', 'rtk'):
        raise ValueError('unsupported exercise')
    if anatomical_sides_verified is not True:
        raise ValueError('verify anatomical sides after upstream horizontal image flip')
    for size in (width, height):
        if type(size) is not int or not 0 < size <= 16384:
            raise ValueError('invalid image dimension')
    try:
        data = json.loads(raw, object_pairs_hook=_unique, parse_constant=_constant)
    except (UnicodeError, RecursionError) as error:
        raise ValueError('invalid JSON encoding/nesting') from error
    if type(data) is not dict or set(data) != {'positions'}:
        raise ValueError('expected positions object')
    positions = data['positions']
    if type(positions) is not dict or not 1 <= len(positions) <= MAX_FRAMES:
        raise ValueError('invalid positions count')
    if type(source_map) is not dict or set(source_map) != set(positions):
        raise ValueError('every row needs an explicit verified source map')
    frames = []
    for key, points in positions.items():
        meta = source_map[key]
        if type(meta) is not dict or set(meta) != {'frame_id', 'time_s', 'valid_joints'}:
            raise ValueError('invalid source mapping fields')
        valid = meta['valid_joints']
        if (type(points) is not dict or type(valid) is not list
                or any(type(k) is not str for k in valid)
                or len(set(valid)) != len(valid) or not set(valid) <= set(points)):
            raise ValueError('invalid joint validity list')
        for point in points.values():
            if type(point) is not list or len(point) != 3:
                raise ValueError('expected xyz image landmark')
            for value in point:
                _number(value)
        joints = {joint: (points[joint][0] * width, points[joint][1] * height)
                  if joint in valid else None for joint in JOINTS}
        frames.append(Frame(meta['frame_id'], meta['time_s'], joints))
    # JSON insertion order is not a timing contract. Source times define order.
    for frame in frames:
        _number(frame.time_s)
    frames.sort(key=lambda frame: frame.time_s)
    result = Sequence(participant_id, take_id, exercise, tracker_version,
                      tuple(frames), tuple(annotations), mapping_provenance,
                      view, capture_complete)
    _validate_sequence(result)
    return result


def _validate_sequence(sequence):
    for value in (sequence.participant_id, sequence.take_id, sequence.tracker_version,
                  sequence.mapping_provenance):
        _text(value)
    if sequence.exercise not in ('elk', 'rtk') or not 1 <= len(sequence.frames) <= MAX_FRAMES:
        raise ValueError('invalid exercise or frame count')
    previous_time, previous_id = -1., -1
    for frame in sequence.frames:
        _number(frame.time_s)
        if (type(frame.frame_id) is not int or frame.frame_id <= previous_id
                or frame.time_s < 0 or frame.time_s <= previous_time):
            raise ValueError('source IDs/times must be nonnegative and strictly increasing')
        previous_time, previous_id = frame.time_s, frame.frame_id
        for joint in JOINTS:
            point = frame.joints.get(joint)
            if point is None:
                continue
            if type(point) not in (tuple, list) or len(point) != 2:
                raise ValueError('expected 2D pixel landmarks')
            for value in point:
                _number(value)
    for a in sequence.annotations:
        _text(a.annotator)
        _number(a.start_s)
        _number(a.end_s)
        if not 0 <= a.start_s <= a.end_s:
            raise ValueError('invalid annotation interval')
        if a.track not in SCHEMA or not a.attributes or any(
                k not in SCHEMA[a.track] or v not in SCHEMA[a.track][k]
                for k, v in a.attributes.items()):
            raise ValueError('unsupported annotation')


def elk_features(sequence):
    """Shared train/live image features. No clinical angle threshold.

    Each elbow/wrist projects onto the shoulder line and ipsilateral torso.
    Return min/mean/max over observed samples, not time-weighted quantities.
    A missing required landmark rejects the clip; no interpolation or zero fill.
    """
    _validate_sequence(sequence)
    if sequence.exercise != 'elk':
        raise ValueError('RTK needs a separate protocol/model')
    if sequence.view != 'front' or sequence.capture_complete is not True:
        raise ValueError('candidate requires a complete frontal take; other views unsupported')
    rows = []
    for frame in sequence.frames:
        if any(frame.joints.get(joint) is None for joint in JOINTS):
            raise ValueError('missing required joint; clip unavailable')
        p = frame.joints
        shoulder_axis = tuple(b-a for a,b in zip(p['Left_shoulder'], p['Right_shoulder']))
        shoulder_length = math.hypot(*shoulder_axis)
        if shoulder_length == 0 or not math.isfinite(shoulder_length):
            raise ValueError('degenerate shoulder line')
        row = []
        for side in ('Left', 'Right'):
            shoulder = p[f'{side}_shoulder']
            torso = tuple(b-a for a,b in zip(shoulder, p[f'{side}_hip']))
            length = math.hypot(*torso)
            if length == 0 or not math.isfinite(length):
                raise ValueError('degenerate torso')
            for joint in ('elbow', 'wrist'):
                offset = tuple((b-a)/length for a,b in zip(shoulder, p[f'{side}_{joint}']))
                row.extend((sum(v * (axis / shoulder_length) for v,axis in zip(offset, shoulder_axis)),
                            sum(v * (axis / length) for v,axis in zip(offset, torso))))
        for value in row:
            _number(value)
        rows.append(row)
    features = tuple(value for column in zip(*rows)
                     for value in (min(column), fmean(column), max(column)))
    for value in features:
        _number(value)
    return features


def _records(records):
    rows = tuple(records)
    if not rows or len({s.take_id for s in rows}) != len(rows):
        raise ValueError('need nonempty records with unique take IDs')
    for row in rows:
        _validate_sequence(row)
    return rows


def partition(records, train_ids, test_ids):
    """Explicit exhaustive participant split, before fitting anything.

    Canonical participant IDs must join A/B subsets and repeated visits. Group
    names are not participant IDs. Unknown cross-group identity blocks splitting.
    """
    rows = _records(records)
    train_ids, test_ids = set(train_ids), set(test_ids)
    if (not train_ids or not test_ids or train_ids & test_ids
            or train_ids | test_ids != {s.participant_id for s in rows}):
        raise ValueError('split must be disjoint, nonempty and exhaustive by participant')
    return (tuple(s for s in rows if s.participant_id in train_ids),
            tuple(s for s in rows if s.participant_id in test_ids))


def _target(sequence, annotator):
    _text(annotator)
    evaluations = [a.attributes.get('evaluation') for a in sequence.annotations
                   if a.annotator == annotator and a.track == 'Global evaluation']
    errors = [a.attributes.get('type') for a in sequence.annotations
              if a.annotator == annotator and a.track == 'Global error']
    temporal = [a for a in sequence.annotations
                if a.annotator == annotator and a.track == 'Temporal error']
    if evaluations == ['Correct'] and errors in ([], ['none']) and not temporal:
        return 0
    if evaluations == ['Incorrect'] and errors == ['Error1']:
        return 1
    raise ValueError('need explicit reviewed Correct or global worst Error1; other labels excluded')


def fit(records, *, annotator):
    """Fixed nearest-centroid baseline; no hyperparameter tuning or probability.

    Caller supplies ONLY the training partition. Normalization uses only these
    records. Choosing features or settings from held-out results is not allowed.
    """
    rows = _records(records)
    if len({s.tracker_version for s in rows}) != 1:
        raise ValueError('training tracker/preprocessing versions differ')
    x = [elk_features(s) for s in rows]
    y = [_target(s, annotator) for s in rows]
    if set(y) != {0, 1}:
        raise ValueError('training needs both Correct and Error1 examples')
    mean = tuple(fmean(c) for c in zip(*x))
    scale = tuple(pstdev(c) or 1. for c in zip(*x))
    z = [tuple((v-m)/s for v,m,s in zip(row, mean, scale)) for row in x]
    centroids = tuple(tuple(fmean(c) for c in zip(*(row for row,label in zip(z,y) if label == k)))
                      for k in (0,1))
    for values in (mean, scale, *centroids):
        for value in values:
            _number(value)
    return Model(mean, scale, centroids, frozenset(s.participant_id for s in rows),
                 frozenset(s.take_id for s in rows), rows[0].tracker_version)


def predict(model, sequence):
    """Clip prediction linked to its actual evidence, NOT a service Finding.

    Global worst-error training does not justify local onset/offset or ruling out
    other errors. This unvalidated result must not become a clinical pass badge.
    """
    if model.feature_version != FEATURE_VERSION or model.tracker_version != sequence.tracker_version:
        raise ValueError('feature/tracker version mismatch')
    x = elk_features(sequence)
    z = tuple((v-m)/s for v,m,s in zip(x, model.mean, model.scale))
    distances = tuple(math.dist(z,c) for c in model.centroids)
    for value in distances:
        _number(value)
    if distances[0] == distances[1]:
        raise ValueError('ambiguous equal centroid distances; abstain')
    label = min(range(2), key=lambda k: distances[k])
    return {'label_code': ('elk.Correct', 'elk.Error1')[label],
            'participant_id': sequence.participant_id, 'take_id': sequence.take_id,
            'granularity': 'clip', 'source_frame_ids': [f.frame_id for f in sequence.frames],
            'source_times_s': [f.time_s for f in sequence.frames],
            'mapping_provenance': sequence.mapping_provenance,
            'feature_version': FEATURE_VERSION, 'validation_status': 'research_demo_unvalidated'}


def evaluate(model, records, *, annotator):
    """Held-out mechanics only. Report denominators; undefined ratios stay None.

    No automatic exclusions. Invalid input aborts the report, so capture failures
    cannot disappear from a denominator. No fabricated temporal overlap metric.
    """
    rows = _records(records)
    if (model.participants & {s.participant_id for s in rows}
            or model.take_ids & {s.take_id for s in rows}):
        raise ValueError('evaluation overlaps training participants/takes')
    counts = {'tn': 0, 'fp': 0, 'fn': 0, 'tp': 0}
    predictions = []
    for row in rows:
        truth = _target(row, annotator)
        prediction = predict(model, row)
        predicted = int(prediction['label_code'] == 'elk.Error1')
        counts[(('tn','fp'), ('fn','tp'))[truth][predicted]] += 1
        predictions.append({**prediction, 'target': truth})
    tn, fp, fn, tp = (counts[k] for k in ('tn','fp','fn','tp'))
    ratio = lambda numerator, denominator: numerator / denominator if denominator else None
    return {'counts': counts, 'n_clips': len(rows),
            'n_participants': len({s.participant_id for s in rows}),
            'support_correct': tn+fp, 'support_error1': tp+fn,
            'precision_error1': ratio(tp,tp+fp), 'recall_error1': ratio(tp,tp+fn),
            'precision_correct': ratio(tn,tn+fn), 'recall_correct': ratio(tn,tn+fp),
            'false_positive_rate_on_correct': ratio(fp,tn+fp),
            'temporal_metrics': None, 'predictions': predictions}
