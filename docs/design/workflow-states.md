# Quest workflow layouts and state map — design handoff

**Status:** versioned, editable layout annotations for the states not fully depicted in the Capture and Review browser exports. These are implementation instructions for Hamza, **not** working Unity screens, finished recordings, clinical findings, or a rendered UI export. Read alongside [Capture](capture.md), [Review](review.md), and `docs/SPEC.md` in the target team repository.

## Shared panel and routing

- Use one stable world-space main panel beside the replay body; keep patient, test, date, visible Back and Options context readable. The app-owned menu is separate from Meta's universal menu.
- Each `AppScreen` in the team repository's `design/quest-menu/AppMenuController.cs` gets a distinct sibling page root when using that controller, including dialog-styled Finding Detail, Foot Review, Microscope and Options. The persistent menu and controller live outside all page roots. A nested dialog inside Review instead requires a separate owner and wiring; **do not** bind an unbound `Open...` action to it.
- The session coordinator decides Back and approves all root changes. A saved Review returns to that patient's dated History and exact saved result version, not Capture. Before any root change away from a recording, it finishes or refuses the interruption/retake guard. A new test cannot skip Test Selection or Processing.
- Capture and Review JPGs are browser-pixel references, not metre-based measurements. Start near a one-metre indirect viewing distance and validate physical size, text, ray/poke targets, and one-handed use on Quest.

## Annotated root layouts

| Root | Top / primary region | Secondary region and action row | Required states and routing |
|---|---|---|---|
| `Home` | App identity and start action; no synthetic result claim. | Visible Patients, History (only with selected patient), and Options actions. | Start at Patients. A missing patient routes to Patients, never an arbitrary saved review. |
| `Patients` | Search/list local profiles with display name; duplicate names must remain separate IDs. | New patient opens the system keyboard; selecting a profile opens their History. | Empty profiles, keyboard cancellation and selection; no cross-patient session carryover. |
| `History` | Selected patient name and dated tests. | Each row names test, date, status and saved result version; New test and Back are visible. | Empty history shows New test. New test → `TestSelection`; saved test → its versioned `Review`, with no capture jump. |
| `TestSelection` | Three mutually exclusive choices only: KERAAL ELK, KERAAL RTK, barefoot. | Selected protocol explanation and required view/side/condition context; Continue and Back. | Do not show unapproved protocol instructions. Continue to `Capture` only when a patient and test are selected. |
| `Capture` | See [Capture annotations](capture.md) and [export](../../design/capture-preview.jpg): broad preview with persistent patient/test context. | Read-only side/view/condition/protocol/scale rows and large Start/Retake actions. | Permission denial, missing source, countdown, recording/stop, captured/missing take, retake, explicit interrupted take. Only completed eligible takes enter `Processing`; preserve completed frames on interruption. |
| `Processing` | Real stage, elapsed time and selected patient/test/take identifiers; never a fabricated progress percentage. | Waiting message, failure reason and Retry that preserves original recordings; Back/History guard. | Waiting, active, failed/retry, completed validated result. Success → `Review`; failed jobs never show a result or fake elapsed time. |
| `Review` | See [Review annotations](review.md) and [export](../../design/review-preview.jpg). In the real app, the blue body/skeleton sits beside the panel. | Finding list, evidence source/take, original vs amplified labels, and playback row: Play/Pause, seek, Reverse, speed, frame steps, Restart and actual source time. | Saved version, empty history, no source, poor evidence, loading/failure. One finding expands to `FindingDetail`; Foot review, Microscope and Options have their own roots. A finding from another take does not seek the replay. |
| `FindingDetail` | One finding title only if supported by real analysis, explanation, region and non-colour-only emphasis. | Evidence action names the source take and interval; optional Magnify motion goes to `Microscope`. | Unsupported/absent evidence stays explicitly unavailable. Back returns to the same `Review` result and time. No treatment advice. |
| `FootReview` | Left/right foot, view, standing/seated condition, evidence image and method. | Calibration/reference/estimated-scale provenance; evidence-quality message and return to Review. | Unavailable source and poor-evidence states; no unsupported gait/arch conclusions or uncalibrated physical measurement. |
| `Microscope` | Paired, explicitly labelled **Original** and **Amplified** footage for the same source interval. | Interval/source identifiers, disabled zoom/focus until valid footage, Back to analysis. | Unavailable footage, processing failure and camera/background-shake rejection. Do not silently substitute another take. |
| `Options` | Resume/Close, display opacity/skeleton/finding-label controls. | Bring panel here, separate Reset replay placement, playback help, Patient history action. | Back/Resume returns to coordinator-held context; bringing the panel closer never moves replay or changes calibration. |

## Quest input and focus annotations

- Route the **left-controller Menu button** and SDK **standard hand-menu route** to the app-owned menu; keep visible Options in the panel. The Meta button/system gesture remains system-owned. Use UI Set controls and supplied ray/poke interaction; do not rebuild Meta's gestures.
- When app input focus is lost, stop accepting app navigation, hide app input visuals, pause the replay clock **without changing source time**, retain the review state, and mark an active capture interrupted while preserving completed frames. On return, restore controls and the same review context; do not silently resume recording or playback.
- Review every action seated with one controller or one hand. Distinguish selected/focus/pressed/disabled states with text, shape or outline as well as colour.

## Source and export mapping

| Editable annotation source in this repository | Versioned visual export | Coverage |
|---|---|---|
| `docs/design/capture.md` | `design/capture-preview.jpg` | Pre-capture and documented illustrative interruption; no working camera. |
| `docs/design/review.md` | `design/review-preview.jpg` | Synthetic session/evidence; no spatial replay or real result. |
| `docs/design/workflow-states.md` (this file) | Text layout/state map; no rendered export | Remaining roots and states above, not yet prototyped or tested in Unity. |

The interactive React prototype lives in the separate Replit design workspace, not in this repository. Its visual exports are reference images only. Hamza owns creating Unity UI Set controls, real session/capture/processing connections, and in-headset verification; any unavailable required feature remains explicitly incomplete.