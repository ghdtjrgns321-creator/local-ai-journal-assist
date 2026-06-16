# PHASE2 Unsupervised Explainability Surface — Strategic Plan

## Executive Summary
PHASE2 unsupervised family (ML02 / VAE) 의 강점인 broad anomaly coverage 는
이미 운영 중이지만, detector 가 산출하는 per-row top-K 재구성 기여 피처와
feature-group attribution 이 details 에만 머무르고 case overlay / narrator /
dashboard 까지 도달하지 못한다. 본 작업은 **점수·순위·threshold·primary
queue 를 일절 손대지 않고**, 이미 생성된 설명 신호를 surface 까지 연결하고
"통계적 이상치" 언어 가드를 추가해 unsupervised family 의 explainability 와
audit attribution 안전성을 동시에 끌어올린다.

> **포지셔닝**: 본 작업은 truth recall / precision / score / threshold 개선이
> 아니다. unsupervised 의 포트폴리오 가치와 감사 언어 안정성을 위한
> **explanation surface only** 변경이다. fitting 위험 0.

## Lock Conditions (사용자 확정, 2026-05-25)

| 항목 | lock |
|------|------|
| scores / rule_flags / family_score / phase2 queue / PHASE1 priority | **변경 금지** |
| Top-K feature · reason tag | **explanation payload only** — score input 진입 금지 |
| narrator / dashboard 문구 | `fraud`, `violation`, `confirmed`, `위반 확정` 금지 |
| 허용 어휘 | `통계적 이상치`, `패턴`, `맥락`, `검토 필요` |
| reason tag 미매핑 | graceful fallback → `feature_pattern_outlier` |
| matching 순서 | 정확 매칭 → prefix → contains |
| reason tag mapping | overlay/narrator 표시 전용. score 에 사용 금지 |
| C (train vs batch ECDF stability) | 본 sprint **out of scope**, 후속 |
| E (IF dead path 정리) | 본 sprint **out of scope**, 별도 PR |

## Current State

| 신호 | 산출 위치 | Surface 도달 | 문제 |
|------|-----------|-------------|------|
| ML02 row score (VAE ECDF) | `_combine_scores` | overlay/queue ✓ | 단독 evidence 위험 |
| `ML02_top_feature_{1..3}` + contrib | `_build_topk_columns` (`vae_detector.py:363-417`) | **details 에만, overlay 미전파** | 설명력 사장 |
| `feature_group_reconstruction_scores` | metadata | metadata 만 | UI 미사용 |
| outlier reason tag | 없음 | 없음 | 피처명 raw 노출 |
| "statistical outlier" 언어 가드 | 시스템 프롬프트 일반 가드만 | unsupervised 분기 없음 | 과장 위험 |

`phase2_case_family_aggregator.py:_top_subdetectors_for_case` 가 unsupervised 일
때 고정 `("VAE-01", "audit_vae_reconstruction")` 만 반환 → details 의 top
feature 가 case overlay 까지 도달하지 못한다.

## Proposed Solution

### A — Overlay 까지 Top-K 피처 전파
- `phase2_case_family_aggregator.py` 에서 unsupervised result 의 details 컬럼
  (`ML02_top_feature_{1..3}` + `ML02_top_feature_{1..3}_contrib`) 을 case row
  들에 대해 max-contrib feature 로 집계.
- `Phase2CaseOverlay.family_contributions[unsupervised]` 에
  `explanation_features: [{feature, contrib, tag, label_ko}]` 필드 부착.
- evidence_type 필드 `statistical_outlier` 부착.

### B — Reason Tag Mapping (최소 셋 7개)
- `config/unsupervised_reason_tags.yaml` 신규: 7개 매핑 + fallback.
- `src/services/unsupervised_reason_tags.py` 신규: loader + `resolve_tag(feature_name)`
  (정확 → prefix → contains, 미매핑은 `feature_pattern_outlier`).
- aggregator 가 feature 명을 받아 tag/label_ko 변환 후 explanation_features 에 동봉.

### D — Language Guard
- `src/llm/phase3_case_prompt.py::phase3_fact_grounding_system_prompt` 에
  unsupervised family 인용 시 "통계적 이상치 (statistical outlier)" 만 허용,
  fraud/violation/confirmed/위반 확정 금지 문구 추가.
- `_case_input` payload 에 `phase2_unsupervised_explanation` 키 추가
  (family_contributions 에서 unsupervised entry 의 explanation_features 추출).

### Reason Tag 매핑 (yaml 진본)

