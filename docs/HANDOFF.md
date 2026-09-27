# Codex session handoff

**Last updated:** September 27, 2026. The UI redesign **0.3.0 / Android code 7**
is built, installed wirelessly and cold-launched on Quest 3. Source is on
`codex/hci-quest-ui` in `/Users/baderasadi/.codex/worktrees/hci-quest-ui/HTH`, based
on `main` at `1a9f9e3`. M1 and clinical evaluation remain incomplete: no new
participant capture → GPU → loaded saved review was verified during this UI work.

## UI redesign and wireless deployment

The user authorized the UI/workflow rebuild, then installation and remote push.
The source baseline is the latest available checked-in checkout above; the prior
on-device 0.2.4 package was backed up locally before updating to 0.3.0.

- One Meta UI Set workspace, compact replay HUD, consistent colours, bounded
  movable uniformly scaled panels, source-linked anatomical highlighting and
  grounded initial replay at 1x reconstructed source scale.
- Explicit camera framing before countdown; elapsed capture/processing clocks;
  animated ELK/RTK/Walking movement dropdowns hidden during framing/recording and
  during supplemental microscope steady holds. Patient/test/view context remains.
- Optional stationary Moon facility with Earth, Kenney assets and a passthrough
  resume gate before capture. Play mode adds presentation-only head nudges and
  transient tomato splats. Real-room wall splats remain incomplete.
- Physical size is still estimated reconstruction scale, not measured height.
  Source recordings, metrics, original-frame mappings and clinical scope remain.

Unity **6000.0.66f2**, Meta Interaction SDK **85.0.0**, Android API 34/ARM64:
`FixtureBuild.Build` exited 0 with `Build Finished, Result: Success`.
APK: **86,281,822 bytes**, SHA-256
`37cfc5b99c5a3106f06dd64e92663ee122902dc4b14fa791adc2f98af4e7759e`.
`adb -s 10.198.154.65:5555 install -r quest/Builds/PhysioFixture.apk` succeeded on
Quest 3 serial `2G97C5ZH95010L`. Installed APK hash matches, and all **257** saved
app files matched their pre-install hashes before launch. No app data was cleared.
`am start -W` reported `Status: ok`, `LaunchState: COLD`; startup PID 26421 reached
tracked-head placement and `PHYSIO_VIEWER_READY` without a managed exception in
the sampled log. This verifies installation/startup, not wearer acceptance.

C# checks passed: Replay **136**, Importer **174**, Capture **104**, Workflow
**673**, UI evidence **33**, Spatial capture **33**, authored Demo **19,827**.
General/C# review and the scoped security/asset-publication review found no
remaining blocker. `pip-audit` found no known vulnerabilities; C#/Markdown
whitespace checks passed. Unity's generated scene is retained for opening the
updated interface; the unrelated TMP serialization migration was restored.

Build and deployment proof, prior APK and local screenshot are outside Git at
`/Users/baderasadi/Library/Caches/HTH/hci-ui-deploy-030/`. Imported asset provenance
is in `quest/Assets/Physio/Art/{Moon,Tomato}/ASSET_SOURCES.md`; no participant media,
APK or credentials are committed. Main code changes are the scene builder,
capture presentation/recorder, replay placement/insights/HUD, movement examples,
panel bounds and environment/play interaction components.

Next: wear the headset and accept panel size/reach, camera framing, saved replay
timeline, grounded scaling, Moon/passthrough transition and Play controls. New
captures require the separately configured authenticated processing service;
this deployment updated the Quest client only. Historical milestones below are
retained as evidence, not new verification of this release.

## Mohammad's persistent inference experiment review

Reviewed Mohammad's `7db2d4c` against `main` at `554d4b7` on
`codex/bader-ml-optimization-review`. Integration fix `2a24986` preserves the
original commit and changes only the experiment: supplied, unverified fixture
calibration remains `estimated`, and rounded source-clock endpoints retain the
last eligible 15 Hz observation. Regression tests failed before both fixes and
passed afterward. Python, ML runtime, general and security reviews found no
remaining blocking issue within the documented public-fixture experiment.

This adds an offline benchmark, **not production acceleration**. The service
still starts fresh inference processes. It does not enable streaming or establish
Quest turnaround, clinical accuracy or numerical equivalence between persistent
and fresh processes. The benchmark covers four independent two-second public
WHAM takes, with all five models retained on CUDA and fresh tracking state per
take. Preserve the original historical measurements in `rtx3070-fp32.json`.

