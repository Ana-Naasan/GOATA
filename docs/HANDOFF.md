# Codex session handoff

## Current state

- **Last updated:** September 26, 2026.
- **Phase:** documentation complete; implementation not started.
- **Original deadline:** September 27, 2026, 10:00 a.m. EDT.
- **Repository:** https://github.com/B2707/HTH-3-sarakbi-asadi-steitieh-grp

The original documentation task produced the portable spec. On September 26 the user then authorized GitHub task allocation and separate branches for the team. This setup does not claim application implementation or authorize paid compute/deployment/participant uploads.

## Team setup — September 26

- Shared starting commit: `ab5bafa` (`docs: specify Quest physio demo and Codex handoff`).
- Current local branch: `codex/bader-backend`, tracking its remote. Team-setup documentation is recorded on this branch; use `git log -1` for its resulting commit.
- Four GitHub issues and four linked personal branches were created from `main`:
  - Bader, [#1](https://github.com/B2707/HTH-3-sarakbi-asadi-steitieh-grp/issues/1): `codex/bader-backend`.
  - Mohammad, [#2](https://github.com/B2707/HTH-3-sarakbi-asadi-steitieh-grp/issues/2): `codex/mohammad-ml`.
  - Hamza, [#3](https://github.com/B2707/HTH-3-sarakbi-asadi-steitieh-grp/issues/3): `codex/hamza-quest`.
  - Mustafa, [#4](https://github.com/B2707/HTH-3-sarakbi-asadi-steitieh-grp/issues/4): `codex/mustafa-design`.
- Issues contain ordered tasks, disjoint file ownership, handoffs and exact first-checkout commands. `AGENTS.md` records the same ownership boundaries. No scheduled checkpoints were added.
- Bader and Mustafa are assignable collaborators. GitHub lists existing pending write invitations for `MohammadESteitieh` and `HamzaAlsarakbi`; their issues name the owners but cannot receive those assignees until acceptance. Recheck before assigning; do not duplicate the invitations.
- Main protection now requires pull requests, applies to administrators, permits zero required approvals, and disallows force-pushes/deletion. No nonexistent status checks were required. Automatic deletion of merged branches was already disabled and remains disabled.
- Only Bader's local checkout was switched. Other teammates must accept invitations where needed and run their issue's checkout commands; remote branch creation does not verify their local state.
- The user reports that Quest hardware and GPU access are ready. Actual GPU model/runtime, body assets, headset camera build and model execution have not been verified in this checkout.

Verification commands executed successfully:

```sh
gh api repos/B2707/HTH-3-sarakbi-asadi-steitieh-grp/collaborators --paginate
gh api repos/B2707/HTH-3-sarakbi-asadi-steitieh-grp/invitations
gh api repos/B2707/HTH-3-sarakbi-asadi-steitieh-grp/assignees --paginate
gh issue create --repo B2707/HTH-3-sarakbi-asadi-steitieh-grp --title '<owner task>' --body-file '<reviewed task file>'
gh issue develop 1 --repo B2707/HTH-3-sarakbi-asadi-steitieh-grp --base main --name codex/bader-backend
gh issue develop 2 --repo B2707/HTH-3-sarakbi-asadi-steitieh-grp --base main --name codex/mohammad-ml
gh issue develop 3 --repo B2707/HTH-3-sarakbi-asadi-steitieh-grp --base main --name codex/hamza-quest
gh issue develop 4 --repo B2707/HTH-3-sarakbi-asadi-steitieh-grp --base main --name codex/mustafa-design
git fetch origin
git switch --track origin/codex/bader-backend
```

The issue-create line abbreviates the four owner-specific title/body-file arguments; Bader and Mustafa were also assigned to their respective issues. Protection was configured through GitHub's branch-protection API and checked from its response. These are repository-setup checks, not application/device/model tests.

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

1. The user reports Quest and GPU access ready; the concrete runtime, model assets and end-to-end compatibility are still unverified.
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
