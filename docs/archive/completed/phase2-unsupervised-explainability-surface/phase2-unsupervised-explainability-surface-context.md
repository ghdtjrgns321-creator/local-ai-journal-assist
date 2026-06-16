# PHASE2 Unsupervised Explainability Surface — Context

## Status
- Phase: A·B·C·D 모두 완료 ✅
- Progress: 4 / 4 (14 tasks, 85 tests passed)
- Last Updated: 2026-05-25

## Completion Summary (2026-05-25)
- 신규 파일: `config/unsupervised_reason_tags.yaml`,
  `src/services/unsupervised_reason_tags.py`,
  `tests/modules/test_services/test_unsupervised_reason_tags.py`,
  `dev/active/phase2-unsupervised-explainability-surface/{plan,context,tasks}.md`
- 수정 파일: `src/services/phase2_case_family_aggregator.py` (explanation 집계),
  `src/services/phase2_case_contract.py` (overlay surface 부착),
  `src/services/phase2_inference_service.py` + `src/pipeline.py` (wiring),
  `src/llm/phase3_case_prompt.py` (system prompt 가드 + payload key),
  `tests/modules/test_services/test_phase2_case_family_aggregator.py`,
  `tests/modules/test_llm/test_phase3_case_prompt.py`
- 검증: scores / rule_flags / family_score / phase2 queue / PHASE1 priority
  변경 0. primary PHASE1+VAE 2-way RRF mismatch 0 (lane_overlay_preservation).
- ruff: All checks passed.

## Origin

사용자 요청 (2026-05-25): "Phase2 unsupervised family 의 강점을 더 부각시킬 수 있는
수정방안 모색. fitting 엄금." 사용자가 직접 제시한 개선 방향:
- score 개선보다 explanation / stability
- reconstruction error top contributing features
- feature group attribution
- train ECDF vs batch ECDF 명확화
- outlier reason tags
- lane 에서는 "statistical outlier" 로만 표현

검토 결과: A (overlay 전파), B (reason tag), D (language guard) 묶음으로 진행.
C (stability 진단) 와 E (IF dead path 정리) 는 out of scope.

## Approval

사용자 승인 문장 (2026-05-25):
> 1번 A+B+D 로 가는 게 맞습니다. 이건 "성능 개선" 이 아니라 Unsupervised
> family 의 포트폴리오 가치와 감사 언어 안정성 개선이라서 fitting 위험이
> 가장 낮습니다. 점수, threshold, ranking, recall 손대지 않고 이미 VAE 가
> 만든 설명 신호를 사람이 볼 수 있게 만드는 작업입니다.

reason tag mapping 정의 (사용자 직접 작성, 2026-05-25):
- posting_date_weekend → unusual_timing / "비정상 거래시점"
- posting_date_after_hours → unusual_timing / "비정상 거래시점"
- round_amount → round_amount_deviation / "금액 패턴 이상"
- amount_z → amount_outlier / "금액 규모 이상"
- trading_partner_frequency → vendor_frequency_anomaly / "거래처 빈도 이상"
- posting_lag_days → posting_lag_anomaly / "전기 지연 패턴 이상"
- manual_entry_flag → manual_entry_context / "수기입력 맥락"
- (미매핑) → feature_pattern_outlier / "피처 패턴 이상"

운영 규칙 (사용자 lock):
- 정확 매칭 우선, 안 맞으면 prefix / contains 매칭.
- 미매핑 feature 는 `feature_pattern_outlier` 로 fallback.
- label 은 "이상", "패턴", "맥락" 까지만 사용. "위반", "부정", "오류 확정" 금지.
- 매핑은 score 에 절대 사용하지 않음. overlay/narrator 표시 전용.

## Key Files

**To Create**:
- `config/unsupervised_reason_tags.yaml` — 7개 매핑 + fallback (Phase A)
- `src/services/unsupervised_reason_tags.py` — loader + resolve_tag (Phase A)
- `tests/modules/test_services/test_unsupervised_reason_tags.py` (Phase A)

**To Modify**:
- `src/services/phase2_case_family_aggregator.py` — `_top_subdetectors_for_case` /
  새 helper `_unsupervised_explanation_features_for_case`, return payload 확장
  (Phase B)
- `src/services/phase2_case_contract.py` — `_build_family_contributions` 에
  unsupervised 분기 (evidence_type / explanation_features 부착) (Phase B)
- `src/llm/phase3_case_prompt.py` — system prompt unsupervised 가드 +
  `_case_input` payload `phase2_unsupervised_explanation` 노출 (Phase C)

**Read-Only Inputs**:
- `src/detection/vae_detector.py` — ML02 details 컬럼 형식 진본
- `docs/spec/PHASE2_GOVERNANCE_DESIGN.md` 결정 8 — family signal lane/overlay/tie-break 한정
- `dev/active/phase2-family-ranking/phase2-family-ranking-plan.md` — Phase D/E
  pivot 정합 (본 작업은 그 후속 surface 보강)

## Key Decisions

1. **C (train vs batch ECDF stability) 는 본 sprint out of scope** (2026-05-25)
   - Rationale: 본 sprint 의 목적은 explanation surface 연결.
     stability 진단은 governance Layer C 후속 PR.
   - Trade-offs: drift 가시성은 그대로. 단 score 미변경 / lock 보호.

2. **E (IF dead path 정리) 는 별도 PR** (2026-05-25)
   - Rationale: 성격이 다르고 PR 이 흐려진다 (사용자 의견).
   - Trade-offs: vae_detector 의 IF 학습 + ECDF 분포 저장은 현재 그대로 유지.

3. **reason tag 매핑은 최소 셋 7개 + fallback** (2026-05-25)
   - Rationale: 처음부터 feature_groups 전체 매핑 시 유지보수 부담 + 의미
     애매한 태그가 섞일 위험.
   - Alternatives: feature_groups 전체 매핑 (보류)

4. **explanation_features 는 score 에 사용 금지** (2026-05-25)
   - Rationale: 사용자 lock. 본 작업은 표시 전용.
   - Implementation guard: `_build_family_contributions` 에서 explanation_features
     를 entry 의 `score`/`ecdf` 와 별개 키로 분리. aggregator 가 family_scores
     계산 후에 부착.

## Sub-Detector Inventory 정합

unsupervised family 의 sub-detector 는 `VAE-01` 하나 (evidence_tier =
`ml_quantile`, `config/phase2_subdetector_tiers.yaml` 진본). 본 작업은 tier
변경 없음. 신규 sub-detector 추가 없음.

## Known Issues

- ML02 details 의 feature 명은 `ColumnTransformer.get_feature_names_out()` 산출이라
  `num__amount`, `cat_low__counterparty_xxxxx` 형태 prefix 포함. 매칭 시 prefix
  제거 후 비교 또는 contains 매칭 필요. loader 에서 normalize 처리.
- aggregator 가 case 매칭 row 가 비어 있을 때 (모두 score=0) explanation_features
  도 비어야 함. 빈 list / `None` 분기 명확화.

## 메모리 정합 체크

- `feedback_phase1_truth_recall_guard` — score / threshold 미변경 정합.
- `feedback_unsupervised_no_y` — 본 작업은 y 라벨 미사용 (overlay surface only).
- `feedback_ecdf_ensemble` — ECDF 사용 정합 (score 미변경).
- `feedback_professional_tone` — narrator 가드 문구 어휘 lock.
- `feedback_no_hardcoded_coa` — reason tag mapping 은 yaml 분리 (코드 상수 금지).
