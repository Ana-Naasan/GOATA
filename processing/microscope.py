"""Conservative original-footage Eulerian magnification; no diagnostic inference.

Independent implementation of spatial decomposition + temporal filtering from
Wu et al., SIGGRAPH 2012: https://people.csail.mit.edu/mrub/evm/ . No upstream
code or assets are copied. A single coarse Laplacian band and modest gain limit
cost and artifacts; this is not the authors' full multiscale implementation.
"""

import hashlib
import json
import logging
import math
from fractions import Fraction
from itertools import pairwise
from pathlib import Path
from uuid import UUID, uuid4

from processing.media_timing import validate_media_mapping
from processing.reconstruction.runtime import bind_pts

MAX_SELECTED_FRAMES = 240
MAX_SOURCE_FRAMES = 3600
MAX_EDGE = 256
MAX_PIXELS = 4096 * 2160
VERSION = '1.0'
LIMITATIONS = [
    'Illustrative, research demo only; no clinical validation or diagnostic meaning.',
    'Compression, lighting, sensor noise and small camera motion can be amplified.',
    'Single coarse spatial band; large motion, poor background texture and irregular sampling are rejected.',
    'No stabilization or interpolation; output retains selected original frames and source timestamps.',
    'Numerical findings must use original unamplified evidence, never these amplified pixels.',
]


def _unavailable(detail):
    return {'feature': {'name': 'microscope', 'status': 'unavailable', 'detail': detail},
            'methods': [], 'microscopes': [], 'artifacts': []}


def _background_guard(gray, cv2, np):
    height, width = gray.shape[1:]
    yy, xx = np.indices((height, width))
    mask = ((xx < width * .2) | (xx >= width * .8)
            | (yy < height * .2) | (yy >= height * .8))
    points = cv2.goodFeaturesToTrack(gray[0], 160, .02, 4, mask=mask.astype('uint8') * 255)
    if points is None or len(points) < 12:
        raise ValueError('Insufficient textured background to check camera motion.')
    quadrants = (points[:, 0, 0] >= width / 2) + 2 * (points[:, 0, 1] >= height / 2)
    if len(np.unique(quadrants)) < 3:
        raise ValueError('Background features do not cover enough of the image.')
    maximum = 0.0
    for frame in gray[1:]:
        tracked, status, errors = cv2.calcOpticalFlowPyrLK(gray[0], frame, points, None)
        if tracked is None or status is None or errors is None:
            raise ValueError('Background tracking failed; camera stability is unknown.')
        valid = (status[:, 0] == 1) & (errors[:, 0] < 20)
        if valid.sum() < max(12, len(points) * .7):
            raise ValueError('Insufficient reliable background tracks to check camera motion.')
        displacement = np.linalg.norm(tracked[valid, 0] - points[valid, 0], axis=1)
        maximum = max(maximum, float(np.quantile(displacement, .75)))
        if maximum > .5:
            raise ValueError('Camera or background motion exceeds the microscope stability limit.')
    background_noise = float(np.std(gray[:, mask].astype('float32'), axis=0).mean())
    if background_noise > 3.0:
        raise ValueError('Background noise or lighting changes dominate the recording.')
    return mask, maximum, background_noise


def _local_motion_guard(gray, border, cv2, np):
    points = cv2.goodFeaturesToTrack(gray[0], 100, .02, 4, mask=(~border).astype('uint8') * 255)
    if points is None or len(points) < 6:
        raise ValueError('Insufficient interior texture to check the small-motion assumption.')
    maximum = 0.0
    for frame in gray[1:]:
        tracked, status, errors = cv2.calcOpticalFlowPyrLK(gray[0], frame, points, None)
        if tracked is None or status is None or errors is None:
            raise ValueError('Interior motion tracking failed.')
        valid = (status[:, 0] == 1) & (errors[:, 0] < 20)
        if valid.sum() < max(6, len(points) * .7):
            raise ValueError('Interior motion cannot be bounded reliably.')
        maximum = max(maximum, float(np.quantile(
            np.linalg.norm(tracked[valid, 0] - points[valid, 0], axis=1), .9)))
        if maximum > 2:
            raise ValueError('Recorded movement is too large for conservative linear magnification.')
    return maximum


