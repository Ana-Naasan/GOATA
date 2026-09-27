"""Synthetic checks establish mechanics, not participant or clinical validation."""
import json
from copy import deepcopy
from fractions import Fraction
from uuid import uuid4

import pytest

np = pytest.importorskip('numpy')
cv2 = pytest.importorskip('cv2')
av = pytest.importorskip('av')

from processing.microscope import magnify_frames, process_microscope


def clip(count=120, *, shake=False, noise=False, amplitude=.65):
    rng = np.random.default_rng(6)
    background = cv2.GaussianBlur(rng.integers(45, 110, (96, 128), dtype=np.uint8), (3, 3), 0)
    frames = []
    for i in range(count):
        dx = amplitude * np.sin(2 * np.pi * i / 30)
        body = np.zeros_like(background)
        cv2.rectangle(body, (49, 27), (77, 72), 110, -1)
        moved = cv2.warpAffine(body, np.float32([[1, 0, dx], [0, 1, 0]]), (128, 96))
        frame = background + moved
        if shake:
            frame = cv2.warpAffine(frame, np.float32([[1, 0, 2 * dx], [0, 1, 0]]), (128, 96), borderMode=cv2.BORDER_REFLECT)
        if noise:
            frame = np.clip(frame.astype(float) + rng.normal(0, 18, frame.shape), 0, 255).astype(np.uint8)
        frames.append(cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR))
    return np.stack(frames)


