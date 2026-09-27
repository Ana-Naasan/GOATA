# GVHMR local inference on Arch Linux and RTX 3070

**Last updated:** September 26, 2026. Original GPU evidence below is preserved;
current integration behavior is documented separately from that historical run.

## Status and supported input

On 2026-09-26, the main session completed real GVHMR inference and finite native SMPL-X geometry export on the Arch Linux RTX 3070 worker using a public WHAM video derivative. The run exported 242 frames, 10,475 vertices and 22 joints per frame; all eight artifact sizes and SHA-256 hashes were independently checked against the manifest. All 36 reconstruction container tests passed, including PyAV. The integration changes received independent approval. See the final smoke evidence below for provenance and measurements. This proves this input ran within the worker's resources, not visual correctness, clinical accuracy, Quest replay or whole-path latency.

Initial development checks ran on macOS with Python 3.14.7, without local Docker, FFmpeg, PyAV, CUDA, body assets or model checkpoints. Those limitations do not describe the now-verified Arch worker. See the separate verification records below.

The CLI prepares an original MP4, runs person tracking, ViTPose, HMR2 features, moving-camera rotation estimation and GVHMR, then evaluates native SMPL-X vertices and 22 body joints from the same fitted parameters. It retains global root translation. The CLI produces the native handoff. The service now invokes it through `processing/pipeline.py`; `processing/export.py` converts the native geometry for Unity and the microscope runs separately on original footage. Automated exercise and foot assessment remain incomplete.

Supported first-pass inputs:

- One consenting participant, exactly one continuous tracked identity, one video stream.
- SPEC sidecar `schema_version: "1.0"`, original source frame IDs and nanosecond PTS strings. UUID take ID. No filenames are read from the sidecar.
- Upright, unmirrored pinhole image: `rotation_degrees: 0`, `mirrored: false`, camera `distortion_model: "none"` and `distortion_coefficients: []`. Unknown distortion is rejected by default; the explicit approximation below is the only opt-in exception. No implicit crop, resize, rectification or camera-pose conversion.
- Even dimensions of at least 32 pixels, at most 2,073,600 pixels. Original MP4 at most 512 MiB and 3,600 decoded source frames. Prepared inference at most 600 frames, about 20 seconds. These are conservative initial bounds, not measured RTX 3070 capacity.
- No invalid source images, explicit `capture.gaps`, interruptions or source intervals longer than 100 ms. Such takes fail rather than concealing gaps. Supply a separately identified contiguous capture, not a silently concatenated edit. Gap-containing replay is not implemented.
- Calibrated or explicitly estimated intrinsics require positive equal `fx` and `fy`. Off-centre `cx` and `cy` are allowed. The inspected GVHMR translation code uses `fx` for both axes. Genuine unequal focal lengths require a separately verified rectification/resizing adapter with updated calibration. They are not invalid cameras, just unsupported here.

When calibration is unavailable, `--allow-estimated-intrinsics` explicitly permits the upstream diagonal-length focal estimate and image-centre principal point. Output remains labelled estimated. Physical scale is always model-estimated even with calibrated intrinsics.

`--allow-unverified-pinhole` permits `distortion_model: "unknown"` only with an
empty coefficient array. It records an unverified pinhole assumption in selection
and processing provenance and labels processing intrinsics estimated. The source
sidecar remains unchanged. Quest's SDK currently exposes intrinsics but no lens
distortion model or coefficients; an empty array is not proof of rectification.
This flag does not validate lens geometry, physical measurements or output
alignment. The corresponding service setting defaults false.

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

## Native handoff to Bader

`handoff.json`, local schema `gvhmr-native-1`, is not the HTTP result or Unity replay manifest. It inventories byte sizes and SHA-256 hashes for these artifacts:

- `parameters.json`: global and in-camera SMPL-X parameters and per-frame K, validated by the existing native validator. Axis-angle body pose, root orientation, betas and translation are unchanged.
- `vertices.f32`, `joints.f32`: little-endian float32, frame-major then vertex/joint-major XYZ. Both come from the same `make_smplx("supermotion")` forward call on global fitted parameters. Root motion is retained. No preview-facing transform or framewise centering is applied.
- `triangles.u32`: fixed native SMPL-X triangle triples, little-endian uint32. Counts are declared in `geometry`.
- `fitted_valid.u8`: frame-major 22-joint mask. A one means a finite fitted estimate, not direct observation or calibrated confidence. Missing image/track evidence rejects this version of the workflow. Unfitted fingers, face and expression remain model defaults, not foot/face measurements.
- `observations.json`: tracked boxes, COCO17 image coordinates/raw pose scores, estimated camera rotations and the VO sampling indices. COCO17 observations are not the 22 SMPL-X joints.
- `selection.json` and `source-sidecar.json`: source provenance and preserved capture metadata.

