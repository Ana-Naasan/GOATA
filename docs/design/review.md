# Quest Review — design handoff

**Scope:** Interactive browser prototype of the app's Review screen, not Quest system UI. The sample session contains no real recording, processing result, clinical finding, or calibrated measurement.

## Layout and context

- The centered, user-facing panel keeps the synthetic patient, current test date and type visible when a session exists. The main evidence area distinguishes source footage from the session-context and evidence-state column. At 1600 × 1000, it is a visual scale reference only; Hamza must validate physical size, legibility, ray targets, and hand-poke reach at roughly 1–1.5 m in Quest.
- The second synthetic patient has no dated sessions. Selecting them replaces the Review content with an empty-session state; it does not carry over Morgan Chen's date, test type, or evidence controls.
- The dated History dialog explicitly marks the older record as a previous recovery example. It must never look like the current result.

## Meta UI Set pattern mapping

This React preview uses browser controls styled around Meta UI Set patterns. **It does not import Unity UI Set prefabs, implement Quest hand/controller input, connect footage, or run processing.**

| App element | UI Set translation and intended behavior |
|---|---|
| Back | Borderless secondary button. The isolated browser preview shows a destination notice rather than navigating. In Unity, a saved Review returns to the selected patient's dated History and exact saved result version; it must never start a new Capture. The session coordinator resolves Back for other contexts. |
| Patient selector | Dropdown/selector with synthetic patients. Selecting a patient resets session-specific preview controls; a patient without history gets the empty state. |
| History | Secondary button opens a dialog of dated test entries or a clear empty-history message with `Start new test`. The recovery example remains marked as previous. |
| Evidence / Foot review | Tab controls with explicit selected state. Foot review shows unavailable source and unset side/view/condition; return to evidence is provided. |
| Original / Amplified footage | Separate labelled source tabs and separate unavailable messages. Never treat amplified footage as the original source. |
| Processing | Status card displays `Waiting for source`, stage `Not started`, and elapsed `—` because no job exists. `Retry` demonstrates checking, then failure when footage remains absent; it is not real processing. |
| Evidence state | Selectable `Unavailable` / `Poor evidence example` tiles. Poor quality is only an illustrative state; verified quality criteria are pending. No diagnosis or treatment is shown. |
| Microscope | Dialog with source-unavailable message and disabled zoom/focus sliders until actual evidence exists. |
| Options | Dialog with local preview toggles for source details and a scale-guide request. A calibrated scale is not claimed. |

The versioned browser export still shows the prototype label “Back to capture.” That label and its notice are **not** the Unity navigation specification: replace them with a contextual Back action. For a saved test, show “Back to patient history” and return to the same patient's dated History; never enter a new capture. The coordinator owns Back for other contexts.

## States and handoff

- Visible or selectable: current synthetic session, second patient with empty history, original/amplified source-unavailable states, waiting/checking/failed retry, unavailable/illustrative poor evidence, foot-unavailable view, microscope-unavailable view, and display options.
- Not implemented: a real completed recording, actual processing stage or elapsed time, verified findings, evidence-quality calculation, calibrated scale, persistent patient data, or in-headset interaction. Do not show a processing success or clinical conclusion until supplied by the runtime.
- Versioned annotation source in the team repository: `docs/design/review.md` (this file); visual export: `design/review-preview.jpg` (1600 × 1000 default synthetic-session state). It is a visual reference, not a Unity prefab or evidence image.
- The interactive browser prototype source remains in the separate Replit design workspace at `artifacts/mockup-sandbox/src/components/mockups/quest-review/QuestReview.tsx`; it is not included in this repository or required for Unity import.
- Unity handoff: Hamza maps the selector, tabs, buttons, dialog, toggles, and disabled sliders to Meta UI Set equivalents, binds actual state/data and footage sources, and checks layout with both ray and poke in Quest. Keep assets outside `quest/**` until Hamza imports them.

## Pending decisions

1. Mohammad's verified protocol and any permitted evidence/condition labels.
2. Actual source and relationship of original versus amplified footage, recording timestamps, processing stages, elapsed time, and failure/retry behavior.
3. Evidence quality criteria, calibrated scale source, and whether microscope controls can operate on available evidence.
4. In-headset target sizes, physical panel dimensions, and placement after testing with Hamza.