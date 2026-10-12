# Archived app menu prototype

`AppMenuController.cs` is a source-only navigation prototype. The current Quest
app uses [`WorkflowPanel`](../../quest/Assets/Physio/Viewer/WorkflowPanel.cs)
instead. This folder contains no scene, prefab, package manifest, or APK.
The repository's working Unity project is in [`quest/`](../../quest/README.md).

The prototype remains available as a reference for guarded navigation. It does
not implement patient storage, camera capture, processing, or reconstructed
replay. Its `Home`, `FindingDetail`, and `FootReview` names differ from current
runtime screen names. Do not use its screen list as the current workflow spec.
See the [current state map](../../docs/design/workflow-states.md).

## Prototype interface

`AppMenuController` shows one bound page root at a time and maintains an
app-owned menu. An optional selected marker identifies each destination.
`IAppNavigationCoordinator` approves transitions and supplies contextual Back.
Without a coordinator, the controller disables itself.

The controller rejects invalid initial screens, duplicate bindings, nested page
roots, and misplaced selected markers. An unbound destination logs an error
and keeps the current page visible. Back closes an open menu before asking the
coordinator for a destination. Focus callbacks block input and notify the
coordinator, which must implement capture and replay effects itself.

## Optional prototype wiring

To experiment with this archived controller in a separate scene:

1. Place the controller and coordinator on always-active objects outside page roots.
2. Assign a separate menu root and independent sibling roots for exposed screens.
3. Implement `IAppNavigationCoordinator`. Complete or reject capture and unsaved-data guards before approving a transition.
4. Bind optional selected markers as distinct children of the menu root.
5. Connect UI buttons to the public methods below. Leave unimplemented destinations hidden.
6. Configure actual ray and poke controls separately. Preserve Quest system input.

| Action | Public method |
|---|---|
| Toggle or close app menu | `ToggleMenu()`, `CloseMenu()` |
| Home, patients, or history | `OpenHome()`, `OpenPatients()`, `OpenHistory()` |
| Test selection or capture | `OpenTestSelection()`, `OpenCapture()` |
| Processing or review | `OpenProcessing()`, `OpenReview()` |
| Finding or foot review | `OpenFindingDetail()`, `OpenFootReview()` |
| Microscope or options | `OpenMicroscope()`, `OpenOptions()` |
| Contextual Back | `Back()` |

Each exposed `Open...` destination needs its own bound root, including screens
styled as dialogs. The coordinator must reject impossible jumps, such as Review
without a selected patient and validated result.

For native controls, see Meta's [UI Set](https://developers.meta.com/horizon/documentation/unity/unity-isdk-uiset/)
and [ray-castable UI](https://developers.meta.com/horizon/documentation/unity/unity-isdk-create-raycast-ui/) guidance.

## Reference images

The [Capture export](../capture-preview.jpg) and [Review export](../review-preview.jpg)
are historical browser mockups. They contain synthetic patient context and
unavailable sources, including earlier Barefoot and Back-to-capture labels.
They are not Unity prefabs or clinical evidence. Current new tests use ELK, RTK,
and Walking review, and saved Review returns to patient History.

Test prototype binding failures and transition guards in Unity before using this
controller in any scene. A successful navigation check does not verify camera,
recording, service, or headset behavior.
