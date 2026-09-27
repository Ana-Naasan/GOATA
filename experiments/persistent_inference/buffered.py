"""Bounded local media helpers retained from the frozen buffered experiment.

No preview, timeline, scheduling or legacy worker entry point is included.
"""
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import uuid

MAX_FILE_BYTES = 256*1024*1024
MAX_OUTPUT_BYTES = 2*1024*1024*1024


def check_output(root):
    files = [p.stat().st_size for p in root.rglob('*') if p.is_file()]
    if any(size > MAX_FILE_BYTES for size in files) or sum(files) > MAX_OUTPUT_BYTES:
        raise ValueError('output byte budget exceeded')


def supervise(command, root, timeout):
    """POSIX process-group watchdog; no retry or concurrent workers."""
    deadline = time.monotonic()+timeout
    process = subprocess.Popen(command, start_new_session=True)
    try:
        while True:
            check_output(root)
            if time.monotonic() >= deadline:
                raise TimeoutError('benchmark deadline exceeded')
            result = process.poll()
            if result is not None:
                if result:
                    raise subprocess.CalledProcessError(result, command)
                return
            time.sleep(.05)
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


def save(path, value):
    tmp = path.with_suffix(path.suffix+'.partial')
    tmp.write_text(json.dumps(value, indent=2, allow_nan=False)+'\n')
    tmp.replace(path)


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()


def inventory(path):
    return dict(byte_size=path.stat().st_size, sha256=sha(path))


def verify(path, entry):
    if inventory(path) != entry:
        raise ValueError(f'artifact verification failed: {path}')


def writer(path, width, height, rate=30, time_base=None, lossless=False):
    import av
    out = av.open(str(path), 'w')
    stream = out.add_stream('libx264', rate=rate)
    stream.width, stream.height, stream.pix_fmt = width, height, 'yuv420p'
    stream.options = dict(crf='0' if lossless else '18', preset='ultrafast', bf='0')
    if time_base is not None:
        stream.time_base = stream.codec_context.time_base = time_base
    return out, stream


def encode(out, stream, image, pts, base):
    import av
    frame = av.VideoFrame.from_ndarray(image, format='bgr24')
    frame.pts, frame.time_base = pts, base
    for packet in stream.encode(frame):
        out.mux(packet)


def close_writer(out, stream):
    try:
        for packet in stream.encode():
            out.mux(packet)
    finally:
        out.close()


def split(args):
    """Decode original once, stop at one lookahead frame after requested span."""
    import av
    from processing.reconstruction.runtime import bind_pts, plan_input
    kvalues = [float(x) for x in args.calibration.read_text().split()]
    if kvalues != [1321., 1321., 960., 540.]:
        raise ValueError('expected provided drone calibration: 1321 1321 960 540')
    if not args.video.is_file() or not 0 < args.video.stat().st_size <= 512*1024*1024:
        raise ValueError('original must be a local file no larger than 512MiB')
    provenance = dict(original_name=args.video.name, original=inventory(args.video),
                      calibration=inventory(args.calibration), source_id=str(uuid.uuid4()),
                      fixture='derived public WHAM video, not Quest capture',
                      calibration_basis='provided drone_calib.txt; rectified pinhole assumed, not independently calibrated')
    rows, frames, out, stream, origin, first_tick = [], [], None, None, None, None
    base = None
    segment_index = 0
    target = Fraction(str(args.segment_s))
    prior_time = None

    def finish(end_time):
        nonlocal frames, out, stream
        if len(frames) < 2:
            raise ValueError('segment too short')
        close_writer(out, stream)
        out = None
        folder = args.output / f'segment-{len(rows):02d}'
        video = folder / 'source.mp4'
        with av.open(str(video)) as check:
            decoded = [(i, Fraction(f.pts)*f.time_base) for i, f in enumerate(check.decode(video=0))]
        offset = int(frames[0]['pts_ns']) - round(decoded[0][1]*10**9)
        bind_pts(frames, decoded, offset)
        sidecar = dict(schema_version='1.0', take_id=str(uuid.uuid4()),
                       adapter=dict(name='derived-public-video-fixture', version='1'),
                       image=dict(width_px=1920, height_px=1080, rotation_degrees=0, mirrored=False),
                       camera=dict(id='WHAM-drone-provided-calibration', calibration_status='estimated',
                                   intrinsics=dict(zip(('fx','fy','cx','cy'), kvalues)),
                                   distortion_model='none', distortion_coefficients=[]),
                       clock=dict(id=provenance['source_id'], unit='nanoseconds', origin_pts_ns=frames[0]['pts_ns']),
                       original_origin_seconds=str(origin),
                       frames=frames, capture=dict(view='other', condition='exercise', side='not_applicable', interrupted=False),
                       provenance=provenance)
        plan_input(sidecar)
        save(folder/'sidecar.json', sidecar)
        row = dict(index=len(rows), take_id=sidecar['take_id'], directory=folder.name,
                   source_end_pts_seconds=str(end_time), source_start_pts_seconds=str(Fraction(frames[0]['original_pts'])*Fraction(frames[0]['original_time_base'])),
                   span_convention='half-open, end is first original PTS of following segment; final uses decoded lookahead',
                   source_start_s=float(Fraction(frames[0]['original_pts'])*Fraction(frames[0]['original_time_base'])-origin),
                   source_end_s=float(end_time-origin), first_frame_id=frames[0]['frame_id'],
                   last_frame_id=frames[-1]['frame_id'], frame_count=len(frames), pts_offset_ns=offset,
                   video=inventory(video), sidecar=inventory(folder/'sidecar.json'))
        rows.append(row)
        frames = []

    try:
        with av.open(str(args.video)) as container:
            if len(container.streams.video) != 1:
                raise ValueError('require one original video stream')
            src = container.streams.video[0]
            for frame_id, frame in enumerate(container.decode(src)):
                if frame.pts is None or (frame.width, frame.height) != (1920,1080):
                    raise ValueError('unexpected original dimensions or missing PTS')
                if src.metadata.get('rotate','0') != '0' or any('DISPLAYMATRIX' in str(x.type) for x in frame.side_data):
                    raise ValueError('unsupported image transform')
                t = Fraction(frame.pts)*frame.time_base
                if prior_time is not None and not 0 < t-prior_time <= Fraction(1,10):
                    raise ValueError('original gap or reordered PTS')
                prior_time = t
                if origin is None:
                    origin, base = t, frame.time_base
                if frame.time_base != base:
                    raise ValueError('changing time base')
                if t-origin >= (segment_index+1)*target:
                    finish(t)
                    segment_index += 1
                    if segment_index == args.segments:
                        break
                if out is None:
                    folder = args.output/f'segment-{segment_index:02d}'
                    folder.mkdir()
                    out, stream = writer(folder/'source.mp4',1920,1080,src.average_rate,base,True)
                    first_tick = frame.pts
                encode(out,stream,frame.to_ndarray(format='bgr24'),frame.pts-first_tick,base)
                frames.append(dict(frame_id=frame_id, pts_ns=str(round(t*10**9)), image_valid=True,
                                   original_pts=str(frame.pts), original_time_base=str(frame.time_base)))
                if len(frames) > 600:
                    raise ValueError('segment exceeds bounded 600 source frames')
            else:
                raise ValueError('original ended before requested span plus boundary lookahead')
    finally:
        if out is not None:
            out.close()
    verify(args.video, provenance['original'])
    verify(args.calibration, provenance['calibration'])
    save(args.output/'provenance.json',dict(provenance, segments=rows))
    return rows