Verification uses Python **3.11.10** and the locked microscope dependencies:

```sh
uv sync --locked --extra microscope --python /Users/baderasadi/Documents/ChatGPT/HTH/.venv/bin/python
.venv/bin/python -m pytest --cov=processing --cov-branch --cov-report=term-missing -q
PHYSIO_ULTRALYTICS_SOURCE=/Users/baderasadi/Library/Caches/HTH/ml-optimization-review-7db2d4c/ultralytics PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" .venv/bin/python -m unittest discover -s experiments/persistent_inference -v
.venv/bin/ruff check processing tests
.venv/bin/pip-audit --progress-spinner off
.venv/bin/python -m processing.contracts validate tests/contracts/fixtures
```

- Processing: **398 passed, 177 subtests passed**, one existing warning;
  **90.20%** combined line/branch coverage.
- Experiment: **44 tests passed, no skips**, including hash-checked Ultralytics
  8.2.42 source checks. CPU coverage is **68%** across all eight experiment modules,
  **84%** excluding CUDA adapter/model wrappers (`adapter.py`, `models.py`). Real
  GPU execution supplements those exclusions; it is not a GPU coverage measure.
- Processing/tests Ruff, dependency audit, contract fixtures, all 18 experiment
  checksums and whitespace validation passed. Experiment source retains its
  existing Ruff style/import diagnostics; no experiment-wide lint pass is claimed.
- An initial Python **3.13.9** run had one failure:
  `test_json_rejects_invalid_utf8_and_deep_nesting`. The same failure reproduced
  on unchanged `main` at `554d4b7`; the merge does not fix that separate runtime
  compatibility issue. Use the verified 3.11 environment for this checkpoint.

Fresh GPU verification of original `7db2d4c` completed on the existing RTX 3070:
**36.178 seconds** for the persistent process versus **84.419 seconds** total
for four fresh processes; subsequent takes took **4.896 / 4.993 / 5.060 seconds**.
All 64 native artifact sizes/hashes across eight outputs, finite geometry,
dimensions, source mappings and model counts passed independent verification.
The first persistent/cold 3D pair matched exactly; later pairs differed alongside
VO estimates, so full numerical equivalence remains unproven.

The first corrected-code GPU attempt failed honestly at pose-model construction
with CUDA OOM while another benchmark occupied 6,384 MiB. It completed zero takes,
applied no fallback and is excluded from performance results. Existing workloads
were left running. After that workload exited, corrected source **`2a24986`**
completed the same full benchmark in `output/resident-reviewed-002`:

- Persistent process: **36.427 seconds**; four fresh processes: **85.100 seconds**
  total, approximately **2.34 times** the persistent duration.
- Subsequent takes: **4.942 / 5.033 / 5.075 seconds**. First output after process
  launch: **20.454 seconds**. Shared input splitting: **4.491 seconds**, excluded
  from the process comparison. Network, preview and Quest loading are excluded.
- Peak PyTorch allocation/reservation: **6,190,825,984 / 6,423,576,576 bytes**;
  these are allocator measurements, not whole-device memory or replica capacity.
- All **64** corrected native artifacts passed size/hash, finite geometry,
  topology and original take/frame/time mapping checks. All eight outputs report
  estimated intrinsics. Each model was constructed once and used four times;
  all 12 recorded code hashes matched the frozen runtime. Inputs, assets, tracks,
  boxes and keypoints matched the fresh-process controls. Later 3D outputs still
  differ alongside VO; this run does not establish numerical equivalence.
- The existing image identity is
  `sha256:66db73a15b803aa99aa47f8929ec2acd7e5d30ee84332dad8c1b62e254beeddc`,
  GVHMR `ee960bb6e2ea2d381aa97f08e9b71ef320b624b1`. All 49 frozen source files
  were checked against commit `2a24986`. No model or dependency was upgraded.

Both successful runs used the bounded, non-networked Docker command in
`processing/reconstruction/GPU_SETUP.md`, with the matching frozen source mounts
and isolated output path. The final in-container command was:

```sh
python /experiment/benchmark.py --video /input/drone_video.mp4 --calibration /input/drone_calib.txt --output /output/resident-reviewed-002 --residency resident --timeout-s 900
```

Proof logs and reports are outside Git:
`/Users/baderasadi/Library/Caches/HTH/ml-optimization-review-7db2d4c/`.
Remote source, inputs and outputs are isolated under
`/home/bader/physio-reconstruction/ml-merge-review.Z1xzK1/`.
No participant recording, checkpoint, credential or generated media was committed.

