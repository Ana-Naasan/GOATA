# Codex project instructions

## Read first

1. `docs/HANDOFF.md`: actual state and next task.
2. `docs/SPEC.md`: accepted scope, architecture, invariants and milestones.
3. `docs/openapi.yaml`: proposed processing-service contract.

These files must be sufficient without the original conversation. Follow the current user's request; the documentation itself does not authorize external spending, deployment or uploading participant recordings.

## Team branches and file ownership

Work continuously and hand off usable output immediately. The user does not want scheduled checkpoints.

| Owner | Branch | Exclusive files | GitHub task |
|---|---|---|---|
| Bader (`B2707`) | `codex/bader-backend` | `processing/**` except the ML paths below; `tests/backend/**`, `tests/contracts/**`; root/shared configuration, Python manifests/lockfiles, `.github/**`, shared project docs | [#1](https://github.com/B2707/GOATA/issues/1) |
| Mohammad (`MohammadESteitieh`) | `codex/mohammad-ml` | `processing/reconstruction/**`, `processing/analysis/**`, `tests/ml/**`; model-specific dependency pins inside those directories | [#2](https://github.com/B2707/GOATA/issues/2) |
| Hamza (`HamzaAlsarakbi`) | `codex/hamza-quest` | All `quest/**`, including scenes, prefabs, imported assets, `.meta` files, Packages, ProjectSettings and Unity tests | [#3](https://github.com/B2707/GOATA/issues/3) |
| Mustafa (`mustafahelmyh`) | `codex/mustafa-design` | `design/**`, `docs/design/**` | [#4](https://github.com/B2707/GOATA/issues/4) |

- Check the current branch and working tree before editing. Each person and their agents use that person's branch and owned paths. Ask the file owner before crossing a boundary; preserve others' changes.
- Hamza alone imports design assets into Unity. Mohammad supplies inference/model outputs; Bader owns the service wrapper and Unity exporter. Agree raw output shapes, coordinates, validity and source-time mapping before separate implementations.
- Bader integrates edits to `AGENTS.md`, `README.md`, `docs/SPEC.md`, `docs/openapi.yaml` and `docs/HANDOFF.md`. Other owners put results/requests in their GitHub issue or owned notes, including end-of-session evidence.
- Open small PRs into `main`. Keep personal branches after merging. Fetch and merge `origin/main` into the personal branch before a PR; resolve conflicts with the file owner. Prefer merge commits when reusing these branches so their shared history stays intact.
- Never force-push or delete another person's branch. Main requires a PR, with zero required approvals; force-push and deletion are disabled. File ownership is a team rule, not a filesystem or GitHub permission boundary.

## Preserve the product decisions

- Quest 3; practitioner wears the headset and captures a consenting participant.
- Exactly three new-test choices: KERAAL ELK seated flank stretch, KERAAL RTK seated torso rotation, and Walking review. The user replaced barefoot capture with Walking review on September 27, 2026; preserve historical barefoot sessions and results.
- Live capture guidance; completed findings and reconstructed replay after processing.
- Target 1–2 minutes from final capture to loaded analysis/replay; measure the whole path.
- Patient-fitted translucent blue body and aligned skeleton. Facial likeness, clothing colour and photorealism are unnecessary.
- Full timeline, reverse, speed, frame steps, walk-around viewing and display manipulation.
- Multiple patients and saved dated tests; findings specific to the chosen test.
- Findings include explanation and evidence. The practitioner chooses corrections; do not add automated exercise-correction or treatment advice.
- Walking observations and motion microscope are required. Observations are estimated quantities, separate from evaluated clinical findings. An unavailable feature must remain marked incomplete, not silently dropped.
- Use Meta's UI Set and familiar input/menu behaviour. Voice is optional only after the required flow works.

## Work simply and verify

Apply Ponytail full-mode principles: understand the actual flow, reuse existing code and native platform components, then write the smallest implementation that meets the requirements. Do not remove agreed features in the name of simplicity. Avoid new frameworks, queue infrastructure, account systems or generic plug-in architectures without a demonstrated need.

Inspect installed tools, device access and upstream revisions. Pin versions only after the relevant proof works. Do not assume CUDA models run on the Mac. Prefer a complete small vertical slice before expanding the UI or classifier.

Delegate independent work where useful, with explicit file ownership. Workers must preserve others' edits. Use architecture/planning help for complex changes and code review after code changes; use Python/C# and security reviewers when applicable and available.

For nontrivial logic, use tests before implementation. Cover timing, coordinate conversion, malformed inputs, patient isolation, persistence and failures. Target at least 80% automated coverage for testable application logic, reporting exclusions honestly. Unit/integration checks do not replace real Quest testing or model evaluation on unseen participants.

## Data and evidence invariants

- Original recordings/timestamps remain the source of truth. Preserve frame mappings through resampling and rejection.
- A skeleton is estimated anatomy. Model scale is not automatically measured physical scale.
- Use one source take per replay; repeated performances from different views are not simultaneous capture.
- Only matching-take findings drive the replay timeline/highlight; other-take evidence opens separately with the hologram paused.
- Surface, skeleton and findings share a verified coordinate/time mapping.
- Display scaling and playback speed must not change stored measurements.
- Missing observations remain invalid, not zero-valued measurements.
- Never fabricate findings, confidence, calibration, processing progress or validation results.
- Keep numerical analysis on original/unamplified evidence. Magnification can reveal recording artifacts.
- Training, evaluation and demo recordings are distinct. Do not split frames from the same person across train/test and claim generalization.

## Security and external actions

Keep credentials out of Git and Unity source. Bound uploads and decoded artifact sizes; reject path traversal, archive links and malformed arrays. Authenticate the processing service and use TLS for remote deployment. Do not expose it publicly by default.

Before commits, inspect staged files for secrets, participant media and restricted assets. Do not publish datasets or weights under a project-wide license. Follow the user's explicit authorization for pushes, deployments and paid compute; do not infer authorization for one from another.

## End-of-session handoff

Each owner records end-of-session evidence in their issue or owned notes. Bader integrates it into `docs/HANDOFF.md` with:

- the current branch/commit and actual completed milestone;
- changed files and exact commands run with outcomes;
- installed versions and model/data revisions actually verified;
- device/GPU access and remaining blockers;
- the next concrete task and any current failure to reproduce;
- feature and performance results, including unfinished requirements.

Update the spec and API contract when implementation changes their decisions. Keep examples labelled as examples. Do not call a feature complete because a mock or canned recording works.
