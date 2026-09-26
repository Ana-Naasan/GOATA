# Codex session handoff

## Current state — September 26, 2026

- Branch: `codex/bader-backend`. Ownership documentation landed through PR #5 at `0331367`; fixture implementation `3fe90e6` landed through PR #6 at `0b326c9`; the local service landed through PR #7 at `4c94f10`. Use `git log -1` for the latest service/handoff commit.
- Completed: Priority 1 capture/replay contract handoff and Priority 2 local upload/job/result/artifact mechanics. Both have tests and independent review.
- Follow-up: targeted ignore rules cover local environment files (including `.envrc`), recordings, data, weights, service/TLS material and Android signing credentials (`.keystore`, `.jks`, `.p12`, `.pfx`) before those assets are introduced. No ignored asset was added to Git.
- Earlier backend-only verification, recorded in `93fcd77`: macOS 27.0 arm64, Python 3.11.1 and uv 0.12.19; that verification environment had no Unity, Android/ADB, connected Quest or NVIDIA compute. This historical snapshot does not describe the current Quest setup.
- Current merge verification uses Bader's Mac: macOS 26.6.2 arm64, Python 3.11.10 and uv 0.11.21. Separately, the Hamza chat installed Unity 6000.0.66f2 and Android tools, built and installed the official camera sample, and received user confirmation of a live moving image on Quest 3 at 16:16 EDT. Recording with metadata, the Unity importer and application replay remain incomplete; the local Quest work is not on `main` yet.
- Real reconstruction, Quest import/capture, automated ELK/RTK/foot assessment and microscope remain unfinished. M1 is not complete. Normal service processing explicitly fails until real inference is integrated.
- Deadline: September 27, 2026, 10:00 a.m. EDT.
- Repository: https://github.com/B2707/HTH-3-sarakbi-asadi-steitieh-grp

## Working order

Prioritize work that unblocks teammates. Before each task inspect `main`; integrate teammate prerequisites only after they land there. When blocked, work on the next independent item. Keep changes in Bader-owned paths and preserve personal branches. Independent code, Python and security review plus passing checks are required before publishing implementation through a PR.