Next: establish repeatable numerical comparison before promoting this runner
into the processing service. The fresh Quest capture-to-loaded-review and clinical
validation gaps below remain open.

## Walking and insights checkpoint

The user approved the plan in `docs/INSIGHTS_PLAN.md` and replaced **new** barefoot
capture with Walking review. The three new choices are ELK, RTK and Walking.
Historical barefoot drafts/results/reprocessing retain their identity and readers.
Walking uses four independent right/front/back/left passes, full body and feet in
view, with one selected source take for replay. It is not a validated gait test.

Result schema **1.1** adds bounded estimated `observations`; capture/replay remain
1.0. Historical result 1.0 remains strict and readable. Existing GVHMR joints feed
one deterministic geometry helper: ELK lateral torso lean, RTK absolute shortest
shoulder/pelvis rotation, Walking left/right knee flexion and unsigned trunk lean.
Each peak retains its exact original frame/time/take. Invalid or degenerate samples
are unavailable, not zero. Finite fitted joints do not establish visibility or
anatomical accuracy. Clinical `findings` stay empty and assessment unavailable.

The Meta UI Set board has observation cards, a separate Assessment tab, source
labels, limitations, method details, a region bracket/label and timeline marker.
The larger original view opens paused at the measured source moment; explicit
full-recording playback supplies context and Return to peak restores evidence.
Version/date/patient context and the existing capture-to-display timing label stay
visible. An optional wrist Insights shortcut opens review. Physical readability,
hand reach and actual VideoPlayer seeking still need wearer acceptance.

Main changed files: `processing/analysis/observations.py`, `pipeline.py`,
`publication.py`, `docs/openapi.yaml`; Quest `WorkflowValidation.cs`, patient store
and capture protocol checks; `InsightPresentation.cs`, `WorkflowPanel.Insights.cs`,
`EvidencePanel.cs`, viewer region/timeline bindings and `HandReviewSceneBuilder.cs`;
their Python/C# checks and scope/runbook documentation. No new dependency, chat
model, queue or server framework was added.

### Automated verification

- Python: **398 passed, 177 subtests passed**, one existing warning; combined
  processing line/branch coverage **90.20%**. Geometry helper **98.51%**, pipeline
  **92%**, publication **98%**. Native GVHMR inference remains mostly outside unit
  coverage and was exercised separately below.
- C#: Workflow **673**, Capture **104**, UI evidence **33**, Spatial **26** checks;
  Replay **136**, Importer **173** and authored Demo **19,827** checks also passed.
  Workflow coverage **99.33% lines / 84.76% branches**; Capture **100% / 98.68%**;
  presentation helpers **98.43% / 77.65%** and spatial presentation **100% / 84.09%**.
  These exclude Unity, camera/GPU/JNI, native video playback and physical input.
- Python, C# and general code/security reviews approved with no blocking findings.
  Reviewed compatibility, bounded artifacts, patient/take isolation and source
  mappings. No credentials, recordings, weights or build artifacts were added.
- Ruff, contract fixture validation and dependency audit passed. `dotnet format`
  reports whitespace diagnostics in the compact `WorkflowChecks.cs`; its build and
  checks pass. This is not a formatting-clean claim.

Commands from the worktree (proof reports under
`/Users/baderasadi/Library/Caches/HTH/insights-proof/`):

```sh
.venv/bin/python -m pytest --cov=processing --cov-branch --cov-report=term-missing --cov-report=json:/Users/baderasadi/Library/Caches/HTH/insights-proof/python-coverage.json -q
.venv/bin/ruff check processing tests
.venv/bin/pip-audit --progress-spinner off
.venv/bin/python -m processing.contracts validate tests/contracts/fixtures
/Users/baderasadi/Library/Caches/HTH/dotnet/dotnet run --project quest/Checks/WorkflowChecks.csproj --no-restore
# Same command for Replay, Importer, Capture, UIEvidence, SpatialCapture and Demo.
```

### Fresh GPU proof

Fresh SSH after group membership changed confirms `bader` has Docker access.
The existing `physio-gvhmr:ee960bb` image on the RTX 3070 ran the public WHAM
football-field walking clip (8.075 seconds, 242 source frames) in **57.783 seconds**.
This is inference CLI time, excluding upload/download and Quest loading.
The sidecar uses explicitly adapted fixture clock/condition metadata; it does not
prove Quest calibration or clinical accuracy. No participant capture was uploaded.

