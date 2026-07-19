---
name: local-ai-assist-review
description: Project-specific code review checklist for local-ai-assist. Use when reviewing changes to audit review queues, journal-entry detection rules, scoring/priority logic, DataSynth synthetic data, DuckDB company/engagement isolation, Streamlit risk UI, OpenAI/LLM narratives, exports, documentation, or any change where audit semantics, data quality, privacy, or evidence grounding may regress.
---

# Local AI Assist Review

Use this skill for code review in `local-ai-assist`. Lead with findings. Focus on bugs, regressions, missing tests, unsafe audit language, data leakage, privacy exposure, and documentation drift.

## Review Output Format

- Start with findings, ordered by severity.
- Include file and line references when possible.
- For each finding, state the impact and the concrete fix direction.
- After findings, add open questions or assumptions.
- Keep summaries secondary and brief.
- If no issues are found, say so and list residual test gaps or unverified risks.

## Audit Semantics

Check that PHASE1 remains an audit review queue generator:

- Results must not be phrased as final fraud determinations.
- `is_fraud`, `is_anomaly`, precision, and recall from DataSynth must remain development validation aids.
- User-facing language should distinguish confirmed exception, review-only candidate, high-risk review item, and macro finding.
- Review-only signals must not be stored, exported, or narrated as confirmed violations.
- Priority and risk language must be evidence-based and should not overstate weak signals.

## Rules / Scoring / Priority

Check detection and scoring changes for:

- Correct use of established rule IDs, severity maps, scoring roles, and normalized scores.
- No direct summing of labels such as High/Medium/Low or Korean severity text.
- Proper separation of `flagged_rules` and `review_rules`.
- Macro findings such as Benford or process/account-level anomalies not being forced into row-level transaction flags without design support.
- Floors, bonuses, and evidence groups not hiding severe control violations or inflating weak evidence.
- Tests covering both positive and negative cases, including graceful no-data cases.

## DataSynth / Synthetic Data Quality

Check DataSynth-related changes for:

- No test fitting. Synthetic data should be fixed at the generation cause.
- Rust source fixes under `tools/datasynth/` for generator defects; no Python patch-around for bad generated data.
- No synthetic label leakage through obvious shortcut features.
- Normal and abnormal data quality noise applied consistently where intended.
- MCAR, typo, and format noise not becoming an accidental target proxy.
- Labels and entry flags remaining synchronized when anomaly/fraud injection changes.
- Quality gates and documentation updated when generator behavior or baseline data changes.

## Ingest / Validation / Data Contracts

Check ingest and validation changes for:

- Required and recommended column behavior remains explicit.
- Encoding fallback, sheet/header detection, type casting, and mapping confidence stay transparent.
- Pandera or existing validators enforce data contracts when schema matters.
- Missing optional fields degrade gracefully and are not mislabeled as defects.
- Raw audit data is not printed in logs, exceptions, test output, or reports.

## DuckDB / Pipeline Isolation

Check database and pipeline changes for:

- Company and engagement isolation is preserved.
- No accidental shared global DB path when context-aware paths exist.
- `CompanyContext`, `ContextFactory`, `ConnectionManager`, loader, schema, and query helpers are used consistently.
- Temporary tests use temporary databases, not production-like `data/companies/**/audit.duckdb`.
- DDL changes preserve existing contracts or include a clear migration path.
- Audit trail paths do not mix system events with user-facing evidence exports.

## Streamlit / Dashboard Review

Check dashboard changes for:

- Risk, priority, and rule descriptions are not overly conclusive.
- Review queues are easy to inspect without implying final fraud proof.
- Large DataFrames are capped before storing in session state or rendering in browser components.
- Session state keys are stable and rerun-safe.
- Download/export flows avoid stale cached bytes after settings/filter changes.
- CSS changes are scoped to the intended tab/component and do not alter global Streamlit containers.
- Changed UI has at least import smoke coverage, focused tests, or browser/Playwright verification when behavior changed.

## OpenAI / LLM Review

Check LLM changes for:

- Latest official OpenAI docs were checked for API/model/structured output changes.
- Live API calls are not part of default tests.
- Structured outputs are strict and validated.
- Prompts and outputs are grounded in available evidence and cite/source the relevant facts where the feature requires it.
- Hallucination fallback paths exist for invalid JSON, missing evidence, timeout, and disabled API settings.
- Raw source descriptions, PII, tokens, `.env` values, and DB contents are not sent or logged unintentionally.
- Cached narratives remain invalidated or scoped when their input evidence changes.

## Export / Reports / Evidence

Check export and report changes for:

- PII masking is applied without mutating the source DataFrame.
- Filenames, filters, stale cache hashes, and download MIME types are tested.
- Reports distinguish data characteristics, expected graceful degradation, and code bugs.
- Audit evidence language remains supportable and does not exceed the underlying rule/evidence strength.
- User audit trail exports use the intended user-event path, not broad system logs.

## Safety / Secrets

Reject or flag changes that:

- Read or print `.env`, `auth.json`, session files, tokens, cookies, credentials, raw audit data, or DB files.
- Add broad logging of DataFrames, SQL results, LLM payloads, or exception objects containing sensitive values.
- Add global installs, destructive cleanup, or git write operations without explicit user approval.
- Weaken hooks, rules, or `AGENTS.md` safety constraints without a clear request.

## Documentation Drift

Check whether the change requires updates to:

- `docs/TASKS.md` for actual task status changes.
- `docs/debugging.md` or `docs/spec/TROUBLESHOOT.md` for meaningful bugs and fixes.
- `docs/spec/DECISION.md` for architecture or policy decisions.
- `docs/spec/DETECTION_RULES.md` or detection result contracts for rule/scoring semantics.
- `docs/archive/completed/raw-plan/` only when the design reference itself changed.

## Verification Expectations

For every review, ask:

- Are tests scoped to the changed behavior?
- Did risky shared-contract changes get broader verification?
- Were slow, browser, live API, or full pipeline tests skipped for a stated reason?
- Is the final report clear about what was verified and what remains risky?
