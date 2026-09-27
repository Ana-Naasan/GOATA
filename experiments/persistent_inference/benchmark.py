#!/usr/bin/env python3
"""Four two-second segments: persistent worker first, then four fresh cold workers."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace

from buffered import check_output, save, split, supervise
from metrics import host_memory
from lifecycle import RESIDENCY_MODES


def launch(command, root, timeout):
    started = time.monotonic()
    supervise(command, root, timeout)
    return time.monotonic()-started


def benchmark(args):
    args.output.mkdir(parents=False)
    start = time.monotonic()
    deadline = start + args.timeout_s
    rows = []
    def execute(command):
        remaining = deadline-time.monotonic()
        if remaining <= 0:
            raise TimeoutError('benchmark deadline exceeded')
        return launch(command, args.output, remaining)
    try:
        preparation_s = execute([sys.executable, str(Path(__file__).resolve()), '--prepare',
                                 '--video', str(args.video), '--calibration', str(args.calibration),
                                 '--output', str(args.output/'inputs')])
        worker = Path(__file__).with_name('worker.py').resolve()
        # Persistent-first order is fixed and reported. Cold means fresh Python
        # process and deserialization, not a flushed OS disk/page cache.
        for mode, indices in [('persistent', [0, 1, 2, 3])] + [('cold', [i]) for i in range(4)]:
            output = args.output/(mode if mode == 'persistent' else f'cold-{indices[0]:02d}')
            wall = execute([sys.executable, str(worker), '--inputs', str(args.output/'inputs'),
                            '--output', str(output), '--indices', *map(str, indices),
                            '--launched-ns', str(time.monotonic_ns()), '--residency', args.residency])
            result = json.loads((output/'result.json').read_text())
            rows.append(dict(mode=mode, indices=indices, process_wall_s=wall, result=result))
            save(args.output/'progress.json', dict(status='running', completed=rows))
        warm, cold = rows[0], rows[1:]
        report = dict(status='complete', width=960, height=540, observation_hz=15, model_hz=30,
                      segment_count=4, requested_segment_seconds=2,
                      residency_mode=args.residency, lifecycle=RESIDENCY_MODES[args.residency],
                      all_resident_fit_proven=args.residency == 'resident' and all(
                          row['result'].get('status') == 'complete' and
                          row['result'].get('all_resident_fit_proven') is True for row in rows),
                      fit_scope='only completed worker workloads/settings/device; not general capacity',
                      shared_input_split_s=preparation_s,
                      persistent_process_wall_s=warm['process_wall_s'],
                      cold_process_wall_sum_s=sum(row['process_wall_s'] for row in cold),
                      first_persistent_segment_s=warm['result']['segments'][0]['seconds'],
                      first_persistent_output_since_launch_s=warm['result']['segments'][0]['output_since_launch_s'],
                      cold_output_since_launch_s=[row['result']['segments'][0]['output_since_launch_s'] for row in cold],
                      subsequent_persistent_segment_s=[row['seconds'] for row in warm['result']['segments'][1:]],
                      end_to_end_benchmark_s=time.monotonic()-start, runs=rows, parent_host=host_memory(),
                      exclusions=['preview', 'network', 'timeline'],
                      cold_definition='same pipeline; fresh process/model deserialization per segment; OS cache not flushed',
                      order='persistent first, then cold sequentially',
                      known_prior_sequential_peaks_bytes=dict(allocated=2811469824, reserved=2963275776),
                      prior_peak_warning='stage-sequential allocator peaks, not whole-device/all-resident/replica capacity')
        save(args.output/'benchmark.json', report)
        check_output(args.output)
    except BaseException as error:
        save(args.output/'failure.json', dict(status='failed', error_type=type(error).__name__, error=str(error),
                                              residency_mode=args.residency, fallback_applied=False,
                                              completed_runs=len(rows), seconds=time.monotonic()-start))
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video', type=Path, required=True)
    parser.add_argument('--calibration', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--timeout-s', type=int, default=1800)
    parser.add_argument('--residency', choices=RESIDENCY_MODES, default='resident',
                        help='resident keeps all five models on CUDA; cpu-offload is a separate mode, never a fallback')
    parser.add_argument('--prepare', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not 1 <= args.timeout_s <= 3600:
        parser.error('timeout must be 1..3600 seconds')
    args.video, args.calibration, args.output = args.video.resolve(), args.calibration.resolve(), args.output.resolve()
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    os.environ['PYTHONHASHSEED'] = '0'
    if args.prepare:
        args.output.mkdir()
        split(SimpleNamespace(video=args.video, calibration=args.calibration, output=args.output,
                              segments=4, segment_s=2))
        check_output(args.output)
    else:
        benchmark(args)


if __name__ == '__main__':
    main()
