# Phase2 Unsupervised Autoencoder - Strategic Plan

## Executive Summary

Phase2는 기본 학습, 추론, promotion surface를 **VAE 기반 비지도 오토인코더 1개 경로**로 줄인다. 현재 CSV에는 `is_fraud`, `is_anomaly` ground truth가 없으므로 supervised, transformer, sequence, stacking, hybrid 계열은 운영 품질을 검증할 수 없다. detector class 자체는 삭제하지 않고, Phase2 default/training/inference contract에서만 제외한다.

이번 구현의 목적은 leaderboard가 아니라 라벨 없는 전표 데이터에서 재현 가능한 anomaly ranking을 만드는 것이다. 따라서 no-label metric은 `flagged_ratio`나 rule-style proxy가 아니라 `unsupervised_selection_score`로 분리한다. 이 지표는 fraud accuracy가 아니라 calibration split의 score tail, top-k stability, review capacity, score degeneracy를 조합한 **모델 선택용 ranking proxy**다.

핵심 범위는 가볍게 둔다.

- 기본 family는 `unsupervised` 하나만 사용한다.
- 기본 promoted model은 VAE 기반 비지도 오토인코더 하나다.
- IsolationForest, ECOD, COPOD 같은 baseline은 MVP promotion에 넣지 않는다.
- synthetic anomaly recall, denoising VAE, high-confidence normal subset, hybrid benchmark는 기본 구현에서 제외하고 실험 백로그로 둔다.
- 전처리와 split은 train/calibration 경계를 지키며, inference에서 같은 matrix schema를 재사용한다.

## Why VAE + Unsupervised Only For Now

Hybrid model의 연구적 가치는 인정한다. VAE + XGBoost, VAE + Transformer, VAE + BiLSTM/Attention은 라벨, sequence contract, external/temporal validation, 충분한 runtime budget이 있을 때 후보가 될 수 있다. 현재 Phase2 기본 경로에는 넣지 않는다.

이유는 다음과 같다.

- 현재 `journal_entries.csv`에는 supervised target으로 쓸 `is_fraud`, `is_anomaly`가 없다.
- 논문의 높은 accuracy 수치는 class prevalence, split protocol, leakage control, external validation이 없으면 이 프로젝트의 성능 근거가 아니다.
- 전표 sequence contract가 아직 없다. Transformer/BiLSTM을 쓰려면 document/user/account/time window 단위 정의가 먼저 필요하다.
- 50,000 row probe가 timeout이 났으므로 모델 복잡도보다 preprocessing, split, calibration, runtime budget을 먼저 안정화해야 한다.
- 감사 워크플로우에는 calibrated fraud probability보다 설명 가능한 high-risk ranking과 review capacity control이 우선이다.

따라서 Phase2 기본 promoted model은 VAE 기반 비지도 오토인코더 하나다. Hybrid는 삭제하지 않고 `off-by-default` benchmark 후보로만 남긴다.

## Current Code Findings

- `src/services/phase2_training_service.py`는 여러 family를 trial queue에 넣고 best-per-family로 promotion한다.
- no-label metric은 `flagged_ratio` 또는 rule-style proxy로 떨어져 많이 flag하는 detector가 유리해질 수 있다.
- `src/detection/vae_detector.py`는 현재 VAE + IsolationForest ensemble이다. MVP에서는 IF를 promotion surface가 아니라 optional diagnostic/legacy compatibility로 낮춰야 한다.
- `src/preprocessing/pipeline_builder.py::_build_unsupervised_preprocessor()`는 high-cardinality categorical을 drop한다.
- `src/preprocessing/feature_quality.py`는 sparse column을 drop하지만 `has_*` indicator를 보존하지 않는다.
- `src/preprocessing/vae_wrapper.py`는 전체 입력을 한 번에 tensor화하므로 1M+ row에서 mini-batch 학습이 필요하다.
- `src/services/phase2_inference_service.py`와 `src/pipeline.py`는 training contract의 promoted version을 실제 model load version으로 강하게 고정하지 않는다.
- `dashboard/tab_phase2.py`는 unsupervised ranking proxy와 supervised metric의 의미 차이를 충분히 분리하지 않는다.

## MVP Architecture

Phase2 기본 모드는 `unsupervised_autoencoder_mvp`다.

- Trainable family: `unsupervised` only
- Promoted model: VAE-based unsupervised autoencoder only
- Secondary detector: default off for promotion; if existing IF path is retained, report it as diagnostic/legacy component only
- Score semantics: anomaly evidence/ranking score, not fraud probability
- Split: `document_id` group split by default, temporal holdout when reliable fiscal/date coverage exists, random split only as fallback
- Preprocessing fit: train split only
- Threshold: calibration split score distribution and review capacity policy
- Matrix contract: fitted preprocessing plan, column order, feature groups, schema hash saved in model bundle
- Loss policy: amount/numeric/categorical/indicator group weighting to prevent sparse one-hot dominance
- Required diagnostics: reconstruction loss, KL loss, posterior collapse warning, score flatness, train/calibration drift, group dominance
- Dashboard wording: show `unsupervised_selection_score` separately from Precision/Recall/F1

