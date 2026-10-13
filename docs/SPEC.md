# GOATA product requirements

GOATA records a consenting participant with Meta Quest 3 and presents the fitted
movement for practitioner review. The requirements below define the intended
product. The [project status](STATUS.md) identifies implemented behavior and
remaining acceptance work. The [engineering guide](ENGINEERING.md) explains the
implementation.

The [processing contract](openapi.yaml) and the
[capture](../processing/schemas/capture_sidecar.schema.json) and
[replay](../processing/schemas/replay_manifest.schema.json) schemas define the
machine-readable interfaces.

## Product scope

| Area | Requirement |
|---|---|
| Operator | The practitioner wears Quest 3 and records a consenting participant. |
| New tests | KERAAL ELK seated flank stretch, KERAAL RTK seated torso rotation, and Walking review. |
| Capture | Live framing guidance, explicit recording controls, original recordings, and source timestamps. |
| Reconstruction | A participant-fitted translucent blue body and an aligned estimated skeleton. Facial likeness, clothing texture, and photorealism are unnecessary. |
| Review | Full timeline, reverse, speed changes, frame steps, walk-around viewing, and display manipulation. |
| Records | Multiple local patients, dated assessments, immutable captures, and saved result versions. |
| Analysis | Test-specific observations and, when evaluated methods exist, clinical findings with explanations and source evidence. The practitioner chooses corrections. |
| Motion microscope | Matched original and amplified footage with explicit availability and limitations. This remains a required feature. |
| Interaction | Meta UI Set controls with familiar hand and controller behavior. |
| Optional work | Voice input follows the required workflow. Presentation effects must not alter evidence. |

Historical barefoot records retain their original identity and remain readable.
They are not relabelled as Walking assessments. New barefoot capture is outside
the current product scope.

The scope excludes automatic treatment advice, arbitrary exercise recognition,
face identification, production clinic accounts, additional sensing hardware,
and a live reconstructed body during capture.

## Patient workflow

The new-assessment flow is Patients, patient history, test selection, capture
setup, capture, capture summary, processing, and movement review. Opening a saved
assessment goes directly to its saved result or its recoverable capture state.

Each patient has a UUID independent of the display name. Patients with equal
names retain separate histories. Results remain associated with the patient and
session that submitted the job, even if the wearer changes the selected patient
while processing runs.

Reprocessing creates another result version. It preserves the original capture
and every previous result. A saved result reopens without rerunning inference.
The current interface does not expose every reprocessing path implemented by
storage and processing. Those limits are recorded in [project status](STATUS.md).

## Capture requirements

A new assessment uses four independent takes in this order: participant's right,
front, back, and left. Available durations are five, ten, or fifteen seconds,
selected before the first take. These settings describe the capture workflow,
not an evaluated clinical protocol.

The wearer previews the actual camera image before starting a three-second
countdown. Camera framing must reflect the recorded field of view. The
passthrough view can include areas that the camera does not record.

Each take retains its ID, test, view, anatomical side, capture condition, source
frames, timestamps, and interruption state. Retakes do not overwrite completed
recordings. A replay uses one selected source take. Separate performances do not
form simultaneous multi-camera evidence.

ELK and RTK remain seated exercises. Their guidance must use the relevant KERAAL
protocol and annotation definitions. Walking uses straight passes with the full
body and feet visible. The practitioner remains at the selected viewpoint while
the participant passes through the frame.

Capture requires consent and camera permission. Permission denial, missing
framing, and interruptions need visible recovery actions. Focus loss preserves
completed frames and marks the take interrupted. Recording does not resume
silently after focus returns.

## Review and spatial interaction

The body and skeleton share one source-time cursor and the same selected frame.
The reviewer can pause, seek, reverse, restart, step frames, and select speeds of
0.25, 0.5, 1, 1.5, or 2 times. Playback stops at either endpoint. Head movement
changes the viewing angle without rerunning reconstruction.

The reviewer can reposition, rotate, and uniformly resize the displayed body.
A common display transform keeps body, skeleton, and attached labels aligned.
Display scale and playback speed never change saved measurements. Initial
grounding uses reconstructed geometry and does not establish measured height or
registration to the physical room.

Matching-take evidence can pause, seek, and highlight the replay. Evidence from
another take opens separately while the body stays paused. Equal elapsed times
in different performances do not identify the same movement.

