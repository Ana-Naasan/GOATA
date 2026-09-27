"""Validate JSON-converted GVHMR parameters with explicit source selections.

Run: python3 -m processing.reconstruction.native INPUT.json
Input keys: take_id, frames, selected_indices, prediction. Prediction contains
smpl_params_global, smpl_params_incam and K_fullimg as nested JSON lists.
In a trusted inference process, convert tensors with detach().cpu().tolist();
omit net_outputs. Frames contain exactly frame_id, pts_ns and image_valid;
other capture metadata belongs in the original sidecar, not this local format.
This module never opens torch/pickle artifacts.

Source: https://github.com/zju3dv/GVHMR/tree/
ee960bb6e2ea2d381aa97f08e9b71ef320b624b1
hmr4d/model/gvhmr/gvhmr_pl_demo.py: DemoPL.predict removes the batch axis.
hmr4d/model/gvhmr/pipeline/gvhmr_pipeline.py: Pipeline.forward defines fields.
hmr4d/model/gvhmr/utils/endecoder.py: EnDecoder.decode emits axis-angle pose.
hmr4d/utils/geo/hmr_cam.py: estimate_K and convert_f_to_K construct zero-skew,
shared-focal pinhole cameras. compute_transl_full_cam uses K[0,0] for both axes;
anisotropic focal lengths and off-diagonal terms are unsupported here.
This is a local preparation format, not the service or Unity export contract.
"""

import argparse
import json
import math
import sys
from copy import deepcopy

from .timing import map_selected_frames

UPSTREAM_COMMIT = 'ee960bb6e2ea2d381aa97f08e9b71ef320b624b1'
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_FRAMES = 3600
WIDTHS = {'body_pose': 63, 'betas': 10, 'global_orient': 3, 'transl': 3}


def _keys(value, expected, name):
    if type(value) is not dict or set(value) != set(expected):
        raise ValueError(f'{name} must contain exactly {sorted(expected)}')


def _array(value, dimensions, name):
    if dimensions:
        if type(value) is not list or len(value) != dimensions[0]:
            raise ValueError(f'{name} has incorrect dimensions')
        for item in value:
            _array(item, dimensions[1:], name)
    else:
        try:
            valid = type(value) in (int, float) and math.isfinite(value)
        except OverflowError:
            valid = False
        if not valid:
            raise ValueError(f'{name} must contain finite numbers, not booleans')


def prepare(data):
    """Validate one take without changing parameters, roots or source times."""
    _keys(data, ('take_id', 'frames', 'selected_indices', 'prediction'), 'input')
    if type(data['take_id']) is not str or not 1 <= len(data['take_id']) <= 128:
        raise ValueError('take_id must be a nonempty identifier of at most 128 characters')
    for field in ('frames', 'selected_indices'):
        if type(data[field]) is not list or not 1 <= len(data[field]) <= MAX_FRAMES:
            raise ValueError(f'{field} must contain 1 to {MAX_FRAMES} entries')
    for frame in data['frames']:
        _keys(frame, ('frame_id', 'pts_ns', 'image_valid'), 'frame')
    mapping = map_selected_frames(data['frames'], data['selected_indices'])
    if any(not row['image_valid'] for row in mapping):
        raise ValueError('selected images must be valid; retain rejected images in frames')
    count = len(mapping)
    prediction = data['prediction']
    _keys(prediction, ('smpl_params_global', 'smpl_params_incam', 'K_fullimg'), 'prediction')
    for space in ('smpl_params_global', 'smpl_params_incam'):
        _keys(prediction[space], WIDTHS, space)
        for field, width in WIDTHS.items():
            _array(prediction[space][field], (count, width), f'{space}.{field}')
    _array(prediction['K_fullimg'], (count, 3, 3), 'K_fullimg')
    for matrix in prediction['K_fullimg']:
        if (matrix[0][0] <= 0 or matrix[1][1] != matrix[0][0]
                or matrix[0][1] != 0 or matrix[1][0] != 0
                or matrix[2] != [0, 0, 1]):
            raise ValueError('K_fullimg requires a positive shared focal length, '
                             'zero skew and last row [0, 0, 1]')
    return {
        'take_id': data['take_id'],
        'source_frames': deepcopy(data['frames']),
        'selected_indices': list(data['selected_indices']),
        'frame_mapping': mapping,
        'parameters': deepcopy(prediction),
        'validator_upstream_commit': UPSTREAM_COMMIT,
        'geometry_available': False,
        'limitations': [
            'Parameter validation only; no inference or geometric reconstruction performed.',
            'Caller must establish that parameter rows match the selected input images.',
            'Explicit selections are not video resampling; repeated source times remain repeated.',
            'Source image validity is not pose confidence or joint observation validity.',
            'Intrinsics provenance and physical scale are unverified.',
            'Body assets are required for geometry; no Unity coordinate conversion applied.',
        ],
    }


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError('nonfinite JSON constant')


def _finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError('nonfinite JSON number')
    return number


def load_json(path):
    """Read bounded JSON, rejecting duplicate keys and all nonfinite numbers."""
    with open(path, 'rb') as stream:
        raw = stream.read(MAX_JSON_BYTES + 1)
    if len(raw) > MAX_JSON_BYTES:
        raise ValueError('JSON exceeds 16 MiB input limit')
    try:
        return json.loads(raw, object_pairs_hook=_unique_object,
                          parse_constant=_reject_constant, parse_float=_finite_float)
    except (UnicodeError, RecursionError) as error:
        raise ValueError('invalid JSON encoding or nesting') from error


def main(argv=None):
    """Print validated preparation JSON, or fail without partial output."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', help='local JSON input, never a pickle or checkpoint')
    args = parser.parse_args(argv)
    try:
        result = prepare(load_json(args.input))
        output = json.dumps(result, allow_nan=False)
    except (OSError, ValueError, RecursionError) as error:
        print(f'Preparation failed: {error}', file=sys.stderr)
        return 1
    print(output)
    return 0


if __name__ == '__main__':
    sys.exit(main())