Image identity:
`sha256:66db73a15b803aa99aa47f8929ec2acd7e5d30ee84332dad8c1b62e254beeddc`.
GVHMR revision: `ee960bb6e2ea2d381aa97f08e9b71ef320b624b1`.
Input SHA-256: `c010567f80e5813c2d1e2811510062dcf9de5a9190a7084c3e253b75ed11b895`.
Remote proof: `/home/bader/physio-reconstruction/insights-proof.UJO3hy/`.
The container ran as UID/GID 1001, without networking, with read-only source,
checkpoint and input mounts, bounded memory/CPU/time and an isolated output folder.
Existing weights were reused; no new model or clinical dataset was installed.
Verified image runtime: PyTorch **2.3.0+cu121**, torchvision **0.18.0+cu121**,
NumPy **1.23.5**, PyAV **13.0.0**, SMPL-X **0.1.28**, pycolmap **4.2.0** and
Ultralytics **8.2.42**. The proof JSON records each model asset's SHA-256.

The fresh 32.57 MB native handoff downloaded in 13.292 seconds. Current local
pipeline code then copied the precomputed GPU boundary, exported the body/joints,
attempted the real microscope gates and generated observations in 7.479 seconds;
publication validation took 0.689 seconds. All source/archive/native hashes matched.
The 242-frame, 22-joint replay produced three estimates: left knee 78.06° at original
frame 178, right knee 79.01° at frame 163, trunk inclination 4.12° at frame 9.
These are software outputs, not accuracy claims. The microscope correctly remained
unavailable because background features did not cover enough of the image.
Proof and exact stage commands: `insights-proof/fresh-publication-proof.json` and
`run_fresh_publication_proof.py` under the cache root above. GPU and local stages
were separate; their durations must not be presented as a Quest end-to-end result.

The strict C# client saved the public capture, validated result 1.1 and artifact
hashes, imported 242 frames / 22 joints / 10,475 vertices, then reopened the saved
result after recreating the store. Desktop import took 0.195 seconds and reopen
0.157 seconds; these exclude Quest rendering. The isolated fixture is labelled
**PUBLIC DEMO - WALKING**, with patient UUID
`90e3a7ab-f268-4efb-b60a-b81d96bd215c` and session UUID
`8e323675-63ba-45fe-a694-da817995a6f8`. Its cache archive contains only those paths;
do not overwrite another patient or session when copying it for device testing.

### Quest build and installation

Unity **6000.0.66f2** completed `FixtureBuild.Build` successfully; log:
`insights-proof/unity-build.log`. Native hand/controller rig validation passed.
The APK is **85,583,680 bytes**, SHA-256
`91920fa27f6f3d860b3bdd4a67e519b46c1543fb771b8ea687c7326c2131f3b9`.
`adb -s 2G97C5ZH95010L install -r quest/Builds/PhysioFixture.apk` succeeded;
the installed package's SHA-256 matches. All 105 frozen source inputs match after
restoring the known build-generated scene/font/settings changes. The generated
scene is preserved in the proof cache; `FixtureBuild.Build` regenerates it from
the reviewed scene builder. No new runtime code changed after this build.

The isolated public demo was copied into the existing app store only after both
UUID paths were confirmed absent; all **13 files** matched their cache hashes.
Other patients/settings were preserved. `am start -W` reported a successful cold
launch; PID 32444 logs reached tracked-head placement and `PHYSIO_VIEWER_READY`
without managed exceptions in the startup sample. The local screenshot confirms
passthrough, hand tracking and the workspace Options surface, not the insight or
video interaction acceptance. Proof: `startup-proof.json`, `quest-startup.log`,
`device-public-demo-proof.json`; screenshot remains local, outside Git.

Current next task: wearer opens **PUBLIC DEMO - WALKING**, verifies all three
cards, source-peak seeking, full-recording playback and return-to-peak. The device
currently has no processing URL/token configured, and Wi-Fi reports disconnected.
The 1.1-capable client is installed; remote service deployment/configuration is
still required before fresh captures can use it. Then test a consenting real
Walking take, four-view progression, saved review, original-frame agreement and
measured full turnaround. Evaluated ELK/RTK clinical labels and useful real-camera
microscope output remain incomplete. Older checkpoints below are historical evidence.

## PR #11 build checkpoint

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
