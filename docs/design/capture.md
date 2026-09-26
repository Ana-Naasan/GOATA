# Quest Capture — design handoff

**Scope:** Capture preflight plus an illustrative interruption state. This handoff covers the browser mockup frame; Review is a separate frame and handoff.

## Panel placement and legibility

- At a 1600 × 1000 browser viewport, the frame is a centered 1080 × 680 panel: about 260 px of horizontal and 160 px of vertical breathing room. The pale, opaque backplate stays readable against the muted spatial surround; the camera well is the single dark focal area.
- Persistent context stays in the compact top bar: app menu, synthetic patient Morgan Chen (`QX-0248`), test date, and selected test. The broad preview is the primary visual anchor; setup details sit in one narrow column, with no unverified step count.
- Main actions have at least 60 px of height; the top-bar test dropdown trigger is at least 56 px tall and its three menu options at least 64 px tall. Context readouts use dividers rather than separate cards. The panel stacks below 1040 px and remains scrollable on small screens.
- Treat browser pixels as a layout proxy only. For a Unity world-space panel, begin around 1–1.5 m viewing distance as required by the handoff spec, keep the panel facing the user and within comfortable reach/field of view, then validate its physical size, text legibility, poke and ray interaction in-headset.

## UI Set control mapping

This React mockup uses native HTML controls styled to map to Meta UI Set patterns. **No Unity UI Set prefab, Meta XR Interaction SDK component, camera permission API, or Quest input binding is imported or connected.**

| Capture element | UI Set pattern / behavior |
|---|---|
| App menu | App-owned navigation dropdown with Home, Patients, History, Capture, Review, and Options. Capture is marked current; other destinations show a preview-only notice rather than claiming connected navigation. In Unity, the session coordinator guards every destination while recording. This is not Meta's system menu. |
| Back | Secondary/borderless button. In this isolated browser preview, it shows a notice that the intended destination is Morgan Chen’s patient history; it does not navigate browser history. |
| ELK / RTK / Barefoot | An app-owned dropdown in the top bar with exactly three mutually exclusive choices. The selected value remains visible when closed; open options use a selection mark, text, and outline/tint—not color alone. Browser pointer and keyboard interactions stand in for future Quest ray/poke behavior. |
| Side / View / Condition | Read-only unset context placeholders until approved session requirements are provided. |
| Capture protocol / Estimated scale | Inline status rows, not interactive cards. Protocol is pending; scale is unavailable. |
| Start capture | Primary button. Opens the source-unavailable alert dialog; it does not start recording. |
| Retake | Disabled secondary button because no recording exists. |
| Camera-permission/source-unavailable example dialog | Focused alert dialog with `Try again` and `Close`, Escape dismissal, focus return, and Tab containment. This is illustrative, not an actual permission result. Retry reports mockup camera-access checking, then the still-unavailable error. |
| Preview interrupted state | Demonstration control beneath the viewfinder; shows `Resume`, `Retake`, and `Cancel` without claiming that a recording exists. Resume/Retake lead to the unavailable-source dialog; Cancel returns to pre-capture. |

## Per-action targets and states

| Action | Target in this preview | States / notes |
|---|---:|---|
| App menu | Large top-bar trigger and stacked choices | Opens inside the Capture panel; Capture is visibly current, and other destinations explain that navigation is preview-only. |
| Back | 92 × 60 px | Rest, hover, pressed, focus-visible; opens a non-blocking destination notice with Dismiss. |
| Test dropdown trigger / each option | At least 56 / 64 px tall | Expanded, selected, hover, pressed, keyboard focus; exactly one selected. Arrow keys navigate; Escape and outside click dismiss the menu. |
| Start capture | 145 × 60 px | Rest, hover, pressed, focus-visible; opens unavailable dialog. No recording state is entered. |
| Retake | 145 × 60 px | Disabled while there is no recording; reason exposed in its accessible name and adjacent recording status. |
| Dialog Close / Try again | At least 138 × 60 px | Close dismisses; retry is available, then disabled with visible checking status; failure remains explicit. Escape is a second dismissal path. |
| Context and availability rows | Read-only | Explicit “Not set,” “Not specified,” “Pending,” and “Unavailable” labels. |

Important states use text and icon/shape alongside color. The disabled retake state, selected dropdown value, illustrative permission/source-error dialog, loading state, and interruption are visible. Live recording, completed recording, and processing are not implemented by this frame.

## Source and export mapping

- Versioned annotation source in the team repository: `docs/design/capture.md` (this file); visual export: `design/capture-preview.jpg` (1600 × 1000 image of the pre-capture state with the app menu open and test dropdown closed). This mapping is a design handoff, not a Unity UI Set prefab.
- The interactive browser prototype source remains in the separate Replit design workspace at `artifacts/mockup-sandbox/src/components/mockups/quest-capture/QuestCapture.tsx`; it is not included in this repository or required for Unity import.
- Unity translation: keep a stable, user-facing world-space Canvas/backplate; replace the browser dropdown, primary/secondary buttons, text/readouts, and alert dialog with corresponding Meta UI Set controls/prefabs. Add ray and poke interactables to the controls and validate focus/pressed feedback in the target headset. Keep the preview area a separately sourced video surface; do not bind it to a camera until the capture runtime is approved and implemented.
- Do not describe the browser styling as imported Meta UI Set assets or as an implementation of Quest camera permissions.

## Pending inputs for Hamza

1. Approve the actual test protocol/instruction text and whether Side, View, or Condition must be set before capture. Keep those fields pending/unset until supplied.
2. Confirm the source of truth for capture date, and replace/approve the clearly marked synthetic demo record before using real participant data.
3. Provide the supported Quest camera/capture integration, permission behavior, evidence-quality criteria, and calibrated scale source. Until then, camera preview and estimated scale remain unavailable; retry is deliberately a mock feedback state only.
4. Confirm the Unity panel physical dimensions, desired default theme, target Quest model, and minimum text/target sizes after in-headset ray and hand-poke testing.