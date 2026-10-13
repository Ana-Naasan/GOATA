# Historical inspection of Zenodo 15256232

This report describes dataset research for the former barefoot test. New tests
use Walking review. The dataset does not complete Walking review or automated
foot assessment. The manual tool requires calibrated anatomical landmarks.

## Decision

The repository has no automatic ingestion or landmark extractor for arch or navicular measurements. The release supplies walking images and folder-level gait-phase labels, not machine-readable anatomical coordinates, arch measurements, calibration or a documented participant split. The existing manual standing tool remains unchanged. These dynamic, marker-dependent images are not eligible inputs to that tool.

The smallest supported local path is to retain archive identity, exact member name, content hash, decoded image format and publisher phase folder for inspection. Do not assign patient IDs, timestamps, anatomical marker identities, millimetres or diagnostic labels from filenames or appearance. A blue-marker candidate detector would detect coloured objects, not establish navicular anatomy. No such detector was implemented.

## Source and download

- Record: https://zenodo.org/records/15256232, DOI 10.5281/zenodo.15256232.
- Title: Lateral images of the foot while walking.
- Creators: Gabriel Trujillo Hernández and colleagues, as listed in cached record metadata.
- Metadata revision 4, published 2025-04-21. The record lists license identifier `cc-by-4.0`. No blanket repository license applied to the data.
- Training.zip: 55,220,170 bytes. Verified MD5 `63c49dc44eee5d75aed8f39b4525389b`.
- Validation.zip: 16,092,350 bytes. Verified MD5 `4ab2835df3f02d3b3f1a044cc53dc35f`.

Archive size and MD5 checks passed during the historical inspection. The archives
and private inspection files are not distributed with this repository.

## Exact inventory

Training.zip contains 1,053 entries: three directories and 1,050 images, totalling 60,662,320 expanded bytes.

- `Initialcontact`: 372 images.
- `Midstance`: 360 images.
- `Propulsion`: 318 images.
- Actual formats: 101 JPEG and 949 PNG. Every filename ends in `.jpg`.
- All images are 320 by 240 pixels.
- 1,041 distinct SHA-256 payload hashes. There are nine duplicate payload entries beyond the first occurrence.

Validation.zip contains 270 entries: three directories and 267 images, totalling 17,522,469 expanded bytes.

- `Initialcontact`: 92 images.
- `Midstance`: 95 images.
- `Propulsion`: 80 images.
- Actual formats: 267 PNG. Every filename ends in `.jpg`.
- All images are 320 by 240 pixels.
- 257 distinct SHA-256 payload hashes. There are ten duplicate payload entries beyond the first occurrence.

Together, the archives contain 1,323 entries, six directories, and 1,317 images. Expanded size totals 78,184,789 bytes, with 101 JPEG and 1,216 PNG images. There are no text files, annotation sidecars, code, weights, or calibration files. Counts match the publisher's description. No identical encoded payload hash or exact relative member path occurs across splits. This does not establish different participants or rule out nearby frames from the same recording across splits.

Historical inspection files were named `Training.zip.inventory.tsv`,
`Validation.zip.inventory.tsv`, and `image-inventory.json`. They are not checked in.

## Archive and image checks

The inspection listed central-directory entries before decoding. It did not extract the archives in bulk. Checks rejected absolute paths and traversal paths, backslashes, colons, duplicate names, encryption, symlinks, special file types, executable file permissions and non-allowlisted suffixes, including nested archives. Inspection ceilings were 5,000 entries per archive, 16 MiB per member, 256 MiB expanded per archive and 100-fold member compression ratio. Both archives passed.

The inspection read members through Python zipfile with CRC checking. It checked payload lengths and JPEG and PNG signatures. Image dimensions were bounded to 16 million pixels, and Pillow verification covered every image. Only the bounded visual sample was fully decoded for review. No archive content was executed. Archive bytes and inspection images remain outside Git.

## Visual sample and annotations

Selected the first, middle and last image in archive order from each phase in each split: 18 images total. A private contact sheet supported this inspection. No participant image is included in this report.

The visual sample showed colour photographic side views of bare feet against a dark background, with a white rectangular floor outline. The publisher calls these lateral foot images. The visible arch-side anatomy suggests medial-side views in the sample, but no per-image view or left or right foot identity annotation establishes that interpretation.

Blue circular markers appear physically attached. Several show thickness or edges and change perspective with the foot. This is a visual assessment, not acquisition documentation. No coordinate dots, anatomical text, rulers or measurement readouts separate from those apparent physical markers were observed in the sample. The publisher describes first-metatarsal, navicular-tuberosity, calcaneus and proximal-interphalangeal landmarks. The release does not map individual marker pixels to those names.

Samples include heel or forefoot elevation, blur, partially cropped feet or markers, and changing contact. Phase labels are publisher folder labels, not independently verified contact events. No original videos, frame timestamps, frame-rate records or rejected-frame mapping are supplied. Do not reconstruct timing from numerical suffixes.

There are no machine-readable arch or navicular coordinates, metric labels or arch-condition classification labels. Gait-phase folder labels are supplied. Image metadata inspection found no EXIF in any image. The 101 JPEGs contained only JFIF fields, and the PNGs had no metadata keys. No documented physical marker diameter, floor-outline dimensions, same-plane scale, intrinsics or camera rectification was found. The floor outline and apparent marker size cannot establish millimetres.

## Participant grouping

Training names use `frameN_N.jpg`, `imagenN_N.jpg` and `imagen_N.jpg`. Validation uses `imagen_N.jpg`. Numeric sequences are not documented subject IDs. There is no participant manifest or take-to-subject mapping. Do not infer identity from skin, clothing or visual similarity, or treat the publisher's Training and Validation folders as a verified held-out-person split.

Grouping remains unknown. The absence of exact duplicate bytes across splits does not rule out leakage. No training, classifier evaluation or generalization claim is justified by this inspection.

## Historical verification and limitations

The inspection used Python 3.14.7 and Pillow 12.3.0. The command
`PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/ml/foot -v`
passed all 18 tests before and after inspection. Those tests cover the existing
manual method, not dataset ingestion or landmark extraction.

No training, physical reference comparison, device test, or latency measurement
formed part of the inspection. The foot-closeup contract accepts standing or
seated evidence. These walking images do not satisfy that condition. Automated
foot assessment remains unavailable. Dataset grouping, anatomical coordinates,
and calibration need publisher documentation or a separate annotation study.
Dynamic marker-assisted evidence requires its own method and validation.
