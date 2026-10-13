# Project status

GOATA has a Quest capture and replay application, an authenticated processing
module, and a CUDA reconstruction adapter. The code includes estimated movement
observations and a deterministic demo score. Clinical assessment remains
unavailable.

This page separates implementation from validation. The [engineering guide](ENGINEERING.md)
explains the code, and the [product requirements](SPEC.md) define acceptance.

## Implemented behavior

| Area | Current implementation | Remaining verification or limitation |
|---|---|---|
| Quest build | Unity 6000.0.66f2. App version 0.3.7, Android code 14. | These are checked-in build settings, not confirmation of the version installed on a headset. |
| Patient history | Local UUID-based profiles, dated assessments, saved takes, and result versions. | Full wearer acceptance and restart recovery on the current build still need a device run. |
| Capture | ELK, RTK, and Walking with four independent views, camera preview, countdown, retakes, and replay-take selection. | Source mapping and synthetic encoder checks do not establish the quality of every real recording. |
| Processing | Authenticated upload, bounded validation, one active job, durable results, and a configured local inference command. | GPU assets, camera assumptions, and the remote connection require operator configuration. |
| Reconstruction | GVHMR and SMPL-X produce aligned body vertices and joints from one take. | The fitted anatomy and physical scale are estimates. There is no measured registration to the Quest room. |
| Replay | Pause, seek, reverse, frame steps, speed changes, walk-around viewing, and display manipulation. | Legibility, reach, alignment, and responsiveness still require headset acceptance. |
| Movement review | Service observations and local Patterns retain source evidence. The viewer displays a Goata Score and summary. | Detailed score provenance exists in the result object but is not exposed by the current viewer. |
| Clinical findings | Results preserve explicit method availability and validation status. | Production results contain no evaluated clinical findings. ELK and RTK assessment and clinical gait analysis remain incomplete. |
| Motion microscope | The processor can produce original and amplified clips. Quest supports a separate steady hold and evidence playback. | The pipeline uses its default interval. User-selected regions and intervals are not forwarded, and a useful real Quest result remains unverified. |
| Optional replay effects | Moon environment, head nudges, and tomato interactions affect presentation. | Physical-room wall collisions remain incomplete. These effects do not alter saved measurements. |

Implementation sources include the [build configuration](../quest/Assets/Physio/Editor/FixtureBuild.cs),
[workflow](../quest/Assets/Physio/Viewer/WorkflowPanel.cs),
[processing pipeline](../processing/pipeline.py), and
[replay exporter](../processing/export.py).

## Known gaps in the current interface

- The score gauge receives the score and summary. The existing **Details** action
  opens observation details, not the full score calculation.
- Storage and processing support new result versions, but normal saved-review
  Options do not expose a general reprocessing action.
- Review Options expose skeleton visibility, body opacity, floor reset, and saved
  versions. Some additional controls in the product requirements remain pending.
- Historical barefoot data remains supported. Barefoot is not a new-test choice.

The [workflow source](../quest/Assets/Physio/Viewer/WorkflowPanel.cs) and
[insights presentation](../quest/Assets/Physio/Viewer/WorkflowPanel.Insights.cs)
define these interface limits.

## Performance evidence

The checked-in [streaming experiment](../experiments/streaming_inference/rtx3070-640-15.json)
records an eight-second prerecorded input on an RTX 3070. Its overlapping mode
produced a decode-verified annotated video 3.56 seconds after input stopped.
The models were already resident, and input arrived in four two-second chunks.
The same run's after-stop mode took 9.99 seconds to that output.

Those measurements exclude Quest capture, network transfer, headset loading, and
model startup. The production processor starts a command for each reconstruction.
It does not run that streaming experiment.

The website's separate [benchmark summary](media/benchmark.json) reports a
2.27-second median with half-second input chunks. Its runner and raw event files
are not included here. That summary cannot be reproduced by running the checked-in
two-second-chunk experiment unchanged.

The full-path target remains one to two minutes from final capture to the first
loaded replay frame. No checked-in result establishes that whole-path timing.

## Remaining acceptance

1. Record a fresh supported assessment, process it, and load the saved result on
   Quest. Measure the complete path, including transfer and loading.
2. Verify camera orientation, source-frame correspondence, body alignment, and
   playback while the wearer moves around the reconstruction.
3. Verify patient isolation, saved-version reopening, interruption handling, and
   one-hand or controller use on the current build.
4. Demonstrate useful microscope output from a steady-hold Quest recording and
   reject recordings dominated by camera or background motion.
5. Evaluate assessment methods on unseen participants before enabling clinical
   labels. Synthetic checks and fitted-pose observations do not replace evaluation.

The [developer guide](DEVELOPMENT.md#run-the-automated-checks) and
[Quest guide](../quest/README.md#run-checks) describe software checks.
Their results must be recorded separately from device and model evaluation.
