# GVHMR local inference on Arch Linux and RTX 3070

## Status and supported input

On 2026-09-26, the main session completed real GVHMR inference and finite native SMPL-X geometry export on the Arch Linux RTX 3070 worker using a public WHAM video derivative. The run exported 242 frames, 10,475 vertices and 22 joints per frame; all eight artifact sizes and SHA-256 hashes were independently checked against the manifest. All 36 reconstruction container tests passed, including PyAV. The integration changes received independent approval. See the final smoke evidence below for provenance and measurements. This proves this input ran within the worker's resources, not visual correctness, clinical accuracy, Quest replay or whole-path latency.

Initial development checks ran on macOS with Python 3.14.7, without local Docker, FFmpeg, PyAV, CUDA, body assets or model checkpoints. Those limitations do not describe the now-verified Arch worker. See the separate verification records below.

The CLI prepares an original MP4, runs person tracking, ViTPose, HMR2 features, moving-camera rotation estimation and GVHMR, then evaluates native SMPL-X vertices and 22 body joints from the same fitted parameters. It retains global root translation. It does not implement the service, Unity conversion, exercise findings, foot assessment or microscope.

Supported first-pass inputs:

- One consenting participant, exactly one continuous tracked identity, one video stream.
- SPEC sidecar `schema_version: "1.0"`, original source frame IDs and nanosecond PTS strings. UUID take ID. No filenames are read from the sidecar.
- Upright, unmirrored, rectified pinhole image. `rotation_degrees: 0`, `mirrored: false`, camera `distortion_model: "none"` and `distortion_coefficients: []`. No implicit crop, resize or camera-pose conversion.
- Even dimensions of at least 32 pixels, at most 2,073,600 pixels. Original MP4 at most 512 MiB and 3,600 decoded source frames. Prepared inference at most 600 frames, about 20 seconds. These are conservative initial bounds, not measured RTX 3070 capacity.
- No invalid source images, explicit `capture.gaps`, interruptions or source intervals longer than 100 ms. Such takes fail rather than concealing gaps. Supply a separately identified contiguous capture, not a silently concatenated edit. Gap-containing replay is not implemented.
- Calibrated or explicitly estimated intrinsics require positive equal `fx` and `fy`. Off-centre `cx` and `cy` are allowed. The inspected GVHMR translation code uses `fx` for both axes. Genuine unequal focal lengths require a separately verified rectification/resizing adapter with updated calibration. They are not invalid cameras, just unsupported here.

When calibration is unavailable, `--allow-estimated-intrinsics` explicitly permits the upstream diagonal-length focal estimate and image-centre principal point. Output remains labelled estimated. Physical scale is always model-estimated even with calibrated intrinsics.

## Arch host setup

The verified worker already has a working NVIDIA Docker runtime. The `bader` account requires `sudo` for Docker access; no Docker group change, daemon reconfiguration or restart is needed. The user authorized sudo, Docker builds and asset downloads on Arch. Asset access and terms still apply.

