#!/usr/bin/env python3
"""One serial persistent process, or one segment in a fresh cold process."""
import time
ENTRY = time.monotonic()

import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import re

from metrics import Metrics
from lifecycle import BATCH_SIZES, PRECISIONS, RESIDENCY_MODES, record_cleanup_error, validate_controls
from fast import VARIANTS


def validate_rows(rows):
    if len(rows) not in (1, 4):
        raise ValueError('worker requires one cold segment or four persistent segments')
    if len({row['take_id'] for row in rows}) != len(rows):
        raise ValueError('duplicate take identity')
    for row in rows:
        if (type(row['index']) is not int or not 0 <= row['index'] < 4 or
                row['directory'] != f"segment-{row['index']:02d}" or
                not re.fullmatch(r'segment-0[0-3]', row['directory']) or
                type(row['pts_offset_ns']) is not int):
            raise ValueError('invalid segment binding')
    if [r['index'] for r in rows] != sorted(set(r['index'] for r in rows)):
        raise ValueError('segments must be unique and ordered')


def dependency_identity(digest):
    if importlib.metadata.version('ultralytics') != '8.2.42':
        raise ValueError('requires inspected Ultralytics 8.2.42')
    import ultralytics
    root = Path(ultralytics.__file__).resolve().parent.parent
    expected = json.loads(Path(__file__).with_name('ultralytics-identity.json').read_text())
    actual = {}
    for name, value in expected['files'].items():
        actual[name] = digest(root / name)
        if actual[name] != value:
            raise ValueError('installed dependency differs from inspected snapshot: ' + name)
    return dict(source_tar_sha256=expected['source_tar_sha256'], installed_file_sha256=actual)


