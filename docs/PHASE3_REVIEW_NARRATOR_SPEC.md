# PHASE3_REVIEW_NARRATOR_SPEC — Deprecated

> Status: Removed from active product path as of 2026-05-26.
>
> Rationale: local-ai-assist is a local ledger analysis assistant. Sending selected case evidence, journal metadata, user/counterparty fields, or rule-hit context to an external LLM conflicts with the local-first product boundary.
>
> Replacement: Local Evidence Brief. Existing PHASE1 rule evidence and PHASE2 family lane signals may be summarized deterministically in the UI without external API calls.
>
> This document is retained only as historical design context. It is not an active implementation contract.

## Current Boundary

PHASE3 LLM Narrator is not an active phase, detector layer, scoring layer, queue ordering layer, or selected-case memo feature.

Active product paths do not call external LLM/API services and do not send ledger rows, case evidence, journal metadata, user/counterparty identifiers, line descriptions, rule hits, PHASE1 case context, or PHASE2 family signals outside the local workspace.

The active explanation path is **Local Evidence Brief**:

- PHASE1: rule-level evidence, review focus, recommended audit actions, and case metadata.
- PHASE2: family-specific lane signals and locally computed anomaly evidence.
- UI/export: deterministic summaries derived from already-computed local evidence.

See [LOCAL_FIRST_EVIDENCE_POLICY.md](LOCAL_FIRST_EVIDENCE_POLICY.md) and [DECISION.md §D068](DECISION.md).

## Deprecated Historical Design

The removed design narrowed Phase 3 to a selected-case Review Narrator. It proposed using an LLM to summarize PHASE1 rule evidence, row context, and selected case metadata into an auditor memo draft.

That design is now superseded. In the active product:

- no external LLM is used for selected-case explanation;
- no OpenAI Structured Output contract is part of the active audit workflow;
- no AI review memo is generated;
- no LLM reranking, priority change, or integrated queue ordering is allowed;
- legacy LLM modules, prompts, schemas, and completion reports may remain only as disabled or historical assets.

## Historical Non-Scope That Remains Removed

| Removed item | Active replacement |
|---|---|
| PHASE3 LLM Narrator | Local Evidence Brief |
| Review Queue Narrator | PHASE1/PHASE2 local evidence panels |
| LLM reranking or priority adjustment | Existing PHASE1/PHASE2 deterministic ranking only |
| AI-generated review memo | Deterministic local evidence summary |
| Text-to-SQL over audit DB via external LLM | Existing local queries and dashboard views |
| LLM rule feedback or parameter suggestions | Manual rule governance and documented decisions |

## Local Evidence Brief Contract

Local Evidence Brief may be implemented as deterministic UI/report text from local evidence only.

Allowed input:

- PHASE1 selected case metadata already visible in the dashboard;
- PHASE1 rule evidence, review focus, and recommended audit actions;
- PHASE2 family lane signal summaries already computed locally;
- row/document references already present in the local result object.

Disallowed behavior:

- external LLM/API calls;
- sending raw ledger evidence or identifiers to remote services;
- creating new fraud hypotheses;
- changing queue ordering, priority score, review band, or official rank;
- treating review-only signals as confirmed violations.

## Change History

- 2026-05-14: Historical v2 design narrowed earlier Phase 3 ideas to Review Queue Narrator.
- 2026-05-15: Historical Sprint A-G implementation records were written under `docs/completed/`.
- 2026-05-26: PHASE3 LLM Narrator, selected-case AI memo, LLM reranking, Text-to-SQL, and LLM rule feedback were removed from the active product path. Local Evidence Brief became the replacement explanation direction.
