# Capture layout

The current Quest capture UI is implemented in
[`WorkflowPanel.Capture.cs`](../../quest/Assets/Physio/Viewer/WorkflowPanel.Capture.cs)
and [`SpatialCaptureOverlay.cs`](../../quest/Assets/Physio/Viewer/SpatialCaptureOverlay.cs).
See the [Quest guide](../../quest/README.md) for setup and the
[workflow state map](workflow-states.md) for navigation.

## Current interface

Capture setup confirms participant consent and selects 5, 10, or 15 seconds per
take. The default is 10 seconds. Duration becomes fixed after a saved take.
New-test choices are ELK seated flank stretch, RTK seated torso rotation, and
Walking review. Historical barefoot sessions retain their selected foot context.

The main workspace hides during capture. One movable panel contains the current
view, instructions, live camera preview, recording status, and Record or Stop
controls. There is no separate Record dock. The preview opens before the
three-second countdown so the practitioner can frame the participant.

The guided sequence records right, front, back, and left views independently.
Completed takes remain saved through interruption and retakes. Capture summary
selects one replay take after all four views are saved. Separate performances
are not fused into simultaneous capture.

Permission failure, unavailable camera, interruption, and save errors require
visible status. A cancelled permission request must not restart recording.
Focus loss interrupts capture. Camera preview and guidance do not establish
calibrated framing or measured body scale.

## Historical browser reference

[`capture-preview.jpg`](../../design/capture-preview.jpg) is a 1600 × 1000 browser
mockup with synthetic patient context and unavailable camera source. Its controls
illustrate menu, preview, disabled retake, and interruption states. The image
records an earlier design, including a Barefoot choice. Use the current Quest
source for test selection and navigation.

The browser design used HTML controls styled around Meta UI Set patterns. It does
not contain Unity prefabs, camera permissions, actual recordings, or Quest input.
Browser pixels do not specify physical panel dimensions.

The Unity scene uses Meta UI Set controls with ray and poke interaction. Physical
legibility, target size, reach, and one-handed capture need checks in Quest.
See [project status](../STATUS.md) for remaining verification.