def run(inputs, output, indices, launched_ns, residency='resident', *,
        precision='fp32', variant='960-15', batch_size=2, vo_seed=0):
    from buffered import check_output, save, verify
    settings = validate_controls(precision, variant, batch_size, vo_seed)
    if residency not in RESIDENCY_MODES:
        raise ValueError('unknown residency mode')
    output.mkdir()
    os.environ['YOLO_OFFLINE'] = 'true'
    os.environ['YOLO_AUTOINSTALL'] = 'false'
    os.environ['YOLO_CONFIG_DIR'] = str(output/'ultralytics-config')
    metrics = Metrics(output/'metrics.jsonl')
    metrics.emit(dict(event='process_entry', residency_mode=residency, experiment=settings, entry_monotonic_s=ENTRY,
                      spawn_to_entry_s=ENTRY-launched_ns/1e9,
                      bootstrap_import_s=time.monotonic()-ENTRY))
    model_store = None
    began = time.monotonic()
    try:
        with metrics.measure('imports'):
            import torch
            from hmr4d import PROJ_ROOT
            from adapter import ASSETS, load_demo_model
            from fast import run as infer
            from models import WorkerModels, Detector
            from processing.reconstruction.runtime import digest
            # Import constructor dependencies before constructor timing starts.
            from hmr4d.utils.preproc import Tracker, Extractor, VitPoseExtractor, SimpleVO
            from hmr4d.model.gvhmr.gvhmr_pl_demo import DemoPL
            from hmr4d.utils.smplx_utils import make_smplx
        if not torch.cuda.is_available():
            raise RuntimeError('CUDA unavailable; benchmark not executed')
        with metrics.measure('cuda_context'):
            torch.cuda.init()
            torch.cuda.synchronize()
        metrics.torch = torch
        metrics.peaks.update(allocated=torch.cuda.max_memory_allocated(), reserved=torch.cuda.max_memory_reserved())
        metrics.emit(dict(event='cuda_initialized', memory=metrics.memory(),
                          peak_allocated_bytes=metrics.peaks['allocated'],
                          peak_reserved_bytes=metrics.peaks['reserved']))
        torch.manual_seed(0)
        torch.cuda.manual_seed_all(0)
        with metrics.measure('dependency_identity'):
            identity = dependency_identity(digest)
        save(output/'dependency-identity.json', identity)
        model_store = WorkerModels(metrics, PROJ_ROOT, ASSETS, digest, residency=residency, **settings)
        with metrics.measure('trusted_asset_identity'):
            assets = model_store.identities.get()
        asset_hash_calls = model_store.identities.hash_calls
        source = json.loads((inputs/'provenance.json').read_text())
        rows = source['segments']
        validate_rows(rows)
        selected = [rows[i] for i in indices]
        validate_rows(selected)
        if residency == 'resident':
            started = time.monotonic()
            model_store.preload(dict(detector=Detector, pose=VitPoseExtractor, features=Extractor,
                                     gvhmr=load_demo_model, body=lambda: make_smplx('supermotion').cuda().eval()))
            metrics.emit(dict(event='resident_ready', seconds=time.monotonic()-started,
                              models=list(model_store.store.models), experiment=settings,
                              dtype_inventories=model_store.dtype_inventories, memory=metrics.memory()))
        completed = []
        for ordinal, row in enumerate(selected):
            metrics.segment = row['index']
            folder = inputs/row['directory']
            verify(folder/'source.mp4', row['video'])
            verify(folder/'sidecar.json', row['sidecar'])
            doc = json.loads((folder/'sidecar.json').read_text())
            if doc['take_id'] != row['take_id']:
                raise ValueError('take identity differs from manifest')
            # Same seed and identical pipeline for both comparison modes.
            torch.manual_seed(0)
            torch.cuda.manual_seed_all(0)
            started = time.monotonic()
            result = infer(folder/'source.mp4', folder/'sidecar.json', output/row['directory'],
                           row['pts_offset_ns'], variant, model_store)
            if model_store.store.active is not None:
                raise RuntimeError('stage still active after segment')
            check_output(output)
            completed.append(dict(index=row['index'], take_id=row['take_id'], seconds=time.monotonic()-started,
                                  output_since_launch_s=time.monotonic()-launched_ns/1e9,
                                  first_in_process=ordinal == 0, counters=result['counters'], gpu=result['gpu'],
                                  constructors=dict(model_store.store.constructors),
                                  model_uses=dict(model_store.store.uses), after=metrics.memory()))
            metrics.emit(dict(event='segment_complete', **completed[-1]))
            del result
        expected = {'detector', 'pose', 'features', 'gvhmr', 'body'}
        if set(model_store.store.constructors) != expected or any(v != 1 for v in model_store.store.constructors.values()):
            raise RuntimeError('constructor count mismatch')
        if model_store.store.uses != dict.fromkeys(expected, len(selected)):
            raise RuntimeError('model use count mismatch')
        dtype_inventories = dict(model_store.dtype_inventories)
        closing, model_store = model_store, None
        closing.close()
        del closing
        metrics.segment = None
        report = dict(status='complete', pid=os.getpid(), residency_mode=residency,
                      experiment=settings, dtype_inventories=dtype_inventories,
                      lifecycle=RESIDENCY_MODES[residency],
                      segments=completed, total_worker_s=time.monotonic()-ENTRY,
                      work_after_bootstrap_s=time.monotonic()-began,
                      process_gpu_peaks_bytes=metrics.peaks, host=metrics.memory(),
                      trusted_asset_sha256=assets, asset_hash_calls=asset_hash_calls,
                      comparison_scope='strict inference and native export; no preview, network or timeline',
                      all_resident_fit_proven=residency == 'resident' and len(completed) == len(selected),
                      fit_scope='only this completed workload, settings and device; not replica or general capacity')
        save(output/'result.json', report)
        return report
    except BaseException as error:
        failure = metrics.failure(error)  # Snapshot before shutdown can release memory.
        if model_store is not None:
            try:
                model_store.close()
            except BaseException as cleanup:
                record_cleanup_error(error, cleanup, 'worker_close')
        failure['cleanup_errors'] = getattr(error, 'cleanup_errors', [])
        save(output/'failure.json', dict(status='failed', **failure,
                                         residency_mode=residency, experiment=settings, all_resident_fit_proven=False,
                                         fallback_applied=False,
                                         segment=metrics.segment, seconds=time.monotonic()-ENTRY,
                                         completed_segments=[r['index'] for r in locals().get('completed', [])]))
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--indices', type=int, nargs='+', required=True)
    parser.add_argument('--launched-ns', type=int, required=True)
    parser.add_argument('--residency', choices=RESIDENCY_MODES, default='resident',
                        help='resident keeps all five models on CUDA; cpu-offload never runs automatically')
    parser.add_argument('--precision', choices=PRECISIONS, default='fp32',
                        help='selective ViTPose/HMR2 neural precision only; all other stages stay FP32')
    parser.add_argument('--variant', choices=VARIANTS, default='960-15')
    parser.add_argument('--batch-size', type=int, choices=BATCH_SIZES, default=2,
                        help='pose/feature crop batch; pose flip test doubles the neural batch')
    parser.add_argument('--vo-seed', type=int, default=0,
                        help='nonnegative pycolmap options.ransac.random_seed per solver')
    args = parser.parse_args()
    if args.vo_seed < 0:
        parser.error('vo-seed must be nonnegative')
    if args.indices != [0, 1, 2, 3] and (len(args.indices) != 1 or args.indices[0] not in range(4)):
        parser.error('indices must be 0 1 2 3 or a single index in 0..3')
    run(args.inputs.resolve(), args.output.resolve(), args.indices, args.launched_ns, residency=args.residency,
        precision=args.precision, variant=args.variant, batch_size=args.batch_size, vo_seed=args.vo_seed)


if __name__ == '__main__':
    main()
