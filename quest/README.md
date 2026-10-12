# Quest app

The Unity client captures consenting participants, stores dated tests by patient,
and loads processed movement replays and source-linked evidence on Quest 3.
Source configuration is version 0.3.7, Android code 14, with Unity 6000.0.66f2.
These values do not establish which APK is installed on a headset.

See [project status](../docs/STATUS.md) for unfinished requirements,
[engineering reference](../docs/ENGINEERING.md) for data and processing rules,
and [development](../docs/DEVELOPMENT.md) for service setup and checks.
Wearer acceptance, clinical validation, and the full capture-to-replay performance
check remain separate from source and automated checks.

## Build and install

Open this directory with Unity 6000.0.66f2 and Android Build Support, including
SDK, NDK, and OpenJDK. The package manifest pins Meta MRUK and Interaction SDK
85.0.0, OpenXR 1.15.1, and Newtonsoft JSON 3.0.2. The app targets Android API 34
and ARM64.

From the repository root on macOS, run:

```sh
BEE_BUILD_THREADS=6 \
  /Applications/Unity/Hub/Editor/6000.0.66f2/Unity.app/Contents/MacOS/Unity \
  -batchmode -quit -buildTarget Android -job-worker-count 2 \
  -projectPath "$PWD/quest" \
  -executeMethod FixtureBuild.Build \
  -logFile /tmp/physio-quest-build.log
```

`FixtureBuild.Build` validates the authored diagnostic resources, generates the
scene, checks for missing scripts, and builds with `CleanBuildCache`.
The output is `quest/Builds/PhysioFixture.apk`, a development build with package
ID `com.hth.physio.fixture`.

With an authorized Quest connected, install and launch the APK:

```sh
adb devices -l
adb install -r quest/Builds/PhysioFixture.apk
adb shell am force-stop com.hth.physio.fixture
adb shell monkey -p com.hth.physio.fixture -c android.intent.category.LAUNCHER 1
```

Installation replaces any app with that package ID. Check the visible app and
interaction in the headset. A successful ADB command alone does not verify them.

## Capture and review

Normal startup opens **Patients**. Selecting a patient opens their dated
**History**. A new test follows **Test selection**, **Capture setup**, **Capture**,
**Capture summary**, **Processing**, then **Review**. Saved results open Review
directly. Patient UUIDs keep identical display names separate.

New tests offer exactly KERAAL ELK seated flank stretch, KERAAL RTK seated torso
rotation, and Walking review. Historical barefoot sessions remain readable.
They are not a fourth new-test choice.

Capture setup requires consent confirmation and offers 5, 10, or 15 seconds per
take, with 10 seconds as the default. Duration becomes fixed after the first
saved take. Capture records the participant's right, front, back, then left
views as separate performances. A single movable panel contains guidance,
live preview, and recording controls. The camera preview opens before the
three-second recording countdown. The main workspace hides during capture.

Saved progress supports interruption recovery and retakes. After all four views,
Capture summary selects one take for body replay. Other takes remain separate
evidence. Walking capture uses four independent passes, with the body and feet
visible. This is not a clinically validated gait protocol.

Review provides play and pause, a full timeline, reverse, frame steps, restart,
and speeds of 0.25×, 0.5×, 1×, 1.5×, and 2×. The translucent blue body and skeleton
share a display transform. Moving or resizing the display does not change stored
measurements or source times.

**Patterns** contains local descriptive classifications of reconstructed pose.
When only saved estimates are available, the tab reads **Observations**.
**Findings** displays evaluated findings supplied by the result, or an explicit
unavailable state. Neither local patterns nor the Goata score is a diagnosis.
The Goata score gauge displays its score and summary when usable matching replay
data exists. Its full calculation details are not exposed in the viewer.
Observation **Details** separately shows the method and limitations.

Selecting matching-take evidence pauses and seeks the replay to its source
interval. Other-take evidence opens separately with the body paused.
**Rerun classifications** recalculates local patterns from saved, unscaled replay
geometry without uploading recordings or changing saved result versions.

The motion microscope accepts a separate steady-hold capture. It retains the
primary assessment and shows original and amplified evidence with their own
intervals and limitations. Missing sources or rejected movement remain explicit.
Useful magnification on real captures still needs verification.

Review Options provides skeleton visibility, body opacity, floor-placement
reset, and saved result versions. **Reprocess saved capture** is guarded by the
Processing screen context and supported session states. It is not a normal
saved-review Options action. Additional display and workflow requirements are
listed in [project status](../docs/STATUS.md).

## Connect processing

New processing requires an authenticated service. Runtime provisioning reads
`processing-connection.json` in `Application.persistentDataPath`, with `endpoint`,
`bearer_token`, and optional `tls_leaf_sha256`. The file is bounded to 16 KiB and
deleted after a load attempt. Keep real credentials outside Git.

Credentials remain in memory for the app session. A full restart requires
provisioning again. Manual connection setup is available in Options from Patients,
Capture summary, or Processing. Only a manually entered URL is saved in preferences.
The startup check looks up a random nonexistent job without uploading recordings
or starting inference. Authentication success does not prove model readiness.

HTTPS uses normal certificate trust unless a leaf certificate fingerprint is
configured. Hostname and validity checks still apply. Redirects are disabled.

