# Phase Provenance

## 목적

이 프로젝트는 단순히 이상거래를 탐지하는 데서 끝나지 않는다.  
포트폴리오 관점에서는 아래 질문에 답할 수 있어야 한다.

- 어떤 학습 리포트가 현재 추론에 사용되었는가
- 현재 추론은 정식 학습 계약 기반인가, cold-start bootstrap인가
- 이 phase2 결과를 바탕으로 어떤 phase3 insight가 생성되었는가
- batch reload 후에도 같은 provenance를 재현할 수 있는가

## 흐름

1. `phase2-train`
- feature variant, search preset, model family trial을 실행한다.
- leaderboard, promoted model, promotion policy, inference contract를 저장한다.
- 현재 기본 family는 `unsupervised`, `supervised`, `transformer`, `sequence`, `timeseries`, `relational`, `duplicate`, `intercompany`, `stacking`이다.
- rule-style family는 `sub_detector_keys`와 `sub_detector_summaries`를 같이 남긴다.

2. `phase2-infer`
- promoted model contract를 우선 사용한다.
- cold-start가 필요한 경우에만 bootstrap이 허용된다.
- 결과에는 `phase2_inference_mode`가 함께 기록된다.
- inference contract에는 `required_models`, `promoted_versions`, `track_map`, `family_sub_detectors`가 함께 남는다.

3. `phase3`
- LLM batch insight 생성 시 phase2 contract snapshot을 prompt에 주입한다.
- 생성된 `BatchInsight` 결과에도 `phase2_context`가 남는다.

4. `DB / restore / export`
- `upload_batches`에는 아래 메타데이터가 저장된다.
- `phase2_training_report_id`
- `phase2_inference_contract`
- `phase2_inference_mode`
- `phase2_promotion_policy`
- `phase3_insight_json`

`phase2_inference_contract` 안에는 다음이 포함된다.
- `selection_mode`
- `required_models`
- `promoted_versions`
- `track_map`
- `family_sub_detectors`

## 현재 운영 모드

- `training_contract`
  - promoted model과 training report contract를 기반으로 추론한 상태
- `cold_start_bootstrap`
  - 학습 계약이 없어 bootstrap 모델로 임시 추론한 상태
- `untrained_contract_only`
  - 학습 계약 없이 결과만 생성된 상태

이 구분은 dashboard, export, DB restore 경로까지 유지된다.

## 포트폴리오 메시지

데모에서는 다음 순서로 설명하면 된다.

1. `Phase 1` 규칙 기반 탐지로 기본 이상 징후를 찾는다.
2. `Phase 2-train`에서 모델 후보와 trial을 비교하고 promoted model을 만든다.
   - 이때 시계열, novelty, duplicate, intercompany 계열도 같은 contract 안에 같이 들어간다.
3. `Phase 2-infer`는 그 promoted contract를 사용해 재현 가능한 추론을 수행한다.
4. `Phase 3`는 그 추론 계약을 알고 LLM 요약을 생성한다.
5. 결과를 저장하고 다시 불러와도 같은 provenance가 복원된다.

즉 이 프로젝트의 강점은 “탐지” 자체뿐 아니라 “탐지 결과의 출처와 계약을 끝까지 추적 가능하게 만든 구조”에 있다.
