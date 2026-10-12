# GVHMR local inference on Arch Linux and RTX 3070

This guide describes the local reconstruction command. GPU measurements below
are historical records, not a report of current host access. See
[project status](../../docs/STATUS.md) for integration and device validation.

## Status and supported input

The CLI prepares an original MP4, runs person tracking, ViTPose, HMR2 features, moving-camera rotation estimation and GVHMR, then evaluates native SMPL-X vertices and 22 body joints from the same fitted parameters. It retains global root translation. The CLI produces the native handoff. The service now invokes it through `processing/pipeline.py`. `processing/export.py` converts the native geometry for Unity and the microscope runs separately on original footage. Automated exercise and foot assessment remain incomplete.

Supported first-pass inputs:

- One consenting participant, exactly one continuous tracked identity, one video stream.
- SPEC sidecar `schema_version: "1.0"`, original source frame IDs and nanosecond PTS strings. UUID take ID. No filenames are read from the sidecar.
- Upright, unmirrored pinhole image: `rotation_degrees: 0`, `mirrored: false`, camera `distortion_model: "none"` and `distortion_coefficients: []`. Unknown distortion is rejected by default. The explicit approximation below is the only opt-in exception. No implicit crop, resize, rectification or camera-pose conversion.
- Even dimensions of at least 32 pixels, at most 2,073,600 pixels. Original MP4 at most 512 MiB and 3,600 decoded source frames. Prepared inference at most 600 frames, about 20 seconds. These are conservative initial bounds, not measured RTX 3070 capacity.
- No invalid source images, explicit `capture.gaps`, interruptions or source intervals longer than 100 ms. Such takes fail rather than concealing gaps. Supply a separately identified contiguous capture, not a silently concatenated edit. Gap-containing replay is not implemented.
- Calibrated or explicitly estimated intrinsics require positive equal `fx` and `fy`. Off-centre `cx` and `cy` are allowed. The inspected GVHMR translation code uses `fx` for both axes. Genuine unequal focal lengths require a separately verified adapter that rectifies or resizes images with updated calibration. They are not invalid cameras, just unsupported here.

When calibration is unavailable, `--allow-estimated-intrinsics` explicitly permits the upstream diagonal-length focal estimate and image-centre principal point. Output remains labelled estimated. Physical scale is always model-estimated even with calibrated intrinsics.

`--allow-unverified-pinhole` permits `distortion_model: "unknown"` only with an
empty coefficient array. It records an unverified pinhole assumption in selection
and processing provenance and labels processing intrinsics estimated. The source
sidecar remains unchanged. Quest's SDK currently exposes intrinsics but no lens
distortion model or coefficients. An empty array is not proof of rectification.
This flag does not validate lens geometry, physical measurements or output
alignment. The corresponding service setting defaults false.

## Arch host setup

Use a Linux amd64 host with a compatible NVIDIA driver and configured NVIDIA Docker runtime. Check access on the target host. The historical worker configuration does not establish current access or authorize installation.