Owners remain Bader/backend (#1), Mohammad/ML (#2), Hamza/Quest (#3), Mustafa/design (#4), as recorded in AGENTS.md. Hamza alone changes Unity files. No model adapter/output boundary has been invented on Mohammad's behalf.

## Priority 1: usable importer handoff

Files: `processing/contracts.py`, `processing/schemas/`, `tests/contracts/`, root Python manifest/lockfile and targeted ignore rules. The fixture guide is `tests/contracts/fixtures/README.md`; SPEC section 8 records the executable contract.

The authored fixture has four frames, four vertices, four triangles and three illustrative joints. It exercises asymmetric axes/winding, shared root motion, irregular original timestamps, repeated resampling references and invalid frame/joint masks. No participant media, body assets, weights or clinical findings are included.

JSON metadata is capped at 16 MiB before parsing. Validation rejects duplicate keys, nonfinite/oversized numbers, invalid calibration/pose shapes, bad counts/indices/parents, incorrect hashes, unsafe binary filenames, missing observations inside declared gaps and decoded replay data over 256 MiB. Capture and replay gaps are closed intervals; their endpoints cannot contain valid observations. Binary files are streamed during validation.

### Verified commands and outcomes

```sh
uv sync --python /opt/homebrew/bin/python3.11
.venv/bin/python -m pytest tests/contracts --cov=processing --cov-report=term-missing -q
.venv/bin/python -m processing.contracts validate tests/contracts/fixtures
.venv/bin/ruff check processing tests/contracts
.venv/bin/pip-audit --progress-spinner off
git diff --check
```

- Tests: 50 passed; 95.22% branch-inclusive coverage. CLI entrypoint lines are included in the report and separately exercised by the command above.
- TDD: tests first failed because the module did not exist. Review regressions reproduced integer-valued-float crashes, huge-number overflow and invalid gap observations before fixes.
- Fixture validation, lint and whitespace checks passed. Dependency audit reported no known vulnerabilities.
- Independent reviews found and resolved numeric exception handling, a quadratic gap scan and unbounded metadata reads. The broad fixture ignore exception was removed to keep credentials/media/weights ignored.
- Installed and used: macOS arm64, Python 3.11.10, uv 0.11.21, jsonschema 4.26.0, pytest 9.1.1, pytest-cov 7.1.0 and Ruff 0.16.9. Exact dependency hashes/versions are in `uv.lock`.
- Python service tooling is separate from the future CUDA/model environment. No GPU/headset/model execution was performed.

## Priority 2: local service mechanics

Implemented `POST /v1/jobs`, job polling, completed result retrieval and authenticated artifact downloads. There are no user accounts/login screens. A deployment token protects this demo; patient names stay on Quest, while patient/session/take/job/artifact UUIDs preserve identity and provenance.

- Authenticated before parsing; bounded multipart receive/header/field limits, strict UTF-8, one validation slot and one processing worker.
- ZIP validation checks bounded central/local records, member types, paths, counts, CRC, actual decompression lengths, hashes and sidecar identity. ZIP64 is unsupported; only STORE/DEFLATE are accepted.
- Atomic private storage, canonical-content idempotency, capacity reservation, persisted stages, process lock and restart recovery. Original extracted recordings and sidecars remain intact; ZIP container bytes need not be retained.
- Results validate job/patient/session/protocol/digest, source frames/intervals, complete assessment takes, feature availability, replay mapping and artifact bytes before publication. Worker input is copied independently of accepted metadata.
- The normal worker returns an actionable `PROCESSING_FAILED` because inference is absent. Successful synthetic processing is confined to tests. No fixture fallback exists in the runnable service.
- MP4 validation checks signatures only. Decoding, frame-count/PTS agreement, model timeouts and CUDA execution remain work for the actual inference adapter; no successful video-decoding proof is claimed.
- CLI defaults to loopback, one process, and TLS arguments are mandatory for other listeners. Detailed setup and curl examples are in README.md. Runtime token: `PROCESSING_TOKEN`; private directory: `PROCESSING_DATA_DIR` (default `var/processing`).
- Provisional capture IDs are `elk`, `rtk`, `barefoot`, matching test type, at version `1.0`. These are not clinically evaluated protocol definitions. API contract documents every input/output/storage ceiling.

### Final verification

```sh
uv run --locked pytest --cov=processing --cov-report=term-missing -q
uv run --locked ruff check processing tests
uv run --locked pip-audit --progress-spinner off
npm exec --yes --package=@redocly/cli@2.54.3 -- redocly lint docs/openapi.yaml --extends=minimal
git diff --check
```

- **189 tests passed; 94.30% branch-inclusive coverage** across all processing modules; no modules are excluded. Remaining uncovered paths include some CLI argument errors and exceptional storage/cleanup cases.
- A real loopback TCP test exercised upload → polling → result → authenticated artifact download → service restart → same-key retry. Its worker and inputs are explicitly synthetic; it establishes backend mechanics only.
- Lint, OpenAPI validation and whitespace checks passed. Dependency audit found no known vulnerabilities.
- Test output has one upstream Starlette warning that its HTTPX TestClient integration is deprecated. Tests pass on the locked versions; dependency replacement was not needed for this handoff.
- Independent code, Python and static security reviews completed. Regressions were reproduced before fixing post-rename fsync/idempotency failure, accepted-evidence aliasing, metadata publication limits, uppercase artifact IDs, interrupted-take assessment, and valid DEFLATE buffering at the chunk boundary.
- Installed/used service versions: FastAPI 0.141.1, Starlette 1.7.0, python-multipart 0.0.32, Uvicorn 0.54.0, HTTPX 0.28.1 and PyYAML 6.0.3. Python and all exact dependency hashes remain recorded above/in `uv.lock`.

### Merge verification — September 26, 2026

Rerun in an isolated checkout combining Bader's follow-up `93fcd77` with
`main` at `1f0bcef`; no processing source or API contract changed.

```sh
uv sync --locked --python /opt/homebrew/bin/python3.11
uv run --locked pytest --cov=processing --cov-report=term-missing -q
uv run --locked ruff check processing tests
uv run --locked pip-audit --progress-spinner off
uv run --locked python -m processing.contracts validate tests/contracts/fixtures
npm exec --yes --package=@redocly/cli@2.54.3 -- redocly lint docs/openapi.yaml --extends=minimal
git diff --check
```

- All commands passed: 189 tests passed at 94.30% branch-inclusive coverage; Ruff and whitespace checks passed; pip-audit reported no known vulnerabilities; the synthetic fixture's mechanical contract and the OpenAPI document validated.
- The suite retains the known upstream Starlette `httpx` TestClient deprecation warning. It does not affect the locked test result.
- This verifies Bader's completed work against SPEC sections 8–9 and the API contract: bounded/validated capture and replay contracts, authenticated persisted/idempotent job mechanics and truthful unavailable processing. It does not verify the model-, footage- or Quest-dependent requirements below.

## Next concrete task and dependency gate

The pre-merge inspection of `main` at `1f0bcef` includes the fixture/service PRs #6 and #7 plus Mustafa's design/menu handoff in PR #9. It still has no `processing/reconstruction`, `processing/analysis` or `quest` implementation. Mohammad is continuing work on his branch; no model handoff is on `main` yet. Hamza's local camera proof and tested replay clock can support continued Quest work, while his recorder/importer remain incomplete. Integrate Mohammad's verified command/output only when it is on main, then export real geometry using the proven source coordinate/time mapping. Integrate Hamza's real capture/importer only when that dependency is on main.

Until then, the independent deliverables in this plan are complete. Do not invent an inference adapter, model topology, exercise label set, camera calibration or microscope algorithm to bypass a missing dependency.

## Required integrations still blocked/unverified

- Mohammad: runnable inference on authorized NVIDIA compute, exact model/output revisions, coordinates, scale and source-time mapping; genuine ELK/RTK/foot outputs and evaluation.
- Hamza: real Quest camera sidecar, Unity importer and on-device replay; patient histories and capture/upload/review flow.
- Bader: actual model wrapper/export transform after the dependency lands; microscope from original footage with camera-shake checks; measured full-path latency.
- No actual GPU, registered model assets, dataset access, real capture calibration, 72 Hz rendering, 250 ms seeking or 1–2 minute turnaround has been verified here.

Fixture success establishes mechanics only. Keep all unfinished required features explicit. Never claim a synthetic replay or test worker completes an application/model/device milestone.
