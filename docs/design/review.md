# Review layout

The current Quest Review UI is implemented in
[`WorkflowPanel.Insights.cs`](../../quest/Assets/Physio/Viewer/WorkflowPanel.Insights.cs)
and [`HandReplayPanel.cs`](../../quest/Assets/Physio/Viewer/HandReplayPanel.cs).
See the [Quest guide](../../quest/README.md) for controls and the
[workflow state map](workflow-states.md) for navigation.

## Current interface

The main workspace shows selected patient, test, and saved-result context beside
the reconstructed body. The separate replay HUD provides play and pause, full
timeline, reverse, speed, frame steps, and restart. The body and skeleton share a
display transform. Display manipulation does not change stored measurements.

**Patterns** lists local descriptive estimates from the reconstructed pose.
If the result has saved observations without local pattern items, the tab reads
**Observations**. **Findings** shows supported findings or an unavailable state.
The Goata score gauge shows a matching replay's score and summary. The viewer
does not expose the score's full calculation details. Observation **Details**
shows its own method and limitations. Conclusions use scrollable text.

Matching-take evidence seeks and highlights the replay's source interval.
Other-take footage opens separately with the hologram paused. Original footage
and amplified microscope footage remain labelled separately. Missing evidence
and rejected microscope processing retain their explanations.

Saved Review returns to the selected patient's History. Options provides skeleton
visibility, body opacity, floor-placement reset, and saved versions. Normal
saved-review Options does not offer reprocessing. The Processing context owns
that guarded action. Local **Rerun classifications** requires no new upload.

Clinical evaluation, useful magnification, and physical interaction checks remain
incomplete. See [project status](../STATUS.md).

## Historical browser reference

[`review-preview.jpg`](../../design/review-preview.jpg) is a 1600 × 1000 browser
mockup with synthetic patient and dated-test context. It illustrates empty
history, missing original and amplified footage, illustrative poor evidence,
and unavailable foot and microscope views.

The image's **Back to capture** label records an earlier design. It does not
specify current saved-result navigation. The browser preview supplies no real
recording, processing stage, finding, calibrated measurement, or persistent
patient store. Its HTML controls are not imported Unity UI Set prefabs.
