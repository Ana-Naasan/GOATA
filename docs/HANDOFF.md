# Codex session handoff

## Current state — September 26, 2026

- Branch: `codex/bader-backend`. Ownership documentation landed through PR #5 at `0331367`; use `git log -1` for the current implementation commit.
- Completed: Priority 1 capture/replay contract handoff, including executable schemas, strict semantic/binary validation and a labelled synthetic fixture.
- Service, real reconstruction, Quest import/capture, automated ELK/RTK/foot assessment and microscope remain unfinished. M1 is not complete.
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

## Next concrete task

Recheck `main`, then implement the existing four-route FastAPI service: authentication, bounded multipart/ZIP validation, private atomic persistence, idempotency, one worker, restart recovery and job-owned artifacts. Keep a synthetic successful worker in tests only. Actual processing must fail clearly until a real worker is available.

Current service dependencies installed for that next task: FastAPI 0.141.1, Starlette 1.7.0, python-multipart 0.0.32, Uvicorn 0.54.0, HTTPX 0.28.1, PyYAML 6.0.3. They are installed tooling, not evidence of a working service.

## Required integrations still blocked/unverified

- Mohammad: runnable inference on authorized NVIDIA compute, exact model/output revisions, coordinates, scale and source-time mapping; genuine ELK/RTK/foot outputs and evaluation.
- Hamza: real Quest camera sidecar, Unity importer and on-device replay; patient histories and capture/upload/review flow.
- Bader: actual model wrapper/export transform after the dependency lands; microscope from original footage with camera-shake checks; measured full-path latency.
- No actual GPU, registered model assets, dataset access, real capture calibration, 72 Hz rendering, 250 ms seeking or 1–2 minute turnaround has been verified here.

Fixture success establishes mechanics only. Keep all unfinished required features explicit. Never claim a synthetic replay or test worker completes an application/model/device milestone.
