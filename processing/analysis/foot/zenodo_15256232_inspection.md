# Zenodo 15256232 inspection

## Decision

No automatic arch/navicular ingestion or landmark extractor added. The release supplies walking images and folder-level gait-phase labels, not machine-readable anatomical coordinates, arch measurements, calibration or a documented participant split. Preserve the existing manual standing tool unchanged. These dynamic, marker-dependent images are not eligible inputs to that tool.

The smallest supported local path is to retain archive identity, exact member name, content hash, decoded image format and publisher phase folder for inspection. Do not assign patient IDs, timestamps, anatomical marker identities, millimetres or diagnostic labels from filenames or appearance. A blue-marker candidate detector would detect coloured objects, not establish navicular anatomy. No such detector was implemented.

## Source and download

- Record: https://zenodo.org/records/15256232, DOI 10.5281/zenodo.15256232.
- Title: Lateral images of the foot while walking.
- Creators: Gabriel Trujillo Hernández and colleagues, as listed in cached record metadata.
- Metadata revision 4, published 2025-04-21; license identifier `cc-by-4.0` in the record. No blanket repository license applied to the data.
- Existing `record.json` reused without a metadata request.
- Private cache: `/var/folders/bz/2xw3w2dx0qq56jtj01wqtl040000gn/T/foot-zenodo-15256232-udte8_l_`.
- Training.zip: 55,220,170 bytes; verified MD5 `63c49dc44eee5d75aed8f39b4525389b`.
- Validation.zip: 16,092,350 bytes; verified MD5 `4ab2835df3f02d3b3f1a044cc53dc35f`.

Each archive was requested once, sequentially, using its cached `/api/records/15256232/files/<name>/content` URL. Python urllib used a 60-second socket timeout, rejected redirects, checked Content-Length when supplied, bounded streamed bytes by the exact authorized size, and renamed the exclusive-created partial file only after size and MD5 verification. Both succeeded; no retry or other network request occurred.

## Exact inventory

Training.zip contains 1,053 entries: three directories and 1,050 images, totalling 60,662,320 expanded bytes.

- `Initialcontact`: 372 images.
- `Midstance`: 360 images.
- `Propulsion`: 318 images.
- Actual formats: 101 JPEG and 949 PNG. Every filename ends in `.jpg`.
- All images are 320 by 240 pixels.
- 1,041 distinct SHA-256 payload hashes; nine duplicate payload entries beyond the first occurrence.

Validation.zip contains 270 entries: three directories and 267 images, totalling 17,522,469 expanded bytes.

- `Initialcontact`: 92 images.
- `Midstance`: 95 images.
- `Propulsion`: 80 images.
- Actual formats: 267 PNG. Every filename ends in `.jpg`.
- All images are 320 by 240 pixels.
- 257 distinct SHA-256 payload hashes; ten duplicate payload entries beyond the first occurrence.

Combined: 1,323 entries, six directories, 1,317 images, 78,184,789 expanded bytes, 101 JPEG and 1,216 PNG. No text files, annotation sidecars, code, weights or calibration files. Counts match the publisher's description. No identical encoded payload hash or exact relative member path occurs across splits. This does not establish different participants or rule out nearby frames from the same recording across splits.

Exact member names, expanded sizes and compressed sizes remain in the private cache as `Training.zip.inventory.tsv` and `Validation.zip.inventory.tsv`. Format/dimension and filename-pattern inventories are in `image-inventory.json`.

## Archive and image checks

Listed central-directory entries before decoding. No bulk extraction performed. Checks rejected absolute/traversal paths, backslashes, colons, duplicate names, encryption, symlinks, special file types, executable file permissions and non-allowlisted suffixes, including nested archives. Inspection ceilings were 5,000 entries per archive, 16 MiB per member, 256 MiB expanded per archive and 100-fold member compression ratio. Both archives passed.

Read members through Python zipfile with CRC checking. Checked actual payload length and JPEG/PNG signatures, bounded image dimensions to 16 million pixels, and ran Pillow verification on every image. Only the bounded visual sample was fully decoded for review. No archive content was executed. Archive bytes and inspection images remain outside Git.

