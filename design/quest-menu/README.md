# Foot Assessment — Quest app menu integration

This folder is a **source-only handoff for the team's existing Unity project**, not a second Unity project. After reviewing the handoff, the Quest/Unity owner can copy `AppMenuController.cs` into that project's `Assets/Scripts/FootAssessment/` folder. This handoff does not change the Unity project. No scene, prefab, package manifest, Android build, or Meta system-menu modification is included.

## What the code does

- Shows exactly one app screen at a time: Home, Patients, History, Capture, Review, or Options.
- Opens/closes the **app-owned** menu and marks the active destination, provided each destination has a selected-state GameObject.
- Routes Back from Review → Capture → History → Patients → Home. Options returns to the screen from which it was opened; Back closes the menu first when the menu is open.
- Rejects invalid initial-screen, duplicate, nested-root, or misplaced selection-marker bindings on startup. An unbound destination logs a Unity console error when clicked and leaves the current page visible.

This is navigation logic, **not a complete headset app**. The separate browser designs for the app menu, Capture, and Review are visual/interaction references only. They cannot be copied into Unity as prefabs.

## Integration work still required

| Area | The existing Unity project must provide |
|---|---|
| App scene | A launchable Quest scene with a world-space app panel, a persistent navigation object, and separate Home, Patients, History, Capture, Review, and Options page roots. This folder provides no scene or prefab. |
| UI Set and input | Actual Meta UI Set controls and their select events, a configured EventSystem/canvas, controller or hand ray, direct poke, focus/pressed feedback, and an app-menu input binding. Do not remap the OS Meta button. |
| Session data | The real patient/session source and access rules, test date/type, side/view/condition requirements, and approved protocol. The browser names and dates are synthetic design examples. |
| Capture | A supported Quest camera/recording source, permission handling, interruption/retry behavior, retake/use-recording actions, and evidence-quality criteria. The browser preview records nothing. |
| Review | Separate original and amplified footage sources, processing stage/elapsed/failure from a real job, evidence provenance, foot review, and microscope/options behavior. No clinical conclusions are supplied by this module. |
| Delivery | Android/Quest build configuration, installation, and in-headset verification in the existing Unity project. This repository cannot produce or validate an APK. |

Request the separate Capture and Review design handoffs for visual layout and state details. The C# controller intentionally owns only navigation; it does not fake camera access, recordings, processing, or patient records.

## Wiring in the existing Unity scene

1. Ensure Meta XR Interaction SDK Essentials/UI Set is available in the **existing Unity project**. Keep the app-owned menu on a stable, readable world-space panel; this is not the Quest universal menu.
2. Add a persistent `FootAssessmentNavigation` GameObject **outside** all screen and menu roots. Attach `AppMenuController`. Keep the menu root separate from the six screen roots; none of those roots should contain another.
3. Assign `Menu Root` to the GameObject containing the menu UI. Add a `Screens` entry for each of the six screens, pointing to its existing page/root. For each entry, optionally assign a **distinct, non-nested child of the menu root** as its small selected marker; never assign the menu root itself. Keep all page roots outside the menu root. Set `Initial Screen` to Home. All six roots must exist before their destinations can be opened.
4. Connect the UI Set select/click event for each menu item to `OpenHome`, `OpenPatients`, `OpenHistory`, `OpenCapture`, `OpenReview`, or `OpenOptions`. Connect the app menu button to `ToggleMenu` and each nested screen's Back button to `Back`. Wire the controller's **app Menu** input to `ToggleMenu` if desired; do **not** intercept or replace the Meta button or Quest universal menu.
5. Configure hand-poke and controller/hand-ray interaction for the actual UI Set controls and world-space Canvas in Unity. Use Meta's [UI Set](https://developers.meta.com/horizon/documentation/unity/unity-isdk-uiset/) and [ray-castable UI](https://developers.meta.com/horizon/documentation/unity/unity-isdk-create-raycast-ui/) guidance. The C# script deliberately avoids direct Meta SDK types so it can be copied in before the UI Set prefabs are wired.
6. Put the real Capture/Review UI, session data, camera/permission handling, evidence processing, and approved clinical protocol in the Quest owner's implementation. Do not substitute the browser mockup's synthetic patients, placeholder footage, or illustrative permission states for real data/results.

### Button-to-method map

| UI Set action | Method on `AppMenuController` |
|---|---|
| App menu trigger / app Menu input | `ToggleMenu()` |
| Home / Patients / History | `OpenHome()` / `OpenPatients()` / `OpenHistory()` |
| Capture / Review / Options | `OpenCapture()` / `OpenReview()` / `OpenOptions()` |
| Back or close-menu action | `Back()` / `CloseMenu()` |

Keep the controller on an always-active GameObject. If a destination has not been wired, `TryOpen` logs an error and leaves the current screen in place; do not treat a missing page as a successful navigation.

Back follows the fixed Review → Capture → History → Patients → Home sequence, not the user's visit history. `TryOpen` immediately deactivates the previous page; it does not ask about unsaved data or an active recording. The Unity owner must add any required capture-interruption confirmation or navigation guard before enabling those actions in a live session.

## Check before calling it Quest-ready

- In Unity Play mode, verify each of the six menu actions opens only its bound page, updates its selected mark, and closes the menu; verify Back and Options return behavior.
- Test missing bindings: clicking an unbound destination must leave the current page visible and log an error.
- In the headset, check panel size/legibility, both ray and poke selection, selected/focus/pressed states, app Menu input, and Back. Confirm that Quest's own universal menu still works.
- Build, install, and test an Android/Quest app **from the existing Unity project**. No APK or in-headset verification was produced with this handoff.