Evidence highlighting must use a label and a shape or line cue as well as color.
The required Options controls include finding-label visibility, manipulation and
playback help, and a patient-history action. Bringing the panel closer must be
separate from resetting replay placement. Controls that the current viewer does
not expose remain acceptance work, as listed in [project status](STATUS.md).

Panels must remain readable against passthrough and usable with one hand or one
controller. The app uses visible Back and Options controls and preserves patient
and test context. The Meta system menu remains system-owned. App focus loss
pauses replay and preserves its source time.

The optional Moon environment and Play mode affect presentation only. Capture
returns to passthrough first. Finding selection and presentation effects must
not obscure or modify source evidence.

## Observations and evaluated findings

| Test | Required observation scope |
|---|---|
| ELK | Estimated signed lateral torso lean from fitted shoulder and hip positions. |
| RTK | Estimated unsigned shoulder-to-pelvis rotation. |
| Walking | Estimated knee flexion on each side and torso inclination. |

Observations use original, unamplified geometry and preserve valid source
samples. Peaks identify their own original frame and time. Invalid joints,
degenerate geometry, and missing observations remain unavailable, not zero-valued
measurements. Gaps do not become measured motion through interpolation.

Fitted joints are estimated anatomy. Finite model output does not prove a joint
was visible or accurately reconstructed. Model scale is not measured physical
scale. Physical distances, step events, cadence, vertebral motion, and clinical
gait conclusions require separate supported methods.

A clinical finding requires an evaluated method, a supported label, an
explanation, body region or side, and inspectable source evidence. An unavailable
method is distinct from a completed assessment with no findings. Production
currently returns no evaluated clinical findings.

Training, evaluation, and demonstration recordings remain distinct. Evaluation
splits are by participant, not by frames from the same person. Results must state
the input domain, class counts, measured errors, and limits before supported
labels appear in the application.

### Goata Score

The score is a deterministic demonstration rule over fitted-pose observations.
It is not a trained classifier or a clinically validated correctness assessment.

| Test | Categories | Full-severity demo scales |
|---|---|---|
| Walking | Difference between knee-bending peaks and upper-body inclination. | 20 degrees and 30 degrees, respectively. |
| ELK | Shoulder-to-hip twist and fore-and-aft torso tilt. | 30 degrees each. |
| RTK | Sideways torso tilt and fore-and-aft torso tilt. | 30 degrees each. |

The two base weights are 50 each. Severity is the absolute angle divided by its
scale, capped at one. Available categories are reweighted to total 100. No
available category produces no score. The raw score is 100 minus the weighted
severity sum. Display rounding uses nearest integer, with halves away from zero.
The display bands are red for 0 through 50, yellow for 51 through 90, and green
for 91 through 100.

The score must preserve its contributing categories and source references.
The current viewer exposes the score and summary. The full calculation details
remain an interface gap. Observation details are a separate action.

## Motion microscope

The microscope retains original and amplified footage from the same take and
interval, with clear labels, method settings, and rejection reasons. Numerical
analysis continues to use the original evidence. Magnification can amplify
camera and compression artifacts.

The intended workflow supports a region and interval relevant to the selected
evidence. The current pipeline instead uses its default interval and does not
receive a user-selected crop. A separate ten-second steady hold is available in
Quest, but a useful real-camera result and region-selection behavior remain
acceptance work.

Unsupported footage, unstable background motion, and missing dependencies must
produce an explicit unavailable result. The microscope must not silently use
another take or turn an amplified artifact into a clinical observation.

## Source data and replay contracts

Original recordings and timestamps remain the source of truth. Capture sidecars
retain source frame IDs, nanosecond timestamps, camera metadata, validity, and
interruption information. Nanosecond timestamps are decimal strings in JSON.

Configured service inference requires the sidecar's explicit encoded-media
mapping. Source camera time and encoded microseconds remain separate. Each
decoded image must match the recorded mapping. The standalone model runtime
also supports an explicit legacy clock offset. That is not the configured
service path.

Resampling retains an inference-to-source map. Export keeps the first inferred
row for each unique source frame and retains the complete map in provenance.
It does not average separate predictions into a new observation.

Body vertices and joints use the same model output and frame selection. The
current exporter reflects native Z and reverses triangle winding once. Root
translation survives. Importers validate the declared Unity convention, finite
values, counts, topology, hashes, time order, and allocation limits before use.