def magnify_frames(frames, times_s, *, low_hz=.5, high_hz=3.0, amplification=4.0):
    """Return new BGR uint8 pixels plus quality data; reject unsuitable evidence.

    Input is already bounded/resized by the caller. Sampling jitter may be at
    most 2%; filtering uses the median period without fabricating source frames.
    """
    import cv2
    import numpy as np

    if (not isinstance(frames, np.ndarray) or frames.dtype != np.uint8 or frames.ndim != 4
            or frames.shape[-1] != 3 or not 32 <= len(frames) <= MAX_SELECTED_FRAMES
            or min(frames.shape[1:3]) < 32 or max(frames.shape[1:3]) > MAX_EDGE):
        raise ValueError('Microscope needs 32 to 240 bounded BGR frames of at least 32 pixels.')
    times = np.asarray(times_s, dtype='float64')
    if times.shape != (len(frames),) or not np.isfinite(times).all():
        raise ValueError('Source times must be finite and match the selected frames.')
    delta = np.diff(times)
    period = float(np.median(delta))
    if period <= 0 or (delta <= 0).any() or np.max(np.abs(delta / period - 1)) > .02:
        raise ValueError('Irregular or missing source sampling cannot be safely magnified.')
    if (any(type(x) not in (int, float) or not math.isfinite(x)
            for x in (low_hz, high_hz, amplification))
            or not 0 < low_hz < high_hz < .5 / period or not 0 < amplification <= 5):
        raise ValueError('Invalid temporal band or amplification; gain must be at most 5.')
    if len(frames) * period < 2 / low_hz - 1e-6:
        raise ValueError('Insufficient duration: record at least two cycles of the lowest frequency.')
    gray = np.stack([cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) for frame in frames])
    border, max_motion, noise = _background_guard(gray, cv2, np)
    local_motion = _local_motion_guard(gray, border, cv2, np)
    # ponytail: one coarse Laplacian band; add multiscale processing only after real-video validation.
    coarse = np.stack([cv2.pyrDown(frame.astype('float32')) for frame in gray])
    band = np.stack([frame - cv2.pyrUp(cv2.pyrDown(frame), dstsize=(frame.shape[1], frame.shape[0]))
                     for frame in coarse])
    padded = np.pad(band, ((len(band), len(band)), (0, 0), (0, 0)), mode='reflect')
    frequencies = np.fft.rfftfreq(len(padded), period)
    passed = (frequencies >= low_hz) & (frequencies <= high_hz)
    spectrum = np.fft.rfft(padded, axis=0)
    padded_count = len(padded)
    del padded, coarse
    filtered = np.fft.irfft(spectrum * passed[:, None, None], n=padded_count, axis=0)
    del spectrum
    filtered = filtered[len(band):2 * len(band)].copy()
    del band
    variation = np.stack([cv2.pyrUp(frame.astype('float32'), dstsize=(gray.shape[2], gray.shape[1]))
                          for frame in filtered])
    signal = float(np.quantile(np.std(variation, axis=0), .95))
    border_signal = float(np.sqrt(np.mean(variation[:, border] ** 2)))
    if signal < .15 or signal < 3 * max(border_signal, .01):
        raise ValueError('No sufficiently localized temporal signal above background noise.')
    changed_frames = []
    clipped = 0
    for frame, change in zip(frames, variation):
        changed = frame.astype('float32') + amplification * change[..., None]
        clipped += int(np.count_nonzero((changed < 0) | (changed > 255)))
        changed_frames.append(np.clip(np.rint(changed), 0, 255).astype('uint8'))
    clipping = clipped / frames.size
    if clipping > .01:
        raise ValueError('Amplification would clip too many pixels; use a steadier, smaller motion.')
    return np.stack(changed_frames), {
        'background_max_displacement_px': max_motion, 'background_noise_levels': noise,
        'interior_p90_max_displacement_px': local_motion, 'interior_displacement_limit_px': 2.0,
        'background_band_rms_levels': border_signal, 'signal_p95_levels': signal,
        'clipped_fraction': clipping, 'sampling_period_s': period,
        'sampling_jitter_limit_fraction': .02, 'background_displacement_limit_px': .5,
        'background_noise_limit_levels': 3.0, 'signal_minimum_levels': .15,
        'signal_background_ratio_minimum': 3.0, 'clipped_fraction_limit': .01,
    }


