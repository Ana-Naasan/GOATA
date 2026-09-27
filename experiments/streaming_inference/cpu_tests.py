#!/usr/bin/env python3
"""Run all streaming + reused-helper CPU tests without writes in readonly helper code."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parent


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--code',type=Path,default=ROOT.parent/'persistent_inference')
    parser.add_argument('--processing-root',type=Path,required=True)
    args=parser.parse_args()
    env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',STREAM_SHARED_CODE=str(args.code.resolve()),
             PYTHONPATH=os.pathsep.join((str(args.code.resolve()),str(args.processing_root.resolve()))))
    jobs=[('tests.log',['-m','unittest','discover','-s',str(ROOT),'-v'])]
    with tempfile.TemporaryDirectory(prefix='cpu-shared-',dir=ROOT) as tmp:
        for path in args.code.glob('test_*.py'): shutil.copyfile(path,Path(tmp)/path.name)
        jobs.append(('shared-tests.log',['-m','unittest','discover','-s',tmp,'-v']))
        for log,command in jobs:
            with (ROOT/log).open('w') as stream:
                result=subprocess.run([sys.executable,*command],cwd=ROOT,env=env,stdout=stream,stderr=subprocess.STDOUT)
            print(log+': '+('PASS' if result.returncode==0 else 'FAIL'))
            if result.returncode: return result.returncode
    return 0


if __name__=='__main__':sys.exit(main())