For a new or unconfigured host only, follow the current [Arch NVIDIA](https://wiki.archlinux.org/title/NVIDIA), [Docker](https://wiki.archlinux.org/title/Docker) and [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) instructions for the installed kernel. Do a full supported system upgrade when installing packages. Never run a partial Arch upgrade such as refreshing package databases then installing only selected packages against an old system.

Install the kernel-appropriate NVIDIA driver, Docker and NVIDIA Container Toolkit from the current supported Arch package sources. This document does not choose a driver package without knowing the kernel. Reboot after a driver or kernel change where required. The container supplies CUDA 12.1 userspace. The host needs a compatible NVIDIA driver, not a separate host CUDA toolkit.

Record the actual host before building:

```sh
uname -a
nvidia-smi
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv
pacman -Q docker nvidia-container-toolkit
docker version
```

Only on a host whose NVIDIA runtime is not configured, an authorized operator can configure it and restart Docker. Skip these commands when the runtime is already configured:

```sh
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

Docker daemon access grants substantial host privileges. Use an authorized local operator. No privileged container, Docker socket mount, participant upload or paid GPU is needed. If any network operation fails, stop and report it rather than retrying or switching download endpoints.

## Build context and dependency record

From the project root:

```sh
docker build --progress=plain --platform linux/amd64 \
  -t physio-gvhmr:ee960bb \
  processing/reconstruction
```

The local build context allowlists only the Dockerfile, dependency supplement and ignore file. Recordings, source code, credentials and checkpoints cannot enter it. The image fetches the public upstream source at exactly `ee960bb6e2ea2d381aa97f08e9b71ef320b624b1`, not its moving main branch. It does not fetch submodules, pretrained checkpoints, body models or datasets. Public upstream source includes its own model-support tensors and notices.

The base is upstream-compatible in intent, `pytorch/pytorch:2.3.0-cuda12.1-cudnn8-runtime`, Linux amd64. Upstream specifies Python 3.10, torch 2.3.0+cu121, torchvision 0.18.0+cu121, NumPy 1.23.5, PyTorch3D 0.7.6 and PyAV 13.0.0. The image installs the pinned source's `requirements.txt`, adds HMR2's missing `yacs` dependency and constrains OpenCV to a NumPy-1-compatible version. It records resolved packages in `/opt/runtime-freeze.txt` and runs `pip check`.

Upstream leaves several dependencies unpinned and the base tag is not digest-pinned. The historical worker build succeeded. Its image ID is recorded below. Preserve `/opt/runtime-freeze.txt` with the run record before changing dependencies or rebuilding. Build compatibility does not establish model compatibility. Network retries are disabled for apt and pip.

## Externally mounted assets and terms

The operator must obtain and approve assets separately. Never point this directory at participant-supplied files. Upstream checkpoint loaders use trusted Python serialization and body-model packages may do so internally. This is not a sandbox for arbitrary pickle or checkpoint uploads.

Expected local asset directory, mounted at `/opt/GVHMR/inputs/checkpoints`:

```text
checkpoints/
  body_models/smplx/SMPLX_NEUTRAL.npz
  gvhmr/gvhmr_siga24_release.ckpt
  hmr2/epoch=10-step=25000.ckpt
  vitpose/vitpose-h-multi-coco.pth
  yolo/yolov8x.pt
```

The upstream stock renderer also requests `body_models/smpl/SMPL_NEUTRAL.pkl`. This adapter exports native SMPL-X topology instead, so it does not need that extra SMPL asset. If a later exporter uses SMPL conversion, obtain it through registration and mount it externally. Do not bundle it.

Access and rights:

- [GVHMR install instructions at the pinned revision](https://github.com/zju3dv/GVHMR/blob/ee960bb6e2ea2d381aa97f08e9b71ef320b624b1/docs/INSTALL.md) link the operator-download checkpoint folder.
- [GVHMR checkpoint access](https://drive.google.com/drive/folders/1eebJ13FUEXrKBawHpJroW0sNSxLjh9xD?usp=drive_link). Inspect each model's terms before downloading or using it.
- Registered [SMPL-X](https://smpl-x.is.tue.mpg.de/) and [SMPL](https://smpl.is.tue.mpg.de/) have separate access and model/output terms.
- The inspected GVHMR `LICENSE` permits educational, research and non-profit purposes, requires notices and open-source non-commercial modifications, and directs commercial enquiries to its authors. HMR2, ViTPose, YOLO and their training/model assets have separate terms. The project does not grant blanket redistribution or commercial rights.

The runtime checks required local files and hashes them into the handoff. Its container has no network, so missing weights cannot trigger successful implicit downloads. No preview assets or model outputs are loaded back through `torch.load` by this adapter.

## Smoke checks

Set absolute paths to the project root, operator-approved assets and input folder. Keep inputs immutable for the run. Mount only the needed directories, never the Docker socket. If local Docker policy requires elevated access, use the host's approved invocation, including under `timeout`.

```sh
PROJECT="$PWD"
ASSETS=/absolute/path/to/checkpoints
INPUT=/absolute/path/to/consented-input
OUTPUT=/absolute/path/to/new-output-parent
mkdir -p "$OUTPUT"

docker run --rm --gpus all --network none --read-only \
  --cap-drop ALL --security-opt no-new-privileges \
  --user "$(id -u):$(id -g)" \
  --tmpfs /tmp:rw,nosuid,nodev,size=2g \
  --mount "type=bind,src=$PROJECT/processing,dst=/app/processing,readonly" \
  --entrypoint python physio-gvhmr:ee960bb \
  -c 'import sys,torch,av,pycolmap; import hmr4d.utils.preproc; print(sys.version); print(torch.__version__); print(torch.cuda.is_available()); print(torch.cuda.get_device_properties(0))'
```

This checks imports and GPU exposure only, not inference. Inspect `/opt/runtime-freeze.txt` using a separate `--entrypoint /bin/cat` invocation, and save it beside the run record. Do not treat an import smoke test as a timing or reconstruction result.

Run the CPU and real-codec tests inside the image before trying a participant recording:

```sh
docker run --rm --network none --read-only \
  --cap-drop ALL --security-opt no-new-privileges \
  --user "$(id -u):$(id -g)" --tmpfs /tmp:rw,nosuid,nodev,size=2g \
  --mount "type=bind,src=$PROJECT/processing,dst=/app/processing,readonly" \
  --mount "type=bind,src=$PROJECT/tests/ml,dst=/tests,readonly" \
  --entrypoint python physio-gvhmr:ee960bb \
  -m unittest discover -s /tests -v
```

## PTS binding and run

The capture adapter must document the relation between its source clock and MP4
stream clock. The current sidecar supports an explicit `media` object with
`binding: "indexed_presentation_time_us"` and `presentation_time_us`: one canonical
nonnegative decimal string per source frame. The Quest encoder checks association
with submitted images, then records the final mux timestamps. Original source
`pts_ns` values remain unchanged.

With `media`, `--pts-offset-ns 0` is required. Every decoded timestamp, converted
to integer microseconds by truncation to match Android MediaExtractor, must match
the corresponding entry. Missing, extra, repeated, changed and reordered frames
are rejected. Mapping count alone is never sufficient. This path supports mux
quantization without pretending both clocks are identical.

Legacy sidecars without `media` use exact rounded decoder nanoseconds plus the
mandatory operator-supplied signed `--pts-offset-ns`. Use zero only if that legacy
clock relation has been verified. Do not infer the offset from frame count or
nominal FPS. The service requires the explicit mapping; legacy CLI support does
not make an old sidecar valid for production upload.

Example only, replace filenames. Zero below is for a verified explicit media mapping; use a measured offset for the legacy CLI path:

```sh
PTS_OFFSET_NS=0

timeout --signal=TERM --kill-after=30s 15m \
  docker run --rm --gpus all --network none --read-only \
  --cap-drop ALL --security-opt no-new-privileges \
  --user "$(id -u):$(id -g)" --memory 16g --cpus 8 --pids-limit 256 \
  --tmpfs /tmp:rw,nosuid,nodev,size=2g \
  --mount "type=bind,src=$PROJECT/processing,dst=/app/processing,readonly" \
  --mount "type=bind,src=$ASSETS,dst=/opt/GVHMR/inputs/checkpoints,readonly" \
  --mount "type=bind,src=$INPUT,dst=/input,readonly" \
  --mount "type=bind,src=$OUTPUT,dst=/output" \
  physio-gvhmr:ee960bb \
  --video /input/take.mp4 --sidecar /input/take.json \
  --pts-offset-ns "$PTS_OFFSET_NS" --output /output/run-001
```

Choose a host memory cap it can support. This command is an example, not a measured resource recommendation. Add `--allow-estimated-intrinsics` only after accepting that limitation. Prepared MP4 contains selected source images at 30 Hz. Original media is never overwritten. `selection.json` retains all source frames, selected positions, original IDs, exact PTS strings, time offsets, target times and selection errors. Repeated selections remain explicit.

A new output directory is required. Failure leaves diagnostic preparation files but no `handoff.json`. Never ingest a directory without that final completion marker. Retry into a new directory, not an existing cache. Monitor disk use and remove failed private outputs under the operator's retention policy. The command bounds container memory/processes and wall time; the parent service must also bound concurrency, output-directory quotas and job lifetime.

## Native geometry contract

`handoff.json`, local schema `gvhmr-native-1`, is not the HTTP result or Unity replay manifest. It inventories byte sizes and SHA-256 hashes for these artifacts:

- `parameters.json`: global and in-camera SMPL-X parameters and per-frame K, validated by the existing native validator. Axis-angle body pose, root orientation, betas and translation are unchanged.
- `vertices.f32`, `joints.f32`: little-endian float32, frame-major then vertex/joint-major XYZ. Both come from the same `make_smplx("supermotion")` forward call on global fitted parameters. Root motion is retained. No preview-facing transform or framewise centering is applied.
- `triangles.u32`: fixed native SMPL-X triangle triples, little-endian uint32. Counts are declared in `geometry`.
- `fitted_valid.u8`: frame-major 22-joint mask. A one means a finite fitted estimate, not direct observation or calibrated confidence. Missing image/track evidence rejects this version of the workflow. Unfitted fingers, face and expression remain model defaults, not foot/face measurements.
- `observations.json`: tracked boxes, COCO17 image coordinates/raw pose scores, estimated camera rotations and the VO sampling indices. COCO17 observations are not the 22 SMPL-X joints.
- `selection.json` and `source-sidecar.json`: source provenance and preserved capture metadata.

Native coordinates are the upstream right-handed, gravity-aligned global `ay` frame with +Y up. Horizontal orientation is a model gauge, not a verified Quest world transform or measured facing direction. Units are model metres with estimated physical scale. Joint names come from SMPL-X `JOINT_NAMES[:22]`, parents from the mounted body's kinematic tree. Hand/face joints are not exported as supported body joints. Artifact hashes and body-asset hash identify the actual topology. The integration exporter reflects Z for both vertices and joints and reverses winding, with automated fixture checks. Real asymmetric-motion visual validation remains pending.

`processing/export.py` implements the final service replay contract, bounds and
patient and session association. Native rows are inference rows. The exporter selects
the first fitted row for each source frame, keeps the full inference mapping as
provenance, and preserves original source times/root movement. It never substitutes
inference index divided by 30 for observed timing. The C# importer accepts the
original public run's 242-frame geometry, but the original legacy sidecar still
fails the strict upload schema; that geometry check is not a successful current
service or Quest run.

The handoff records asset and adapter-source hashes, resolved key dependency versions, measured device memory, peak torch allocated/reserved memory and local stage durations. Local elapsed time includes preparation, asset checks, inference and export up to final manifest serialization. It does not measure capture completion, upload, service wait, download or Quest loading. The agreed 1 to 2 minute whole-path target remains untested.

## Camera motion and source evidence

The adapter follows the pinned upstream revision. Relevant upstream files:

- `docs/INSTALL.md`, `requirements.txt`, `setup.py`, `LICENSE`: runtime, asset paths and terms.
- `tools/demo/demo.py`: stock 30 FPS copy, preprocessing, `DemoPL.predict`, global and in-camera output and optional render paths.
- `hmr4d/utils/preproc/tracker.py`: stock identity selection and missing-box interpolation. This adapter uses raw `Tracker.track` and rejects missing or ambiguous tracks instead.
- `hmr4d/utils/preproc/vitpose.py`, `vitfeat_extractor.py`: crop and feature extraction and upstream batch size 16. This adapter supplies two crops per call to lower peak memory. The final smoke below demonstrates 3070 fit for that 242-frame input only.
- `hmr4d/utils/preproc/relpose/simple_vo.py`, `solver_two_view.py`: SIFT, pycolmap two-view solve, accumulated world-to-camera rotations and interpolation. This adapter passes the same K used for GVHMR, scaled for the half-size VO images. It never defaults to a static camera or uses SimpleVO's unrelated 24 mm estimate.
- `hmr4d/utils/preproc/slam.py` and upstream install instructions: DPVO requires its git submodule, Eigen 3.4, torch-scatter, numba, pypose, a CUDA development toolchain and `dpvo.pth`. It is optional and not installed here. No `--use-dpvo` promise is made. Use the inspected upstream default SimpleVO path first. Quest camera-pose fusion is not implemented.
- `hmr4d/model/gvhmr/gvhmr_pl_demo.py`, `pipeline/gvhmr_pipeline.py`, `utils/geo/hmr_global.py`: prediction fields, translation integration and `any->ay` conversion.
- `hmr4d/utils/smplx_utils.py`, `body_model/body_model_smplx.py`: neutral SMPL-X construction, batch forward, retained translation and default unpredicted face and hand fields.

SIFT and visual odometry may fail on textureless scenes, insufficient parallax, independently moving backgrounds or repeated frames. Failures do not fall back to identity rotations or static camera motion. The algorithm's interpolated camera rotations are estimates, not measured headset tracking. Record real-footage failures before choosing DPVO or a tracked-pose adapter.

## Check the adapter

Run dependency-managed checks from the project root. ML discovery imports project
dependencies such as `jsonschema`. It is not dependency-free.

```sh
uv sync --locked --group dev
uv run --locked python -m unittest discover -s tests/ml -v
uv run --locked python -m processing.reconstruction.runtime --help
```

Real codec checks require PyAV, available in the GPU image. Mocked control-flow
tests do not prove inference, visual alignment, or clinical accuracy.

## Historical GPU evidence

### Worker environment, September 26, 2026

The recorded worker used Arch Linux kernel `7.2.6-arch2-1`, NVIDIA RTX 3070
with 8192 MiB physical memory, driver `615.71.09`, Docker `29.8.1`, and NVIDIA
Container Toolkit `1.20.0`. The successful image build had ID
`sha256:66db73a15b803aa99aa47f8929ec2acd7e5d30ee84332dad8c1b62e254beeddc`.
The container used Python `3.10.14`, torch `2.3.0+cu121`, PyAV `13.0.0`,
and pycolmap `4.2.0`. These versions describe that build only.

The public upstream tennis demo failed strict tracking because it contained
multiple people. The `LittleFrog/GVHMR` example `examples/cxk.mp4` failed
camera-motion estimation because pycolmap returned no relative pose. The adapter
reports that failure without a static-camera fallback or completion manifest.
A demo-model registration fix preceded the successful run below.

### Final public WHAM smoke evidence, 2026-09-26

The recorded run used the image identified above with updated source mounted
read-only, network disabled, nonroot execution, and external model assets.
The reconstruction container exited with code 0. Historical records included
`handoff.json`, `provenance.json`, `tests-container.log`, `runtime-freeze.txt`,
and `run-001.log`. Those private run files are not included in this repository.

The public examples archive came from WHAM's official [fetch_demo_data.sh](https://github.com/yohanshin/WHAM/blob/main/fetch_demo_data.sh), documented Drive ID `1KjfODCcOUm_xIMLLR54IcjJtf816Dkc7`. The recorded archive download was 88.2 MB. Extraction included only `examples/drone_video.mp4` and `examples/drone_calib.txt`. Archive SHA-256 is `8c23111f1ef92eec644da02406704d4ec6e13281046676d699a93e7b7ffb4fee`. This is a public smoke fixture, not participant evaluation data or evidence of redistribution rights.

The original 22.12-second, 664-frame video was retained unchanged, SHA-256 `0da55210a305c3c75caa732c46b7330bb3d4e39ebeb9bc3af1e2b100dd8990c1`. The explicitly identified derivative used video stream-copy of approximately the first eight seconds, with no crop, resize or explicit frame-rate conversion. It has 242 decoded frames at 1920 by 1080 pixels, with last decoded PTS 8.041366667 seconds. Derivative SHA-256 is `c010567f80e5813c2d1e2811510062dcf9de5a9190a7084c3e253b75ed11b895`.

The synthetic sidecar uses decoder PTS with offset zero. It does not verify a Quest capture clock. Provided intrinsics from `drone_calib.txt` use focal lengths 1321 pixels on both axes and principal point 960, 540 pixels, marked estimated because calibration accuracy was not independently verified. Upright, unmirrored pinhole imagery and no distortion were assumed only for this smoke. Actual lens distortion is unknown. Capture labels are fixture placeholders, not measured annotations. Sidecar SHA-256 is `a078ed72ab70c6deef9bfc5c4e523ca7e58bedbde4a9c0ae569ec9430fff1aa3`.

Tracking, ViTPose, HMR2 features, moving-camera estimation with SIFT and pycolmap, real GVHMR prediction and native geometry export all completed. The manifest records 242 fitted frames, 10,475 vertices, 20,908 triangles and 22 joints, with finite fitted estimates and retained root translation. The recorded verification checked byte sizes and SHA-256 for all eight inventoried artifacts. Neither finite arrays nor matching hashes establish visual alignment or anatomical correctness.

Manifest durations, rounded to milliseconds:

- Preparation: 6.765 seconds.
- Tracking: 9.774 seconds.
- ViTPose: 16.597 seconds.
- HMR2 features: 10.984 seconds.
- Camera motion: 6.484 seconds.
- GVHMR: 1.608 seconds.
- Geometry: 0.662 seconds.
- CLI local elapsed: 58.623 seconds, including preparation, asset checks, inference and export up to final manifest serialization. Stage timers are not an exhaustive elapsed-time breakdown.

The 58.623-second result is not final-capture-to-loaded-replay latency. It excludes capture completion, upload, service wait, download and Quest loading. The whole-path target remains unmeasured.

The manifest reports torch-visible device memory of 8,268,611,584 bytes, peak torch allocation of 2,811,469,824 bytes and peak torch reservation of 2,963,275,776 bytes. Allocation and reservation are torch allocator measurements, not entire-device peak VRAM or peak host RAM. Success establishes resource fit only for this derivative and configuration, not the full original or the configured maximum input.

The freeze and manifest confirm torch `2.3.0+cu121`, torchvision `0.18.0+cu121`, PyAV `13.0.0`, NumPy `1.23.5`, SMPL-X `0.1.28`, pycolmap `4.2.0` and ultralytics `8.2.42`. The freeze also records OpenCV `4.10.0.84`, PyTorch3D `0.7.6` and yacs `0.1.8`. Upstream revision remains `ee960bb6e2ea2d381aa97f08e9b71ef320b624b1`. The manifest records all five asset hashes and four adapter-source hashes. The executed `gvhmr.py` hash is `1c1c8d547d4a9b5e3e38e5c761f006018411e53bbc8fa634ced54a6dcf44533a`.

Recorded verification outcomes:

- `python -m unittest discover -s /tests -v`: 36 reconstruction tests passed in 0.388 seconds, zero skips, including both real PyAV tests. This is a historical test result.
- Full inference completed and published `handoff.json`. The successful WHAM run does not establish that the rejected tennis or `cxk.mp4` inputs pass.

### Current integration and remaining proof

The historical sidecar contains legacy `smoke_test_provenance` and lacks
required `capture.gaps`, so production validation rejects it. Preserve its inputs
and hashes. A current service run requires a separate valid capture sidecar with
explicit media mapping. The historical geometry alone does not prove that path.

The production pipeline launches a fresh local reconstruction command per take.
The persistent and streaming experiments below do not install a resident service.
Native scale remains estimated. registration between Quest and model coordinates, anatomical alignment,
clinical assessment, held-out-person evaluation, and capture-to-loaded-replay
latency require separate evidence. See [project status](../../docs/STATUS.md).

## Persistent FP32 experiment, September 27, 2026

`experiments/persistent_inference/` contains the GPU-tested optimization runner.
It is separate from the production service, which still starts a fresh inference
process. This publication does not enable Quest streaming or change that service.
The fixture runner accepts the public WHAM drone and its supplied calibration,
not arbitrary uploaded recordings. It splits the first eight seconds into four
independent takes. Tracker and temporal state reset between those takes. Do not
concatenate their reconstructions as a validated continuous movement.

The runner retains YOLO, ViTPose, HMR2 features, GVHMR and SMPL-X on CUDA. Each is
constructed once and reused for all four takes. Detector prediction and tracking state
is fresh per take. Checkpoint identity hashing occurs once per process. Images
are resized to 960 by 540. Expensive observations are computed at 15 Hz and held
on the 30 Hz model grid. Camera motion uses the full 30 Hz mapping. Omitted images
are not identity-verified. Pose and feature batches remain two, with FP32 weights.
CPU offload is an explicit separate mode, never an automatic OOM fallback.

Historical measurements are in `rtx3070-fp32.json`. On the RTX 3070:

- Subsequent two-second segments took 4.900, 5.008 and 5.108 seconds, including
  local preparation and native export. No preview, network or Quest loading.
- The persistent four-segment process took 36.252 seconds including initialization.
  Four matching fresh processes took 84.948 seconds in total.
- First output after process launch took 20.346 seconds. Preloading must finish
  before a request to avoid this startup delay.
- Peak PyTorch allocation was 6,190,825,984 bytes. Peak reservation was
  6,423,576,576 bytes, about 5.98 GiB. These are not whole-device memory readings.
- The shared fixture split took 4.478 seconds, outside those process times.

The original run used shared reconstruction helpers from `20cf164`. Its source
inventory and GPU measurements identify that historical run, not a fresh execution.
All eight native artifact hashes were checked for each of the eight outputs.
Camera-motion estimates differed between persistent and fresh-process runs.
Full 3D numerical equivalence and accuracy remain unproven. The historical
`all_resident_fit_proven` field is hardcoded false. Completed-segment counts,
constructor and use counts and allocator measurements are the actual fit evidence.
That initial publication did not include FP16, larger batches or streaming.
The later bounded experiment below adds those controls without changing the
production service.

CPU checks from the repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" \
  python3 -m unittest discover -s experiments/persistent_inference -v
```

Pinned Ultralytics source-body checks require installed version 8.2.42. Without
it those checks explicitly skip. An operator may instead set
`PHYSIO_ULTRALYTICS_SOURCE` to an inspected 8.2.42 `ultralytics` package directory.
File hashes are checked against the committed identity inventory before execution.
The remaining tests use CPU stand-ins and do not prove GPU correctness.

Run in the existing model image with the same approved assets. Set `PROJECT`,
`ASSETS`, `INPUT` and `OUTPUT` to absolute paths as above. `INPUT` must contain
`drone_video.mp4` and `drone_calib.txt`. Obtain them under their own terms, never
commit them. The new `resident-001` directory must not already exist.

```sh
docker run --rm --gpus all --network none --read-only \
  --cap-drop ALL --security-opt no-new-privileges \
  --user "$(id -u):$(id -g)" --memory 24g --cpus 8 --pids-limit 256 \
  --tmpfs /tmp:rw,nosuid,nodev,size=2g \
  --env PYTHONPATH=/experiment:/app:/opt/GVHMR \
  --env PYTHONDONTWRITEBYTECODE=1 --env PYTHONHASHSEED=0 \
  --mount "type=bind,src=$PROJECT/experiments/persistent_inference,dst=/experiment,readonly" \
  --mount "type=bind,src=$PROJECT/processing,dst=/app/processing,readonly" \
  --mount "type=bind,src=$ASSETS,dst=/opt/GVHMR/inputs/checkpoints,readonly" \
  --mount "type=bind,src=$INPUT,dst=/input,readonly" \
  --mount "type=bind,src=$OUTPUT,dst=/output" \
  --workdir /opt/GVHMR --entrypoint /usr/bin/timeout physio-gvhmr:ee960bb \
  --kill-after=30s 16m python /experiment/benchmark.py \
  --video /input/drone_video.mp4 --calibration /input/drone_calib.txt \
  --output /output/resident-001 --residency resident --timeout-s 900
```

`benchmark.json` records the persistent run followed by four fresh-process
controls. Each worker records stage timings, constructor and use counts, input and
asset identities, and failure diagnostics. A completed benchmark is not a live
service, annotated-video output, Quest latency measurement or clinical result.

## Selected streaming experiment: 640px and 15 observations per second

The selected defaults in `experiments/streaming_inference/experiment.py` are
`640-15`, selective `weights-fp16`, and pose and feature batches of eight. This means
640 by 360 analysis images with 15 expensive observations per second. Original
frame IDs and presentation times remain intact. The model and camera-motion grid
remain 30 Hz. Annotated playback retains the original rate. This does not change
Quest capture settings or the production service command.

The worker constructs all five models once and keeps them on the RTX 3070.
Only ViTPose and HMR2 feature weights and forward passes use FP16. Decoding, detector,
GVHMR, body geometry and camera motion stay FP32. Autocast weight caching is
explicitly disabled to avoid retaining two additional large weight copies.
Failure is explicit. There is no automatic precision or static-camera fallback.

The experiment releases four chunks at two-second intervals. One tracker spans
the whole take, and camera-motion pairs cross chunk boundaries. The overlap mode
runs CPU visual odometry while the GPU computes observations. It makes one final
whole-take GVHMR call after capture stops. It does not concatenate independently
fitted two-second bodies or claim concurrent GPU model replicas.

On the public eight-second WHAM clip, the selected configuration completed all
three scheduling modes. With CPU-VO overlap, native geometry was verified 2.626
seconds after scheduled capture stop. The annotated MP4 was closed and decoded
successfully after 3.560 seconds. Serial streaming took 3.790 seconds to verified
video. Ninety observations completed before stop in both streaming modes. Each
model was constructed once across three takes. Scheduling modes produced exactly
matching intermediate arrays and native geometry for this test.

The after-stop control took 9.988 seconds, but ran first in its process and includes
first-use effects. Do not attribute its full difference to scheduling. Initialization
took 15.200 seconds before capture. Initialization must finish before accepting work. Fixture
creation, camera encoding, network transfer, service publication, download and Quest
loading are excluded. The original source has 240 selected frames at 30000/1001 fps,
so normal playback is 8.008 seconds while the capture-stop timing origin is eight
seconds. These are one-source measurements, not latency or accuracy guarantees.

A historical four-panel demo used 640px at 10 observations per second and
960px at 15. A separate GPU run measured 640px at 15. Its compact evidence is `experiments/streaming_inference/rtx3070-640-15.json`.
No video, checkpoint, body-model asset or credential is included in Git.

Run CPU checks from the project root. Without model dependencies, pinned-source
checks skip explicitly. The GPU image must pass them without skips. An inspected
GVHMR checkout can be supplied through `PHYSIO_GVHMR_SOURCE` for CPU source-body
checks, alongside `PHYSIO_ULTRALYTICS_SOURCE` described above.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 experiments/streaming_inference/cpu_tests.py \
  --processing-root "$PWD"
```

Run only on an otherwise idle GPU. Reuse the approved image, inputs and assets
from the setup above. `OUTPUT` must be writable by the container user. Outputs are
bounded beneath a writable copy of the streaming scripts. Choose a new directory
for each run. The helper code and model files stay read-only.

```sh
docker run --rm --gpus all --network none --read-only \
  --cap-drop ALL --security-opt no-new-privileges \
  --user "$(id -u):$(id -g)" --memory 24g --cpus 8 --pids-limit 256 \
  --tmpfs /tmp:rw,nosuid,nodev,size=2g \
  --env PYTHONPATH=/experiment:/app:/opt/GVHMR \
  --env PYTHONDONTWRITEBYTECODE=1 --env PYTHONHASHSEED=0 \
  --mount "type=bind,src=$PROJECT/experiments/persistent_inference,dst=/experiment,readonly" \
  --mount "type=bind,src=$PROJECT/experiments/streaming_inference,dst=/stream-source,readonly" \
  --mount "type=bind,src=$PROJECT/processing,dst=/app/processing,readonly" \
  --mount "type=bind,src=$ASSETS,dst=/opt/GVHMR/inputs/checkpoints,readonly" \
  --mount "type=bind,src=$INPUT,dst=/input,readonly" \
  --mount "type=bind,src=$OUTPUT,dst=/output" \
  --workdir /opt/GVHMR --entrypoint /usr/bin/timeout physio-gvhmr:ee960bb \
  --kill-after=30s 10m sh -c '
    set -eu
    mkdir /output/stream-640-15
    cp /stream-source/*.py /output/stream-640-15/
    S=/output/stream-640-15/experiment.py
    python "$S" prepare --code /experiment --video /input/drone_video.mp4 \
      --calibration /input/drone_calib.txt --output /output/stream-640-15/fixture
    python "$S" run --code /experiment --fixture /output/stream-640-15/fixture \
      --output /output/stream-640-15/result --deadline 300
  '
```

The fixture adapter intentionally accepts the inspected public source, not
arbitrary participant recordings. The service and Quest client do not yet integrate two-second network ingestion
and a persistent service lifecycle. The GPU
experiment produces native arrays, source-linked annotations and an MP4. It does
not establish full Quest end-to-end behavior or clinical validity.

The website benchmark reports a separate half-second-ingress run with a 2.2745-second median. The checked-in fixture releases four two-second chunks. The runner and raw files for that half-second run are absent, so its hashes identify historical evidence without making that run reproducible here.