| feature key (prefix/contains) | tag | label_ko |
|---|---|---|
| posting_date_weekend | unusual_timing | 비정상 거래시점 |
| posting_date_after_hours | unusual_timing | 비정상 거래시점 |
| round_amount | round_amount_deviation | 금액 패턴 이상 |
| amount_z | amount_outlier | 금액 규모 이상 |
| trading_partner_frequency | vendor_frequency_anomaly | 거래처 빈도 이상 |
| posting_lag_days | posting_lag_anomaly | 전기 지연 패턴 이상 |
| manual_entry_flag | manual_entry_context | 수기입력 맥락 |
| _fallback_ | feature_pattern_outlier | 피처 패턴 이상 |

모두 `evidence_type: statistical_outlier` 고정.

## Implementation Phases

### Phase A: Reason tag config + loader (0.25 day)
- [ ] `config/unsupervised_reason_tags.yaml` 작성 — Size: S
- [ ] `src/services/unsupervised_reason_tags.py` loader + 매칭 — Size: M
- [ ] `tests/modules/test_services/test_unsupervised_reason_tags.py` — Size: M

### Phase B: Aggregator 에 explanation_features 전파 (0.5 day)
- [ ] `phase2_case_family_aggregator.py` 의 `_top_subdetectors_for_case` 가
      unsupervised 일 때 ML02_top_feature_* details 를 case row max-contrib
      기준으로 집계해 explanation_features payload 부착 — Size: M
- [ ] `Phase2CaseOverlay.family_contributions[unsupervised]` 가
      `explanation_features` + `evidence_type=statistical_outlier` 를 받도록
      `_build_family_contributions` 확장 — Size: S
- [ ] `tests/modules/test_services/test_phase2_case_family_aggregator.py` 에
      explanation_features 전파 회귀 test — Size: M

### Phase C: Narrator language guard 강화 (0.25 day)
- [ ] `phase3_fact_grounding_system_prompt()` 에 unsupervised 분기 가드 문구 추가
      (통계적 이상치 한정, fraud/violation/confirmed/위반 확정 금지) — Size: S
- [ ] `_case_input` payload 에 `phase2_unsupervised_explanation` 키 노출 — Size: S
- [ ] `tests/modules/test_llm/test_phase3_case_prompt.py` 회귀 + 신규 1건 — Size: S

### Phase D: 회귀 검증 (0.25 day)
- [ ] primary RRF 순위 mismatch 0 확인 — `tests/modules/test_pipeline/test_phase2_lane_overlay_preservation.py` — Size: S
- [ ] family_contributions 기존 필드 보존 — `test_phase2_case_contract.py` — Size: S
- [ ] ruff + 전체 phase2/llm 모듈 회귀 — Size: S

## Risk Assessment

- **High**: explanation_features 가 score input 으로 새는 경우. Mitigation:
  loader / aggregator unit test 가 `family_scores_by_case` 동결 검증.
- **Medium**: reason tag 어휘가 audit 결론처럼 읽히는 경우. Mitigation: lock
  조건 7번 어휘만 사용, label 검수 + narrator system prompt 가드 통과 test.
- **Medium**: details 컬럼 부재 (구버전 detector bundle) → KeyError. Mitigation:
  aggregator 에서 `ML02_top_feature_1` 부재 시 explanation_features 빈 list 로
  graceful fallback.
- **Low**: yaml 매핑 미충족 feature 의 fallback tag 가 의미 불명확.
  Mitigation: `feature_pattern_outlier` 명시 + label "피처 패턴 이상".

## Success Metrics

- `config/unsupervised_reason_tags.yaml` + loader unit test 통과.
- aggregator 가 unsupervised case 의 explanation_features 를 채움 — 매칭 feature
  최소 1개 이상 propagate (V7 fixed3 sample 기준).
- `Phase2CaseOverlay.family_contributions[unsupervised]` 에 evidence_type +
  explanation_features 동봉.
- `phase3_fact_grounding_system_prompt` 출력에 unsupervised guard 문장 포함.
- primary PHASE1+VAE 2-way RRF mismatch 0 (regression).
- ruff / pytest 회귀 전부 통과.

## Dependencies

- Code:
  - `src/detection/vae_detector.py` (read-only)
  - `src/services/phase2_case_family_aggregator.py`
  - `src/services/phase2_case_contract.py`
  - `src/services/unsupervised_reason_tags.py` (신규)
  - `src/llm/phase3_case_prompt.py`
- Config:
  - `config/unsupervised_reason_tags.yaml` (신규)
- Tests:
  - `tests/modules/test_services/test_unsupervised_reason_tags.py` (신규)
  - `tests/modules/test_services/test_phase2_case_family_aggregator.py`
  - `tests/modules/test_services/test_phase2_case_contract.py`
  - `tests/modules/test_llm/test_phase3_case_prompt.py`
  - `tests/modules/test_pipeline/test_phase2_lane_overlay_preservation.py`
- Docs (touch-up):
  - 없음 — 본 작업은 governance lock 변경 없음. PHASE2_GOVERNANCE_DESIGN.md
    결정 8 의 "family signal lane/overlay/tie-break 한정" 정합 유지.