For a new or unconfigured host only, follow the current [Arch NVIDIA](https://wiki.archlinux.org/title/NVIDIA), [Docker](https://wiki.archlinux.org/title/Docker) and [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) instructions for the installed kernel. Do a full supported system upgrade when installing packages. Never run a partial Arch upgrade such as refreshing package databases then installing only selected packages against an old system.

Install the kernel-appropriate NVIDIA driver, Docker and NVIDIA Container Toolkit from the current supported Arch package sources. This document does not choose a driver package without knowing the kernel. Reboot after a driver/kernel change where required. The container supplies CUDA 12.1 userspace; the host needs a compatible NVIDIA driver, not a separate host CUDA toolkit.

Record the actual host before building:

```sh
uname -a
nvidia-smi
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv
pacman -Q docker nvidia-container-toolkit
sudo docker version
```

Only on a host whose NVIDIA runtime is not configured, an authorized operator can configure it and restart Docker. Do not run these on the already-configured worker:

```sh
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

Docker daemon access grants substantial host privileges. Use an authorized local operator. No privileged container, Docker socket mount, participant upload or paid GPU is needed. If any network operation fails, stop and report it rather than retrying or switching download endpoints.

## Build context and dependency record

From the project root:

```sh
sudo docker build --progress=plain --platform linux/amd64 \
  -t physio-gvhmr:ee960bb \
  processing/reconstruction
```

The local build context allowlists only the Dockerfile, dependency supplement and ignore file. Recordings, source code, credentials and checkpoints cannot enter it. The image fetches the public upstream source at exactly `ee960bb6e2ea2d381aa97f08e9b71ef320b624b1`, not its moving main branch. It does not fetch submodules, pretrained checkpoints, body models or datasets. Public upstream source includes its own model-support tensors and notices.

The base is upstream-compatible in intent, `pytorch/pytorch:2.3.0-cuda12.1-cudnn8-runtime`, Linux amd64. Upstream specifies Python 3.10, torch 2.3.0+cu121, torchvision 0.18.0+cu121, NumPy 1.23.5, PyTorch3D 0.7.6 and PyAV 13.0.0. The image installs the pinned source's `requirements.txt`, adds HMR2's missing `yacs` dependency and constrains OpenCV to a NumPy-1-compatible version. It records resolved packages in `/opt/runtime-freeze.txt` and runs `pip check`.

This is not a complete reproducibility lock: upstream leaves several dependencies unpinned and the base tag is not digest-pinned. The worker build succeeded; its image ID is recorded below. Preserve `/opt/runtime-freeze.txt` with the run record before changing dependencies or rebuilding. Build compatibility does not establish model compatibility. Network retries are disabled for apt and pip.

## Externally mounted assets and terms

The operator must obtain and approve assets separately. Never point this directory at participant-supplied files. Upstream checkpoint loaders use trusted Python serialization and body-model packages may do so internally. This is not a sandbox for arbitrary pickle/checkpoint uploads.

Expected local asset directory, mounted at `/opt/GVHMR/inputs/checkpoints`:

```text
checkpoints/
  body_models/smplx/SMPLX_NEUTRAL.npz
  gvhmr/gvhmr_siga24_release.ckpt
  hmr2/epoch=10-step=25000.ckpt
  vitpose/vitpose-h-multi-coco.pth
  yolo/yolov8x.pt
```

The upstream stock renderer also requests `body_models/smpl/SMPL_NEUTRAL.pkl`. This adapter exports native SMPL-X topology instead, so it does not need that extra SMPL asset. If a later exporter uses SMPL conversion, obtain it through registration and mount it externally; do not bundle it.

Access and rights:

- [GVHMR install instructions at the pinned revision](https://github.com/zju3dv/GVHMR/blob/ee960bb6e2ea2d381aa97f08e9b71ef320b624b1/docs/INSTALL.md) link the operator-download checkpoint folder.
- [GVHMR checkpoint access](https://drive.google.com/drive/folders/1eebJ13FUEXrKBawHpJroW0sNSxLjh9xD?usp=drive_link). Inspect each model's terms before downloading or using it.
- Registered [SMPL-X](https://smpl-x.is.tue.mpg.de/) and [SMPL](https://smpl.is.tue.mpg.de/) have separate access and model/output terms.
- The inspected GVHMR `LICENSE` permits educational, research and non-profit purposes, requires notices and open-source non-commercial modifications, and directs commercial enquiries to its authors. HMR2, ViTPose, YOLO and their training/model assets have separate terms. The project does not grant blanket redistribution or commercial rights.

The runtime checks required local files and hashes them into the handoff. Its container has no network, so missing weights cannot trigger successful implicit downloads. No preview assets or model outputs are loaded back through `torch.load` by this adapter.

## Smoke checks

Set absolute paths to the project root, operator-approved assets and input folder. Keep inputs immutable for the run. Mount only the needed directories, never the Docker socket. On the verified worker, prefix the `docker run` examples below with `sudo`, including the invocation under `timeout`.

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

The capture adapter must document the relation between its clock and the MP4 stream clock. `--pts-offset-ns` is mandatory, signed and operator supplied. For each decoded image, the adapter requires the rounded decoder timestamp in nanoseconds plus this offset to equal one unique sidecar `pts_ns`. It rejects missing, extra, repeated or reordered timestamps. Equal decoder and sidecar frame counts alone do not establish correspondence.

Use offset zero only if both clocks are known to be the same. A monotonic camera clock rebased to zero by the MP4 muxer needs its measured offset. Do not guess this offset by frame count or label nominal FPS as observed timing. This first adapter supports exact rounded-nanosecond binding only. If the capture muxer quantizes PTS differently, capture must supply a verified per-frame media-PTS mapping in a future agreed sidecar extension; this CLI fails rather than inventing one.

Example only, replace filenames and the verified offset:

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

## Native handoff to Bader

`handoff.json`, local schema `gvhmr-native-1`, is not the HTTP result or Unity replay manifest. It inventories byte sizes and SHA-256 hashes for these artifacts:

- `parameters.json`: global and in-camera SMPL-X parameters and per-frame K, validated by the existing native validator. Axis-angle body pose, root orientation, betas and translation are unchanged.
- `vertices.f32`, `joints.f32`: little-endian float32, frame-major then vertex/joint-major XYZ. Both come from the same `make_smplx("supermotion")` forward call on global fitted parameters. Root motion is retained. No preview-facing transform or framewise centering is applied.
- `triangles.u32`: fixed native SMPL-X triangle triples, little-endian uint32. Counts are declared in `geometry`.
- `fitted_valid.u8`: frame-major 22-joint mask. A one means a finite fitted estimate, not direct observation or calibrated confidence. Missing image/track evidence rejects this version of the workflow. Unfitted fingers, face and expression remain model defaults, not foot/face measurements.
- `observations.json`: tracked boxes, COCO17 image coordinates/raw pose scores, estimated camera rotations and the VO sampling indices. COCO17 observations are not the 22 SMPL-X joints.
- `selection.json` and `source-sidecar.json`: source provenance and preserved capture metadata.

Native coordinates are the upstream right-handed, gravity-aligned global `ay` frame with +Y up. Horizontal orientation is a model gauge, not a verified Quest world transform or measured facing direction. Units are model metres with estimated physical scale. Joint names come from SMPL-X `JOINT_NAMES[:22]`, parents from the mounted body's kinematic tree. Hand/face joints are not exported as supported body joints. Artifact hashes and body-asset hash identify the actual topology. No axis conversion has been verified with a real asymmetric motion fixture.

Bader owns the final service contract, source-time replay selection, verified take-local/Unity transform, winding change where needed, package limits and patient/session association. Native rows are inference rows. A repeated original source timestamp cannot be inserted unchanged into a final manifest that requires strictly increasing source times. Select one representative fitted row per source frame and retain the full mapping as provenance, or agree an explicit display-resampling contract before implementation. Do not replace original times with inference index divided by 30.

The handoff records asset and adapter-source hashes, resolved key dependency versions, measured device memory, peak torch allocated/reserved memory and local stage durations. Local elapsed time includes preparation, asset checks, inference and export up to final manifest serialization. It does not measure capture completion, upload, service wait, download or Quest loading. The agreed 1–2 minute whole-path target remains untested.

## Camera motion and source evidence

Initial source inspection used `git clone --no-checkout` and detached checkout at the exact revision above, without downloading weights or datasets in that inspection. The main session has since installed the five approved assets. Relevant inspected files:

- `docs/INSTALL.md`, `requirements.txt`, `setup.py`, `LICENSE`: runtime, asset paths and terms.
- `tools/demo/demo.py`: stock 30 FPS copy, preprocessing, `DemoPL.predict`, global/in-camera output and optional render paths.
- `hmr4d/utils/preproc/tracker.py`: stock identity selection and missing-box interpolation. This adapter uses raw `Tracker.track` and rejects missing or ambiguous tracks instead.
- `hmr4d/utils/preproc/vitpose.py`, `vitfeat_extractor.py`: crop/feature extraction and upstream batch size 16. This adapter supplies two crops per call to lower peak memory; the final smoke below demonstrates 3070 fit for that 242-frame input only.
- `hmr4d/utils/preproc/relpose/simple_vo.py`, `solver_two_view.py`: SIFT, pycolmap two-view solve, accumulated world-to-camera rotations and interpolation. This adapter passes the same K used for GVHMR, scaled for the half-size VO images. It never defaults to a static camera or uses SimpleVO's unrelated 24 mm estimate.
- `hmr4d/utils/preproc/slam.py` and upstream install instructions: DPVO requires its git submodule, Eigen 3.4, torch-scatter, numba, pypose, a CUDA development toolchain and `dpvo.pth`. It is optional and not installed here. No `--use-dpvo` promise is made. Use the inspected upstream default SimpleVO path first. Quest camera-pose fusion is not implemented.
- `hmr4d/model/gvhmr/gvhmr_pl_demo.py`, `pipeline/gvhmr_pipeline.py`, `utils/geo/hmr_global.py`: prediction fields, translation integration and `any->ay` conversion.
- `hmr4d/utils/smplx_utils.py`, `body_model/body_model_smplx.py`: neutral SMPL-X construction, batch forward, retained translation and default unpredicted face/hand fields.

SIFT/VO may fail on textureless scenes, insufficient parallax, independently moving backgrounds or repeated frames. Failures do not fall back to identity/static camera motion. The algorithm's interpolated camera rotations are estimates, not measured headset tracking. Record real-footage failures before choosing DPVO or a tracked-pose adapter.

## CPU checks and remaining validation

From the project root, no extra test dependencies:

```sh
python3 -m unittest discover -s tests/ml -v
python3 -m compileall -q processing/reconstruction tests/ml
python3 -m processing.reconstruction.runtime --help
```

The original 16 tests passed before implementation. New tests first failed because `runtime` did not exist, then passed after implementation. Malformed-sidecar tests also failed before the structural validation change. CPU tests exercise planning, PTS binding, rejection, metadata and CLI/orchestration failures. Mocks test only control flow, never GPU correctness. Two real PyAV encode/decode tests skipped on the initial Mac but passed inside the Arch worker image. Docker build and CUDA exposure are now verified. Preprocessing has run on public demos, with failures recorded below. The final WHAM smoke completed GVHMR prediction and finite geometry export. No automated coverage percentage is claimed for the GPU adapter; one successful inference is not a coverage measurement.

Start with a short consented full-body take and a known asymmetric movement. Check PTS binding, participant identity, root movement, native joint/surface alignment, camera rotation, axis orientation and all artifact sizes/hashes before integrating replay. Record actual driver, VRAM, package freeze, peak host/GPU memory, stage times and end-to-end timing. If CUDA OOM occurs, retain the failure record and shorten a new test capture or tune measured batching limits. Do not silently lower evidence quality or claim the failed take succeeded.

### Initial Mac verification record, 2026-09-26

These results predate the Arch worker checks and describe only the local Mac environment.

- `python3 -m unittest discover -s tests/ml -v`: 31 tests, 29 passed, two real-codec tests skipped because PyAV is unavailable.
- `python3 -m compileall -q processing/reconstruction tests/ml`: passed.
- `python3 -m processing.reconstruction.runtime --help`: passed.
- `python3 -m trace --count --summary --missing --coverdir /tmp/gvhmr-runtime-coverage --module unittest discover -s tests/ml`: passed with the same skips. Line coverage reported native 99.0%, timing 100%, runtime 80.2%. The runtime denominator includes the unexecuted PyAV function. The lazy-imported `gvhmr.py` GPU adapter was not executed or included by trace; no whole-runtime coverage claim follows from these percentages.
- `command -v docker ffmpeg ffprobe`: none found. Python reports 3.14.7. Docker build, GPU smoke, real codec tests and participant inference were not run.
- Upstream `git ls-remote`, source clone and detached checkout succeeded. No network failures occurred. No tools, weights or restricted assets were installed/downloaded.

### Arch worker verification record, 2026-09-26

The main session performed these checks with user authorization. This documentation update records its supplied evidence; it did not contact or modify the host.

- Arch Linux, kernel `7.2.6-arch2-1`, x86_64. NVIDIA RTX 3070, driver `615.71.09`. `nvidia-smi` reported physical total memory of 8192 MiB, with 10 MiB used at the initial check.
- Host RAM was 62 GiB, about 57 GiB available; disk availability was 144 GiB at the initial check. These are point-in-time observations, not inference resource measurements.
- Docker `29.8.1`, NVIDIA Container Toolkit `1.20.0`; NVIDIA runtime already configured.
- Source snapshot: `/home/bader/physio-reconstruction/snapshot-20260926`. The initial home-directory asset search to maximum depth 5 found no assets; this was not an exhaustive filesystem search.
- Build command, from the snapshot root: `sudo docker build --progress=plain --platform linux/amd64 -t physio-gvhmr:ee960bb processing/reconstruction`. Result: success. Image ID: `sha256:66db73a15b803aa99aa47f8929ec2acd7e5d30ee84332dad8c1b62e254beeddc`. Log: `docker-build.log` in the snapshot.
- Smoke checks used all GPUs, no network, a read-only container, nonroot user `1001:1001`, a 2 GiB tmpfs, and mounts of `processing` at `/app/processing` and `tests/ml` at `/tests`. Log: `gpu-smoke.log` in the snapshot.
- Container versions: Python `3.10.14`, torch `2.3.0+cu121`, PyAV `13.0.0`, pycolmap `4.2.0`. Import of `hmr4d.utils.preproc` succeeded. CUDA availability was true, and a CUDA `torch.ones(1).item()` check returned `1.0`.
- The torch device report showed `total_memory=7885MB`, the memory exposed to torch. Keep this distinct from the 8192 MiB physical total reported by `nvidia-smi`; neither proves model VRAM fit or peak usage.
- Container command `python -m unittest discover -s /tests -v`: 31 passed, zero skips, including real encode/decode tests. Most tests exercise CPU logic, not GPU model execution.

All five approved assets were subsequently hash-verified and installed. At this initial checkpoint, completed inference and native geometry export were still unverified. The final smoke below supersedes that status with successful moving-camera estimation, prediction, export and torch allocator measurements. Visual geometry correctness, entire-device peak VRAM and whole-path latency remain unverified.

New files from the original implementation are `processing/reconstruction/{runtime.py,gvhmr.py,Dockerfile,.dockerignore,requirements.runtime.txt,GPU_SETUP.md}` and `tests/ml/{test_runtime.py,test_media_runtime.py}`. Existing parent-owned native/timing modules and their 16 tests were not changed. No commits or pushes were made.

Branch at implementation start: `codex/mohammad-ml`, base `ab5bafa1afe78c9ea4f1b8d49929a6f43cbe12f7`. Shared `docs/HANDOFF.md`, spec and API were outside this assignment's write scope and remain unchanged. The parent must transfer this actual status into the shared handoff and review the proposed local interchange with capture and service owners. The scoped integration subsequently received independent approval. It is not a verified deployment or completed M1.

### Integration fix record, 2026-09-26, before the successful smoke

Historical failures supplied by the main session, not reproduced by this local implementation session:

- Image `physio-gvhmr:ee960bb` on the Arch RTX 3070, driver `615.71.09`, torch `2.3.0+cu121`, pycolmap `4.2.0`; all five approved assets are hash-verified and installed. The previously reported 31 container tests passed before these fixes.
- The public upstream tennis demo failed strict tracking with three to four people in every frame. That rejection is correct; identity rules are unchanged.
- Public HuggingFace `LittleFrog/GVHMR` example `examples/cxk.mp4` passed tracking, ViTPose and HMR2 feature extraction, then failed in `solver_two_view.py` at line 105 because `answer.cam2_from_cam1` was `None`.
- A separate load diagnostic confirmed `register_store_gvhmr(); compose('demo')` fails with missing config `model/gvhmr/gvhmr_pl_demo`. No completed prediction or geometry result had been supplied at that point.

Local source review at `/tmp/gvhmr-runtime-inspection`, revision `ee960bb6e2ea2d381aa97f08e9b71ef320b624b1`, confirmed that the general store imports the training model but not the demo model. The upstream demo imports `DemoPL` before composition. `load_demo_model()` now follows that order and retains nonrecursive instantiation, checkpoint loading, evaluation mode and CUDA placement.

The subsequent path was traced through `demo.yaml`, `Pipeline`, `EnDecoder`, `SmplxLiteV437Coco17`, `make_smplx('supermotion')` and `BodyModelSMPLX`. The network and endecoder registrations are in the general store. Pipeline instantiation is explicit in the config. The reduced body model reads the mounted neutral SMPL-X asset and upstream source-tree support tensors; the full export wrapper reads the same body-asset directory and supplies batch-sized defaults for unfitted fields. No additional registration or asset-path mismatch was established by this inspection. That inspection established source compatibility only. Subsequent actual loading, forward execution and prediction are recorded below; visual geometry validation remains outstanding.

`CameraMotionSolver` retains the pinned upstream pycolmap backend's camera/options, correspondence construction, pose conversion and SimpleVO serial accumulation. It checks only the reported no-relative-pose state before matrix access and raises an actionable `ValueError`. It does not catch unrelated estimator/API failures, synthesize poses, relax tracking, change sampling or switch to static mode. Serial execution is explicit because this adapter does not implement the upstream parallel solver cloning interface. The existing CLI reports the failure and does not publish `handoff.json`.

Changed files for this fix are `processing/reconstruction/gvhmr.py`, `processing/reconstruction/GPU_SETUP.md`, `tests/ml/test_gvhmr.py` and `tests/ml/test_runtime.py`. Shared documentation and analysis files remain outside scope. Branch/base remain `codex/mohammad-ml` at `ab5bafa1afe78c9ea4f1b8d49929a6f43cbe12f7`.

Local commands and outcomes:

- `python3 -m unittest discover -s tests/ml -v`: baseline 67 tests, 65 passed and two PyAV skips; after the fix 72 tests, 70 passed and the same two skips. Discovery includes other owners' existing exercise/foot tests; those files were not changed.
- `python3 -m unittest discover -s tests/ml -p test_gvhmr.py -v`: four expected missing-symbol errors before implementation, then four passed. Tests cover demo registration/composition/load order, unchanged successful VO conversion/settings, missing-pose rejection and propagation of unrelated failures. These use mocked dependency boundaries, not CUDA.
- The added CLI failure regression verifies preserved source/preparation files, a nonzero result and no completion marker after camera-motion failure.
- `python3 -m compileall -q processing/reconstruction tests/ml/test_gvhmr.py tests/ml/test_runtime.py`: passed.
- `python3 -m processing.reconstruction.runtime --help`: passed without importing GPU dependencies.

No GPU, network or remote commands, downloads, credentials, commits or pushes were used in this fix session. No agents were spawned. A cohesive local self-review covered registration through export and failure publication. The main session subsequently reported independent approval of these integration changes. That approval does not establish final cross-workstream or product validation.

### Final public WHAM smoke evidence, 2026-09-26

This evidence-only update read local copies of `handoff.json`, `provenance.json`, `tests-container.log`, `runtime-freeze.txt` and `run-001.log` under `/tmp/physio-gpu-verification`. The main session performed the worker operations and independent artifact verification. This editing session did not run network or GPU commands, download assets or repeat inference.

The main session used updated `gvhmr.py` through the source bind mount in the same `physio-gvhmr:ee960bb` image identified above, with network disabled, a read-only container, nonroot execution and approved external assets. Container `physio-wham-smoke-001` exited 0. Output is `/home/bader/physio-reconstruction/public-wham-smoke/output/run-001`. Remote evidence remains under `/home/bader/physio-reconstruction/public-wham-smoke/` as `run-001.log`, `runtime-freeze.txt`, `tests-container.log` and `container-inspect.json`. The inspect file was not among the local evidence copies read here.

The public examples archive came from WHAM's official [fetch_demo_data.sh](https://github.com/yohanshin/WHAM/blob/main/fetch_demo_data.sh), documented Drive ID `1KjfODCcOUm_xIMLLR54IcjJtf816Dkc7`. The main session reported an 88.2 MB download and safe extraction of only `examples/drone_video.mp4` and `examples/drone_calib.txt`. Archive SHA-256 is `8c23111f1ef92eec644da02406704d4ec6e13281046676d699a93e7b7ffb4fee`. This is a public smoke fixture, not participant evaluation data or evidence of redistribution rights.

The original 22.12-second, 664-frame video was retained unchanged, SHA-256 `0da55210a305c3c75caa732c46b7330bb3d4e39ebeb9bc3af1e2b100dd8990c1`. The explicitly identified derivative used video stream-copy of approximately the first eight seconds, with no crop, resize or explicit frame-rate conversion. It has 242 decoded frames at 1920 by 1080 pixels, with last decoded PTS 8.041366667 seconds. Derivative SHA-256 is `c010567f80e5813c2d1e2811510062dcf9de5a9190a7084c3e253b75ed11b895`.

The synthetic sidecar uses decoder PTS with offset zero. It does not verify a Quest capture clock. Provided intrinsics from `drone_calib.txt` use focal lengths 1321 pixels on both axes and principal point 960, 540 pixels, marked estimated because calibration accuracy was not independently verified. Upright, unmirrored pinhole imagery and no distortion were assumed only for this smoke; actual lens distortion is unknown. Capture labels are fixture placeholders, not measured annotations. Sidecar SHA-256 is `a078ed72ab70c6deef9bfc5c4e523ca7e58bedbde4a9c0ae569ec9430fff1aa3`.

Tracking, ViTPose, HMR2 features, SIFT/pycolmap moving-camera estimation, real GVHMR prediction and native geometry export all completed. The manifest records 242 fitted frames, 10,475 vertices, 20,908 triangles and 22 joints, with finite fitted estimates and retained root translation. The main session independently checked byte sizes and SHA-256 for all eight inventoried artifacts. This update inspected the manifest, not the remote binary arrays. Neither finite arrays nor matching hashes establish visual alignment or anatomical correctness.

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

The freeze and manifest confirm torch `2.3.0+cu121`, torchvision `0.18.0+cu121`, PyAV `13.0.0`, NumPy `1.23.5`, SMPL-X `0.1.28`, pycolmap `4.2.0` and ultralytics `8.2.42`. The freeze also records OpenCV `4.10.0.84`, PyTorch3D `0.7.6` and yacs `0.1.8`. Upstream revision remains `ee960bb6e2ea2d381aa97f08e9b71ef320b624b1`. The manifest records all five asset hashes and four adapter-source hashes; the executed `gvhmr.py` hash is `1c1c8d547d4a9b5e3e38e5c761f006018411e53bbc8fa634ced54a6dcf44533a`.

Verification outcomes supplied by the main session:

- `python -m unittest discover -s /tests -v`: 36 reconstruction tests passed in 0.388 seconds, zero skips, including both real PyAV tests. The local copied log confirms this outcome.
- `python3 -m unittest discover -s tests/ml -v`: combined local suite, 72 tests, 70 passed and two PyAV skips, as recorded in the integration fix record.
- Separate actual `load_demo_model()` and neutral `make_smplx` forward execution succeeded after the import fix. This diagnostic outcome is supplied by the main session; its separate log was not included in the local evidence set.
- Full inference completed and published `handoff.json`; the run log records checkpoint loading and completed preprocessing. The successful WHAM run does not erase the tennis identity rejection or establish that `cxk.mp4` now passes VO.

### Remaining proof

Inspect the source video and exported body/skeleton together, including root motion, camera rotation and a known asymmetric axis fixture. Verify native-to-Unity coordinates, winding, source-time replay selection and joint/surface alignment before claiming replay correctness. Repeat with a consented Quest take and a verified camera/clock mapping. Measure final capture through loaded replay, including transfers and loading, and separately measure entire-device and host memory peaks if needed.

Native scale remains estimated; there is no Quest/world registration, Unity conversion, visual validation, clinical validation or held-out-person evaluation. The reconstruction CLI does not implement exercise findings, foot assessment or motion microscope. Service and Quest integration remain outside this proof. M1 and the required product flow are incomplete.

Only `processing/reconstruction/GPU_SETUP.md` changed in this final evidence update. No tests or inference were rerun for this prose-only change; the results above are attributed to their existing evidence. No commits or pushes were made. The scoped documentation is ready for independent review.
