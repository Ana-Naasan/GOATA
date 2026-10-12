# Synthetic capture and replay fixture v1

This fixture contains authored geometry for importer checks. It contains no recording,
fitted human, model output, clinical finding, or measured calibration. Successful
playback verifies parsing, orientation, timing, and validity handling. It does not
verify camera capture, model accuracy, or Quest rendering. See the [project
status](../../../docs/STATUS.md) for integration evidence. From the repository root:

```sh
uv run --locked python -m processing.contracts validate tests/contracts/fixtures
uv run --locked python -m pytest tests/contracts -q
```
Regenerate the five data files deterministically (overwrites those files):

```sh
uv run --locked python -m processing.contracts generate tests/contracts/fixtures
```
The five data files are `capture_sidecar.json`, `replay_manifest.json`, and the three
binaries listed below. `generate_fixture` in
[processing/contracts.py](../../../processing/contracts.py) defines their content. The
generator does not overwrite this README.

## Import contract

The [capture sidecar schema](../../../processing/schemas/capture_sidecar.schema.json)
and [replay manifest schema](../../../processing/schemas/replay_manifest.schema.json)
define structural validation. JSON validation rejects duplicate keys, unknown
properties, and nonfinite values. `validate_sidecar(data)` and
`validate_replay(manifest, artifact_dir)` add semantic and binary checks. Both raise
`ValueError` on invalid input.

`load_json(bytes_or_str)` parses strict UTF-8 JSON. `read_json_file(path)` bounds the
read before parsing. Both enforce a 16 MiB metadata ceiling by default. The HTTP upload
manifest has a separate 1 MiB ceiling. `ContractValidator` requires integer
representations for counts, indices, and frame IDs. Send `3`, never `3.0`. The replay
has four frames, four vertices, four triangles, and three joints. Binaries contain
little-endian 32-bit scalars. Vertices and joints are frame-major, then point-major XYZ.
Triangles are index triples shared by every frame. The manifest records UUIDs, exact
byte sizes and SHA-256 hashes. Only its three fixed flat filenames are accepted.

| File | Scalars | Bytes |
|---|---:|---:|
| mesh_triangles.u32 | 12 unsigned indices | 48 |
| mesh_vertices.f32 | 48 floats | 192 |
| skeleton_joints.f32 | 36 floats | 144 |
Counts, sizes, checksums, finite coordinates, parent cycles and index bounds are checked
before use. The 256 MiB decoded input ceiling sums binary sizes, decoded numeric arrays
and masks, and serialized metadata. This is an input bound rather than measured runtime
memory. Never allocate from unchecked counts. Validity uses JSON booleans. `frame_valid`
has one entry per frame. `joint_valid` has one row per frame and one boolean per joint.
Entire invalid frames have no valid joints. Zero-filled invalid slots are placeholders
and must not be rendered or measured as observations. `joint_parents` uses `-1` for
exactly one root. Region names here are synthetic, not anatomical mappings.

## Expected orientation and movement

Coordinates are Unity left-handed: +X right, +Y up, +Z forward. Units are authored
metres with `scale_status: estimated`. No physical size was measured. The
source-to-replay matrix is a row-major affine 4×4 matrix multiplying a column vector
`[x,y,z,1]`. Translation occupies indices 3, 7 and 11. It is identity here. Binary
coordinates are already converted. An importer must not apply the source transform
again. At frame 0 the asymmetric tetrahedron has:

- Left tip `(-0.25, 0, 0)` and longer right tip `(0.5, 0, 0)`.
- High tip `(0, 0.7, 0)` and forward apex `(0, 0.1, 0.4)`.
- Root joint `(0, 0, 0)`, high-tip joint `(0, 0.7, 0)` and right-tip joint `(0.5, 0, 0)`. The parents are `[-1, 0, 0]`.
- Outward winding: the base triangle `0,2,1` is clockwise when viewed from negative Z toward the origin. Check this with backface culling enabled.

| Replay index | Original frame ID | Original PTS (ns) | Time (s) | Root XYZ | Validity |
|---:|---:|---:|---:|---|---|
| 0 | 100 | 1000000000 | 0.00 | (0, 0, 0) | All valid |
| 1 | 101 | 1040000000 | 0.04 | (0.1, 0, 0.05) | Right-tip joint invalid |
| 2 | 103 | 1110000000 | 0.11 | Invalid zero placeholder | Entire frame invalid |
| 3 | 107 | 1200000000 | 0.20 | (0.3, 0, 0.15) | All valid |
Time is seconds from the first original source PTS, including when initial samples are
rejected. Original IDs remain distinct from replay indices. The fixture uses irregular
timing rather than a nominal frame rate. The missing interval is `[0.08, 0.15]` seconds,
including both boundaries. Gaps are ordered and disjoint. A sidecar image or replay
frame inside a gap must be invalid. Frame step exposes frame 103 as unavailable. Forward
and reverse playback preserve the asymmetric orientation and shared body and skeleton
root motion. Interpolation across a gap would invent measured motion.

`resampling_map` demonstrates seven inference sample IDs referring to four original
samples, with repeated original IDs permitted. Replay samples themselves retain unique
original IDs. The map does not imply the replay has seven frames. This is an
illustrative nearest-source mapping, not evidence that actual model resampling works.
The sidecar retains the same original IDs and PTS and labels its adapter synthetic.
Calibration is unavailable, so intrinsics are omitted. Camera-pose fields are optional.
When present, document their coordinate frame and synchronization method and supply a
normalized XYZW quaternion. Intrinsics describe stored image pixels, and any resizing or
cropping belongs in `camera.calibration_note`. Capture gap entries use original PTS
strings.
