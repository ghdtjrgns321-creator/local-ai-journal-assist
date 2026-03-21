# 현재 진행 태스크

> 상세 태스크 목록은 `docs/TASKS.md` 참조

## 현재: Phase 1b — 이상탐지 + DB

- [ ] constants.py — RULE_CODES, SEVERITY_MAP, LAYER_WEIGHTS 상수
- [ ] base.py — BaseDetector(ABC), DetectionResult, RuleFlag, validate_input
- [ ] integrity_layer.py — A01~A03 (데이터 무결성)
- [ ] fraud_layer.py — B01~B10 (부정 탐지)
- [ ] anomaly_layer.py — C01~C09 (이상 징후, C07=Benford)
- [ ] score_aggregator.py — 3레이어 가중합 + risk_level + 자동 승격
- [ ] DuckDB — connection, schema, loader, queries
- [ ] pipeline.py — 전체 오케스트레이터

## 다음: Phase 1c — 대시보드

- [ ] UI 컴포넌트 + Tab 1~3 + 메인 앱

## 이후: Phase 2 — ML

### Phase 2a: ML 전처리 파이프라인
- [ ] feature_groups.py, transformers.py, pipeline_builder.py
- [ ] label_strategy.py (자동 지도/비지도 전환)
- [ ] cv_selector.py (LR/RF/XGBoost/LightGBM 자동 비교)
- [ ] vae_wrapper.py + vae_model.py (Basic FC VAE)
- [ ] model_registry.py, transparency.py

### Phase 2b: ML 탐지기
- [ ] SupervisedDetector (전이 학습 포함)
- [ ] VAEDetector + IF 앙상블
- [ ] score_aggregator 5트랙 확장 (Percentile Ranking + 전략 패턴)
- [ ] SHAP 시각화

### Phase 2c: 추가 탐지기 (별도 계획)
- [ ] DuplicateDetector, TimeseriesDetector, IntercompanyMatcher
