# Quest app

**Last updated:** September 26, 2026. The patient/capture/processing/review flow is
implemented with native Meta UI Set controls. The first integrated Android build
succeeded. The frozen final build is running and still needs wearer acceptance; the
latest layout, gestures and fresh recording-to-replay flow remain unverified.

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
- **Tests:** ELK seated flank stretch, RTK seated torso rotation or barefoot.
  Captures require consent confirmation and show test/view/side context.
- **Capture:** native permission request, preview/countdown, stop and interruption
  recovery. Keep the participant and required body region in frame. Current
  capture is bounded to 600 frames/about 20 seconds. This is a prototype limit,
  not a clinically established recording protocol.
- **Processing:** enter the HTTPS service URL and token through Options/system
  keyboard. The token stays in memory; enter it again after app restart. The URL
  is saved. Processing reports actual stages, retry errors and unavailable methods.
- **Review:** play/pause, full timeline, reverse, frame steps, restart and
  0.25×/0.5×/1×/1.5×/2× speed. Body and skeleton share one display transform;
  moving/resizing them never changes stored measurements.
- **Evidence:** a finding can drive replay only for the matching take. Other-take
  original video opens with the body paused. Video seeking uses the retained
  encoded timestamp mapping. Foot results without replay clear any earlier body.
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

The first-display timing is recorded after an end-of-frame boundary, including
loading/binding. Continuous sessions use a monotonic interval from the final
capture; restart recovery shows a labelled wall-clock estimate. No complete
real capture-to-display benchmark has been recorded yet.

## Native interface and input

`Assets/Physio/Editor/HandReviewSceneBuilder.cs` builds a dark UI Set workspace
with cyan emphasis, persistent patient/test context and explicit primary actions.
The panel is 0.92 × 0.94 metres, initially about 1.25 metres in front of the user,
and can be repositioned. These are implementation values, not accepted comfort
or readability measurements.

The scene uses Meta's `OVRInteractionComprehensive` rig, OpenXR hand skeletons,
ray/poke buttons, native grab/rotation and two-hand scaling. Locomotion is disabled
for this stationary MR workflow. Smaller/Larger controls provide a one-hand
alternative. Standard hand-menu input reads SDK `HandStatus.MenuPressed` because
Android disables legacy pinch-button mapping; controller Start is also supported.
Focus loss pauses replay, disables interaction and interrupts capture. Permission
callbacks from a cancelled request cannot restart recording.

The layout follows [Meta UI Set](https://developers.meta.com/horizon/documentation/unity/unity-isdk-uiset/),
[panel guidance](https://developers.meta.com/horizon/design/panels/) and
[UI Set setup](https://developers.meta.com/horizon/documentation/unity/unity-isdk-create-uiset-ui/).
Native components and readable source layouts still require headset checks for
reach, target size, contrast, one-handed navigation and visible focus.

## Source map

| Directory | Responsibility |
|---|---|
| `Assets/Physio/Capture/` | Camera/permission lifecycle, exact source timestamps, sidecars and capture bundles. |
| `Assets/Plugins/Android/` | AVC encoder, MP4 mux/extractor and YUV conversion. |
| `Assets/Physio/Workflow/` | Private patient/session store, authenticated processing client, result/cache validation. |
| `Assets/Physio/Replay/` | Bounded importer, original-time cursor, validity/gaps and take-isolated findings. |
| `Assets/Physio/Viewer/` | Body/skeleton rendering, UI flow, evidence playback and native input bindings. |
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
```

All six ran serially and passed **136 / 173 / 54 / 283 / 19,827 / 12** checks.
`Checks/Directory.Build.props` isolates each project's output to prevent one
harness from accidentally running another's cached apphost.

Coverage checkpoints: importer/data **98.56% lines / 87.71% branches**; capture
logic **100% / 98%** at 53 checks; workflow assembly **99.6% / 81.47%** at 282
checks. Later checks above passed; those coverage percentages describe the
preceding snapshots. Unity rendering, native Android and physical interaction
are outside these console coverage measurements.

Normal startup opens patients. The six-second authored mannequin is an explicitly
selected diagnostic demo: 121 frames, 21 joints, 1,634 vertices, 3,192 triangles.
It never substitutes for a patient's result. The four-frame tetrahedron remains
a coordinate/validity fixture. Neither produces clinical findings.

## Device and real-data evidence

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
- **Integrated app:** first integrated APK built. Intermediate build 2 was
  intentionally cancelled as obsolete; the frozen final build/install/wearer
  checks are pending at this checkpoint.

Still required: a fresh consented capture through actual service/GPU to saved
Quest replay, body/skeleton/axis inspection, real ELK/RTK/foot methods, useful
steady-hold magnification, patient/retry/restart rehearsal and measured active
72 Hz / 250 ms seek / 1–2 minute full-path performance.

Upstream sample assets keep their original GUIDs and licenses; see
[META-SAMPLE-LICENSE.txt](META-SAMPLE-LICENSE.txt) and
[the sample license](Assets/PassthroughCameraApiSamples/LICENSE.txt).
No model weights or participant recordings belong in Git.
