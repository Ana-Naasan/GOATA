# Quest app

**Last updated:** September 27, 2026. The UI redesign with restored automatic
connection setup and corrected camera encoding is version **0.3.2 / code 9**
on `codex/hci-quest-ui`, based on `main` at `1a9f9e3`. It uses one main workspace,
a compact replay HUD, bounded movable panels, explicit camera framing/countdown,
visual movement examples, grounded replay, anatomical evidence highlights and an
optional Moon environment with Play mode. `docs/HANDOFF.md` records current build
and installation evidence. Wearer acceptance and clinical evaluation remain
incomplete; automated checks and startup logs do not establish physical usability.

Walking review and estimated observations remain available alongside ELK/RTK and
historical barefoot sessions. **PUBLIC DEMO - WALKING** is a fixture with adapted
capture metadata, not a participant assessment. New captures still require a
configured authenticated processing service. No service deployment is implied by
installing this client APK.

## Open and build

Open this directory as a Unity project with **Unity 6000.0.66f2** and its Android
Build Support, SDK/NDK and OpenJDK modules. Verified packages are Meta MRUK and
Interaction SDK **85.0.0**, OpenXR **1.15.1** and Newtonsoft JSON **3.0.2**.
The app targets Android API 34/ARM64 on Quest 3.

From the repository root on the configured Mac:

```sh
BEE_BUILD_THREADS=6 \
  /Applications/Unity/Hub/Editor/6000.0.66f2/Unity.app/Contents/MacOS/Unity \
  -batchmode -quit -buildTarget Android -job-worker-count 2 \
  -projectPath "$PWD/quest" \
  -executeMethod FixtureBuild.Build \
  -logFile /tmp/physio-quest-build.log
```

Output: `quest/Builds/PhysioFixture.apk`. The retained package ID is
`com.hth.physio.fixture`; installing it replaces the earlier diagnostic app.
The build method validates both authored resource sets, constructs the scene
from the proven camera rig, configures native interaction and checks for missing
scripts. UI assets and TMP Essentials are included locally with their licenses.

`FixtureBuild` uses `CleanBuildCache`. Earlier reuse of the sample's Library
packaged surplus serialized asset chunks and stalled Android startup. Keep the
clean build until cache behavior has been independently verified. Generated
Library/Temp/Builds, .NET `bin`/`obj`, reports and detection weights are ignored.

After a successful build, with the authorized Quest connected:

```sh
adb devices -l
adb install -r quest/Builds/PhysioFixture.apk
adb shell am force-stop com.hth.physio.fixture
adb shell monkey -p com.hth.physio.fixture -c android.intent.category.LAUNCHER 1
```

ADB success establishes installation/launch only. Wear the headset to verify the
visible result and physical interaction. A head-tracked placement waits for input
focus and valid tracked position/orientation instead of using an untracked pose.

## App flow

- **Patients:** create a locally stored name and choose a dated saved test. Names
  stay on the headset; UUIDs isolate patients, including identical display names.
- **Tests:** ELK seated flank stretch, RTK seated torso rotation or Walking review.
  Captures require consent confirmation and show test/view/side context.
- **Capture:** choose 5, 10 or 15 seconds per take, default 10, then record the
  patient's **right → front → back → left** views. Duration is fixed after the
  first saved view. Guidance and a separate Record control float beside the
  participant; the workspace hides during capture. Permission, countdown,
  automatic completion, stop, interruption and retry are explicit states.
  Adapter `85.0.0/2` writes the verified upright row order. Older `/1` recordings
  from the faulty encoder remain saved, but require a new test for processing.
- **Saved views:** each performance stays separate with immutable originals and
  retakes. Progress and selected takes recover after restart/crash. Choose one
  ELK/RTK/Walking take for 3D replay after all four views are saved. Other views remain
  evidence; they are never fused into a simultaneous performance.
- **Walking capture:** four independent straight passes. Keep the full body and
  feet visible, leave a clear path and remain at the selected camera position
  during each pass. Front approaches the camera, back moves away and side views
  cross the image. This is a review workflow, not a validated clinical gait test.
- **Historical barefoot capture:** four standing close-ups around one selected foot, with
  anatomical side fixed after the first saved view. No body replay is produced.
  This collection sequence is not a clinically validated foot protocol.
