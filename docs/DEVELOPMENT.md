# Develop and verify local processing

Run all commands from the repository root. Use Python 3.11 or later, `uv`, and
`curl`. Keep the service environment separate from the GPU model environment in
the [GPU setup guide](../processing/reconstruction/GPU_SETUP.md).

Read the [project status](STATUS.md), [specification](SPEC.md), and
[processing contract](openapi.yaml) before continuing an incomplete milestone.
The [Quest guide](../quest/README.md) covers Unity builds, C# checks, and device
verification.

For the implemented architecture, module interfaces, source-time mappings, and
failure handling, read the [engineering guide](ENGINEERING.md).

## Start the local service

Install the locked service dependencies and the optional microscope dependencies:

```sh
uv sync --locked --python 3.11 --extra microscope
```

Create a private token for the first run. Retain the same token across restarts
and supply it to the client:

```sh
export PROCESSING_TOKEN="$(uv run --locked python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export PROCESSING_DATA_DIR="$PWD/var/processing"
```

If you need real reconstruction, [configure inference](#connect-real-inference)
before starting the service. Without it, jobs that request a replay fail with
`PROCESSING_FAILED` and retain their captures. Historical barefoot jobs without
a replay can succeed with unavailable assessment. The service does not substitute
a synthetic replay.

```sh
uv run --locked --extra microscope python -m processing --host 127.0.0.1 --port 8000
```

Keep the token private. Patient names and histories stay on Quest. The service
receives opaque patient, session, and take IDs. One deployment token protects this
private demo. Use one process. A filesystem lock rejects a second process using
the same store.

This command starts a loopback listener. For a non-loopback listener, the CLI
requires both `--ssl-certfile` and `--ssl-keyfile`. Do not expose the service
publicly by default. See [the deployment constraints](SPEC.md#storage-and-deployment)
before changing access.

The `microscope` extra installs NumPy, OpenCV, and PyAV. Without it, the microscope
returns an explicit unavailable result. The extra does not install GVHMR, CUDA,
checkpoints, or registered body assets.

## Connect real inference

Complete the independent proof in the [GPU setup guide](../processing/reconstruction/GPU_SETUP.md)
before configuring inference. Set these variables in the service shell before
startup. Replace the example paths with the actual model environment and GVHMR
checkout:

```sh
export PROCESSING_INFERENCE_COMMAND='["/absolute/model-env/bin/python","-m","processing.reconstruction.runtime"]'
export PROCESSING_INFERENCE_CWD=/absolute/path/to/GVHMR
```

The service runs one operator-configured local command without a shell. The
worker appends `--video`, `--sidecar`, `--output`, and `--pts-offset-ns 0`. It adds
the repository to `PYTHONPATH` and removes `PROCESSING_TOKEN` from the child
process environment.

No SSH connection is embedded in the service. If you use a container wrapper,
expose the same CLI and map the supplied paths correctly. The standalone Docker
commands in the GPU guide do not configure that wrapper.

Set these optional environment variables before startup if the defaults do not
fit the verified model setup. Their implementation is in
[processing/settings.py](../processing/settings.py).

| Setting | Default and meaning |
|---|---|
| `PROCESSING_INFERENCE_TIMEOUT_SECONDS` | `900`. Stops the inference process group when exceeded. |
| `PROCESSING_INFERENCE_WORKSPACE_BYTES` | `805306368`, or 768 MiB. Bounds inference scratch output. |
| `PROCESSING_ALLOW_ESTIMATED_INTRINSICS` | `false`. `true` permits estimating intrinsics when the source marks them unavailable. |
| `PROCESSING_ALLOW_UNVERIFIED_PINHOLE` | `false`. `true` permits only unknown distortion with no coefficients as an explicitly unverified pinhole approximation. |

Quest's camera SDK supplies intrinsics but no distortion model or coefficients.
The sidecar preserves that unknown state. Strict defaults reject that unverified
camera model. The pinhole opt-in records an approximation and labels processing
intrinsics estimated. It does not calibrate the lens, establish physical scale,
or alter the original sidecar. Rectification and real alignment still need
validation.

Include `media.presentation_time_us` in each reconstruction sidecar. The service
requires this per-frame encoded timestamp mapping for configured inference.
Source camera nanoseconds remain unchanged. The worker checks encoded microseconds
separately against every decoded image. Replay export preserves source references
and root motion, converts the body surface and skeleton together, and validates
artifact hashes. Unavailable assessment methods remain labelled unavailable when
reconstruction succeeds. Barefoot close-ups do not produce a full-body replay.

## Submit a capture and retrieve its result

Prepare a capture manifest and flat ZIP that match the
[processing contract](openapi.yaml). Use protocol ID `elk`, `rtk`, or `walking`,
the matching test type, and version `1.0`. Historical `barefoot` captures and
results remain supported. For Walking full-body takes, use condition `exercise`
and anatomical side `not_applicable`. These identify capture contracts, not
clinically evaluated protocols.

Set the capture paths and create an idempotency key for this processing attempt:

```sh
export CAPTURE_MANIFEST=/path/to/capture_manifest.json
export CAPTURE_ZIP=/path/to/capture.zip
export IDEMPOTENCY_KEY="$(uv run --locked python -c 'import uuid; print(uuid.uuid4())')"

curl --fail-with-body -i http://127.0.0.1:8000/v1/jobs \
	-H "Authorization: Bearer $PROCESSING_TOKEN" \
	-H "Idempotency-Key: $IDEMPOTENCY_KEY" \
	--form-string "manifest=$(cat "$CAPTURE_MANIFEST")" \
	--form "media=@$CAPTURE_ZIP;type=application/zip"
```

Set `JOB_ID` to the `job_id` in the accepted response. Keep the same idempotency
key for network retries. Poll at the response's `Retry-After` interval while the
job is active:

```sh
export JOB_ID=job-uuid-from-the-accepted-response

curl --fail-with-body -i "http://127.0.0.1:8000/v1/jobs/$JOB_ID" \
	-H "Authorization: Bearer $PROCESSING_TOKEN"
```

After the job succeeds, fetch its result manifest:

```sh
curl --fail-with-body "http://127.0.0.1:8000/v1/jobs/$JOB_ID/result" \
	-H "Authorization: Bearer $PROCESSING_TOKEN"
```

Set `ARTIFACT_ID` to an `artifact_id` from the result inventory, then download it:

```sh
export ARTIFACT_ID=artifact-uuid-from-the-result-inventory

curl --fail-with-body "http://127.0.0.1:8000/v1/jobs/$JOB_ID/artifacts/$ARTIFACT_ID" \
	-H "Authorization: Bearer $PROCESSING_TOKEN" --output /tmp/replay-artifact
```

Verify the artifact size and SHA-256 against the result inventory before loading
it. Result and artifact routes return 409 for failed or incomplete jobs. For a
deliberate reprocessing attempt, create a new key. The service preserves the
original capture and result version.

Use the default limits in [Settings](../processing/settings.py). These limits
are admission ceilings, not recommended recording sizes:

| Resource | Limit |
|---|---|
| ZIP upload | 512 MiB |
| Upload manifest | 1 MiB |
| Expanded files | 1 GiB |
| Archive members | 64 |
| Takes | 8 |
| Metadata | 16 MiB |
| Decoded replay | 256 MiB |
| Result output | 1 GiB |
| Private storage | 8 GiB |
| Upload deadline | 120 seconds |

Only the inference timeout and scratch budget in the table above have environment
settings. Other upload and storage limits come from `Limits` in
`processing/settings.py`.

The service reserves storage before acceptance and returns retryable 429 when
busy or full. It never deletes accepted recordings to free space. Upload
validation checks ZIP contents and MP4 signatures. The inference and microscope
adapters also bound decoding and verify frame and time correspondence before
producing output.

## Run the automated checks

Use the [authored contract fixture](../tests/contracts/fixtures/README.md) to check
the capture and replay contract. It contains no participant or anatomical model.

```sh
uv sync --locked --python 3.11 --extra microscope
uv run --locked --extra microscope python -m processing.contracts validate tests/contracts/fixtures
uv run --locked --extra microscope pytest --cov=processing --cov-report=term-missing -q
uv run --locked --extra microscope ruff check processing tests
uv run --locked --extra microscope pip-audit --progress-spinner off
```

Tests exercise a real loopback upload, poll, download, and restart flow with
synthetic inputs and a test-only worker. CPU tests cover model orchestration and
real codec timestamps. They do not establish CUDA execution or model accuracy.
Follow the [Quest guide](../quest/README.md) for builds and C# checks. Verify
on-device input, real-video reconstruction, and assessment on unseen participants
separately. Record the remaining work in the [project status](STATUS.md).

Keep participant recordings, identifying profile data, model weights,
credentials, and restricted datasets out of Git.