Native coordinates are the upstream right-handed, gravity-aligned global `ay` frame with +Y up. Horizontal orientation is a model gauge, not a verified Quest world transform or measured facing direction. Units are model metres with estimated physical scale. Joint names come from SMPL-X `JOINT_NAMES[:22]`, parents from the mounted body's kinematic tree. Hand/face joints are not exported as supported body joints. Artifact hashes and body-asset hash identify the actual topology. The integration exporter reflects Z for both vertices and joints and reverses winding, with automated fixture checks. Real asymmetric-motion visual validation remains pending.

`processing/export.py` implements the final service replay contract, bounds and
patient/session association. Native rows are inference rows. The exporter selects
the first fitted row for each source frame, keeps the full inference mapping as
provenance, and preserves original source times/root movement. It never substitutes
inference index divided by 30 for observed timing. The C# importer accepts the
original public run's 242-frame geometry, but the original legacy sidecar still
fails the strict upload schema; that geometry check is not a successful current
service or Quest run.

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

### Current integration and remaining proof

The original public-run sidecar contains legacy extra `smoke_test_provenance` and
lacks required `capture.gaps`. Production validation rejects it. Do not rewrite the
original run's inputs, hashes or history. A separate strict sidecar with explicit
media mapping and a separate adaptation-provenance record has been prepared for
a **new** GPU run. Completion is pending interactive Docker access; see the shared
handoff. The original run above does not prove the current adapter executed.

The service, native-to-Unity exporter, C# importer and source evidence UI are now
implemented and tested as components. Inspect real source video and exported
body/skeleton together, including root motion, camera rotation, handedness and a
known asymmetric movement. Then repeat with a consented Quest take, verified
camera/mux mapping and an explicit calibration policy. Measure final capture
through loaded replay, including transfers and loading.

Native scale remains estimated; there is no verified Quest/world registration,
visual/anatomical validation, clinical validation or held-out-person evaluation.
ELK/RTK findings and automated foot assessment remain incomplete. The microscope
implementation has not yet produced an accepted real Quest result. M1 and the
required complete product flow remain incomplete.

## Persistent FP32 experiment, September 27

`experiments/persistent_inference/` contains the GPU-tested optimization runner.
It is separate from the production service, which still starts a fresh inference
process. This publication does not enable Quest streaming or change that service.
The fixture runner accepts the public WHAM drone and its supplied calibration,
not arbitrary uploaded recordings. It splits the first eight seconds into four
independent takes. Tracker and temporal state reset between those takes; do not
concatenate their reconstructions as a validated continuous movement.

The runner retains YOLO, ViTPose, HMR2 features, GVHMR and SMPL-X on CUDA. Each is
constructed once and reused for all four takes. Detector prediction/tracking state
is fresh per take. Checkpoint identity hashing occurs once per process. Images
are resized to 960 by 540; expensive observations are computed at 15 Hz and held
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
- Peak PyTorch allocation was 6,190,825,984 bytes; peak reservation was
  6,423,576,576 bytes, about 5.98 GiB. These are not whole-device memory readings.
- The shared fixture split took 4.478 seconds, outside those process times.

The original run used shared reconstruction helpers from `20cf164`. Publication
is based on current main with separate CPU verification. Original GPU evidence
and its source-inventory digest are preserved, not attributed to a new run.
All eight native artifact hashes were checked for each of the eight outputs.
Camera-motion estimates differed between persistent and fresh-process runs;
full 3D numerical equivalence and accuracy remain unproven. The historical
`all_resident_fit_proven` field is hardcoded false; completed-segment counts,
constructor/use counts and allocator measurements are the actual fit evidence.
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
`PHYSIO_ULTRALYTICS_SOURCE` to an inspected 8.2.42 `ultralytics` package directory;
file hashes are checked against the committed identity inventory before execution.
The remaining tests use CPU stand-ins and do not prove GPU correctness.

Run in the existing model image with the same approved assets. Set `PROJECT`,
`ASSETS`, `INPUT` and `OUTPUT` to absolute paths as above. `INPUT` must contain
`drone_video.mp4` and `drone_calib.txt`; obtain them under their own terms, never
commit them. The new `resident-001` directory must not already exist.

