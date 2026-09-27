# Physio Motion Replay

Record a supported test through Meta Quest 3, then inspect a translucent blue body,
aligned skeleton and source-linked evidence. The practitioner chooses corrections.

**Last updated:** September 26, 2026. Capture, local patient history, processing,
replay import and the native Meta UI are implemented together. A public-video
GVHMR run produced real geometry on an RTX 3070. A fresh Quest recording has not
yet completed the full path. Automated ELK/RTK findings, automated foot assessment,
a useful real Quest microscope result and on-device performance remain incomplete.
See [the current handoff](docs/HANDOFF.md) for the exact verification boundary.

## Run the local processing service

Use Python 3.11 or later for the service. Its environment is separate from the
GPU model environment in [GPU setup](processing/reconstruction/GPU_SETUP.md).

```sh
uv sync --locked --python 3.11 --extra microscope
export PROCESSING_TOKEN="$(uv run --locked python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export PROCESSING_DATA_DIR="$PWD/var/processing"
uv run --locked --extra microscope python -m processing --host 127.0.0.1 --port 8000
```

Keep the token private and retain it across restarts. Patient names and histories
stay on Quest; the service receives opaque patient/session/take IDs. One deployment
token protects this private demo. The CLI requires a TLS certificate and key for
non-loopback listeners. This command starts a local service, not a deployment.
Use one process; a filesystem lock rejects a second process using the same store.

The `microscope` extra installs NumPy, OpenCV and PyAV. Without it, the microscope
returns an explicit unavailable result. Installing the extra does not install
GVHMR, CUDA, checkpoints or registered body assets.

### Connect real inference

The service runs one operator-configured local command without a shell. Configure
it **before** starting the service, after the independent GPU proof succeeds.
Example paths below must point to the actual model environment and GVHMR checkout:

```sh
export PROCESSING_INFERENCE_COMMAND='["/absolute/model-env/bin/python","-m","processing.reconstruction.runtime"]'
export PROCESSING_INFERENCE_CWD=/absolute/path/to/GVHMR
```

The worker appends `--video`, `--sidecar`, `--output` and `--pts-offset-ns 0`, adds
the repository to `PYTHONPATH`, and removes `PROCESSING_TOKEN` from the child
process environment. No SSH connection is embedded in the service. A container
wrapper must expose the same CLI and map the supplied paths correctly; the
standalone Docker commands in GPU setup do not configure that wrapper for you.
The default unconfigured service retains accepted full-body captures and reports
`PROCESSING_FAILED`; it never substitutes a synthetic replay.

| Setting | Default and meaning |
|---|---|
| `PROCESSING_INFERENCE_TIMEOUT_SECONDS` | `900`; stops the inference process group when exceeded. |
| `PROCESSING_INFERENCE_WORKSPACE_BYTES` | `805306368` (768 MiB); bounds inference scratch output. |
| `PROCESSING_ALLOW_ESTIMATED_INTRINSICS` | `false`; `true` permits estimating intrinsics when the source marks them unavailable. |
| `PROCESSING_ALLOW_UNVERIFIED_PINHOLE` | `false`; `true` permits only unknown distortion with no coefficients as an explicitly unverified pinhole approximation. |

Quest's camera SDK supplies intrinsics but no distortion model/coefficients.
Its sidecar preserves that unknown state. The pinhole opt-in records an
approximation and labels processing intrinsics estimated; it does not calibrate
the lens, establish physical scale or alter the original sidecar. Strict defaults
reject that unverified camera model. Rectification and real alignment still need
validation.

Configured inference requires a per-frame encoded media timestamp mapping. Source
camera nanoseconds remain unchanged; encoded microseconds are checked separately
against every decoded image. Replay export preserves source references and root
motion, converts surface and skeleton together, and validates artifact hashes.
Assessment methods that are unavailable remain labelled unavailable even when
reconstruction succeeds. Barefoot close-ups do not produce a full-body replay.

### API request examples

`CAPTURE_MANIFEST` and `CAPTURE_ZIP` identify a capture manifest and flat ZIP.
Use protocol ID `elk`, `rtk` or `barefoot`, matching test type, and version `1.0`.
These identify capture contracts, not clinically evaluated protocols.