## Visual sample and annotations

Selected the first, middle and last image in archive order from each phase in each split: 18 images total. Exact sample paths are in the private cache's `sample.json`. A private contact sheet was used for inspection; no participant image is included in this repository report.

Observed colour photographic side views of bare feet against a dark background, with a white rectangular floor outline. The publisher calls these lateral foot images. The visible arch-side anatomy suggests medial-side views in the sample, but no per-image view or left/right identity annotation establishes that interpretation.

Blue circular markers appear physically attached: several show thickness or edges and change perspective with the foot. This is a visual assessment, not acquisition documentation. No coordinate dots, anatomical text, rulers or measurement readouts separate from those apparent physical markers were observed in the sample. The publisher describes first-metatarsal, navicular-tuberosity, calcaneus and proximal-interphalangeal landmarks; the release does not map individual marker pixels to those names.

Samples include heel/forefoot elevation, blur, partially cropped feet or markers, and changing contact. Phase labels are publisher folder labels, not independently verified contact events. No original videos, frame timestamps, frame-rate records or rejected-frame mapping are supplied. Do not reconstruct timing from numerical suffixes.

There are no machine-readable arch/navicular coordinates, metric labels or arch-condition classification labels. Gait-phase folder labels are supplied. Image metadata inspection found no EXIF in any image; only JFIF fields in the 101 JPEGs and no metadata keys in the PNGs. No documented physical marker diameter, floor-outline dimensions, same-plane scale, intrinsics or camera rectification was found. The floor outline and apparent marker size cannot establish millimetres.

## Participant grouping

Training names use `frameN_N.jpg`, `imagenN_N.jpg` and `imagen_N.jpg`; Validation uses `imagen_N.jpg`. Numeric sequences are not documented subject IDs. There is no participant manifest or take-to-subject mapping. Do not infer identity from skin, clothing or visual similarity, or treat the publisher's Training/Validation folders as a verified held-out-person split.

Grouping remains unknown. Absent cross-split exact duplicate bytes does not resolve leakage. No training, classifier evaluation or generalization claim is justified by this inspection.

## Verification and handoff

- Branch inspected: `codex/mohammad-ml`; HEAD `ab5bafa`, `docs: specify Quest physio demo and Codex handoff`.
- Existing `processing/` and `tests/` were untracked before this task. Their contents were preserved.
- Python 3.14.7 at `/opt/homebrew/bin/python3`; Pillow 12.3.0.
- Command: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/ml/foot -v`. All 18 existing tests passed before and after inspection. `git diff --check` passed for tracked changes; the new report is untracked and therefore outside that check.
- Download, ZIP listing, image inspection and payload-hash inventory used local `python3 - <<'PY'` shell invocations. Their results are recorded above; these were one-off inspection operations, not a new application ingestion implementation.
- The first image-inspection attempt rejected PNG bytes under a `.jpg` name. A subsequent attempt encountered Pillow's requirement to call PNG `verify()` directly after opening. Separate metadata and verification opens fixed the inspection. Neither failure caused a network retry or changed archive bytes. No unresolved image-verification failure remains.
- Changed repository file for this task: `processing/analysis/foot/zenodo_15256232_inspection.md` only. The approved `measurement.py`, `method.json` and existing tests remain unchanged.
- `docs/HANDOFF.md`, SPEC and OpenAPI were read but not edited because write ownership is limited to the two foot paths. This file records the lane handoff instead.

No device/GPU access was attempted or verified. No participant upload, training, diagnosis threshold, service integration, Quest test, physical reference comparison or latency measurement occurred. A12 and automated foot assessment remain incomplete. The OpenAPI foot-closeup contract accepts standing/seated evidence; these walking images must not be relabelled to fit it.

Inspection findings are ready for review; automated ingestion/landmark implementation is not established. The next useful evidence is a publisher-provided participant/take mapping and anatomical coordinate/calibration documentation, or a separately authorized annotation study. Neither is fabricated here. Dynamic marker-assisted evidence would still require its own method and validation rather than completing the static Quest requirement.