```sh
sudo docker run --rm --gpus all --network none --read-only \
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
controls. Each worker records stage timings, constructor/use counts, input and
asset identities, and failure diagnostics. A completed benchmark is not a live
service, annotated-video output, Quest latency measurement or clinical result.

## Selected streaming experiment: 640px and 15 observations per second

The selected defaults in `experiments/streaming_inference/experiment.py` are
`640-15`, selective `weights-fp16`, and pose/feature batches of eight. This means
640 by 360 analysis images with 15 expensive observations per second. Original
frame IDs and presentation times remain intact; the model and camera-motion grid
remain 30 Hz. Annotated playback retains the original rate. This does not change
Quest capture settings or the production service command.

The worker constructs all five models once and keeps them on the RTX 3070.
Only ViTPose and HMR2 feature weights/forward passes use FP16. Decoding, detector,
GVHMR, body geometry and camera motion stay FP32. Autocast weight caching is
explicitly disabled to avoid retaining two additional large weight copies.
Failure is explicit; there is no automatic precision or static-camera fallback.

The experiment releases four chunks at two-second intervals. One tracker spans
the whole take, and camera-motion pairs cross chunk boundaries. The overlap mode
runs CPU visual odometry while the GPU computes observations. It makes one final
whole-take GVHMR call after capture stops. It does not concatenate independently
fitted two-second bodies or claim concurrent GPU model replicas.

On the public eight-second WHAM clip, the selected configuration completed all
three scheduling modes. With CPU-VO overlap, native geometry was verified 2.626
seconds after scheduled capture stop; the annotated MP4 was closed and decoded
successfully after 3.560 seconds. Serial streaming took 3.790 seconds to verified
video. Ninety observations completed before stop in both streaming modes. Each
model was constructed once across three takes. Scheduling modes produced exactly
matching intermediate arrays and native geometry for this test.

The after-stop control took 9.988 seconds, but ran first in its process and includes
first-use effects. Do not attribute its full difference to scheduling. Initialization
took 15.200 seconds before capture; this must finish before accepting work. Fixture
creation, camera encoding, network transfer, service publication, download and Quest
loading are excluded. The original source has 240 selected frames at 30000/1001 fps,
so normal playback is 8.008 seconds while the capture-stop timing origin is eight
seconds. These are one-source measurements, not latency or accuracy guarantees.

The reviewed four-panel demo used 640px at **10** observations per second and
960px at 15. The user selected 640px at **15**, then a separate GPU run verified
that combination. Its compact evidence is `experiments/streaming_inference/rtx3070-640-15.json`.
No video, checkpoint, body-model asset or credential is included in Git.

Run CPU checks from the project root. Without model dependencies, pinned-source
checks skip explicitly; the GPU image must pass them without skips. An inspected
GVHMR checkout can be supplied through `PHYSIO_GVHMR_SOURCE` for CPU source-body
checks, alongside `PHYSIO_ULTRALYTICS_SOURCE` described above.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 experiments/streaming_inference/cpu_tests.py \
  --processing-root "$PWD"
```

Run only on an otherwise idle GPU. Reuse the approved image, inputs and assets
from the setup above. `OUTPUT` must be writable by the container user. Outputs are
bounded beneath a writable copy of the streaming scripts; choose a new directory
for each run. The helper code and model files stay read-only.

