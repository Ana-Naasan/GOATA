# Quest workflow states

[`WorkflowPanel`](../../quest/Assets/Physio/Viewer/WorkflowPanel.cs) owns the
current app screens. The generated Unity scene uses a shared workspace, a
capture panel, and a separate replay HUD. The archived
[`AppMenuController`](../../design/quest-menu/README.md) is not the runtime router.

## Main route

Normal startup opens Patients. A new test follows Patients, History, Test
selection, Capture setup, Capture, Capture summary, Processing, then Review.
A saved result opens Review directly from History. Incomplete saved capture
resumes setup or summary, while other unfinished sessions open Processing.

| Runtime `Screen` | Visible state and routing |
|---|---|
| `Patients` | Local patient list and name entry. Selection opens that UUID's History. Duplicate display names remain distinct. |
| `History` | Selected patient's dated tests. New test opens `Tests`. A saved result opens `Review`; unfinished sessions resume their stored state. |
| `Tests` | Test selection with exactly ELK, RTK, and Walking review. Selection opens `CaptureSetup`. Historical barefoot tests remain readable. |
| `CaptureSetup` | Consent confirmation and recording duration. Existing takes fix duration. Continue prepares guided capture. |
| `Capture` | One spatial panel with guidance, preview, countdown, Record or Stop, and view progress. Saved takes remain separate through interruption and retakes. |
| `CaptureSummary` | Completed view choices and the selected source take for replay. Starts processing of saved capture. |
| `Processing` | Real job updates, failures, and retry. Success opens the validated result in `Review`. |
| `Review` | Saved-result context, score, Patterns or Observations, Findings, and source-linked evidence. Back returns to History. |

## Secondary screens

| Runtime `Screen` | Purpose |
|---|---|
| `Finding` | Selected observation or finding details, method, limitations, and evidence. |
| `Feature` | Feature status and explanation. Unsupported processing remains explicit. |
| `Foot` | Historical foot-result review without carrying over a previous body replay. |
| `Microscope` | Original and amplified evidence, source interval, limitations, and separate steady-hold capture. |
| `Options` | Context-dependent controls. Review offers skeleton, opacity, placement reset, and versions. Processing owns guarded reprocessing. |
| `Versions` | Latest and previous saved results for the selected patient and test. |
| `Demo` | Diagnostic screen retained in source. Normal patient navigation does not expose the authored mannequin as a participant result. |

## Input and evidence rules

Navigation guards block changes while capture or an unsaved completed take needs
attention. Focus loss disables app interaction, pauses replay, and interrupts
capture. Focus regain must not silently resume recording or playback.

Only evidence from the replay's source take can drive its timeline and highlight.
Other-take evidence opens separately with replay paused. Missing measurements
remain invalid. Display scale and playback speed do not change stored analysis.

Controller Menu, the SDK hand-menu route, visible Options, and optional wrist
shortcuts open app controls. Meta's system menu remains separate.

## Design reference scope

[Capture](capture.md) and [Review](review.md) document current source alongside
historical browser exports. The exports contain synthetic examples and earlier
labels. They do not prove camera, processing, or physical interaction behavior.
See the [Quest guide](../../quest/README.md) for checks and
[project status](../STATUS.md) for unfinished requirements.
