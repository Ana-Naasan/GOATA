# Movement analysis reference

Movement review combines estimated pose observations, local movement patterns,
and a separate Findings view. The review labels results as research output without
clinical validation. See [project status](STATUS.md) for verification and device gaps.

## Service outputs

[Result contract](openapi.yaml) version 1.1 includes `observations` alongside
`findings`. [Publication validation](../processing/publication.py) checks the result
before publication. Historical version 1.0 results remain supported.

[The pipeline](../processing/pipeline.py) reconstructs the selected take, exports
its replay geometry, and calculates observations from original exported joints.
It publishes `findings: []` because no evaluated exercise classifier is installed.
An empty Findings view does not establish a correct repetition.

[Observation calculations](../processing/analysis/observations.py) use these quantities:

| Test | Quantity | Meaning |
|---|---|---|
| ELK seated flank stretch | Lateral torso lean | Signed hip-to-shoulder midpoint angle relative to estimated upright and the horizontal hip axis, at the greatest absolute eligible sample. |
| RTK seated torso rotation | Shoulder-to-pelvis rotation | Maximum absolute shortest angle between horizontal shoulder and hip axes. It does not establish anatomical turn direction or accumulated rotation. |
| Walking review | Left and right knee bending | Separate maximum hip-knee-ankle bending angles. A straight fitted leg is zero degrees. |
| Walking review | Trunk inclination | Maximum unsigned hip-to-shoulder midpoint angle relative to estimated upright. It does not establish walking direction or lumbar motion. |

The generator validates source take, frame IDs, timestamps, frame validity, joint
validity, and geometry. Missing joints or degenerate geometry produce explicit
unavailable quantities. The generator does not bridge gaps or interpolate peaks.
Each observation links to its exact source frame. Equal peaks retain the first frame.

Measurements use unamplified joints before display transforms. Display scale,
playback speed, and microscope amplification do not change stored measurements.
Finite fitted joints are model estimates, not proof of visible anatomical landmarks.
Output has limited evidence quality and no calibrated confidence or clinical thresholds.

## Quest review

[The review panel](../quest/Assets/Physio/Viewer/WorkflowPanel.Insights.cs) defaults
to local Patterns and presents a Goata score gauge. It uses saved Observations
when local pattern items are absent. Findings occupy a separate tab. Cards have
pagination, a scrollable review body, and a method-and-limitations detail view.
The Goata score is a local research summary, not an evaluated clinical finding.
The score model's `Details` are not connected to a score-detail viewer.

[Local pattern review](../quest/Assets/Physio/Viewer/WorkflowPanel.Patterns.cs)
classifies the saved reconstructed pose. This path is separate from the service's
observation generator and from an evaluated clinical assessment.

Selecting a matching-take card pauses and seeks the replay to its evidence and
highlights named joints. [Evidence selection](../quest/Assets/Physio/Viewer/ReviewEvidence.cs)
keeps other-take evidence separate. Opening another take pauses the hologram and
clears temporal highlights. Independent performances do not share a timeline.

Review Options exposes saved result versions. Reprocessing is available only
through the guarded Processing context. Device legibility, input, anatomical
alignment, and restart recovery require real Quest checks.

## Motion microscope

[The microscope](../processing/microscope.py) processes original video, separately
from reconstructed-joint measurements. The pipeline supplies no user-selected crop
or interval. Its default selects the first eight seconds, bounded to 240 source
frames, and can reject unsuitable evidence. Review controls do not establish that
a user-selected crop reaches this processing path. Amplified motion may include
recording artifacts and must not drive numerical assessment.

## Assessment limits

The ELK Error1 nearest-centroid candidate is an offline baseline. It is not an
installed, evaluated Quest exercise assessment. RTK predictions remain unsupported.
Automated foot assessment is unavailable. The historical manual foot method needs
calibrated landmarks. Preserve older barefoot records without relabelling them as
Walking review.

Clinical assessment still requires reviewed labels, participant mappings, matching
training and live pose definitions, participant-separated evaluation, and fresh
Quest recordings. Report per-class counts, precision, recall, and false positives
on correct takes. Only evaluated temporal labels justify onset and offset claims.
The practitioner chooses corrections. Output does not prescribe treatment.

The 1 to 2 minute target covers final capture through loaded analysis and replay.
GPU stage timings alone do not measure that path.

## Source references

- [KERAAL repository and annotations](https://github.com/nguyensmai/KeraalDataset)
- [GVHMR reconstruction](https://github.com/zju3dv/GVHMR)
- [Product specification](SPEC.md)
- [GPU setup and historical measurements](../processing/reconstruction/GPU_SETUP.md)