```sh
sudo docker run --rm --gpus all --network none --read-only \
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
arbitrary participant recordings. Two-second network ingestion and a persistent
service lifecycle still need integration by the service/Quest owners. The GPU
experiment produces native arrays, source-linked annotations and an MP4; it does
not establish full Quest end-to-end behavior or clinical validity.

## Persistent service worker

`PROCESSING_RESIDENT_COMMAND` selects one long-lived local GPU child. The service
starts it before accepting new work. The child loads all five models, completes a
full inference on an operator-approved warmup video, removes the warmup output,
and only then reports ready. Original warmup media stays unchanged. Each accepted
take gets fresh tracking and camera-motion state; model weights stay resident.

This integrates model lifetime into the completed-upload service. It does not
add streaming upload or promote the public-fixture experiment's 640px/15Hz input
selection. Production retains its existing source dimensions, 30Hz inference map,
calibration rules and native export contract. Resident ViTPose and HMR2 forwards
use FP16 with batches of eight. Detector, GVHMR, body export and camera motion stay
FP32. The half-second experiment's latency is not a production-service measurement.

The legacy `PROCESSING_INFERENCE_COMMAND` remains an explicit cold-process mode.
It cannot be configured alongside the resident command. A failed resident worker
never falls back to that mode. Warm readiness is available through authenticated
`GET /v1/ready`. New work is rejected with retryable `NOT_READY` while warming or
unavailable; existing jobs and artifacts remain readable. Idempotent resubmission
still resolves the original accepted job. The existing one-job capacity limit
remains, rather than an unbounded queue.

A failed or dead child loses readiness immediately when detected. The supervisor
stops its process group and allows one fresh recovery attempt, including a complete
warmup. The interrupted job stays failed; recovery only restores readiness for
new submissions. Another failure leaves the worker unavailable until the service
restarts. Startup, inference and scratch usage are bounded. Readiness is a model-lifecycle
check, not a latency guarantee, a GPU capacity reservation or clinical validation.

The built-in pipeline's direct child inherits the service's exclusive storage
lock in both resident and legacy cold modes. If the service
crashes but its child survives, a replacement service cannot recover or delete
that child's files. Stop the old process group or container first. After the lock
is released, the next service start removes abandoned warmup scratch before
warming. Stop all older service and model processes before upgrading; older
versions did not pass this lock to their children.

Storage admission keeps a full warmup workspace in reserve and budgets native
scratch separately from published output. Startup and recovery check available
disk space and the total storage limit before launching. These conservative
reservations can reject work before the disk is full. If kill, reap or cleanup
cannot be confirmed, the service retains temporary output, rejects new work and
requires operator intervention. It does not report recovery or delete files that
a surviving child could still be writing.

### Separate model and service environments

The model image uses Python 3.10 and the tested Torch/CUDA dependencies. The service
requires Python 3.11 or later. `Dockerfile.service` adds a separate locked Python
3.11.10 environment without upgrading the model stack. First build or retain
`physio-gvhmr:ee960bb` as described above. Build the service image from a minimal
context so recordings, checkpoints and credentials cannot enter it:

```sh
CONTEXT=$(mktemp -d)
cp pyproject.toml uv.lock processing/reconstruction/Dockerfile.service "$CONTEXT/"
sudo docker build --progress=plain --platform linux/amd64 \
  -f "$CONTEXT/Dockerfile.service" -t physio-service-resident:local "$CONTEXT"
rm -r "$CONTEXT"
```

The image runs the service with `/opt/physio-service-venv/bin/python`. Configure its
model child with `/opt/conda/bin/python`, not the service interpreter. Source stays
in readonly mounts at `/app/processing` and `/app/docs`; approved checkpoints remain
at `/opt/GVHMR/inputs/checkpoints`. Both processes must see the same absolute private
data paths. The supervisor owns a direct child process, not a detached container
or an SSH command. Do not configure `docker run`, `docker exec` or SSH as the
resident command and assume killing that client also stopped GPU inference.

Example environment inside that image, with separately mounted input and data
folders:

```sh
PROCESSING_DATA_DIR=/data
PROCESSING_INFERENCE_CWD=/opt/GVHMR
PROCESSING_RESIDENT_COMMAND='["/opt/conda/bin/python","-u","-m","processing.reconstruction.resident","--warmup-video","/warmup/take.mp4","--warmup-sidecar","/warmup/take.json"]'
```

Supply `PROCESSING_TOKEN` separately, never in source or an image layer. The warmup
must be a suitable full-body video with a valid explicit media timestamp mapping,
local approved assets and the same deliberate calibration policy as real requests.
Do not use a synthetic blank video to bypass tracking or camera-motion checks.
Both calibration approximation flags still default false.

Use a bounded container with a readonly root, nonroot execution, dropped
capabilities, private writable data/cache mounts and the existing GPU runtime.
Only an authorized operator should enable a persistent deployment or change its
network exposure. Keep the service on loopback unless TLS is configured. The
service entrypoint still requires TLS for non-loopback listeners. No new public
endpoint or Quest deployment follows merely from building this image.

### Persistent service verification, 2026-09-27

The Arch RTX 3070 ran the dual-environment image successfully. Service image ID:
`sha256:bb9ad2d95b560db097cb64dbdaa62058269ac936933230389bd34e5c24e4d4fa`.
The base model image and its Python 3.10.14/Torch 2.3.0+cu121 stack remain unchanged.
The locked service environment uses Python 3.11.10, PyAV 16.1.0 and NumPy 2.4.6.
Model-side PyAV remains 13.0.0 and NumPy remains 1.23.5.

The fixture is the unchanged public 242-frame, 1920x1080 WHAM derivative identified
above. A new strict sidecar binds actual decoded media timestamps and labels
unknown distortion honestly. The proof explicitly permits unverified pinhole
geometry. These are fixture labels and estimated intrinsics, not Quest calibration.

Two isolated full HTTP runs completed. The final run used a network-disabled,
nonroot, readonly-root container with separate readonly source/input/asset mounts,
24 GiB host-memory limit, eight CPUs and a 20-minute outer deadline. It started real
Uvicorn on container loopback and used the default service pipeline, not a mocked
inference boundary. No host port or persistent deployment was opened.

The final driver invocation inside that container was:

```sh
timeout --kill-after=30s 20m \
  /opt/physio-service-venv/bin/python /tools/service_smoke_04.py