Unavailable camera calibration remains unavailable. A documented pinhole
approximation is not lens calibration. No measured scale, confidence, or
alignment can be inferred from a successful export alone.

## Storage and deployment

Quest stores patient names, histories, recordings, and cached results privately.
The processor receives opaque patient, session, and take IDs. It stores accepted
captures and versioned results in a configured private directory.

The processing module validates a bounded flat ZIP and manifest, admits one
active job, and persists state before acceptance. The same idempotency key and
content identify the same job. Changed content conflicts. Admission limits can
still reject a retry before the stored key is checked.

A worker restart marks unfinished jobs interrupted and preserves accepted input.
Result publication validates and flushes artifacts before reporting success.
Failed or partial output cannot become a successful replay.

The HTTP interface requires a bearer token and TLS outside loopback. Credentials,
private recordings, restricted datasets, and model weights stay outside Git.
The included public demo film is presentation media. Model and asset terms apply
separately. This repository does not grant blanket redistribution rights.

Reconstruction runs through an operator-configured local command. Missing
configuration fails a requested full-body reconstruction explicitly. Historical
barefoot-only jobs can complete with unavailable analysis because they do not
require a replay.

The [developer guide](DEVELOPMENT.md) contains setup and request commands.
The [processing contract](openapi.yaml) and [settings](../processing/settings.py)
define enforced upload, storage, output, and runtime limits.

## Performance targets

The whole-path target is one to two minutes from the final required capture to
completed analysis and the first loaded replay frame. Measurement includes
preparation, transfer, inference, analysis, export, download, and headset loading.

Review targets are 72 Hz display refresh and feedback within 250 ms after seek.
These are acceptance targets, not measured claims. Local experiment timings
exclude parts of the Quest path and must retain their stated measurement scope.

## Acceptance checks

| ID | Check |
|---|---|
| A01 | Two patients retain separate histories while jobs complete asynchronously. |
| A02 | Restart restores the saved assessment, result version, replay, and evidence. |
| A03 | New tests offer only ELK, RTK, and Walking with their own guidance. Historical barefoot records remain accessible. |
| A04 | Permission denial, retakes, and interrupted capture preserve prior work. |
| A05 | Source timestamps survive rejection and resampling, including irregular timing. |
| A06 | An asymmetric fixture detects mirroring, wrong handedness, triangle winding, and scale conversion errors. |
| A07 | Body, skeleton, and matching-take evidence remain aligned through every playback action. Other-take evidence cannot seek this replay. |
| A08 | Display scale and playback speed leave saved measurements unchanged. |
| A09 | A paused body remains fixed in the room as the wearer changes viewpoint. |
| A10 | Invalid frames and joints remain distinguishable from zero movement. |
| A11 | Evaluation reports results on unseen participants and checks the Quest input domain. |
| A12 | Walking observations retain side, view, source frame and time, definitions, and limitations. |
| A13 | Microscope output pairs original and amplified evidence and rejects camera-dominated motion. |
| A14 | Findings contain explanations and evidence. The practitioner chooses corrections. |
| A15 | Navigation, recording, and review remain usable with one hand or controller. |
| A16 | App and system menus preserve replay time and interrupt capture correctly. |
| A17 | Idempotency, conflicting retries, and worker recovery cannot create false success. |
| A18 | Uploads and replay imports reject unauthorized, malformed, or oversized input. |
| A19 | A device run measures review refresh and seek latency against the stated targets. |
| A20 | A fresh run measures the complete final-capture-to-loaded-replay duration. |

Automated checks target at least 80% coverage for testable processing logic,
with exclusions stated. Device acceptance and model evaluation remain separate
from software coverage.

## Technical references

- [Engineering implementation](ENGINEERING.md)
- [Current analysis behavior](INSIGHTS_PLAN.md)
- [Quest build and checks](../quest/README.md)
- [GPU setup and model assets](../processing/reconstruction/GPU_SETUP.md)
- [KERAAL dataset and protocol code](https://github.com/nguyensmai/KeraalDataset)
- [GVHMR at the pinned revision](https://github.com/zju3dv/GVHMR/tree/ee960bb6e2ea2d381aa97f08e9b71ef320b624b1)
- [SMPL-X access and terms](https://smpl-x.is.tue.mpg.de/)
