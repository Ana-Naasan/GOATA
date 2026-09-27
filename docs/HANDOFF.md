# Codex session handoff

**Last updated:** September 26, 2026. Integration source `636746d` built, installed and cold-launched successfully. The integrated change is tracked in [PR #10](https://github.com/B2707/HTH-3-sarakbi-asadi-steitieh-grp/pull/10).

## Current state

- Working branch: `codex/hamza-quest`, checkout
  `/Users/baderasadi/.codex/worktrees/hamza-quest/HTH`, based on `main` at `fc8cd51`.
  Integration commit `636746d` has parents `fc8cd51` and Mohammad's `20cf164`, preserving both histories. It is pushed to `origin/codex/hamza-quest`.
- `origin/main` was still `fc8cd51` at the final pre-PR fetch. Mohammad's `20cf164` is included as a merge parent; no teammate history was overwritten.
- UI work ran separately in `/Users/baderasadi/.codex/worktrees/quest-ui/HTH`.
  Its final Viewer/scene-builder files are copied into the integration checkout. The frozen source hashes remained unchanged through the final build.
- Completed in source: bounded capture, private patient/session persistence,
  authenticated client/service integration, native reconstruction export, replay
  controls, evidence routing, microscope processing and native Meta UI Set flow.
- **M1 is still incomplete:** no fresh Quest participant recording has passed
  capture → GPU processing → loaded saved replay. M2/M3 also lack evaluated
  ELK/RTK findings, automated foot assessment and useful real Quest magnification.
- The user authorized filling the gaps and merging to `main`. Deployment, paid
  compute and uploading participant recordings require their own authorization.
- Original deadline: September 27, 2026, 10:00 a.m. EDT.

## What changed

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

### Verified checkpoint

These results were reported by the implementing/reviewing sessions and final
combined checks. Final APK/device acceptance remains separate.

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

### Device evidence

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

1. Confirm PR #10 status against remote `main` (`gh pr view 10`, `git log -1`).
   The source build, installation and automated checks are complete; feature
   acceptance below remains open. Do not reclassify those checks as full product completion.
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
