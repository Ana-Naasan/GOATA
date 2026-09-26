# Physio Motion Replay

A Meta Quest 3 physiotherapy demo: record a supported test, then walk around a translucent blue replay of the participant with an aligned skeleton and evidence-linked findings.

**Current state: specification only. No Quest app, processing service, trained model or validated assessment has been implemented in this repository.**

## Start a new Codex session

Open this repository and tell Codex:

> Read AGENTS.md, docs/HANDOFF.md, docs/SPEC.md and docs/openapi.yaml. Continue with the next incomplete implementation milestone. Inspect the actual environment before choosing versions. Preserve the agreed features, use existing Meta components, and update the handoff with verified results before stopping.

| Document | Purpose |
|---|---|
| [Complete specification](docs/SPEC.md) | Product decisions, capture and analysis, architecture, replay formats, implementation order and acceptance criteria. |
| [Session handoff](docs/HANDOFF.md) | Actual completion state, blockers, next work and verification record. |
| [Processing API contract](docs/openapi.yaml) | Proposed transfer, job status and result interface for Quest and the processing service. |
| [Codex instructions](AGENTS.md) | Working rules and requirements that must survive session changes. |

## Agreed demonstration

1. Select a patient and one of three tests: seated flank stretch, seated torso rotation, or barefoot assessment.
2. Follow test-specific capture instructions through Quest 3.
3. After capture, process the recording. Target **1–2 minutes** until results are loaded; this has not been benchmarked.
4. Inspect the animated blue body and skeleton, pause, walk around it, scrub, reverse or change speed.
5. Select a labelled finding to inspect its recorded evidence. The physio chooses any correction.
6. Use motion magnification on suitable original footage and reopen saved tests from patient history.

Barefoot assessment uses its own close-up evidence. It cannot create a full-body replay from cropped feet. Foot analysis and motion magnification remain required features with unresolved validation work.

## Intended implementation

- **Quest:** Unity/C#, OpenXR, Meta XR SDKs and Meta Horizon OS UI Set.
- **Processing:** Python on compatible NVIDIA compute for the selected reconstruction model; a small HTTP service for transfer and jobs.
- **Data:** local patient histories, original recordings, versioned results and explicit evidence provenance.

The original hackathon deadline is **September 27, 2026, 10:00 a.m. America/Toronto**. Recheck the current time before allocating work. Source links and known limitations are in the specification.

Do not commit participant recordings, identifying profile data, model weights, credentials or restricted datasets.
