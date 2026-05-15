# AGENTS.md

> Companion file — see [CLAUDE.md](./CLAUDE.md) for the Korean Phase roadmap, document index, Skill/Agent activation map, and gpt-5.4 tier notes. This file owns the English policy layer (Stack / Non-negotiables / Common Commands / Testing / Coding / Audit / DataSynth / Documentation / Skill use / Safety / Secrets / Git). Both files are loaded by their respective agents; keep overlapping rules in sync via the shared sync checklist memory.

## Project

- This repository is `local-ai-assist`, a local Python audit analytics assistant for journal-entry testing.
- The product goal is to help auditors create review queues from full-population accounting data, not to replace auditor judgment.
- PHASE1 is not a fraud determination stage and does not try to match a final fraud label. PHASE1 surfaces rule violations, policy violations, anomalies, analytical review signals, and prioritization evidence for auditor review.
- Treat `is_fraud`, `is_anomaly`, precision, and recall from DataSynth as development validation aids only. Operational language must distinguish confirmed exceptions, review-only candidates, and high-risk review items.
- Current task status is owned by `docs/TASKS.md`. If `docs/NEW_TASKS.MD` exists, use it for RC / Company-Centric task detail. Do not copy phase progress or long roadmaps into this file.
- Keep `CLAUDE.md` for legacy Claude-oriented guidance. This file is the Codex / general agent entry point.

## Stack

- Python: `>=3.11`
- Package manager: `uv` with `pyproject.toml` dependency groups.
- Core data stack: pandas, numpy, scipy, Pandera, DuckDB, PyYAML, pydantic-settings.
- Dashboard: Streamlit, Plotly, streamlit-aggrid, streamlit-option-menu.
- ML / analytics: scikit-learn, XGBoost, LightGBM, SHAP, PyTorch, networkx.
- NLP / LLM: kiwipiepy, OpenAI API through the project LLM abstraction layer.
- Export: fpdf2, Excel/PDF/CSV reporting modules.
- Synthetic data generator: EY-ASU DataSynth under `tools/datasynth/`, implemented in Rust.

## Non-negotiables

- Read the relevant docs before changing code. Start with `docs/TASKS.md`, then the matching `docs/pre-plan/*.md`, `docs/DETECTION_RULES.md`, `docs/DETECTION_REFERENCE.md`, or `docs/DECISION.md` as applicable.
- Update relevant docs after behavior, architecture, task status, rules, reports, or DataSynth behavior changes.
- Do not treat review-only signals as confirmed violations in UI, DB exports, LLM narratives, or reports.
- Preserve user changes. Never revert files you did not change unless the user explicitly asks.
- Keep changes scoped to the requested behavior and nearby code. Avoid unrelated refactors.
- Prefer structured parsers and existing project helpers over ad hoc string manipulation.
- Use `uv`-based commands first unless a local `.venv\Scripts\...` command is required by the existing workflow.
- When OpenAI API, model behavior, structured outputs, or prompt/model selection is involved, check the latest official OpenAI documentation before implementing.
- Do not install packages, change global Codex config, edit hooks, or change global rules unless the user explicitly requests that step.

## Common Commands

```powershell
uv sync --group core --group dashboard --group dev
uv sync --group core --group dashboard --group dev --group ml --group llm
uv run pytest tests/ -v
uv run pytest tests/modules/test_detection -q
uv run pytest tests/modules/test_dashboard -q
uv run ruff check .
uv run mypy .
uv run streamlit run dashboard/app.py
```

- For narrow verification, run the smallest pytest target that covers the changed code first.
- For pipeline, detection, DB, or shared schema changes, expand to affected module suites and then broader tests if risk remains.
- For Streamlit work, prefer an import smoke test and, when UI behavior changed, a browser or screenshot verification path.
- For DataSynth Rust changes, use the relevant Cargo command in `tools/datasynth/` and then project-side validation.

## Testing & Verification

- Start narrow: changed function tests, focused module tests, then integration tests as needed.
- Broaden verification when touching shared contracts: schemas, DB tables, pipeline orchestration, score aggregation, settings, export formats, or dashboard state.
- Type-sensitive changes should include `mypy` or `pyright` when available.
- Use `pytest` markers and existing basetemp conventions. The project config disables pytest cache provider and uses `.tmp_pytest_workspace`.
- Do not skip tests to make a change pass. Fix the root cause or document why a test is not applicable.
- When tests cannot be run, report the exact reason and the command that should be run next.
- Streamlit changes should include at least one of:
  - import smoke, for example `uv run python -c "import dashboard.app"`;
  - focused dashboard tests;
  - local browser validation of the affected flow.
- LLM-related tests should mock network calls unless the user explicitly requests live API verification.
- Export/report changes must verify output shape, masking behavior, and graceful degradation for missing optional data.
- Korean text, docs, UI labels, and reports must stay strict UTF-8. Avoid PowerShell `Set-Content` or `Out-File` round-trips for Korean documents; if mojibake is suspected, run a manual check or dedicated script. Codex hook enforcement for mojibake is currently deferred.

## Coding Rules