## Automatic EDA and Preprocessing Design

전처리가 품질의 대부분이므로 `profile_dataframe()` 결과는 단순 설명이 아니라 replayable preprocessing plan으로 이어져야 한다.

자동 EDA 산출물:

- row/column count, memory usage, capped duplicate estimate
- column role 후보: id, datetime, label, amount, numeric, categorical_low, categorical_high, boolean, sparse_indicator_source, excluded
- missingness profile: null ratio, all-null, near-all-null, structured missingness
- cardinality profile: unique count, unique ratio, rare category ratio, top-k concentration
- numeric profile: quantiles, skewness proxy, zero ratio, negative ratio, outlier tail ratio
- categorical profile: mode share, rare bucket share, unknown handling policy
- hard/soft gate: empty matrix, all-constant features, extreme missingness, profile cap warning

자동 전처리 원칙:

- ID/document/label/date raw column은 학습 feature에서 제외하되 provenance에는 남긴다.
- amount 계열은 signed log transform 후 robust scaling을 기본으로 한다.
- numeric은 median imputation, missing indicator, robust/standard scaling selector를 사용한다.
- low-cardinality categorical은 one-hot + rare bucket + unknown bucket을 사용하고 feature width cap을 둔다.
- high-cardinality categorical은 train split에서만 frequency/count encoder를 fit한다.
- sparse raw column은 필요 시 drop하되 `has_*` indicator는 별도 signal로 보존한다.
- fitted preprocessing state와 matrix metadata는 model bundle에 저장하고 inference에서 재사용한다.

## MVP Implementation Phases

### Phase 0: Surface Reduction

- `_DEFAULT_MODEL_FAMILIES`를 `("unsupervised",)`로 축소한다.
- Phase2 default queue, training, inference contract, promotion에서 supervised/transformer/sequence/stacking/rule-style family를 제외한다.
- detector class 파일은 삭제하지 않는다.
- Phase2-only inference는 promoted `unsupervised` version만 load한다.

### Phase 1: Contract and Report Semantics

- `phase2_training_mode="unsupervised_autoencoder_mvp"`를 추가한다.
- training report에 `training_mode`, `evaluation_policy`, `metric_name`, `metric_semantics`를 저장한다.
- Precision/Recall/F1은 ground truth가 있을 때만 표시한다.
- no-label 상황에서는 `unsupervised_selection_score`를 ranking proxy로 표시한다.

### Phase 2: Capped EDA and Preprocessing Plan

- Phase2 profile cap을 EDA 첫 단계에 적용한다.
- `Phase2PreprocessingPlan`과 `Phase2ColumnDecision`을 추가한다.
- leakage column, sparse column, high-cardinality column, constant column에 reason code를 남긴다.
- plan JSON과 schema hash를 training report와 model bundle에 저장한다.

### Phase 3: Leakage-Safe Split

- `_split_unsupervised_train_calibration()`을 추가한다.
- 기본은 `document_id` group split이다.
- fiscal year/date가 충분하면 temporal holdout을 우선 검토한다.
- random row split은 fallback으로만 사용한다.
- scaler, imputer, rare grouping, frequency encoding은 train split에서만 fit한다.
- calibration split은 threshold, selection metric, reliability diagnostics 계산에만 사용한다.

### Phase 4: Autoencoder Matrix Builder

- signed log amount transformer를 추가한다.
- low-cardinality one-hot rare grouping과 high-cardinality frequency encoder를 구현한다.
- missing/sparse indicators를 생성한다.
- transformed feature를 amount/numeric/categorical/boolean/indicator group으로 기록한다.
- inference에서 training-time column order와 unknown category policy를 그대로 적용한다.

### Phase 5: VAE Training and Loss

- `VAEDetector.fit()`을 mini-batch DataLoader 기반으로 바꾼다.
- VAE preset은 `compact`, `balanced`, `strict_capacity` 정도로 시작한다.
- hidden dim, latent dim, epochs, batch size, learning rate, beta를 설정화한다.
- reconstruction loss는 feature group별 weight를 적용한다.
- reconstruction loss, KL loss, beta, KL/reconstruction ratio를 epoch metadata로 저장한다.
- posterior collapse warning을 추가한다.

### Phase 6: Evaluation and Promotion

- `_compute_unsupervised_metric()`을 추가한다.
- primary components는 `score_tail_gap`, `topk_stability`, `capacity_penalty`, `score_degeneracy_penalty`로 제한한다.
- `flagged_ratio`는 metadata component로만 저장한다.
- threshold는 calibration split과 review capacity에서 산정한다.
- severe reliability warning이 있으면 completed-but-diagnostic-only로 낮춘다.
- promotion contract는 `unsupervised` 하나만 허용한다.

### Phase 7: Inference, Dashboard, Runtime Budget

- inference는 training report의 promoted version과 matrix schema hash를 따른다.
- dashboard는 metric semantics, preprocessing summary, split policy, reliability warnings를 표시한다.
- 50k smoke path가 지정된 local timeout 안에 끝나는지 테스트한다.
- train/calibration row cap을 설정화하고 report에 기록한다.

