# Synthetic capture/replay fixture v1

This is authored geometry for importer checks. It contains no recording, fitted human, model output, clinical finding or measured calibration. Successful playback verifies mechanics only; real capture/model/Quest integration remains unfinished.

From the repository root:

```sh
.venv/bin/python -m processing.contracts validate tests/contracts/fixtures
.venv/bin/python -m pytest tests/contracts -q
```

Regenerate the five data files deterministically (overwrites those files):

```sh
.venv/bin/python -m processing.contracts generate tests/contracts/fixtures
```

## Import contract

Use `processing/schemas/capture_sidecar.schema.json` and `processing/schemas/replay_manifest.schema.json` for structural validation. JSON rejects duplicate keys, unknown properties and nonfinite values. Python's `validate_sidecar(data)` and `validate_replay(manifest, artifact_dir)` add semantic and binary checks and raise `ValueError` on invalid input. `load_json(bytes_or_str)` performs strict UTF-8 JSON parsing; `read_json_file(path)` bounds reading before parsing. Both enforce a 16 MiB metadata ceiling by default; the HTTP upload manifest separately uses its 1 MiB ceiling. `ContractValidator` extends JSON Schema with strict integer representation: send `3`, never `3.0`, for counts, indices and frame IDs.

The replay has four frames, four vertices, four triangles, and three joints. Binaries contain little-endian 32-bit scalars. Vertices and joints are frame-major, then point-major XYZ. Triangles are index triples shared by every frame. The manifest records UUIDs, exact byte sizes and SHA-256 hashes. Only its three fixed flat filenames are accepted.

| File | Scalars | Bytes |
|---|---:|---:|
| mesh_triangles.u32 | 12 unsigned indices | 48 |
| mesh_vertices.f32 | 48 floats | 192 |
| skeleton_joints.f32 | 36 floats | 144 |

Counts, sizes, checksums, finite coordinates, parent cycles and index bounds are checked before use. The 256 MiB decoded input ceiling sums binary sizes, decoded numeric arrays/masks, and serialized metadata; this is an input bound rather than measured runtime memory. Never allocate from unchecked counts.

Validity uses JSON booleans. `frame_valid` has one entry per frame; `joint_valid` has one row per frame and one boolean per joint. Entire invalid frames have no valid joints. Zero-filled invalid slots are placeholders and must not be rendered or measured as observations. `joint_parents` uses `-1` for exactly one root. Region names here are synthetic, not anatomical mappings.

## Expected orientation and movement

Coordinates are Unity left-handed: +X right, +Y up, +Z forward; units are authored metres with `scale_status: estimated`. No physical size was measured. The source-to-replay matrix is a row-major affine 4×4 matrix multiplying a column vector `[x,y,z,1]`; translation occupies indices 3, 7 and 11. It is identity here. Binary coordinates are already converted; an importer must not apply the source transform again.

At frame 0 the asymmetric tetrahedron has:

- Left tip `(-0.25, 0, 0)` and longer right tip `(0.5, 0, 0)`.
- High tip `(0, 0.7, 0)` and forward apex `(0, 0.1, 0.4)`.
- Root joint `(0, 0, 0)`, high-tip joint `(0, 0.7, 0)` and right-tip joint `(0.5, 0, 0)`; parents `[-1, 0, 0]`.
- Outward winding: the base triangle `0,2,1` is clockwise when viewed from negative Z toward the origin. Check this with backface culling enabled.

| Replay index | Original frame ID | Original PTS (ns) | Time (s) | Root XYZ | Validity |
|---:|---:|---:|---:|---|---|
| 0 | 100 | 1000000000 | 0.00 | (0, 0, 0) | All valid |
| 1 | 101 | 1040000000 | 0.04 | (0.1, 0, 0.05) | Right-tip joint invalid |
| 2 | 103 | 1110000000 | 0.11 | Invalid zero placeholder | Entire frame invalid |
| 3 | 107 | 1200000000 | 0.20 | (0.3, 0, 0.15) | All valid |

Time remains seconds from the first original source PTS, including when initial samples are rejected. Do not replace original IDs with replay indices or assume nominal frame rate. The explicit missing interval is `[0.08, 0.15]` seconds; do not interpolate across it as measured motion. All gaps include both boundaries and must be ordered and disjoint; a sidecar image or replay frame inside a gap must be invalid. Frame-step should expose frame 103 as unavailable. Playing/reversing should preserve asymmetric orientation and common body/skeleton root motion.

`resampling_map` demonstrates seven inference sample IDs referring to four original samples, with repeated original IDs permitted. Replay samples themselves retain unique original IDs; the map does not imply the replay has seven frames. This is an illustrative nearest-source mapping, not evidence that actual model resampling works.

The sidecar retains the same original IDs/PTS and labels its adapter synthetic. Calibration is unavailable, so intrinsics are omitted. Camera-pose fields are optional; when present, document their coordinate frame and synchronization method and supply a normalized XYZW quaternion. Intrinsics describe stored image pixels, and any resizing/cropping belongs in `camera.calibration_note`. Capture gap entries use original PTS strings.