```

Evidence and the driver remain outside Git under
`/home/bader/physio-reconstruction/warmed-service-01/`. The final receipt is
`output/service-04/proof.json`; source snapshot is `code-04`; the driver is
`tools/service_smoke_04.py`. Its source archive SHA-256 is
`eb00f098f5cee3afcdc0be315f8417610bbdd65677ba2701b474df20024fab83`.
Later source changes extend the same inherited lease to the legacy cold path;
real OS subprocess tests verify that change. No model or resident-controller code
changed after this final GPU snapshot.

Verified behavior:

- Unauthenticated readiness returned 401. Initial readiness and new-job admission
  returned 503 until full warmup completed after 45.465 seconds.
- Two distinct HTTP jobs completed in the same child. All five constructor counts
  stayed at one; use counts advanced from two to three, including warmup.
- A third accepted job reached real child preparation before forced SIGKILL. The
  job failed, original input hashes stayed unchanged, and no partial artifacts
  were published. Idempotent retries still resolved their existing jobs.
- Recovery used one new PID and full warmup, taking 45.092 seconds from the recovery
  polling start. New work stayed rejected during warmup. A subsequent job succeeded.
- Killing that replacement child left readiness false with no further restart.
  Shutdown stopped the HTTP thread and left no resident children.
- All six published artifacts per successful job passed HTTP byte/hash checks.
  Replay retained 242 source-linked frames and 22 joints. Six source/body/joint
  frames were visually inspected in two model views, without claiming camera or
  Quest registration, anatomical accuracy or clinical validation.

The three successful warmed HTTP jobs took 35.661, 35.412 and 35.380 seconds from
submission to persisted success. That includes upload, preparation, inference,
the microscope attempt and publication; it excludes Quest loading/display and
later artifact downloads. Median native runtime was 29.691 seconds. This is the
existing full-resolution completed-upload path, **not** the 640px/15Hz streaming
experiment or its half-second after-capture wait.

Peak Torch allocation was 3.259 GiB; peak reservation was 4.627 GiB in each job.
These are allocator measurements, not total device VRAM. A separate matched cold
FP32/batch-two control took 57.864 seconds in the native runtime. The resident
configuration also changes pose/features to FP16/batch-eight, so that comparison
does not isolate savings from model retention alone.

Numerical equivalence is not claimed. Against the cold control, the two warmed
jobs had median root-relative joint differences of 1.49 and 1.27 millimetres in
model scale, with maxima of 12.23 and 20.58 millimetres. Raw global-joint maxima
were 117.62 and 163.77 millimetres. The comparison also includes unisolated
camera-motion/model variation; it is not a precision-only or ground-truth error
measurement. Inputs, calibration, selected source indices and asset identities
matched. Body alignment and world/root motion still need task-specific validation.

Local verification uses the locked project environment:

```sh
.venv/bin/python -m pytest --cov=processing --cov-branch --cov-report=term-missing -q
.venv/bin/ruff check processing tests
.venv/bin/python -m processing.contracts validate tests/contracts/fixtures
git diff --check
```

The full suite passed 485 tests and 270 subtests, with one real-CUDA check skipped
on the Mac. The model-image run separately passed all nine resident-model tests,
including actual FP16 CUDA weights, FP32 boundaries and batch tails, without skips.
Synthetic subprocess tests cover live orphan lock exclusion, first safe restart,
low storage, recovery overlap, malformed protocol, failed kill/reap/cleanup,
retained evidence and bounded shutdown. Unit coverage is not GPU-model coverage.
