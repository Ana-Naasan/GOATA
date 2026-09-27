"""Excluded fixture encoding, then timed released-only decode/preparation helpers."""
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import time
import uuid


def save(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False)+'\n')


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for data in iter(lambda:f.read(1024*1024), b''): h.update(data)
    return h.hexdigest()


def inventory(path): return dict(byte_size=path.stat().st_size, sha256=sha(path))


def verify(path, expected):
    if inventory(path)!=expected: raise ValueError('file changed: '+str(path))


def write_video(path, images, width, height):
    from buffered import writer, encode, close_writer
    out, stream=writer(path,width,height,lossless=True)
    try:
        for i, image in enumerate(images): encode(out,stream,image,i,Fraction(1,30))
    finally: close_writer(out,stream)
    import av
    pixels=hashlib.sha256(); pts=[]
    with av.open(str(path)) as src:
        for f in src.decode(video=0):
            if (f.width,f.height)!=(width,height): raise ValueError('prepared dimensions mismatch')
            pts.append(Fraction(f.pts)*f.time_base)
            pixels.update(f.to_ndarray(format='bgr24').tobytes())
    if pts!=[Fraction(i,30) for i in range(len(images))]: raise ValueError('prepared PTS mismatch')
    return dict(file=inventory(path),decoded_bgr24_sha256=pixels.hexdigest(),frame_count=len(pts))


def prepare(video, calibration, output, variant):
    import av
    import cv2
    from buffered import writer, encode, close_writer
    from fast import resized
    start=time.monotonic()
    if video.name!='drone_video.mp4' or not 0<video.stat().st_size<=512*1024**2:
        raise ValueError('only existing public drone_video.mp4, <=512MiB')
    k=[float(x) for x in calibration.read_text().split()]
    if k!=[1321.,1321.,960.,540.]: raise ValueError('provided WHAM drone calibration required')
    from fast import VARIANTS
    width,hz=VARIANTS[variant]
    w,h,scaled=resized(1920,1080,width,dict(zip(('fx','fy','cx','cy'),k)))
    source_identity,calibration_identity=inventory(video),inventory(calibration)
    rows=[]; current=None; out=stream=None; origin=base=rate=None; count=0
    try:
        with av.open(str(video)) as source:
            if len(source.streams.video)!=1: raise ValueError('require single video stream')
            src=source.streams.video[0]; rate=src.average_rate
            if rate is None or not 10<=rate<=60: raise ValueError('invalid bounded source rate')
            for i,f in enumerate(source.decode(src)):
                if (f.pts is None or (f.width,f.height)!=(1920,1080) or src.metadata.get('rotate','0')!='0'
                        or any('DISPLAYMATRIX' in str(s.type) for s in f.side_data)):
                    raise ValueError('invalid original dimensions/PTS/transform')
                t=Fraction(f.pts)*f.time_base
                if origin is None: origin,base=t,f.time_base
                if f.time_base!=base or t-origin!=Fraction(i,1)/rate:
                    raise ValueError('this public fixture requires verified constant-rate original PTS')
                if t-origin>=8:
                    # The actual 30000/1001-fps source has its first excluded
                    # lookahead at 8.008 s, not exactly 8 s. Preserve its clock.
                    break
                index=int((t-origin)//2)
                if current!=index:
                    if out is not None: close_writer(out,stream); out=None
                    path=output/f'chunk-{index}.mp4'
                    out,stream=writer(path,w,h,rate,base,True)
                    rows.append(dict(index=index, path=path.name, frames=[], release_offset_s=2*(index+1)))
                    current=index
                    chunk_origin=t
                encode(out,stream,cv2.resize(f.to_ndarray(format='bgr24'),(w,h),interpolation=cv2.INTER_AREA),
                       int((t-chunk_origin)/base),base)
                rows[-1]['frames'].append(dict(frame_id=i,pts_ns=str(round(t*10**9)),image_valid=True,
                                                original_pts=str(f.pts),original_time_base=str(base),
                                                encoded_pts_seconds=str(t-chunk_origin)))
                count+=1
                if count>480: raise ValueError('source frame bound')
            else: raise ValueError('need original first eight seconds plus one boundary frame')
    finally:
        if out is not None: close_writer(out,stream)
    if len(rows)!=4: raise ValueError('expected four chunks')
    for row in rows:
        path=output/row['path']; row['identity']=inventory(path)
        with av.open(str(path)) as src:
            times=[str(Fraction(f.pts)*f.time_base) for f in src.decode(video=0)]
        if times!=[f['encoded_pts_seconds'] for f in row['frames']]: raise ValueError('fixture PTS changed')
    verify(video,source_identity); verify(calibration,calibration_identity)
    manifest=dict(schema='stream-fixture-1',take_id=str(uuid.uuid4()),variant=variant,width=w,height=h,
                  hz=hz,rate=str(rate),original_time_base=str(base),origin_pts_ns=str(round(origin*10**9)),
                  original_origin_seconds=str(origin),source_duration_s=8,source_frame_count=count,
                  original_file=video.name,original_identity=source_identity,calibration_identity=calibration_identity,
                  source_K=[[1321.,0,960.],[0,1321.,540.],[0,0,1]],
                  K=[[scaled['fx'],0,scaled['cx']],[0,scaled['fy'],scaled['cy']],[0,0,1]],chunks=rows,
                  calibration_basis='provided drone_calib.txt; rectified pinhole assumed, not independently calibrated',
                  exclusion='fixture source decode, resize and four independent lossless-YUV420 encodes BEFORE capture clock; no observations/features',
                  preparation_s=time.monotonic()-start)
    save(output/'fixture.json',manifest)
    return manifest


def playback_duration(manifest):
    """Constant-rate frame presentation can end just after the capture cutoff."""
    return Fraction(manifest['source_frame_count'], 1) / Fraction(manifest['rate'])


def decode_released(folder, manifest, row):
    import av
    path=folder/row['path']; verify(path,row['identity'])
    images=[]
    with av.open(str(path)) as src:
        if len(src.streams.video)!=1 or src.streams.video[0].metadata.get('rotate','0')!='0':
            raise ValueError('invalid chunk stream')
        for i,f in enumerate(src.decode(video=0)):
            if (i>=len(row['frames']) or i>=120 or f.pts is None
                    or (f.width,f.height)!=(manifest['width'],manifest['height'])
                    or str(Fraction(f.pts)*f.time_base)!=row['frames'][i]['encoded_pts_seconds']
                    or any('DISPLAYMATRIX' in str(s.type) for s in f.side_data)):
                raise ValueError('released decode/PTS/resize mismatch')
            images.append(f.to_ndarray(format='bgr24'))
    if len(images)!=len(row['frames']): raise ValueError('truncated released chunk')
    return images
