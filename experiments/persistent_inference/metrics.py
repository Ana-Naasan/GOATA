"""Synchronized CUDA measurements and Linux host RSS; JSONL survives stage failures."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import resource
import sys
import time


def host_memory():
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak *= 1 if sys.platform == 'darwin' else 1024
    current = None
    status = Path('/proc/self/status')
    if status.exists():
        for line in status.read_text().splitlines():
            if line.startswith('VmRSS:'):
                current = int(line.split()[1]) * 1024
    return {'rss_bytes': current, 'peak_rss_bytes': peak}


class Metrics:
    def __init__(self, path, torch=None):
        self.path, self.torch = Path(path), torch
        self.origin = time.monotonic()
        self.segment = None
        self.failed_stage = None
        self.events = []
        self.peaks = {'allocated': 0, 'reserved': 0}

    def memory(self):
        result = host_memory()
        if self.torch is not None:
            cuda = self.torch.cuda
            cuda.synchronize()
            free, total = cuda.mem_get_info()
            result.update(allocated_bytes=cuda.memory_allocated(), reserved_bytes=cuda.memory_reserved(),
                          device_free_bytes=free, device_total_bytes=total)
        return result

    def emit(self, value):
        row = dict(pid=os.getpid(), segment=self.segment, elapsed_s=time.monotonic()-self.origin, **value)
        self.events.append(row)
        with self.path.open('a') as stream:
            stream.write(json.dumps(row, allow_nan=False)+'\n')
        return row

    def failure(self, error):
        try:
            memory = self.memory()
        except Exception as diagnostic_error:
            memory = dict(host_memory(), diagnostic_error=str(diagnostic_error))
        return dict(error_type=type(error).__name__, error=str(error), failed_stage=self.failed_stage,
                    cleanup_errors=getattr(error, 'cleanup_errors', []),
                    cuda_oom=self.torch is not None and isinstance(error, self.torch.cuda.OutOfMemoryError),
                    memory=memory, process_gpu_peaks_bytes=dict(self.peaks))

    @contextmanager
    def measure(self, name):
        before = self.memory()
        if self.torch is not None:
            self.torch.cuda.reset_peak_memory_stats()
        start = time.monotonic()
        ok = False
        try:
            yield
            ok = True
        except BaseException:
            self.failed_stage = self.failed_stage or name
            raise
        finally:
            values = {}
            try:
                after = self.memory()
                if self.torch is not None:
                    cuda = self.torch.cuda
                    allocated, reserved = cuda.max_memory_allocated(), cuda.max_memory_reserved()
                    self.peaks['allocated'] = max(self.peaks['allocated'], allocated)
                    self.peaks['reserved'] = max(self.peaks['reserved'], reserved)
                    values.update(peak_allocated_bytes=allocated, peak_reserved_bytes=reserved,
                                  allocated_delta_bytes=after['allocated_bytes']-before['allocated_bytes'],
                                  reserved_delta_bytes=after['reserved_bytes']-before['reserved_bytes'])
            except Exception as diagnostic_error:
                if ok:
                    self.failed_stage = self.failed_stage or name
                    raise
                # Do not replace the original OOM with a failed CUDA query.
                after = dict(host_memory(), diagnostic_error=str(diagnostic_error))
            self.emit(dict(event=name, ok=ok, seconds=time.monotonic()-start, before=before, after=after, **values))