def sidecar(count=120):
    return {'take_id': str(uuid4()), 'image': {'width_px': 128, 'height_px': 96, 'rotation_degrees': 0, 'mirrored': False},
            'clock': {'origin_pts_ns': '1000000000'},
            'media': {'binding': 'indexed_presentation_time_us', 'presentation_time_us': [str(i * 1_000_000 // 30) for i in range(count)]},
            'capture': {'condition': 'steady_hold', 'side': 'not_applicable', 'interrupted': False, 'gaps': []},
            'frames': [{'frame_id': 10+i, 'pts_ns': str(1_000_000_000 + round(i * 1e9 / 30)), 'image_valid': True} for i in range(count)]}


def video(path, frames):
    with av.open(str(path), 'w', format='mp4') as container:
        stream = container.add_stream('libx264', rate=30)
        stream.width, stream.height, stream.pix_fmt = 128, 96, 'yuv420p'
        stream.options = {'crf': '10', 'preset': 'ultrafast'}
        for i, pixels in enumerate(frames):
            frame = av.VideoFrame.from_ndarray(pixels, format='bgr24')
            frame.pts, frame.time_base = i, Fraction(1, 30)
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)


def test_local_subpixel_motion_is_amplified_without_changing_input():
    frames = clip()
    original = frames.copy()
    amplified, report = magnify_frames(frames, np.arange(len(frames)) / 30)
    assert np.array_equal(frames, original)
    assert amplified.shape == frames.shape
    region = np.s_[:, 25:75, 45:82, :]
    assert amplified[region].astype(float).std(axis=0).mean() > 1.4 * frames[region].astype(float).std(axis=0).mean()
    assert report['background_max_displacement_px'] < .5


@pytest.mark.parametrize('kind', ['shake', 'noise', 'constant', 'textureless', 'short', 'irregular', 'large'])
def test_rejects_unsuitable_evidence(kind):
    frames = clip(shake=kind == 'shake', noise=kind == 'noise', amplitude=8 if kind == 'large' else .65)
    times = np.arange(len(frames)) / 30
    if kind == 'constant':
        frames = np.repeat(frames[:1], len(frames), axis=0)
    if kind == 'textureless':
        frames = np.full_like(frames, 90)
    if kind == 'short':
        frames, times = frames[:10], times[:10]
    if kind == 'irregular':
        times = times + (np.arange(len(frames)) % 2) * .008
    with pytest.raises(ValueError):
        magnify_frames(frames, times)


def test_process_writes_paired_videos_and_exact_mapping(tmp_path):
    source = tmp_path / 'source.mp4'
    output = tmp_path / 'result'
    output.mkdir()
    frames, metadata = clip(), sidecar()
    video(source, frames)
    before = deepcopy(metadata)
    result = process_microscope(source, metadata, output, max_output_bytes=10_000_000, crop=(32, 16, 64, 64))
    assert result['feature']['status'] == 'available', result
    assert metadata == before
    assert len(result['artifacts']) == 3
    scope = result['microscopes'][0]
    assert scope['region'] == 'recorded_view'
    assert scope['evidence']['first_frame_id'] == 10
    assert scope['evidence']['last_frame_id'] == 129
    settings = json.loads((output / scope['settings_artifact_id']).read_text())
    assert settings['crop_xywh_px'] == [32, 16, 64, 64]
    assert settings['source_frame_mapping'][0]['source_pts_ns'] == '1000000000'
    assert settings['source_frame_mapping'][-1]['source_frame_id'] == 129
    assert settings['stabilization'] == 'none; unsuitable camera motion is rejected'
    assert 'clinical' in ' '.join(settings['limitations']).lower()
    timelines = []
    for key in ('original_artifact_id', 'amplified_artifact_id'):
        with av.open(str(output / scope[key])) as container:
            decoded = list(container.decode(video=0))
            assert len(decoded) == 120
            assert (decoded[0].width, decoded[0].height) == (64, 64)
            timelines.append([float(frame.pts * frame.time_base) for frame in decoded])
    assert timelines[0] == timelines[1]
    assert abs(timelines[0][-1] - 119/30) < .00001
    assert len(list(output.iterdir())) == 3


@pytest.mark.parametrize('kind', ['invalid', 'gap', 'interrupted', 'mismatch', 'budget', 'bad_crop', 'bad_interval'])
def test_process_rejects_bad_inputs_without_publishing_partial_files(tmp_path, kind):
    source, output = tmp_path / 'source.mp4', tmp_path / 'result'
    output.mkdir()
    metadata = sidecar()
    if kind == 'invalid':
        metadata['frames'][50]['image_valid'] = False
    if kind == 'gap':
        metadata['capture']['gaps'] = [{'start_pts_ns': '2000000000', 'end_pts_ns': '2200000000'}]
    if kind == 'interrupted':
        metadata['capture']['interrupted'] = True
    if kind == 'mismatch':
        metadata['frames'][50]['pts_ns'] = str(int(metadata['frames'][50]['pts_ns']) + 100_000_000)
    video(source, clip())
    result = process_microscope(source, metadata, output,
                               max_output_bytes=1 if kind == 'budget' else 10_000_000,
                               crop=(-1, 0, 20, 20) if kind == 'bad_crop' else None,
                               interval_s=(20, 30) if kind == 'bad_interval' else None)
    assert result['feature']['status'] == 'unavailable'
    assert result['artifacts'] == []
    assert not list(output.iterdir())


@pytest.mark.parametrize('kind', ['count', 'duplicate_id', 'frame_id', 'timestamp', 'origin', 'mapping', 'rotation', 'mirrored', 'dimensions', 'budget'])
def test_rejects_malformed_contract_fields(tmp_path, kind):
    source, output = tmp_path / 'source.mp4', tmp_path / 'result'
    output.mkdir()
    metadata = sidecar()
    if kind == 'count':
        metadata['frames'] = []
    if kind == 'duplicate_id':
        metadata['frames'][50]['frame_id'] = 10
    if kind == 'frame_id':
        metadata['frames'][50]['frame_id'] = True
    if kind == 'timestamp':
        metadata['frames'][50]['pts_ns'] = 'not_a_timestamp'
    if kind == 'origin':
        metadata['clock']['origin_pts_ns'] = '999999999999999'
    if kind == 'mapping':
        del metadata['media']
    if kind == 'rotation':
        metadata['image']['rotation_degrees'] = 90
    if kind == 'mirrored':
        metadata['image']['mirrored'] = True
    if kind == 'dimensions':
        metadata['image']['width_px'] = 99999
    result = process_microscope(source, metadata, output, max_output_bytes=-1 if kind == 'budget' else 10_000_000)
    assert result['feature']['status'] == 'unavailable'
    assert not list(output.iterdir())


def test_specific_interval_keeps_source_ids_and_relative_output_pts(tmp_path):
    source, output = tmp_path / 'source.mp4', tmp_path / 'result'
    output.mkdir()
    metadata = sidecar(180)
    video(source, clip(180))
    result = process_microscope(source, metadata, output, max_output_bytes=10_000_000,
                               interval_s=(1, 4.966666667))
    assert result['feature']['status'] == 'available', result
    scope = result['microscopes'][0]
    assert scope['evidence']['start_s'] == 1
    assert scope['evidence']['first_frame_id'] == 40
    settings = json.loads((output / scope['settings_artifact_id']).read_text())
    mapping = settings['source_frame_mapping']
    assert mapping[0]['output_pts_us'] == '0'
    assert mapping[0]['source_pts_ns'] == '2000000000'
    assert mapping[-1]['source_frame_id'] == 159


def test_failure_preserves_existing_artifacts(tmp_path):
    source, output = tmp_path / 'source.mp4', tmp_path / 'result'
    output.mkdir()
    existing = output / 'existing-artifact'
    existing.write_bytes(b'preserve this')
    video(source, clip())
    result = process_microscope(source, sidecar(), output, max_output_bytes=1)
    assert result['feature']['status'] == 'unavailable'
    assert list(output.iterdir()) == [existing]
    assert existing.read_bytes() == b'preserve this'


def test_decode_failure_is_reported_without_private_path(tmp_path):
    output = tmp_path / 'result'
    output.mkdir()
    result = process_microscope(tmp_path / 'private-patient-name.mp4', sidecar(), output,
                               max_output_bytes=10_000_000)
    assert result['feature']['status'] == 'unavailable'
    assert 'private-patient-name' not in result['feature']['detail']


def test_selected_static_crop_has_no_claimed_amplification(tmp_path):
    source, output = tmp_path / 'source.mp4', tmp_path / 'result'
    output.mkdir()
    video(source, clip())
    result = process_microscope(source, sidecar(), output, max_output_bytes=10_000_000,
                               crop=(0, 0, 32, 32))
    assert result['feature']['status'] == 'unavailable'
    assert not list(output.iterdir())


@pytest.mark.parametrize('collision_index', [0, 1, 2])
def test_failed_exclusive_creation_never_removes_existing_artifact(tmp_path, monkeypatch, collision_index):
    from processing import microscope

    source, output = tmp_path / 'source.mp4', tmp_path / 'result'
    output.mkdir()
    video(source, clip())
    identifiers = [uuid4() for _ in range(3)]
    existing = output / str(identifiers[collision_index])
    existing.write_bytes(b'previous artifact')
    values = iter(identifiers)
    monkeypatch.setattr(microscope, 'uuid4', lambda: next(values))
    result = process_microscope(source, sidecar(), output, max_output_bytes=10_000_000)
    assert result['feature']['status'] == 'unavailable'
    assert existing.read_bytes() == b'previous artifact'
    assert list(output.iterdir()) == [existing]
