# Codex session handoff

## Current state

- **Last updated:** September 26, 2026.
- **Phase:** documentation complete; implementation not started.
- **Original deadline:** September 27, 2026, 10:00 a.m. EDT.
- **Repository:** https://github.com/B2707/HTH-3-sarakbi-asadi-steitieh-grp

The repository was empty when this documentation task began. The user requested a complete portable spec and explicitly authorized committing/pushing it here. That request did not ask this session to implement the app, provision compute or upload participant recordings.

Read `SPEC.md` for all accepted decisions and `openapi.yaml` for the proposed service contract. This handoff records actual progress, not intended architecture.

## What is complete

- Product interview: three tests, guided capture, patient histories, blue 3D body/skeleton, replay controls, evidence-linked findings, foot assessment and microscope.
- User accepted 1–2 minutes after final capture as the target for loaded results; not benchmarked.
- User selected findings/explanation/evidence only; the physio decides corrective action.
- Standard Meta UI and menu approach documented.
- Requirements, data/replay formats, service contract, work sequence, failure cases and acceptance checks written.

## What is not implemented or verified

- Unity project/APK, camera capture, headset rendering or UI.
- Service, upload, persistence or job processing.
- GVHMR running on our footage or export/import working on Quest.
- KERAAL data access/preprocessing, trained exercise analysis or held-out evaluation.
- Foot model/measurement and its validation.
- Motion magnification on Quest footage.
- Any target latency, memory, frame rate or clinical performance.

No actual participant recording, trained model, private credential or downloaded dataset is included.

## Next task for a fresh session

**Start M0/M1: prove one real recording can become an aligned blue-body/skeleton replay.**

1. Inspect Git status and read all four project documents.
2. Recheck the current time and available tools/device/GPU. Do not assume hardware is already connected.
3. Confirm model/body-asset and KERAAL access. Prioritize the CUDA model compatibility proof and a minimal official Quest camera/UI sample.
4. Build/test one source-time-preserving export and Unity import before expanding UI or model categories.
5. Record actual commands, pinned versions, durations and failures here.

Independent work can be split between camera/UI, reconstruction/export and replay/clock. Assign file ownership first. A desktop fixture verifies mechanics; a real clip and eventual Quest run are still required.

### First inspection commands

Run from the repository root:

```sh
git status --short --branch
git log -5 --oneline
cat AGENTS.md docs/HANDOFF.md
cat docs/SPEC.md
command -v python3 adb git gh
```

Then inspect Unity installations and any manifests that actually exist. There is no application install/build command yet. Do not invent `npm install`, a Unity version or a working Python environment.

## Risks to address first

1. Hardware/compute and model assets are unverified. The user mentioned sponsor compute, but no provider/GPU/credentials have been confirmed.
2. GVHMR's inspected demo assumes 30 FPS and estimated intrinsics in relevant paths. Preserve source timing and verify camera calibration integration.
3. KERAAL ELK/RTK are seated protocols. Use the actual annotation guide, not generic standing exercise heuristics.
4. Dataset skeletons and Quest/model joints may differ. Establish a tested mapping or shared feature extraction.
5. No suitable automated foot method has been established. Preserve this required workstream and report its state honestly.
6. Head movement/noise may defeat useful motion magnification.

## Verification record for this documentation revision

Repository access and its empty state were checked before writing. This revision contains five documentation files; no application/dependency manifests exist yet.

Verified checks:

- `npm exec --yes --package=@redocly/cli@2.54.3 -- redocly lint docs/openapi.yaml --extends=minimal`: passed with zero warnings/errors.
- YAML parsing and local OpenAPI references: passed.
- Markdown relative links, balanced code fences and required sections: passed.
- Independent scope/contract review: addressed the separate-take timing rule. Findings from another recording cannot seek/highlight the main replay.
- Independent security review: no detected secrets, private local paths, participant data or restricted assets. No material design blocker found.

These are document/contract checks only. No application tests, dataset evaluation or headset tests have run. The publishing session verifies the remote commit after pushing; a fresh session should use `git status` and `git log -1` to confirm its checkout.

Implementation evidence: **none yet**. M0–M4 and A01–A20 in the specification remain unverified.

## How to update this file

Replace stale status with the current branch/commit, exact successful/failed commands, actual environment versions, completed acceptance checks and the next concrete action. Keep implementation facts separate from planned features. Do not preserve an obsolete success claim after a regression.

Use `git log -1` for the exact latest documentation commit; this file does not embed its own commit hash.