For a configured private route through wireless ADB reverse and a local tunnel,
the repair helper restores Quest loopback port 8443 to laptop loopback port 8443:

```sh
python3 quest/Tools/keep_processing_connection.py --serial HEADSET_IP:5555
```

Replace `HEADSET_IP` with the connected headset's address. `--once` checks once.
The helper does not provision credentials or create the upstream tunnel.

## Data and input

`LocalPatientStore` uses Unity's private `Application.persistentDataPath`, UUID
patient and session identities, and bounded caches. Its default storage budget
is 4 GiB. Capture publication and result loading validate identities, sizes, and
hashes. Originals remain immutable, and accepted-upload retries retain their
idempotency key.

Source timestamps come from the camera SDK and remain nanosecond strings at the
SDK's microsecond precision. Lens distortion is unknown, physical body scale is
uncalibrated, and image-time camera poses are omitted when tracking validity is
unavailable. Display size is not measured anatomy.

The generated scene uses Meta UI Set controls, ray and poke interaction, native
grab and rotation, and two-hand scaling. Smaller and Larger controls offer a
one-hand alternative. Controller Menu, the SDK hand-menu route, visible Options,
and optional wrist shortcuts open app controls. Quest system input remains
system-owned. Focus loss pauses replay, disables interaction, and interrupts
capture. Placement waits for valid tracked head data.

The optional Moon environment and playful replay assets change presentation only.
Their credits are in [Moon asset sources](Assets/Physio/Art/Moon/ASSET_SOURCES.md)
and [Tomato asset sources](Assets/Physio/Art/Tomato/ASSET_SOURCES.md).
The authored mannequin and coordinate fixture are diagnostic resources, not
participant assessments or a normal patient-navigation demo.

## Run checks

Import the Unity project first so its Newtonsoft DLL is available. With .NET 8,
run these commands from the repository root:

```sh
for check in Replay Importer Capture Workflow Demo UIEvidence SpatialCapture Pattern GoataScore Connection; do
  dotnet run --project "quest/Checks/${check}Checks.csproj" -p:UseSharedCompilation=false || exit "$?"
done
```

The projects isolate their output directories. These checks cover testable C#
logic, not Unity scene behavior, Quest input, camera delivery, or model accuracy.

Run the Java color and YUV conversion checks with the Unity JDK:

```sh
quest_jdk=/Applications/Unity/Hub/Editor/6000.0.66f2/PlaybackEngines/AndroidPlayer/OpenJDK
quest_yuv_checks="$(mktemp -d /tmp/physio-yuv-checks.XXXXXX)"
"$quest_jdk/bin/javac" -Xlint:all -Werror -d "$quest_yuv_checks" \
  quest/Assets/Plugins/Android/PhysioYuv420.java \
  quest/Checks/CaptureColorChecks.java quest/Checks/CaptureYuvChecks.java
"$quest_jdk/bin/java" -cp "$quest_yuv_checks" CaptureColorChecks
"$quest_jdk/bin/java" -cp "$quest_yuv_checks" CaptureYuvChecks
```

For a development APK, the synthetic capture diagnostic exercises GPU texture,
readback, JNI, and MP4 encoding without opening a camera:

```sh
adb shell am force-stop com.hth.physio.fixture
adb shell am start -a android.intent.action.MAIN \
  -c android.intent.category.LAUNCHER -p com.hth.physio.fixture \
  --ez physio_capture_benchmark true
adb logcat -d -v threadtime -s Unity PhysioCapture VrApi
```

Inspect `PHYSIO_CAPTURE_METRICS`, `PHYSIO_NATIVE_TIMING`, and
`PHYSIO_CAPTURE_BENCHMARK` for admitted, encoded, missed, and mux-verified frames.
Check the resulting synthetic MP4 with:

```sh
python3 quest/Checks/check_capture_orientation.py /path/to/synthetic.mp4
```

The pixel check requires blue above red and a green stripe on the left.
Synthetic encoding does not establish sustained camera performance. The required
full-path check starts at final capture and ends at loaded analysis and replay,
including save, upload, processing, download, import, and first display.

## Source map

| Directory | Responsibility |
|---|---|
| `Assets/Physio/Capture/` | Camera lifecycle, timestamps, ordered readbacks, capture bundles, and synthetic benchmark. |
| `Assets/Plugins/Android/` | MP4 encoder, extractor, and YUV conversion. |
| `Assets/Physio/Workflow/` | Patient storage, capture recovery, authenticated processing, and cache validation. |
| `Assets/Physio/Replay/` | Import, source-time playback, patterns, score, and take-isolated evidence. |
| `Assets/Physio/Viewer/` | Body rendering, capture panel, replay HUD, evidence, and input. |
| `Assets/Physio/Editor/` | Generated scene and Android build. |
| `Checks/` | C# checks, Java conversion checks, and MP4 orientation check. |
| `Assets/Resources/Physio/` | Authored diagnostic data. |

Upstream sample assets retain their GUIDs and licenses. See
[META-SAMPLE-LICENSE.txt](META-SAMPLE-LICENSE.txt) and
[the sample license](Assets/PassthroughCameraApiSamples/LICENSE.txt).
Model weights and participant recordings do not belong in Git.
