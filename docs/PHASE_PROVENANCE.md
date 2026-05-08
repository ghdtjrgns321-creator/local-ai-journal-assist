# Phase Provenance

> **PHASE1 역할 원칙**: PHASE1은 `fraud`를 확정하거나 정답 라벨을 맞히는 단계가 아니다. PHASE1의 목적은 전수 모집단에서 규칙 위반, 정책 위반, 이상 징후, 분석적 검토 신호를 넓게 올려 **감사인이 봐야 할 항목과 우선순위**를 만드는 것이다. DataSynth의 `is_fraud`/`is_anomaly`와 precision/recall은 개발 검증 보조 지표이며, 운영 해석은 예외 처리 대상, 감사인 리뷰 대상, 고위험 후보를 구분하는 review queue 기준으로 한다.
## 2026-05-07 Phase2 Streamlit Alignment

Phase2의 운영 정의를 다음처럼 고정한다.

1. `phase2-train`
- Streamlit에서는 별도 `Phase 2 학습 실행` action으로 노출한다.
- 학습 결과는 회사/engagement별 `model_dir/phase2_train/{report_id}/reports/training_report.json`에 저장한다.
- report metadata에는 `inference_contract`와 `promotion_policy`가 포함되어야 한다.

2. `phase2-infer`
- Streamlit에서는 `저장된 모델로 Phase 2 추론` action으로 노출한다.
- 최신 training report가 있으면 `training_contract` 모드로 provenance를 붙인다.
- 최신 training report가 없으면 `untrained_contract_only`로 표시한다.
- bootstrap 상태가 detector status에 남아 있으면 `cold_start_bootstrap`으로 표시한다.

3. Streamlit 표시 원칙
- Phase2 탭은 학습과 추론을 같은 버튼으로 숨기지 않는다.
- Phase2 결과에는 `phase2_training_report_id`, `phase2_inference_mode`, `phase2_inference_contract` 요약을 먼저 표시한다.
- DB에서 불러온 읽기 전용 결과는 provenance 표시를 우선하고, 재학습/재추론은 원본 파일 재업로드 후 실행한다.

4. Registry 경로
- Phase2 detector model load는 회사/engagement별 `ctx.model_dir`를 우선 사용한다.
- anonymous/legacy context에서는 기존 global model registry를 fallback으로 사용한다.

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
