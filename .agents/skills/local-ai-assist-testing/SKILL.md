---
name: local-ai-assist-testing
description: Project-specific verification guide for local-ai-assist. Use when Codex changes Python modules, pytest suites, Streamlit dashboard code, DuckDB/db/pipeline logic, detection rules/scoring, DataSynth Rust code, OpenAI/LLM Phase 3 code, exports, or docs and needs to choose the right tests, smoke checks, ruff/mypy commands, and completion evidence for this repository.
---

# Local AI Assist Testing

Use this skill to choose verification for `local-ai-assist`. Keep tests proportional to the change, start narrow, and expand when contracts or user-visible behavior are touched.

## Baseline Commands

Prefer `uv` commands:

```powershell
uv run pytest tests -q
uv run pytest tests/ -v
uv run ruff check .
uv run mypy .
uv run streamlit run dashboard/app.py
```

Local entry points are acceptable when the repo workflow already uses them:

```powershell
.venv\Scripts\pytest.exe tests -q
.venv\Scripts\ruff.exe check .
.venv\Scripts\python.exe -m streamlit run dashboard/app.py
```

## Test Selection

### Pure Python Utility

- Run the focused test file or nearest module test first.
- Add `uv run ruff check <touched files>` when imports, typing, or formatting could be affected.
- Run `uv run mypy` when public types, dataclasses, Protocols, or settings models changed.

### Type-Sensitive Changes

- Prefer `uv run mypy .` for type-sensitive changes.
- If the pyright CLI is already installed, use `pyright` as an optional supporting check; missing pyright must not block the task.
- Consider type checks for Pandera schemas, DB row/record types, pipeline or detector interfaces, ML model inputs/outputs, LLM structured-output schemas, and export/report data shapes.

### Ingest / Validation

- Read the relevant `docs/archive/completed/raw-plan/02-ingest.md` or `docs/archive/completed/raw-plan/04-validation.md` section before editing.
- Prefer tests around file validation, header detection, column mapping, type casting, Pandera schemas, and accounting validators.
- Include edge cases for Korean ERP exports, encoding fallback, required/recommended mappings, and missing optional columns.
- Verify graceful degradation: a missing optional input should not be reported as a code defect.

### Detection / Rules / Scoring

- Run the narrow detector or scoring tests first.
- Expand to `tests/modules/test_detection` when rule semantics, constants, severity maps, scoring roles, or aggregation changed.
- Check that PHASE1 still creates review queues and does not turn review-only signals into confirmed violations.
- For score changes, test both row-level scores and case/priority behavior when applicable.

### DuckDB / DB / Pipeline

- Use temporary DB paths or fixtures. Do not open or dump real `audit.duckdb` files unless the user explicitly authorizes a safe scope.
- Preserve company/engagement isolation: `data/companies/{company_id}/engagements/{engagement_id}/audit.duckdb`.
- Run focused DB loader/schema/query tests first.
- Expand to pipeline tests when schema, loading, orchestration, or detection-to-db contracts change.
- Verify migrations or DDL changes against empty and existing-like temporary databases when feasible.

### Streamlit / Dashboard

- Run focused dashboard tests for touched tabs/components.
- Always include an import smoke check for app-level changes:

```powershell
uv run python -c "import dashboard.app"
```

- If UI behavior changed, run the app and verify with browser/Playwright when practical.
- Check session state keys, large DataFrame caps, download button two-step flows, and Streamlit rerun behavior.
- Avoid relying on visual judgment only; pair screenshots or browser checks with focused unit tests where possible.

### DataSynth / Rust

- DataSynth defects must be fixed at the Rust generation source, not patched over in Python.
- Use the relevant Cargo command in `tools/datasynth/`:

```powershell
cargo check
cargo test
cargo fmt
cargo build
```

- For CLI binary work, prefer package-specific build commands if existing docs require them.
- After generator behavior changes, run the relevant Python quality gates or contract checks that consume the generated data.
- Verify no label leakage or shortcut feature was introduced.
- Update debugging/data-quality docs after regeneration or generator behavior changes.

### LLM / OpenAI Phase 3

- Do not make live API calls in default tests.
- Prefer mocks, fake clients, structured-output contract tests, schema enforcement tests, and cache/fallback tests.
- Check latest official OpenAI docs before changing API calls, model names, structured outputs, tool use, or prompt/model selection behavior.
- Verify raw descriptions, PII, tokens, and secret values are not sent or logged unintentionally.

### Export / Reports

- Verify output bytes or file signatures for Excel/PDF/CSV paths.
- Test filters, masking, filenames, stale-cache invalidation, and missing optional data.
- Ensure reports distinguish code bugs, expected graceful degradation, and data characteristics.
- For docs, reports, and Korean UI text changes, check for mojibake: U+FFFD replacement characters, cp949 mojibake signatures, and excessive standalone Hangul jamo ratio.
- Do not mix automatic `ruff format`/`ruff check --fix` with mojibake checks; encoding checks should be detect-only.

### Docs-Only

- Pytest is usually unnecessary.
- Verify links, source-of-truth claims, and whether `docs/TASKS.md`, `docs/debugging.md`, or decision docs need updates.
- Do not update task status unless the work actually changes status.

## Basetemp / Cache Isolation

- Respect `pyproject.toml`: pytest disables cache provider and uses `.tmp_pytest_workspace`.
- For repeated focused runs, use unique basetemp directories such as `.tmp_pytest_<topic>` only when needed.
- Do not delete temp directories with recursive force commands unless the user has approved and the path is resolved inside the workspace.

## Slow / Large Tests

- Treat large DataSynth, full pipeline, long report generation, browser E2E, and model training checks as slow.
- Run slow tests when the changed behavior is only covered there or the user asks for full verification.
- Otherwise report the exact slow command as a follow-up verification item.

## Completion Evidence

Before final response, report:

- Validation commands actually run.
- Result of each command.
- Verification intentionally skipped and why.
- Remaining risk if broader, slow, live API, or browser checks were not run.