- **Processing:** the private deployment launcher supplies the service address,
  token and optional TLS certificate fingerprint before launch. The app consumes
  and deletes the setup file, then checks authentication in the background.
  Credentials stay in memory for that app session; a full restart requires the
  launcher to provision them again. Manual setup and a connection check remain
  under Options. Only a manually entered URL is saved in preferences. Processing
  reports actual stages, retry errors and unavailable methods.
- **Review:** play/pause, full timeline, reverse, frame steps, restart and
  0.25×/0.5×/1×/1.5×/2× speed. Body and skeleton share one display transform;
  moving/resizing them never changes stored measurements.
- **Insights:** up to three compact observation cards beside the replay show
  estimated angles, source view/time and a limitation. Selecting a card pauses at
  its measured source frame, marks the detached timeline and labels/brackets the
  region. Details include method/version and all limitations. Assessment has a
  separate tab and remains unavailable until an evaluated method exists.
- **Evidence:** matching-take observations/findings seek the replay and highlight
  only their own interval. Other-take originals open with the body paused. The
  larger video view opens paused at the encoded source time; **Play full recording**
  supplies context and **Return to peak** restores the measured moment. Original
  evidence never changes when the display is resized or playback speed changes.
  Historical result 1.0 and barefoot records remain readable; foot results without
  replay clear any earlier body. Clinical `findings` remain empty.
- **Microscope:** add a separate steady-hold recording to the selected test.
  A new saved assessment preserves the primary take and earlier versions.
  Source/amplified views show their own interval, crop, settings and limitations.
  Insufficient texture, camera motion or large movement returns an explanation.
- **Options/history:** reprocess saved originals into a new result version, reopen
  earlier versions, reset placement, change display/skeleton settings and return
  through the standard Menu/Options route.

Local data is stored under Unity's private `Application.persistentDataPath`.
Capture publication and cached results validate identities, sizes and hashes;
accepted-upload retries retain the idempotency key. Original captures remain
immutable. Heavy file, network, JSON and importer work runs outside Unity's
main thread; scene changes and mesh binding run on the main thread.

### Private processing connection

Runtime provisioning uses `processing-connection.json` in the app's persistent
data directory, with `endpoint`, `bearer_token` and optional `tls_leaf_sha256`.
Keep this file and its real values outside Git. It is bounded to 16 KiB and
deleted after a load attempt. The optional fingerprint pins a private server's
leaf certificate; hostname and validity checks remain enforced. Without it,
normal HTTPS certificate trust applies. Redirects are disabled.

The current private route is Quest loopback port 8443 → wireless ADB reverse →
Mac loopback port 8443 → the existing SSH tunnel → GPU service. Keep the laptop,
wireless ADB connection and tunnel available. The startup check is an
authenticated lookup of a random nonexistent job; it uploads no recording and
starts no inference. It leaves local recording controls usable while offline.
An authenticated connection does not establish GPU/model readiness.

Wireless ADB reconnects can erase reverse forwarding. While using this private
route, run the local repair helper alongside the existing SSH tunnel:

```sh
python3 quest/Tools/keep_processing_connection.py --serial <headset-ip>:5555
```

It checks the route every five seconds, reconnects the named headset when needed,
and restores only `tcp:8443` forwarding. `--once` checks/repairs once; Ctrl-C stops
the loop. It does not read credentials, restart the app, upload recordings or
submit processing. Keep the Mac awake. A full app restart still needs the existing
private session-provisioning launcher.

### Check camera encoding orientation

For a development build, launch with Android intent boolean
`physio_capture_benchmark=true`. This records an asymmetric synthetic texture
through the same GPU readback and MP4 encoder without opening the camera.
Pull the new MP4 from the app cache's `synthetic-capture-benchmark` directory and
run `python3 quest/Checks/check_capture_orientation.py /path/to/synthetic.mp4`.
The independent pixel check requires blue above red and the green stripe on
the left. A codec round trip alone does not establish correct orientation.

The first-display timing is recorded after an end-of-frame boundary, including
loading/binding. Continuous sessions use a monotonic interval from the final
capture; restart recovery shows a labelled wall-clock estimate. No complete
real capture-to-display benchmark has been recorded yet.

## Native interface and input

`Assets/Physio/Editor/HandReviewSceneBuilder.cs` uses Meta's stock UI Set prefabs
and theme. A compact workspace handles patient/test details, with independent
spatial widgets for capture and playback:

| Surface | Current dimensions |
|---|---|
| Patient/assessment workspace | 0.64 × 0.86 m; hidden during room capture. |
| Guidance | 0.54 × 0.344 m; placed above/left and draggable. |
| Record dock | 0.36 × 0.138 m; separate elapsed-time and Record/Stop control. |
| Replay timeline | 0.62 × 0.29 m; separate from the details workspace. |

These are source values, not accepted comfort/readability measurements. Guidance
updates at 10 Hz; listeners bind once. It explicitly warns that the recorded
camera field of view is smaller than passthrough. Projected calibrated framing
has not been implemented or validated.

The scene uses Meta's `OVRInteractionComprehensive` rig, OpenXR hand skeletons,
ray/poke buttons, native grab/rotation and two-hand scaling. Locomotion is disabled
for this stationary MR workflow. Smaller/Larger controls provide a one-hand
alternative. Standard hand-menu input reads SDK `HandStatus.MenuPressed` because
Android disables legacy pinch-button mapping; controller Start is also supported.
A native `DominantHandRef`/`HandJoint` wrist anchor on the non-dominant hand adds
optional Capture/Replay/Options shortcuts. The launcher appears only after 150 ms
of valid tracked/confident hand data, focus and suitable palm/head orientation.
Floating controls remain available without using the hand shortcut.

Focus loss pauses replay, disables interaction and interrupts capture. Permission
callbacks from a cancelled request cannot restart recording.