```sh
export CAPTURE_MANIFEST=/path/to/capture_manifest.json
export CAPTURE_ZIP=/path/to/capture.zip
export IDEMPOTENCY_KEY="$(uv run --locked python -c 'import uuid; print(uuid.uuid4())')"

curl --fail-with-body -i http://127.0.0.1:8000/v1/jobs \
  -H "Authorization: Bearer $PROCESSING_TOKEN" \
  -H "Idempotency-Key: $IDEMPOTENCY_KEY" \
  --form-string "manifest=$(cat "$CAPTURE_MANIFEST")" \
  --form "media=@$CAPTURE_ZIP;type=application/zip"

# Set JOB_ID from the accepted response. Keep the same key for network retries.
curl --fail-with-body "http://127.0.0.1:8000/v1/jobs/$JOB_ID" \
  -H "Authorization: Bearer $PROCESSING_TOKEN"
curl --fail-with-body "http://127.0.0.1:8000/v1/jobs/$JOB_ID/result" \
  -H "Authorization: Bearer $PROCESSING_TOKEN"
curl --fail-with-body "http://127.0.0.1:8000/v1/jobs/$JOB_ID/artifacts/$ARTIFACT_ID" \
  -H "Authorization: Bearer $PROCESSING_TOKEN" --output /tmp/replay-artifact
```

Poll at `Retry-After` while active. A deliberate reprocessing attempt uses a new
key and keeps the original capture/result version. Failed or incomplete jobs
return 409 from result/artifact routes. Verify artifact size and SHA-256 against
the result inventory before loading it.

Default ceilings: 512 MiB ZIP, 1 MiB upload manifest, 1 GiB expanded files,
64 members, eight takes, 16 MiB metadata, 256 MiB decoded replay, 1 GiB result
output, 8 GiB private storage and a 120-second upload deadline. The service
reserves storage before acceptance and returns retryable 429 when busy/full.
It never deletes accepted recordings to free space. Upload validation checks ZIP
contents and MP4 signatures; the inference/microscope adapters additionally bound
decoding and verify frame/time correspondence before producing their outputs.

## Build and verify

The [Quest guide](quest/README.md) contains the Unity build, device procedure and
C# checks. The [fixture guide](tests/contracts/fixtures/README.md) describes the
small authored contract fixture; it contains no participant or anatomical model.

```sh
uv sync --locked --python 3.11 --extra microscope
uv run --locked --extra microscope python -m processing.contracts validate tests/contracts/fixtures
uv run --locked --extra microscope pytest --cov=processing --cov-report=term-missing -q
uv run --locked --extra microscope ruff check processing tests
uv run --locked --extra microscope pip-audit --progress-spinner off
```

Tests include a real loopback upload → poll → download → restart flow, using
synthetic inputs and a test-only worker. CPU tests cover model orchestration and
real codec timestamps; they do not establish CUDA/model accuracy. On-device input,
real-video reconstruction and held-out assessment evaluation remain separate gates.

## Required demonstration

1. Select a patient and ELK seated flank stretch, RTK seated rotation or barefoot assessment.
2. Confirm consent and follow the capture guidance. Keep original recordings.
3. Process and load the saved result. The **1–2 minute** whole-path target remains unmeasured.
4. Walk around the body, scrub, reverse, step frames, change speed and manipulate its display.
5. Open genuine findings and matching source evidence; unsupported methods explain their status.
6. Add a separate steady-hold take for microscope inspection and reopen dated tests from history.

Foot assessment uses its own side/view/condition and calibration evidence. Motion
magnification can amplify recording artifacts. Neither feature is complete merely
because its capture or unavailable-state UI works.

| Document | Purpose |
|---|---|
| [Specification](docs/SPEC.md) | Accepted scope, invariants and acceptance criteria. |
| [Session handoff](docs/HANDOFF.md) | Current branch, verified results, blockers and next task. |
| [Processing API](docs/openapi.yaml) | Upload, job status, results and artifact contracts. |
| [Quest guide](quest/README.md) | App structure, checks, build and device evidence. |
| [GPU setup](processing/reconstruction/GPU_SETUP.md) | Pinned model/assets, standalone inference and original GPU proof. |
| [Agent instructions](AGENTS.md) | Project working rules. |

The original deadline is **September 27, 2026, 10:00 a.m. America/Toronto**.
Do not commit participant recordings, identifying profile data, model weights,
credentials or restricted datasets. New sessions should read the handoff,
specification and API contract before continuing the next incomplete milestone.
