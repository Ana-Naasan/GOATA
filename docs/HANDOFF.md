# Codex session handoff

**Last updated:** September 26, 2026. [PR #10](https://github.com/B2707/HTH-3-sarakbi-asadi-steitieh-grp/pull/10)
merged as `fbbe24f`. The spatial capture follow-up built and installed successfully.
Build 6 recorded all 90 scheduled synthetic frames at 30 fps with verified mux
timestamps and zero drops on two cold launches. Real-camera capture and wearer
acceptance remain pending; M1 and the clinical requirements are still incomplete.

## Current state

- Working branch: `codex/hamza-quest`, checkout
  `/Users/baderasadi/.codex/worktrees/hamza-quest/HTH`, based on `main` at `fbbe24f`.
  The spatial UI/capture implementation commit is `cba5dc9`. Fetch again
  before publishing. The user clarified that Mohammad's update was PR #10;
  verification confirmed it contains `20cf164`, local/remote `main` are `fbbe24f`,
  and no newer remote changes were found at this checkpoint.
- The prior integration source `636746d` built, installed and cold-launched;
  `9973f80` recorded its results before PR #10 merged. Those results do not verify
  the new source below. Earlier UI work used the separate `quest-ui` worktree;
  current changes are in the primary integration checkout.
- Completed in source: bounded capture, private patient/session persistence,
  authenticated client/service integration, native reconstruction export, replay
  controls, evidence routing, microscope processing and native Meta UI Set flow.
- **M1 is still incomplete:** no fresh Quest participant recording has passed
  capture → GPU processing → loaded saved replay. M2/M3 also lack evaluated
  ELK/RTK findings, automated foot assessment and useful real Quest magnification.
- The user authorized filling the gaps and merging to `main`. Deployment, paid
  compute and uploading participant recordings require their own authorization.
- Original deadline: September 27, 2026, 10:00 a.m. EDT.

## Current follow-up: native spatial capture

The user approved Meta's stock UI Set look and separate spatial controls. Source
now uses native UI Set prefabs for a compact workspace, a guidance widget,
a separate Record dock and a detached replay timeline. During capture the large
workspace is hidden. A native non-dominant-hand wrist anchor provides optional
Capture/Replay/Options shortcuts; floating controls remain available. The launcher
requires tracked/confident hand data, input focus, head/palm orientation and a
150 ms reveal delay. Device reach, readability and gesture behavior remain pending.

Guided capture persists **right → front → back → left**, relative to the patient.
Choose **5, 10 or 15 seconds** per take, default 10, before the first saved view;
the duration is then fixed for the assessment. Each view is an independent
performance. Saved selections and immutable retakes recover across crashes.
After all views are saved, the practitioner chooses one source for the ELK/RTK
replay; other takes remain separate evidence. Barefoot uses four viewpoints of
one selected foot, with fixed anatomical side and standing close-up condition.
It creates no full-body replay and does not establish a validated foot protocol.
The existing eight-take API contract is unchanged.

Recording on the prior app dropped from roughly **72 Hz to 3 Hz**. The current
path keeps 1280×960, reuses signed-byte buffers and caches the JNI submit method.
`CaptureReadbacks` permits at most three reads at once, then submits completed
frames in source order. The counter APK identified native encoder admission as
the loss point: all 90 frames reached JNI, but 37 were rejected as busy.

The minimal native fix bulk-writes contiguous Y rows using one reusable two-row
scratch buffer; strided Y and U/V retain the original scalar path. Color math,
2×2 chroma averaging, orientation, dimensions, frame IDs and mux timestamps are
unchanged. Build 5 then accepted 88/90 frames, losing source IDs 3 and 5 during
cold conversion. Build 6 performs six private synthetic conversions before the
encoder reports ready. Warmup never enters the codec queue, source timestamps or
recording counts. Two cold-launch app diagnostics now pass 90/90 with zero drops.
Code, C#, Java and security reviews completed; camera and wearer acceptance remain open.

| Follow-up check | Confirmed result |
|---|---|
| Capture | 100 checks passed. `CaptureBundle` + `CaptureReadbacks`: 146/146 lines (100%), 140/142 branches (98.59%); queue alone 100% lines/branches. Excludes Unity recorder/benchmark, GPU, JNI and native code. |
| Guided workflow | 363 checks passed, independently rebuilt/rerun in C# review. `Physio.Workflow`: 99.28% line / 83.33% branch coverage; excludes Replay, Unity and native code. |
| Spatial presentation | 20 checks passed, including source selection/timing regressions and hand-reveal gates. |
| Existing UI/replay | 12 evidence-routing checks and 136 replay checks passed at the UI checkpoint. |
| Native synthetic encoder | 90 frames / 2.360 seconds / 38.13 fps; source-to-mux verification passed, no camera opened. |
| Native conversion | Strict `javac -Xlint:all -Werror` passed. Four color checks, 1,600 exact scalar/bulk layout comparisons, malformed scratch/limit checks and warmup scratch isolation passed. |
| Bulk-luma native trials | Paced cloned frames: 90/90 accepted, zero busy. Saturated run: 47.52 fps, all 90 mux timestamps verified. Subsequent warmup trial counted six warmups separately from 90 actual conversions/encoded frames. |
| Final synthetic app diagnostic | Build 6, two cold launches: 90 observed/read back/submitted/accepted each, zero misses, maximum pending two, 30.00 source fps, mux verified and `complete_without_drops=True`. See exact timing and exclusions below. |

Main changed paths: `QuestTakeRecorder.cs` and `.Benchmark.cs`, `CaptureBundle.cs`,
`CaptureReadbacks.cs`, Android `PhysioMp4Recorder.java`/`PhysioYuv420.java`,
`CaptureYuvChecks.java`,
`LocalPatientStore.GuidedCapture.cs`, shared workflow data/archive merge,
`WorkflowPanel.Capture.cs`, `SpatialCaptureOverlay.cs`, `SpatialCapturePresentation.cs`,
`HandSpatialMenu.cs`, the native scene builder, viewer/replay bindings and their
checks. Saved-draft recovery and archive work run off the Unity thread. Capture
text updates at 10 Hz and button listeners are bound once.

Finding details now include method name/version. Matching-take finding intervals
use the existing replay clock to gate joint highlights while the detached timeline
is visible; other-take evidence remains separate and paused. This wires the UI,
but the current processing pipeline still returns `findings: []` and marks
movement/foot assessment unavailable. Mohammad owns the missing evaluated
analysis; a reconstructed body is not an exercise finding.

Guidance explains that the camera captures less than the visible passthrough.
A calibrated projected framing overlay has not been implemented or validated.
Official Meta UI Set and the `meta-quest/agentic-tools` guidance inspected at
revision prefix `3a8553d` informed the source; neither is device acceptance.

### Final build and capture diagnostics

Evidence root: `/Users/baderasadi/Library/Caches/HTH/spatial-proof/`.

`build-final-6.log` completed successfully with exit 0. All 30 entries in
`frozen-source-6.json` still match the source. The installed APK is
`quest/Builds/PhysioFixture.apk`, **85,550,160 bytes**, SHA-256
`288773c47457da9109bf3a5446d3fcb19e566e072d2d7a664836d9b863972356`.
Installation used `adb install -r`; implementation commit: `cba5dc9`.
After both diagnostics, the app was relaunched normally without the benchmark intent.

| Final app measurement | First cold launch | Repeat cold launch |
|---|---|---|
| Log / PID / time (EDT) | `unity-benchmark-6.log` / 11437 / 21:45:02–05 | `unity-benchmark-6-repeat.log` / 11854 / 21:45:26–29 |
| Observed / read back / submitted / accepted | 90 / 90 / 90 / 90 | 90 / 90 / 90 / 90 |
| Missed / maximum pending | 0 / 2 | 0 / 2 |
| Source span / effective rate / wall time | 2.967 s / 30.00 fps / 3.428 s | 2.967 s / 30.00 fps / 3.415 s |
| Average callback / copy / JNI; maximum JNI | 39.769 / 0.469 / 2.412 ms; 3.435 ms | 39.823 / 0.486 / 2.438 ms; 3.298 ms |
| Native warmup count / duration | 6 / 269.836 ms | 6 / 264.045 ms |
| Actual conversion count / total / maximum | 90 / 2762.681 / 37.307 ms | 90 / 2773.694 / 35.653 ms |
| Native input wait / drain / lifetime | 7.715 / 46.681 / 3390.197 ms | 7.815 / 50.852 / 3373.857 ms |
| App FPS samples during recording / target | 71, 71, 73 / 72 | 70, 72, 72 / 72 |
| Final mux / complete without drops | Verified / True | Verified / True |

Earlier failed probes remain useful evidence: `unity-benchmark.log` accepted
52/90 with 38 readback misses; `unity-benchmark-4.log` reached JNI for all 90 but
accepted 53/90 with 37 `encoder_busy`; `unity-benchmark-5.log` accepted 88/90 with
two `encoder_busy` misses (source IDs 3 and 5, confirmed from mux timestamps).
Each verified its accepted mux frames but reported incomplete capture. Build 6's
pre-readiness warmup removed those losses in both measured synthetic runs.
Native-only trial details remain under
`/Users/baderasadi/Library/Caches/HTH/recording-perf/production-bulk/`.

The app diagnostic uses a synthetic GPU texture and opens no camera. It excludes
camera delivery, per-frame journal writes, the actual capture page and participant
processing. Head pose remained untracked in both runs. Native hand configuration
passed `scene-hand-verified.log`; wearer/layout/gesture acceptance remains pending.
These three-second runs do not establish sustained real recording or active replay
performance. Reproducible commands are in `quest/README.md`.

**Next acceptance:** test the actual camera with consent, guided-view progression,
stop/retake/restart recovery, hand shortcuts, floating controls and evidence/replay.
Record actual outcomes here. Fresh participant capture-to-GPU-to-replay, clinical
methods and full-path latency remain incomplete.

## PR #10 implementation baseline

| Area | Files and implemented behavior |
|---|---|
| Exact frame binding | `processing/media_timing.py`, contracts/schema, reconstruction runtime and `tests/contracts/test_media_binding.py`: preserve camera nanoseconds; validate a separate indexed mux-microsecond mapping, including Android truncation. |
| Reconstruction export | `processing/export.py`: bounded native arrays/hashes, common Z reflection for body/joints, winding conversion, preserved root motion, one fitted row per source frame plus complete inference mapping. |
| Service integration | `processing/pipeline.py`, settings/service and backend tests: one local subprocess, deadline/scratch limits, validated result publication, explicit unavailable assessment methods. |
| Microscope | `processing/microscope.py` and tests: source-timed original/amplified artifacts, conservative background/foreground-motion and noise rejection, bounded decoding, rollback of only newly created outputs. |
| Quest capture | `quest/Assets/Physio/Capture/`, Android plugins and capture checks: permission/countdown/stop/interruption, original source times, native AVC/MP4, verified encoded PTS, immutable capture bundles. |
| Quest workflow | `quest/Assets/Physio/Workflow/` and checks: private UUID-based patients/history, accepted-upload retries, persisted jobs/results, bounded authenticated downloads, versioned reprocessing and original evidence extraction. |
| Quest replay/UI | `quest/Assets/Physio/Replay/`, `Viewer/`, `Editor/` and checks: bounded importer, playback clock, native Meta controls, patient/test context, capture/processing/review, findings, foot status and microscope evidence. |
| ML foundations | `processing/reconstruction/`, `processing/analysis/` and `tests/ml/` from Mohammad: real GPU adapter, candidate ELK classifier machinery and manually annotated foot geometry. These do not establish working automated assessments. |

Review fixes include capture saving after focus loss, invalidated permission
callbacks, actual-file-size checks before allocation, crash recovery that preserves
original media, background file/JSON work, source-to-video evidence seeking,
clearing old geometry for a result without replay, correct Options navigation,
and timing the first displayed result after an end-of-frame boundary. The UI
labels wall-clock timing after restart as an estimate; continuous capture/display
uses a monotonic interval. No measured full-path result is claimed yet.

A separate steady-hold take can supplement the same test. The new saved assessment
retains the primary recording and earlier versions; only the selected primary
take drives 3D replay. Other-take evidence leaves the body paused.

## Run and verify

From the integration checkout:

```sh
uv sync --locked --python /opt/homebrew/bin/python3.11 --extra microscope
uv run --locked --extra microscope pytest --cov=processing --cov-report=term-missing -q
uv run --locked --extra microscope ruff check processing tests
uv run --locked --extra microscope pip-audit --progress-spinner off
uv run --locked --extra microscope python -m processing.contracts validate tests/contracts/fixtures
git diff --check
```

The README has service configuration and API examples. The Quest guide has exact
C# checks and Unity build commands. Test discovery includes backend, contracts
and ML tests. The `microscope` extra is required for the complete codec/microscope
checks. The service environment and GPU environment are separate.

### PR #10 verified checkpoint

These are the previous integration results. They remain valid historical evidence;
they do not substitute for the follow-up build/device checks above.

| Check | Verified outcome and limit |
|---|---|
| Python suite | 346 passed; 165 unittest subtests also passed; 89.57% branch-inclusive coverage across all `processing` modules, with none excluded. GPU-specific `gvhmr.py` was only 19% covered by CPU tests. |
| Lint and API | Ruff and OpenAPI validation passed. Authored staged whitespace checks passed. Preserved upstream/Unity-generated assets contain trailing whitespace/CRLF; no clean global whitespace result is claimed. |
| C# client over real TCP | Actual `ProcessingClient` passed multipart upload, polling, authenticated download, cached reopen, same-name patient isolation, reprocessing and older-version reopen against FastAPI on loopback. Worker/media were explicitly synthetic; no GPU/Quest rendering claim. Local harness and output: `/Users/baderasadi/Library/Caches/HTH/integration-proof/client-http/`. |
| Dependencies | `pip-audit` checked 61 installed packages and reported no known vulnerabilities. |
| Capture checks | 54 checks passed. The preceding 53-check coverage run measured 100% lines / 98% branches in testable capture logic. Native Unity/device behavior is outside that denominator. |
| Workflow checks | 283 checks passed. The preceding 282-check coverage run measured 99.6% lines / 81.47% branches in the tested workflow assembly. |
| Importer checks | 173 passed; 98.56% lines / 87.71% branches in importer/data files. |
| Replay / demo / UI | 136 replay/input-edge checks, 19,827 authored-demo checks and 12 evidence-routing/paging checks passed. Synthetic data verifies mechanics only. |
| Microscope | 33 tests passed; 86.4% coverage in that module at its review checkpoint. |
| Independent review | Code, C#, Java, Python and security source reviews completed; identified blockers were fixed. Final source/build checks still apply after subsequent changes. |
| Real native geometry import | The C# importer loaded 242 frames, 10,475 vertices and 22 joints in 291 ms on Mac. This does not measure Quest load/render latency. |
| Staged inventory | Final integration staged inventory inspected: no participant media, keys, model weights or secret-pattern hits. Third-party sample/font licenses retained. Unity temporary build assets are excluded. |
| Integrated Unity build | Final frozen source built successfully (exit 0), installed and cold-launched on Quest. APK: 85,431,296 bytes; SHA-256 `6f16d5dd100fcdfce58ffbad8a88204c9961245decaf65641953b34387c82dac`. Build log: `/Users/baderasadi/Library/Caches/HTH/integration-proof/integration-build-final.log`. Intermediate build 2 was cancelled before the final-source build. |

### PR #10 and earlier device evidence

- Final APK installed and cold-launched at approximately 20:12 EDT. Startup logs
  show configured native manipulation and input focus, with no captured C# exceptions.
  Placement waits for a tracked head; the screenshot does not establish layout
  acceptance because the headset was not tracking a wearer. The user has been
  asked to check readability, patient keyboard and Menu/Options physically.
  Log: `/Users/baderasadi/Library/Caches/HTH/integration-proof/final-startup.log`.
- A Quest 3 is connected and authorized through ADB. The official camera sample
  built/installed and the user confirmed a live moving camera image at 16:16 EDT.
  This proves camera display, not fresh recording metadata or calibrated geometry.
- The earlier synthetic fixture passed startup visibility/gap checks on the
  device; controller seek, frame-step and reset input were observed. The newer
  native-hands diagnostic build installed and launched at 18:30 EDT without its
  earlier rig assertions. It awaited valid head tracking; new UI hand/poke/grab
  interactions and comfort have not been accepted by a wearer.
- A **synthetic native encoder device check** encoded 12 frames at 1280×960,
  verified mux/source timestamp association and decoded color orientation. It
  opened no camera and recorded no participant. It does not test the complete
  Unity camera/readback/encoder path or sustained performance.
- No final-layout visual acceptance, 72 Hz active replay benchmark, 250 ms seek
  measurement or real capture-to-loaded-result measurement exists yet.

### GPU and real-video evidence

The original public WHAM derivative ran through tracking, ViTPose, HMR2 features,
SimpleVO, GVHMR and native SMPL-X export on the RTX 3070: **242 frames, 10,475
vertices, 20,908 triangles and 22 joints; 58.623 seconds CLI local elapsed**.
Artifact hashes were checked. This duration excludes capture, upload, service
wait, download and Quest loading. Exact upstream/assets/runtime provenance and
historical failures remain in [GPU setup](../processing/reconstruction/GPU_SETUP.md).

The original smoke sidecar has legacy extra provenance and lacks `capture.gaps`;
it does not pass the production upload schema. A local geometry-only export
check verified its arrays/transform/mappings but deliberately bypassed that old
sidecar schema. It is not a successful service run. Original source files and
hashes remain unchanged.

A new strict sidecar and updated source snapshot are staged for a **new inference**
under `/home/bader/physio-reconstruction/integration-20260926/` on Arch. Docker
requires an interactive sudo password. The user has been asked to run:

```sh
ssh -t arch 'sudo sh /home/bader/physio-reconstruction/integration-20260926/run-gpu-proof.sh'
```

Completion is pending. It uses only the existing public demo. Inspect the new
output/handoff, run strict export validation, then inspect the real geometry in
Quest. Do not attribute the new sidecar or current adapter hashes to the old run.

The real public source did not pass microscope background-coverage checks.
No amplified result was produced. A positive real Quest steady-hold example,
negative controls and artifact inspection remain required.

## Verified environment and configuration

- Mac: macOS 26.6.2 arm64, Python 3.11.10, uv 0.11.21; .NET SDK 8.0.425 at
  `/Users/baderasadi/Library/Caches/HTH/dotnet`.
- Unity 6000.0.66f2; Meta MRUK/Interaction SDK 85.0.0; OpenXR 1.15.1;
  Newtonsoft JSON Unity package 3.0.2. Package locks are in `quest/Packages/`.
- Android toolchain: Temurin JDK 17.0.9+9, NDK r27c (27.2.12479018), target
  API 34, ARM64. Quest reports Android 14/API 34; the human-readable Horizon OS
  version has not been verified. ADB 37.0.1 is available.
- Service lock: FastAPI 0.141.1, Starlette 1.7.0, Uvicorn 0.54.0, NumPy 2.4.6,
  OpenCV headless 4.14.0.94 and PyAV 16.1.0. See `uv.lock` for all exact versions.
- GPU: Arch Linux, NVIDIA RTX 3070, driver 615.71.09; image
  `physio-gvhmr:ee960bb`, pinned GVHMR `ee960bb6e2ea2d381aa97f08e9b71ef320b624b1`.
  The model image uses Python 3.10.14, torch 2.3.0+cu121, PyAV 13.0.0,
  NumPy 1.23.5 and OpenCV 4.10.0.84. Do not replace its tested model dependencies
  with the service's microscope environment.

Configure `PROCESSING_INFERENCE_COMMAND` as JSON argv and
`PROCESSING_INFERENCE_CWD` as the installed model checkout. Defaults are a
900-second deadline and 768 MiB inference scratch budget. The default unconfigured
worker fails honestly for reconstruction. No remote service has been deployed.

Both calibration opt-ins default false: `PROCESSING_ALLOW_ESTIMATED_INTRINSICS`
and `PROCESSING_ALLOW_UNVERIFIED_PINHOLE`. Quest preserves the SDK intrinsics,
unknown lens distortion and unavailable image-time pose. The latter opt-in allows
only unknown distortion with empty coefficients, records an unverified pinhole
assumption, and labels processing intrinsics estimated. It does not alter the
original, prove rectification or provide physical body scale.

## Next concrete tasks and incomplete requirements

1. Complete the real-camera/wearer checks above; build 6 and both synthetic app
   runs passed. Inspect the final changes and fetch `main` before the authorized
   PR/merge. Record actual outcomes without treating
   synthetic capture as participant or clinical acceptance.
2. Finish the new GPU proof after interactive Docker access. Exercise the actual
   service with verified current output and then a consented fresh Quest capture.
   Validate camera/mux timing, intrinsics/distortion policy, image orientation,
   one-person tracking, asymmetric geometry, winding and joint/body alignment.
3. Have the wearer test the final native UI: patient creation, test selection,
   permission denial/retry, interruption, save/reopen, upload retry, results,
   evidence, standard Menu/Options, one-hand use, grabs, rotation and resizing.
4. Establish real ELK and RTK methods with authorized data and participant-held-out
   evaluation. The current ELK candidate and protocol files are foundations;
   no classifier is installed to produce genuine supported findings.
5. Establish automated foot landmarks/calibration/reference validation. Current
   manual dorsal-height geometry is not an automated foot assessment.
6. Validate a dedicated steady-hold microscope take with a suitable background
   and negative controls. Reject visible camera/noise artifacts; keep numerical
   analysis on originals.
7. Measure the full 1–2 minute path, active 72 Hz rendering and 250 ms seeking.
   Record shortfalls instead of inferring performance from local model duration.

Do not mark M1–M4 or all branch tasks complete based on these component checks.