- Follow the existing package layout and naming conventions.
- Keep modules cohesive. Prefer small functions with clear contracts over large orchestration blocks.
- For new detection tracks, follow the established detector pattern: `BaseDetector` plus `detect() -> DetectionResult`.
- Keep Company-Centric architecture intact: use `CompanyContext`, `ContextFactory`, and engagement-scoped DuckDB paths where relevant.
- Do not reintroduce global singleton settings into paths that already accept context.
- Keep DuckDB access behind existing connection/schema/loader/query helpers when possible.
- Use Pandera or existing validators for data contracts instead of informal checks when the data shape is part of the domain contract.
- Use project scoring helpers for risk / priority semantics. Do not directly sum UI labels such as High, Medium, Low, or Korean severity text.
- Preserve backward-compatible DB/export behavior unless a migration or contract update is part of the task.
- For UI code, keep Streamlit state keys stable and avoid storing large DataFrames in session state unless capped or explicitly designed.
- For LLM code, keep structured output schemas strict and include graceful fallback paths.

## Audit / DataSynth Rules

- PHASE1 creates an audit review queue. It does not prove fraud and must not phrase results as final fraud determinations.
- Separate confirmed/immediate rules from review-only signals:
  - `flagged_rules` is for confirmed/immediate findings with supporting details.
  - `review_rules` is for review-only candidates and weak signals.
- Benford and other macro findings may belong to account/process queues rather than row-level transaction flags.
- DataSynth data must not be fitted to tests. If a test reveals bad synthetic data, fix the data generation cause.
- DataSynth root-cause fixes belong in Rust under `tools/datasynth/`. Do not patch around generator defects in Python.
- Normal data should remain accounting-plausible and include natural noise.
- Abnormal data should represent intentional anomaly, error, fraud, or process issue patterns with traceable labels.
- Data-quality noise such as MCAR missingness, typos, and format variance must not become a shortcut feature that lets ML models learn labels trivially.
- After DataSynth regeneration or generator behavior changes, update the relevant debugging / data quality docs.
- Reports must distinguish code bugs, expected graceful degradation, and data characteristics. Do not list expected missing optional columns as defects.

## Documentation Rules

- `docs/TASKS.md` is the primary source for phase/task status.
- `docs/NEW_TASKS.MD` may be referenced by older docs, but if it is absent, do not invent status from memory. Use `docs/TASKS.md` and mention the missing file when relevant.
- Use `docs/DECISION.md` for architecture decisions and tradeoffs.
- Use `docs/debugging.md` or `docs/TROUBLESHOOT.md` for meaningful debugging history, failures, and fixes.
- Use `docs/DETECTION_RULES.md` and related detection result docs for rule semantics and scoring contracts.
- Use `docs/pre-plan/` as implementation reference, not as always-current task status.
- When updating docs, avoid duplicating the same long explanation in multiple places. Prefer one source of truth and links.
- Keep generated reports and user-facing audit language precise: candidate, exception, review item, finding, and confirmed violation are not interchangeable.

## Agent / Skill Usage

- Before substantial work, actively consider whether a repo-local or global skill would improve correctness, safety, speed, or verification quality.
- Use a skill when the task clearly fits its description, even if the user did not name it explicitly.
- Use the smallest useful set of skills; skip skills for tiny tasks where they add no value.
- Prefer local project rules and docs over generic skill advice when they conflict.
- Use `local-ai-assist-testing` first when choosing verification scope, smoke checks, or completion evidence for this repo.
- Use `local-ai-assist-review` first for reviews, risk checks, audit-domain regressions, and pre-completion review.
- Use `pandera-validation` first for Pandera/schema/validation/COA/opening_balance/closing_balance work.
- Use `accounting-precision` first for materiality/round/float/currency/VAT/tax work.
- Use `imbalanced-ml` first for Phase 2/ML/SMOTE/threshold/VAE/IsolationForest/anomaly score work.
- These three repo-local skills are more specific to this project's audit-domain judgment than general global skills.
- Use global Python, Streamlit, and DuckDB skills for general tool knowledge, but prefer repo-local skills for audit semantics, DataSynth rules, and project verification choices.
- Useful recurring skills for this repo:
  - Python quality: ruff, mypy, packaging, pytest.
  - Debugging: systematic debugging and verification before completion.
  - Data work: data analysis and DuckDB.
  - UI work: Streamlit layout, session state, dashboards, and Playwright/browser validation.
  - Documentation: documentation review for Korean technical docs when requested.
- Use subagents only when the user explicitly asks for delegation or parallel agent work.
- For code review requests, lead with findings, severity, and file/line references. Keep summaries secondary.
- For OpenAI API work, use official OpenAI docs first. Do not rely on stale model names or remembered API details.

## Safety / Secrets / Git

- Do not open, print, summarize, or exfiltrate:
  - `.env`, `.env.*` except `.env.example`;
  - `auth.json`;
  - API keys, tokens, session files, cookies, credentials, or private config;
  - raw audit source data;
  - DuckDB/SQLite database files unless the user explicitly asks and the scope is safe.
- Avoid printing full paths or snippets that reveal secrets or sensitive customer/audit data.
- Treat `data/journal/primary/**`, `data/companies/**/audit.duckdb`, and large generated datasets as sensitive by default.
- Use synthetic or minimal fixtures for examples and tests.
- Git write commands require explicit user approval before execution. This includes `git add`, `git commit`, `git checkout`, `git switch`, `git merge`, `git rebase`, `git reset`, `git clean`, `git tag`, and `git push`.
- Read-only git inspection is allowed when needed, but respect any active user hook or policy that blocks git commands.
- Never use destructive filesystem commands unless the target is explicit, verified, and inside the intended workspace.
- Before recursive delete or move on Windows, resolve the absolute path and verify it is inside the intended project or temp directory.
- Do not modify `.codex/config.toml`, `.codex/hooks.json`, global Codex config, hooks, or rules unless the task explicitly asks for those files.
