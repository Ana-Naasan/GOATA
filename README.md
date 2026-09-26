# Physio Motion Replay

A Meta Quest 3 physiotherapy demo: record a supported test, then walk around a translucent blue replay of the participant with an aligned skeleton and evidence-linked findings.

**Current state:** executable capture/replay contracts, a synthetic importer fixture, and a tested local upload/job/artifact service. Real inference, the Quest app and assessment features remain unverified. The normal service retains accepted recordings and reports `PROCESSING_FAILED` until inference is integrated.

## First handoff: capture and replay contracts

From the repository root:

```sh
uv sync --locked --python 3.11
uv run python -m processing.contracts validate tests/contracts/fixtures
uv run --locked pytest tests/contracts --cov=processing.contracts --cov-report=term-missing
```

The [fixture guide](tests/contracts/fixtures/README.md) describes the expected
geometry, source times, masks and binary checksums. Hamza can use it to build the
Unity importer without waiting for reconstruction. The fixture contains no
participant recording or anatomical model. Regenerate a copy with
`uv run python -m processing.contracts generate /tmp/physio-replay-fixture`.

Executable schemas live in `processing/schemas`; semantic validation is in
`processing/contracts.py`. The service Python environment is separate from
Mohammad's model-specific environment.

## Run the local service

There are no user accounts or login screens. Quest owns patient names and
histories; the server receives opaque patient/session/take IDs. One deployment
token protects all jobs in this private demo.

```sh
uv sync --locked --python 3.11
export PROCESSING_TOKEN="$(uv run --locked python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export PROCESSING_DATA_DIR="$PWD/var/processing"
uv run --locked python -m processing --host 127.0.0.1 --port 8000
```

Keep the token in this shell or a private secret store; retain the same value
when connecting the client or restarting. Do not commit it or print it in logs.
The CLI requires a TLS certificate and key for any non-loopback listener. This
command is a local run, not a deployment. Use one process; a filesystem lock
rejects another process using the same storage directory.

### Client request examples

`CAPTURE_MANIFEST` and `CAPTURE_ZIP` are paths to the client's capture manifest
and flat ZIP. Use `protocol_id` equal to `elk`, `rtk` or `barefoot` and
`protocol_version: "1.0"`. These are provisional capture identifiers; clinical
protocols and supported finding labels remain dependent on the model work.

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

Poll at `Retry-After` while active. A deliberate new processing attempt uses a
new key. Failed and incomplete jobs return 409 from result/artifact routes.
Until real inference lands, completed-result delivery is exercised through the
explicitly synthetic worker in tests only; the runnable service has no fixture
fallback. Verify artifact size and SHA-256 against the returned result inventory.

Defaults: 512 MiB ZIP, 1 MiB upload manifest, 1 GiB expanded files, 64 members,
8 takes, 16 MiB sidecar/replay JSON, 256 MiB decoded replay, 1 GiB result output,
8 GiB private storage budget, and a 120-second upload receive deadline. The
service reserves disk space before acceptance and returns retryable 429 when
busy or full. It never deletes accepted recordings to make room. MP4 checks
currently verify signatures only; bounded decoding/frame-alignment validation
must accompany the real inference adapter.

## Verify backend changes

```sh
uv run --locked pytest --cov=processing --cov-report=term-missing
uv run --locked ruff check processing tests
uv run --locked pip-audit --progress-spinner off
```

The suite includes a real loopback HTTP upload/poll/download/restart test,
using synthetic input and a test-only worker. Run it alone with
`uv run --locked pytest tests/backend/test_live_http.py -q`. These checks do not
verify Quest rendering, usable video decoding, clinical models or turnaround.

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
