"""Four synchronized panels for visual review, with measured server-only stop latency."""
import argparse
from contextlib import ExitStack
from fractions import Fraction
import hashlib
import json
from pathlib import Path


def digest(path):
    result=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):result.update(block)
    return result.hexdigest()


def common_source(reports):
    expected=None
    for report in reports:
        if report['status']!='complete':raise ValueError('cannot demonstrate an incomplete experiment')
        fixture=report['fixture']
        rows=[(f['frame_id'],f['pts_ns'],f['original_pts'],f['original_time_base'])
              for chunk in fixture['chunks'] for f in chunk['frames']]
        key=(fixture['original_identity'],fixture['original_origin_seconds'],fixture['rate'],rows)
        if not 2<=len(rows)<=480 or len(rows)!=fixture['source_frame_count']:
            raise ValueError('invalid source count')
        if expected is not None and expected!=key:raise ValueError('demo sources/timestamps differ')
        expected=key
    if expected is None:raise ValueError('no reports')
    return expected[-1]


def render(root,source,output):
    import av
    import cv2
    import numpy as np
    configs=('fp32-960','fp16-960','fp16-640')
    folders=[root/name for name in configs]
    reports=[json.loads((folder/'comparison.json').read_text()) for folder in folders]
    rows=common_source(reports)
    original=reports[0]['fixture']['original_identity']
    if source.stat().st_size!=original['byte_size'] or digest(source)!=original['sha256']:
        raise ValueError('original video identity mismatch')
    mode='streaming-cpu-vo-overlap'
    paths=[source]+[folder/mode/'annotated.mp4' for folder in folders]
    labels=['Original footage']+[
        f"{report['config']['precision']} | {report['fixture']['width']}px | "
        f"{report['fixture']['hz']} observations/s" for report in reports]
    delays=[]
    for folder,report in zip(folders,reports):
        result=next(r for r in report['results'] if r['mode']==mode)
        if result['status']!='complete':raise ValueError('selected scheduling mode did not complete')
        artifact=json.loads((folder/mode/'video.json').read_text())
        # Both byte identity and exact decoder PTS are verified below.
        path=folder/mode/'annotated.mp4'
        declared=artifact['identity']
        if 'sha256' not in declared or 'byte_size' not in declared:
            raise ValueError('video identity missing')
        if path.stat().st_size!=declared['byte_size'] or digest(path)!=declared['sha256']:
            raise ValueError('annotation video changed')
        delays.append(result['latencies']['stop_to_video_closed_decoded_s'])
    if output.exists():raise FileExistsError(output)
    temporary=output.with_name(output.stem+'.partial.mp4')
    origin=Fraction(reports[0]['fixture']['original_origin_seconds'])
    times=[Fraction(pts)*Fraction(base)-origin for _,_,pts,base in rows]
    base=Fraction(reports[0]['fixture']['original_time_base'])
    with ExitStack() as stack:
        containers=[stack.enter_context(av.open(str(path))) for path in paths]
        decoders=[iter(c.decode(video=0)) for c in containers]
        destination=stack.enter_context(av.open(str(temporary),'w'))
        stream=destination.add_stream('libx264',rate=Fraction(reports[0]['fixture']['rate']))
        stream.width,stream.height,stream.pix_fmt=1920,1080,'yuv420p'
        stream.time_base=stream.codec_context.time_base=base
        stream.options={'crf':'18','preset':'fast','bf':'0'}
        for index,expected in enumerate(times):
            panels=[]
            for col,decoder in enumerate(decoders):
                frame=next(decoder)
                t=Fraction(frame.pts)*frame.time_base-(origin if col==0 else 0)
                if t!=expected:raise ValueError('comparison panel PTS mismatch')
                image=cv2.resize(frame.to_ndarray(format='bgr24'),(960,540),interpolation=cv2.INTER_AREA)
                cv2.rectangle(image,(0,0),(960,80),(15,15,15),-1)
                cv2.putText(image,labels[col],(18,29),cv2.FONT_HERSHEY_SIMPLEX,.74,(255,255,255),2,cv2.LINE_AA)
                detail='Source video. Outputs are fitted estimates, not clinical findings.' if col==0 else f'Measured stop-to-video: {delays[col-1]:.2f}s | server only'
                cv2.putText(image,detail,(18,62),cv2.FONT_HERSHEY_SIMPLEX,.53,(225,225,225),1,cv2.LINE_AA)
                panels.append(image)
            image=np.concatenate((np.concatenate(panels[:2],axis=1),np.concatenate(panels[2:],axis=1)),axis=0)
            frame=av.VideoFrame.from_ndarray(image,format='bgr24');frame.pts=int(expected/base);frame.time_base=base
            for packet in stream.encode(frame):destination.mux(packet)
        for decoder in decoders[1:]:
            if next(decoder,None) is not None:raise ValueError('extra annotated frame')
        for packet in stream.encode():destination.mux(packet)
    with av.open(str(temporary)) as check:
        actual=[Fraction(f.pts)*f.time_base for f in check.decode(video=0)]
    if actual!=times:raise ValueError('comparison encode changed source timing')
    temporary.replace(output)
    evidence=dict(status='complete',video=dict(byte_size=output.stat().st_size,sha256=digest(output)),
                  frames=len(rows),configs=list(configs),scheduling_mode=mode,stop_to_video_s=delays,
                  original_identity=original,source_frame_ids=[r[0] for r in rows],source_pts_ns=[r[1] for r in rows],
                  limitations=['Offline visual review, not live Quest playback.','Server-only measured timings exclude fixture creation, capture, network and Quest loading.',
                               'Numerical and visual consistency are not clinical accuracy.'])
    output.with_suffix('.json').write_text(json.dumps(evidence,indent=2)+'\n')
    print(json.dumps(evidence),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('root','source','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();render(args.root,args.source,args.output)