def _selection(sidecar, interval_s):
    frames = sidecar['frames']
    if not isinstance(frames, list) or not 1 <= len(frames) <= MAX_SOURCE_FRAMES:
        raise ValueError('Source frame count exceeds microscope limits.')
    if sidecar['capture']['interrupted']:
        raise ValueError('Interrupted recording cannot produce a microscope result.')
    UUID(sidecar['take_id'])
    origin = int(sidecar['clock']['origin_pts_ns'])
    if any(type(frame['frame_id']) is not int or frame['frame_id'] < 0
           or type(frame['pts_ns']) is not str or len(frame['pts_ns']) > 30
           or not frame['pts_ns'].isascii() or not frame['pts_ns'].isdigit()
           or type(frame['image_valid']) is not bool for frame in frames):
        raise ValueError('Invalid source frame identity or timestamp.')
    if len({frame['frame_id'] for frame in frames}) != len(frames):
        raise ValueError('Source frame identities must be unique.')
    times = [(int(frame['pts_ns']) - origin) / 1e9 for frame in frames]
    if times[0] < 0 or any(a >= b for a, b in pairwise(times)):
        raise ValueError('Source timestamps must strictly increase from the capture origin.')
    interval = (times[0], min(times[-1], times[0] + 8)) if interval_s is None else interval_s
    if (not isinstance(interval, (list, tuple)) or len(interval) != 2
            or any(type(x) not in (int, float) or not math.isfinite(x) for x in interval)
            or not times[0] <= interval[0] < interval[1] <= times[-1]
            or interval[1] - interval[0] > 8):
        raise ValueError('Requested interval must be inside the recording and at most 8 seconds.')
    selected = [i for i, time in enumerate(times) if interval[0] <= time <= interval[1]]
    if interval_s is None:
        selected = selected[:MAX_SELECTED_FRAMES]
    if not 32 <= len(selected) <= MAX_SELECTED_FRAMES:
        raise ValueError('Requested interval must contain 32 to 240 source frames.')
    if any(not frames[i]['image_valid'] for i in selected):
        raise ValueError('Microscope interval contains missing or rejected source images.')
    start, end = (int(frames[i]['pts_ns']) for i in (selected[0], selected[-1]))
    if any(int(gap['start_pts_ns']) <= end and int(gap['end_pts_ns']) >= start
           for gap in sidecar['capture']['gaps']):
        raise ValueError('Microscope interval overlaps a source capture gap.')
    return selected, times