## Experimental Backlog

다음 항목은 현재 MVP에 넣지 않는다.

- high-confidence normal subset using Phase1 risk/rule-hit/extreme-tail
- denoising VAE objective
- cyclical KL schedule
- ECOD/COPOD/IsolationForest sanity baseline comparison
- synthetic anomaly benchmark module
- subgroup-specific thresholds
- VAE + XGBoost, VAE + Transformer, VAE + BiLSTM/Attention benchmark

이 항목들은 기본값 off, promotion 영향 없음, 별도 benchmark 문서와 검증셋이 있을 때만 진행한다.

## Success Metrics

- 기본 Phase2 trial queue가 `unsupervised` family만 포함한다.
- Phase2 default path가 supervised/transformer/sequence/stacking/rule-style family를 instantiate하지 않는다.
- no-label metric name은 `unsupervised_selection_score`다.
- training report가 preprocessing plan, schema hash, split policy, threshold policy, metric semantics를 저장한다.
- model bundle이 fitted preprocessing state와 matrix metadata를 저장한다.
- VAE training metadata가 reconstruction loss, KL loss, beta, collapse warning을 저장한다.
- severe reliability warning이 있으면 promoted model이 아니라 diagnostic-only status가 된다.
- inference loaded version이 training contract의 `promoted_versions["unsupervised"]`와 일치한다.
- 50,000 row smoke path가 설정된 시간 예산 안에 완료된다.

## Risks

- no-label metric은 fraud precision을 보장하지 않는다. UI와 report에서 ranking proxy로만 설명한다.
- VAE가 tabular anomaly detection에서 항상 강한 모델이라는 가정은 금지한다.
- train reconstruction score 기준 threshold는 optimistic할 수 있으므로 calibration split 기준을 사용한다.
- document line leakage를 막기 위해 row random split을 기본으로 쓰지 않는다.
- frequency encoding, rare grouping, scaler, imputer는 train split에서만 fit한다.
- one-hot categorical block이 loss를 지배할 수 있으므로 group loss weighting을 적용한다.
- DataSynth 기반 검증은 개발 smoke/contract 검증에는 유용하지만 실데이터 일반화 근거는 아니다.
- full-data duplicate/unique 계산은 1M+ row에서 비쌀 수 있으므로 Phase2 profile cap을 먼저 적용한다.

## Sources

### Primary Documentation

- scikit-learn preprocessing: https://scikit-learn.org/stable/modules/preprocessing.html
- scikit-learn OneHotEncoder: https://scikit-learn.org/stable/modules/generated/sklearn.preprocessing.OneHotEncoder.html
- Great Expectations missingness: https://docs.greatexpectations.io/docs/reference/learn/data_quality_use_cases/missingness
- Great Expectations uniqueness: https://docs.greatexpectations.io/docs/reference/learn/data_quality_use_cases/uniqueness/
- Frictionless Table Schema: https://specs.frictionlessdata.io/table-schema/
- PyOD model and contamination docs: https://pyod.readthedocs.io/en/latest/pyod.models.html
- Alibi Detect VAE detector docs: https://docs.seldon.io/projects/alibi-detect/en/latest/od/methods/vae.html

### Research And Benchmarks

- Robust Variational Autoencoders for Outlier Detection in Mixed-Type Data: https://www.research.ed.ac.uk/en/publications/robust-variational-autoencoders-for-outlier-detection-in-mixed-ty
- Large scale anomaly detection in mixed numerical and categorical input spaces: https://doi.org/10.1016/j.ins.2019.03.013
- Detecting Out-of-Distribution Inputs to Deep Generative Models Using Typicality: https://openreview.net/forum?id=r1lnxTEYPS
- Cyclical Annealing Schedule for KL Vanishing: https://aclanthology.org/N19-1021/
- Robust VAE using beta divergence: https://pubmed.ncbi.nlm.nih.gov/36714396/
- ADBench benchmark: https://proceedings.neurips.cc/paper_files/paper/2022/hash/cf93972b116ca5268827d575f2cc226b-Abstract-Datasets_and_Benchmarks.html
- Limitations of self-supervised learning for tabular anomaly detection: https://link.springer.com/article/10.1007/s10044-023-01208-1

### Cautionary Or Experimental References

- Autoencoders for Anomaly Detection are Unreliable: https://openreview.net/forum?id=X8XQOLjLX6
- Explaining Anomalies using Denoising Autoencoders for Financial Tabular Data: https://www.researchgate.net/publication/363765464_Explaining_Anomalies_using_Denoising_Autoencoders_for_Financial_Tabular_Data
- Diffusion-Scheduled Denoising Autoencoders for Tabular Data: https://www.researchgate.net/publication/394262741_Diffusion-Scheduled_Denoising_Autoencoders_for_Anomaly_Detection_in_Tabular_Data
- Multi-scale temporal VAE for financial fraud detection: https://www.sciencedirect.com/science/article/pii/S1110016826001870