The layout follows [Meta UI Set](https://developers.meta.com/horizon/documentation/unity/unity-isdk-uiset/),
[panel guidance](https://developers.meta.com/horizon/design/panels/) and
[UI Set setup](https://developers.meta.com/horizon/documentation/unity/unity-isdk-create-uiset-ui/).
The official [Meta agentic tools](https://github.com/meta-quest/agentic-tools)
guidance was also inspected at revision prefix `3a8553d`. Native components and
source layouts still require headset checks for reach, target size, contrast,
one-handed navigation and visible focus.

## Source map

| Directory | Responsibility |
|---|---|
| `Assets/Physio/Capture/` | Camera/permission lifecycle, exact timestamps, three-slot ordered `CaptureReadbacks`, reusable JNI submission, capture bundles and explicit synthetic benchmark. |
| `Assets/Plugins/Android/` | AVC encoder, MP4 mux/extractor, bulk contiguous-luma conversion and six private conversion warmups before readiness. |
| `Assets/Physio/Workflow/` | Private patient/session store, guided-view recovery, authenticated processing client, result/cache validation. |
| `Assets/Physio/Replay/` | Bounded importer, original-time cursor, validity/gaps and take-isolated findings. |
| `Assets/Physio/Viewer/` | Body/skeleton rendering, spatial capture widgets, hand shortcuts, evidence playback and native input bindings. |
| `Assets/Physio/Editor/` | Scene generation and reproducible Android build. |
| `Checks/` | Runnable C# harnesses and synthetic Java encoder/YUV checks. |
| `Assets/Resources/Physio/` | Explicitly authored diagnostic fixture and mannequin; no participant data. |

The source clock is the camera SDK image timestamp, preserved as nanosecond
strings at its actual microsecond precision. Native encoder association and final
mux timestamps are checked separately. SDK intrinsics are adjusted using its
centered sensor crop. Lens distortion is **unknown**, physical body scale is
uncalibrated, and image-time camera poses are omitted because tracking validity
is unavailable. See the root README for strict service defaults and the explicit
unverified-pinhole opt-in; do not relabel these as measured calibration.

## Runnable checks

Import the Unity project first so the cached Newtonsoft DLL is available.
Use .NET 8 (`/Users/baderasadi/Library/Caches/HTH/dotnet/dotnet` on the current Mac),
from the repository root:

```sh
dotnet run --project quest/Checks/ReplayChecks.csproj -p:UseSharedCompilation=false
dotnet run --project quest/Checks/ImporterChecks.csproj -p:UseSharedCompilation=false
dotnet run --project quest/Checks/CaptureChecks.csproj -p:UseSharedCompilation=false
dotnet run --project quest/Checks/WorkflowChecks.csproj -p:UseSharedCompilation=false
dotnet run --project quest/Checks/DemoChecks.csproj -p:UseSharedCompilation=false
dotnet run --project quest/Checks/UIEvidenceChecks.csproj -p:UseSharedCompilation=false
dotnet run --project quest/Checks/SpatialCaptureChecks.csproj -p:UseSharedCompilation=false
```

Follow-up checks passed: **100 capture**, **363 workflow** and **20 spatial
presentation** checks; the workflow count was independently rebuilt and rerun
in C# review. The UI checkpoint also passed **12 evidence / 136 replay** checks.
Earlier unchanged importer/demo checkpoints passed **173 / 19,827** checks.
`Checks/Directory.Build.props` isolates each project's output to prevent one
harness from running another's cached apphost.

`CaptureBundle` + `CaptureReadbacks` coverage is **100% lines (146/146)** and
**98.59% branches (140/142)**; the queue alone is 100% lines/branches. This excludes
Unity recorder/benchmark, GPU, JNI and native code. `Physio.Workflow` coverage is
**99.28% lines / 83.33% branches**, excluding Replay/Unity/native; its ignored
report is `Checks/coverage/workflow-guided/`. Historical importer/data coverage
is **98.56% / 87.71%**. None is a whole-app or device-acceptance measurement.

Pure Java checks cover the actual `PhysioYuv420` conversion. Run from the repo
root with the installed Unity JDK:

```sh
quest_jdk=/Applications/Unity/Hub/Editor/6000.0.66f2/PlaybackEngines/AndroidPlayer/OpenJDK
quest_yuv_checks="$(mktemp -d /tmp/physio-yuv-checks.XXXXXX)"
"$quest_jdk/bin/javac" -Xlint:all -Werror -d "$quest_yuv_checks" \
  quest/Assets/Plugins/Android/PhysioYuv420.java \
  quest/Checks/CaptureColorChecks.java quest/Checks/CaptureYuvChecks.java
"$quest_jdk/bin/java" -cp "$quest_yuv_checks" CaptureColorChecks
"$quest_jdk/bin/java" -cp "$quest_yuv_checks" CaptureYuvChecks
```

Strict compilation, four color checks and **1,600 exact scalar/bulk comparisons**
passed. Layouts include heap/direct and shared UV/VU buffers, pixel/row strides,
offsets, padding, limits and vertical flip. Short scratch/plane-limit checks also
pass; buffer positions are preserved. A reused-scratch check verifies that warmup
pixels cannot enter the next frame. These checks do not open a camera.

Normal startup opens patients. The six-second authored mannequin is an explicitly
selected diagnostic demo: 121 frames, 21 joints, 1,634 vertices, 3,192 triangles.
It never substitutes for a patient's result. The four-frame tetrahedron remains
a coordinate/validity fixture. Neither produces clinical findings.

## Recording performance — two synthetic app runs passed

The previous app fell from about 72 Hz to 3 Hz during recording. Current source
keeps 1280×960, reusable signed-byte buffers and cached JNI submission.
`CaptureReadbacks` allows at most three overlapping requests and submits them
in source order. The native encoder now bulk-writes contiguous Y rows using one
reusable two-row scratch array; strided Y and U/V keep scalar writes. Color math,
chroma averaging, orientation and source/mux identity are unchanged. The encoder
also performs six conversions into private synthetic buffers before accepting
source frames. These warmups never enter the codec queue or recording counts.

Evidence root: `/Users/baderasadi/Library/Caches/HTH/spatial-proof/`.
`build-final-6.log` succeeded with exit 0. All 30 source hashes in
`frozen-source-6.json` match implementation commit `cba5dc9`. The installed APK
is **85,550,160 bytes**, SHA-256
`288773c47457da9109bf3a5446d3fcb19e566e072d2d7a664836d9b863972356`.

| Final app measurement | First cold launch | Repeat cold launch |
|---|---|---|
| Log / PID / time (EDT) | `unity-benchmark-6.log` / 11437 / 21:45:02–05 | `unity-benchmark-6-repeat.log` / 11854 / 21:45:26–29 |
| Observed / read back / submitted / encoded | 90 / 90 / 90 / 90 | 90 / 90 / 90 / 90 |
| Missed / maximum pending | 0 / 2 | 0 / 2 |
| Source span / effective rate / wall time | 2.967 s / 30.00 fps / 3.428 s | 2.967 s / 30.00 fps / 3.415 s |
| Average callback / copy / JNI; maximum JNI | 39.769 / 0.469 / 2.412 ms; 3.435 ms | 39.823 / 0.486 / 2.438 ms; 3.298 ms |
| Native warmup count / duration | 6 / 269.836 ms | 6 / 264.045 ms |
| Actual conversion count / total / maximum | 90 / 2762.681 / 37.307 ms | 90 / 2773.694 / 35.653 ms |
| App FPS samples during recording / target | 71, 71, 73 / 72 | 70, 72, 72 / 72 |
| Final mux / complete without drops | Verified / True | Verified / True |

Earlier probes explain the changes: `unity-benchmark.log` encoded 52/90 with
38 readback misses. The bounded-readback counter build (`unity-benchmark-4.log`)
delivered all 90 to JNI but encoded 53, with 37 `encoder_busy` misses. Bulk-luma
build 5 (`unity-benchmark-5.log`) encoded 88/90; missing source IDs 3 and 5 were
confirmed from mux timestamps. Build 6's pre-readiness warmup removed those losses
in both measured synthetic runs. Earlier native-only trials and source hashes
remain under `/Users/baderasadi/Library/Caches/HTH/recording-perf/production-bulk/`.
Code, C#, Java and security review completed.

Both final app runs had an untracked head pose. The diagnostic excludes camera
delivery, per-frame journal writes, the actual capture page and participant
processing. It covers three seconds of synthetic input, so sustained real-camera
performance, physical hand/layout acceptance and M1 remain incomplete. Native
hand configuration passed `scene-hand-verified.log`; this does not establish
wearer interaction. The app was relaunched normally after both diagnostics.

To repeat the development diagnostic after installation, use its explicit intent.
It exercises GPU texture → readback → JNI → encoder without opening a camera:

```sh
adb shell am force-stop com.hth.physio.fixture
adb shell am start -a android.intent.action.MAIN \
  -c android.intent.category.LAUNCHER -p com.hth.physio.fixture \
  --ez physio_capture_benchmark true
adb logcat -d -v threadtime -s Unity PhysioCapture VrApi
```

It waits five seconds for startup, then schedules 90 synthetic 1280×960 frames
at 30 fps. Inspect `PHYSIO_CAPTURE_METRICS`, `PHYSIO_NATIVE_TIMING`,
`PHYSIO_CAPTURE_BENCHMARK` and app-PID `VrApi` samples for admission, conversion,
missed counts, mux verification and rendering. It creates no patient
profile or clinical evidence; its temporary output is explicitly synthetic.
The encoder's six private conversion warmups occur before source-frame admission.

**Next checkpoint:** record actual camera timing with consent and verify guided
progression, stop/retake/restart recovery, hand shortcuts, floating controls and
evidence/replay. Synthetic success does not establish real capture acceptance.

## Prior device and real-data evidence

- **16:16 EDT:** user confirmed a live moving image in the official camera sample.
- **17:30–17:31 EDT:** earlier tetrahedron fixture rendered; observed controller
  input sought, stepped frames and reset placement. This predates the new UI.
- **18:30 EDT:** corrected native-hands diagnostic APK installed and cold-launched
  without the prior rig assertions. It waited for valid head tracking. Physical
  hand, poke, grab and two-hand validation remained pending.
- **Native encoder:** a synthetic 12-frame 1280×960 device test verified final mux
  timestamp identity/truncation and decoded colors. It opened no camera.
- **Real geometry:** the C# importer loaded the original public GVHMR output:
  242 frames, 10,475 vertices and 22 joints, in 291 ms on the Mac. This is importer
  timing on desktop, not first-frame Quest latency or visual correctness.
- **PR #10 integration:** source `636746d` built as an 85,431,296-byte ARM64 APK,
  installed and cold-launched at approximately 20:12 EDT. Logs showed no captured
  C# exceptions and placement awaiting a tracked head. It predates this spatial
  UI/recording fix and does not prove the new path.

Still required: a fresh consented capture through actual service/GPU to saved
Quest replay, body/skeleton/axis inspection, evaluated ELK/RTK methods and walking estimates, useful
steady-hold magnification, patient/retry/restart rehearsal and measured active
72 Hz / 250 ms seek / 1–2 minute full-path performance.

Upstream sample assets keep their original GUIDs and licenses; see
[META-SAMPLE-LICENSE.txt](META-SAMPLE-LICENSE.txt) and
[the sample license](Assets/PassthroughCameraApiSamples/LICENSE.txt).
No model weights or participant recordings belong in Git.
