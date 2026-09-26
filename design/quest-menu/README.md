# Foot Assessment — Quest app menu integration

This folder is a **source-only handoff for the team's existing Unity project**, not a second Unity project. After reviewing the handoff, the Quest/Unity owner can copy `AppMenuController.cs` into that project's `Assets/Scripts/FootAssessment/` folder. This handoff does not change the Unity project. No scene, prefab, package manifest, Android build, or Meta system-menu modification is included.

## What the code does

- Shows exactly one bound app screen at a time, including Test Selection, Processing, Finding Detail, Foot Review and Microscope alongside the main destinations.
- Opens/closes the **app-owned** menu and marks the active destination, provided each destination has a selected-state GameObject.
- Closes the app menu first on Back. Every other Back destination comes from the session coordinator, not a hard-coded page sequence.
- Refuses screen changes when the coordinator has not approved the transition. This applies to direct menu choices as well as Back, so capture and unsaved-session guards cannot be bypassed by a menu button.
- Rejects invalid initial-screen, duplicate, nested-root, or misplaced selection-marker bindings on startup. An unbound destination logs a Unity console error when clicked and leaves the current page visible.

This is navigation logic, **not a complete headset app**. The separate browser designs for the app menu, Capture, and Review are visual/interaction references only. They cannot be copied into Unity as prefabs.

## Integration work still required

| Area | The existing Unity project must provide |
|---|---|
| App scene | A launchable Quest scene with a world-space app panel, a persistent navigation object, and the workflow roots listed below. This folder provides no scene or prefab. |
| Session coordinator | A `MonoBehaviour` implementing `IAppNavigationCoordinator` to resolve contextual Back, approve or reject every transition, preserve the saved result version, and complete capture-interruption/unsaved-data handling **before** allowing a page to deactivate. Without it this controller disables itself. |
| UI Set and input | Actual Meta UI Set controls and their select events, a configured EventSystem/canvas, controller or hand ray, direct poke, focus/pressed feedback, the left-controller Menu button and SDK standard hand-menu route. Do not consume the Meta/system gesture. |
| Session data | The real patient/session source and access rules, test date/type, side/view/condition requirements, and approved protocol. The browser names and dates are synthetic design examples. |
| Capture | A supported Quest camera/recording source, permission handling, interruption/retry behavior, retake/use-recording actions, and evidence-quality criteria. The browser preview records nothing. |
| Review | Separate original and amplified footage sources, processing stage/elapsed/failure from a real job, evidence provenance, foot review, and microscope/options behavior. No clinical conclusions are supplied by this module. |
| Delivery | Android/Quest build configuration, installation, and in-headset verification in the existing Unity project. This repository cannot produce or validate an APK. |

Versioned layout references in this repository: [Capture annotations](../../docs/design/capture.md) and [Capture export](../../design/capture-preview.jpg); [Review annotations](../../docs/design/review.md) and [Review export](../../design/review-preview.jpg); [remaining workflow layouts and states](../../docs/design/workflow-states.md). The exported images show synthetic, unavailable-source examples rather than live footage. The C# controller owns only navigation; it does not fake camera access, recordings, processing, or patient records.

### Required flow and scene mapping

The intended path is **Patients → dated patient History → Test Selection (new test) → Capture → Processing → Review**, or **History → saved Review**. Opening a saved result restores that patient's dated test and result version; it does not start a new capture. `Home` is the app landing panel. Bind an independent root for each destination used below; leave other destinations unbound until their real page exists, and do not present an unbound action as ready.

| `AppScreen` / root | Required state and navigation owner |
|---|---|
| `Patients` | Local profiles, new patient/system keyboard; selecting one opens that patient's `History`. |
| `History` | Patient name, dated tests and status, **New test → TestSelection**, **saved test → Review** with its stored result version; empty history is explicit. |
| `TestSelection` | Exactly ELK, RTK or barefoot, then test-specific capture requirements before `Capture`. |
| `Capture` | Actual protocol/framing, permission denial, countdown, record/stop, separate takes, missing/retake and interrupted states. Only completed eligible takes proceed to `Processing`. |
| `Processing` | Real stage and elapsed time, waiting, failure/retry retaining the recording; successful validated result opens `Review`. |
| `Review` | Patient/test/date and saved result version, replay, evidence and findings; don't treat a previous recovery example as current. |
| `FindingDetail` | One expanded finding with explanation, evidence interval and source take; return to the same `Review` session. |
| `FootReview` | Side/view/condition, source and scale provenance, unavailable or poor-evidence state; return to the same `Review` session. |
| `Microscope` | Labelled original and amplified footage of the matching interval, source-unavailable state and Back to the same analysis. |
| `Options` | Display, placement, controls and patient-history actions; Back/Resume returns to the coordinator's prior context. |