def _decode(video_path, sidecar, selected, decoder_offset_ns, av, cv2, np):
    image = sidecar['image']
    width, height = image['width_px'], image['height_px']
    if (type(width) is not int or type(height) is not int or min(width, height) < 32
            or width * height > MAX_PIXELS):
        raise ValueError('Stored image dimensions exceed the microscope decode limit.')
    if image['rotation_degrees'] != 0 or image['mirrored']:
        raise ValueError('Rotated or mirrored stored images are unsupported by the microscope.')
    media = sidecar.get('media')
    validate_media_mapping(media, len(sidecar['frames']))
    if media is None and type(decoder_offset_ns) is not int:
        raise ValueError('An explicit recording-to-source timestamp mapping is required.')
    scale = min(1.0, MAX_EDGE / max(width, height))
    size = (int(width * scale) // 2 * 2, int(height * scale) // 2 * 2)
    if min(size) < 32:
        raise ValueError('Image aspect ratio is too narrow for the bounded microscope preview.')
    pixels, decoded = [], []
    wanted = set(selected)
    with av.open(str(video_path)) as container:
        if len(container.streams.video) != 1:
            raise ValueError('Microscope requires exactly one source video stream.')
        stream = container.streams.video[0]
        stream.codec_context.options = {**stream.codec_context.options, 'max_pixels': str(width * height)}
        if (stream.width, stream.height) != (width, height) or stream.metadata.get('rotate', '0') != '0':
            raise ValueError('Stored video image does not match its source metadata.')
        for i, frame in enumerate(container.decode(stream)):
            if i >= len(sidecar['frames']) or frame.pts is None:
                raise ValueError('Source video has extra frames or missing presentation timestamps.')
            if (frame.width, frame.height) != (width, height):
                raise ValueError('Source image dimensions changed during decoding.')
            if any('DISPLAYMATRIX' in str(data.type) for data in frame.side_data):
                raise ValueError('Source video display transforms are unsupported.')
            decoded.append((i, Fraction(frame.pts) * frame.time_base))
            if i in wanted:
                pixels.append(cv2.resize(frame.to_ndarray(format='bgr24'), size, interpolation=cv2.INTER_AREA))
    bind_pts(sidecar['frames'], decoded, 0 if media is not None else decoder_offset_ns, media=media)
    return np.stack(pixels), size


def _crop(crop, image, size):
    width, height = image['width_px'], image['height_px']
    requested = (0, 0, width, height) if crop is None else crop
    if (not isinstance(requested, (list, tuple)) or len(requested) != 4
            or any(type(value) is not int for value in requested)):
        raise ValueError('Crop must contain four integer pixel coordinates.')
    x, y, w, h = requested
    if min(x, y) < 0 or min(w, h) < 32 or x + w > width or y + h > height:
        raise ValueError('Requested crop lies outside the source image or is too small.')
    # Both clips use the same even-pixel crop after identical downsampling.
    left, top = int(x * size[0] / width) // 2 * 2, int(y * size[1] / height) // 2 * 2
    right = int((x + w) * size[0] / width) // 2 * 2
    bottom = int((y + h) * size[1] / height) // 2 * 2
    if min(right - left, bottom - top) < 32:
        raise ValueError('Requested crop is too small at the bounded output resolution.')
    return list(requested), [left, top, right - left, bottom - top]


def _encode(path, pixels, pts_us, max_bytes, av, created):
    with path.open('xb') as handle:
        created.append(path)
        _encode_stream(handle, pixels, pts_us, max_bytes, av)
    if path.stat().st_size > max_bytes:
        raise ValueError('Microscope artifacts exceed the output byte budget.')
    with av.open(str(path)) as check:
        actual = [round(frame.pts * frame.time_base * 1_000_000) for frame in check.decode(video=0)]
    if actual != pts_us:
        raise ValueError('Encoded microscope timing did not preserve the source frame mapping.')


def _encode_stream(handle, pixels, pts_us, max_bytes, av):
    with av.open(handle, 'w', format='mp4') as container:
        stream = container.add_stream('libx264', rate=30)
        stream.width, stream.height = pixels.shape[2], pixels.shape[1]
        stream.pix_fmt, stream.time_base = 'yuv420p', Fraction(1, 1_000_000)
        stream.codec_context.time_base = Fraction(1, 1_000_000)
        stream.options = {'crf': '12', 'preset': 'ultrafast', 'bf': '0'}
        for array, pts in zip(pixels, pts_us):
            frame = av.VideoFrame.from_ndarray(array, format='bgr24')
            frame.pts, frame.time_base = pts, Fraction(1, 1_000_000)
            for packet in stream.encode(frame):
                container.mux(packet)
            if handle.tell() > max_bytes:
                raise ValueError('Microscope artifacts exceed the output byte budget.')
        for packet in stream.encode():
            container.mux(packet)


def _sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _publish(output_dir, frames, amplified, selected, times, sidecar, crop, size, report, max_bytes, av):
    requested, actual_crop = _crop(crop, sidecar['image'], size)
    x, y, width, height = actual_crop
    import numpy as np

    difference = np.abs(amplified[:, y:y+height, x:x+width].astype('int16')
                        - frames[:, y:y+height, x:x+width].astype('int16'))
    if float(difference.mean()) < .05:
        raise ValueError('Selected crop has insufficient temporal signal to magnify.')
    del difference
    first = int(sidecar['frames'][selected[0]]['pts_ns'])
    pts_us = [round((int(sidecar['frames'][i]['pts_ns']) - first) / 1000) for i in selected]
    settings = {'method': 'single_laplacian_band_eulerian', 'version': VERSION,
                'reference': 'https://people.csail.mit.edu/mrub/evm/',
                'temporal_band_hz': [.5, 3.0], 'amplification_added': 4.0,
                'spatial_band': 'Gaussian level 1 minus expanded level 2; luminance only',
                'temporal_filter': 'ideal FFT bandpass with reflection padding; median source period',
                'stabilization': 'none; unsuitable camera motion is rejected',
                'crop_xywh_px': requested, 'output_crop_xywh_px': actual_crop,
                'resized_full_image_size_px': list(size), 'source_take_id': sidecar['take_id'],
                'preview_max_edge_px': MAX_EDGE, 'maximum_selected_frames': MAX_SELECTED_FRAMES,
                'codec': {'name': 'libx264', 'pixel_format': 'yuv420p', 'crf': 12, 'b_frames': 0},
                'source_frame_mapping': [{'output_index': j, 'output_pts_us': str(pts_us[j]),
                                          'source_frame_id': sidecar['frames'][i]['frame_id'],
                                          'source_pts_ns': sidecar['frames'][i]['pts_ns']}
                                         for j, i in enumerate(selected)],
                'quality_checks': report, 'limitations': LIMITATIONS}
    identifiers = [str(uuid4()) for _ in range(3)]
    paths = [output_dir / identifier for identifier in identifiers]
    created = []
    try:
        _encode(paths[0], frames[:, y:y+height, x:x+width], pts_us, max_bytes, av, created)
        _encode(paths[1], amplified[:, y:y+height, x:x+width], pts_us,
                max_bytes - paths[0].stat().st_size, av, created)
        with paths[2].open('x') as handle:
            created.append(paths[2])
            json.dump(settings, handle, allow_nan=False)
        if sum(path.stat().st_size for path in paths) > max_bytes:
            raise ValueError('Microscope artifacts exceed the output byte budget.')
        roles = ['microscope_original', 'microscope_amplified', 'processing_settings']
        artifacts = [{'artifact_id': identifier, 'role': role,
                      'media_type': 'application/json' if role == 'processing_settings' else 'video/mp4',
                      'byte_size': path.stat().st_size, 'sha256': _sha256(path)}
                     for identifier, path, role in zip(identifiers, paths, roles)]
    except Exception:
        for path in created:
            path.unlink(missing_ok=True)
        raise
    method_id = f'eulerian_microscope_{sidecar["take_id"]}'
    detail = 'Original and amplified views share one source interval and crop. Artifacts may be amplified; visualization is unvalidated.'
    evidence = {'take_id': sidecar['take_id'], 'start_s': times[selected[0]], 'end_s': times[selected[-1]],
                'first_frame_id': sidecar['frames'][selected[0]]['frame_id'],
                'last_frame_id': sidecar['frames'][selected[-1]]['frame_id'],
                'condition': sidecar['capture']['condition'], 'quality': 'limited',
                'quality_reason': 'Heuristic camera/noise checks only; visual fidelity needs practitioner review.'}
    return {'feature': {'name': 'microscope', 'status': 'available', 'detail': detail},
            'methods': [{'method_id': method_id, 'name': 'Conservative Eulerian motion microscope',
                         'version': VERSION, 'settings_artifact_id': identifiers[2]}],
            'microscopes': [{'microscope_id': str(uuid4()), 'method_id': method_id, 'evidence': evidence,
                            'region': 'recorded_view', 'side': sidecar['capture']['side'], 'status': 'available',
                            'detail': detail, 'original_artifact_id': identifiers[0],
                            'amplified_artifact_id': identifiers[1], 'settings_artifact_id': identifiers[2]}],
            'artifacts': artifacts}


def process_microscope(video_path, sidecar, output_dir, *, max_output_bytes,
                       crop=None, interval_s=None, decoder_offset_ns=None):
    """Produce service-ready artifact UUID files or an explicit unavailable feature.

    Inputs are the validated original sidecar and original MP4. Default selection
    is the first <=8 seconds/240 frames, never a reconstruction or resampled clip.
    Files are only published together after all checks; existing files remain.
    """
    try:
        import av
        import cv2
        import numpy as np
    except ImportError:
        return _unavailable('Microscope dependencies are missing: install the microscope optional extra.')
    try:
        if type(max_output_bytes) is not int or not 0 < max_output_bytes <= 1024 ** 3:
            raise ValueError('Microscope requires a positive output budget of at most 1 GiB.')
        selected, times = _selection(sidecar, interval_s)
        frames, size = _decode(video_path, sidecar, selected, decoder_offset_ns, av, cv2, np)
        amplified, report = magnify_frames(frames, [times[i] for i in selected])
        return _publish(Path(output_dir), frames, amplified, selected, times, sidecar,
                        crop, size, report, max_output_bytes, av)
    except ValueError as error:
        return _unavailable(str(error)[:500])
    except (KeyError, TypeError, OverflowError):
        return _unavailable('Invalid source metadata for microscope processing.')
    except (OSError, av.FFmpegError, cv2.error):
        logging.getLogger(__name__).exception('Microscope media decoding or artifact writing failed')
        return _unavailable('Microscope media could not be decoded or written; original recording is preserved.')
