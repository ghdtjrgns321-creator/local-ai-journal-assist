# Local-First Evidence Policy

## Active Boundary

No active product path sends ledger data, case evidence, journal metadata, user/counterparty identifiers, descriptions, rule hits, PHASE1 case context, or PHASE2 family signals to external LLM/API services.

PHASE1 and PHASE2 analytics run locally. Any explanatory UI must be deterministic or derived from already-computed local evidence.

## Active Architecture

- PHASE1: local rule-based review queue.
- PHASE2: local family-specific analytical lanes.
- Local Evidence Brief: deterministic summary from existing local evidence.
- Export/UI: local rendering only.

## Removed

- PHASE3 LLM Narrator.
- Review Queue Narrator.
- LLM reranking.
- AI-generated review memo.
- Text-to-SQL over audit DB via external LLM.
- LLM rule feedback loop.
- LLM parameter or preprocessing suggestions as active product capability.

## Allowed Future Work

Local-only NLP or local model inference may be considered if:

1. no external data transmission occurs;
2. raw ledger data remains within the workspace;
3. outputs remain review-supporting, not fraud-determining;
4. deterministic fallback exists.

## Documentation Rule

LLM/OpenAI/PHASE3 references may remain only as historical, deprecated, removed, or legacy documentation. They must not be described as active product capability, active dependency, active phase, or active implementation contract.