For this controller, **every `Open...` destination must have its own bound sibling root**, even when it is visually presented as a dialog within the main world-space panel. Do not wire an `Open...` method to an unbound local overlay. The existing Capture/Review exports do **not** depict a complete Test Selection, Processing, Finding Detail or spatial replay implementation; use the annotated workflow guide and real runtime state instead of treating synthetic screenshots as completed features.

## Wiring in the existing Unity scene

1. Ensure Meta XR Interaction SDK Essentials/UI Set is available in the **existing Unity project**. Keep the app-owned menu on a stable, readable world-space panel; this is not the Quest universal menu.
2. Add a persistent `FootAssessmentNavigation` GameObject **outside** all screen and menu roots. Attach `AppMenuController`. Keep the menu root separate from all screen roots; none of those roots should contain another.
3. Implement `IAppNavigationCoordinator` on the Quest project's session controller and assign that component to `Navigation Coordinator Behaviour`. `TryPrepareNavigation(from, to)` must synchronously finish or refuse any capture interruption/retake or unsaved-data guard **before** returning `true`. It must also reject impossible jumps (for example, Review without a selected patient and saved/validated result, or Capture before test selection). `TryGetBackDestination` resolves Back from patient/session context; from a saved Review it returns that patient's dated History, never Capture. Return `false` if the destination is not known or a confirmation is pending. `OnAppFocusChanged(false)` pauses replay without resetting source time, preserves review state, hides app input visuals, and marks any active capture interrupted while retaining completed frames. Focus regain restores controls/state without silently resuming recording or replay.
4. Assign `Menu Root` to the GameObject containing the menu UI. Add `Screens` entries for all eleven `AppScreen` destinations before exposing their actions. They must be sibling roots outside the menu root, even for dialog-styled destinations. For each entry, optionally assign a **distinct, non-nested child of the menu root** as its small selected marker; never assign the menu root itself. Set `Initial Screen` to Home. A destination must have a root before it can be opened.
5. Connect UI Set select/click events to the appropriate public `Open...` method. Connect the app menu control to `ToggleMenu` and Back controls to `Back`. **Required:** route the left-controller Menu button and the SDK's standard hand-menu route to the same app-owned menu action; provide a visible `OpenOptions` action. Do **not** intercept or replace the Meta button, system gesture or Quest universal menu.
6. Configure hand-poke and controller/hand-ray interaction for the actual UI Set controls and world-space Canvas in Unity. Use Meta's [UI Set](https://developers.meta.com/horizon/documentation/unity/unity-isdk-uiset/) and [ray-castable UI](https://developers.meta.com/horizon/documentation/unity/unity-isdk-create-raycast-ui/) guidance. The C# script deliberately avoids direct Meta SDK types so it can be copied in before the UI Set prefabs are wired.
7. Put the real Capture/Review UI, session data, camera/permission handling, evidence processing, and approved clinical protocol in the Quest owner's implementation. Do not substitute the browser mockup's synthetic patients, placeholder footage, or illustrative permission states for real data/results.

### Button-to-method map

| UI Set action | Method on `AppMenuController` |
|---|---|
| App menu trigger / app Menu input | `ToggleMenu()` |
| Home / Patients / History | `OpenHome()` / `OpenPatients()` / `OpenHistory()` |
| Capture / Review / Options | `OpenCapture()` / `OpenReview()` / `OpenOptions()` |
| New test / completed capture / finding | `OpenTestSelection()` / `OpenProcessing()` / `OpenFindingDetail()` |
| Foot review / microscope | `OpenFootReview()` / `OpenMicroscope()` |
| Back or close-menu action | `Back()` / `CloseMenu()` |

Keep the controller and coordinator on always-active GameObjects. If a destination has not been wired, `TryOpen` logs an error and leaves the current screen in place; do not treat a missing page as a successful navigation. All `Open...` actions, including menu actions, call the same coordinator guard before changing roots.

The controller receives Unity focus/pause callbacks and blocks app input while unfocused. The session coordinator must implement the actual capture, replay and hand/controller-visual effects; this handoff does not claim to save a recording or pause a clock by itself.

## Check before calling it Quest-ready

- In Unity Play mode, verify bound routes show only their page, update selected marks, and close the menu. Test a saved Review → dated History Back, new test → Test Selection → Capture → Processing → Review, and contextual Back/Options return.
- While recording, try Back, History, Review and Options. No page may deactivate until interruption is confirmed or the action is rejected; completed frames remain intact and a take is explicitly marked interrupted.
- Test missing bindings: clicking an unbound destination must leave the current page visible and log an error.
- In the headset, check panel size/legibility, both ray and poke selection, selected/focus/pressed states, the left-controller Menu button, standard hand-menu route, visible Options and Back. Confirm that Quest's own universal menu still works.
- Trigger system UI/focus loss during capture and review: ignore app input, hide app input visuals, keep replay source time, explicitly interrupt active capture, and restore review state on return without auto-resuming.
- Build, install, and test an Android/Quest app **from the existing Unity project**. No APK or in-headset verification was produced with this handoff.