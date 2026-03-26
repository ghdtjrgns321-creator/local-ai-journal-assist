# Preprocessing Pipeline 테스트 결과 통합 리포트

> 최종 갱신: 2026-03-26 | **62 passed**, 0 failed in 7.22s
> __pycache__ 바이트코드에서 소스 복원 후 재실행 통과 (11개 구현 모듈, 8개 테스트 파일)

---

## 1. 전체 요약

```
모듈                 테스트 수   결과     소요시간
─────────────────────────────────────────────────
feature_groups            10   ✅ PASS   0.12s
transformers               8   ✅ PASS   0.15s
pipeline_builder           6   ✅ PASS   1.23s
label_strategy             9   ✅ PASS   0.08s
cv_selector                7   ✅ PASS   0.52s
transparency               4   ✅ PASS   0.06s
model_registry            10   ✅ PASS   0.14s
vae_wrapper                8   ✅ PASS   1.82s
─────────────────────────────────────────────────
합계                      62   ALL PASS  7.22s
```

---

## 2. 모듈별 검증 항목

### feature_groups.py (10 cases)

EDAProfile → 6그룹(numeric/categorical_high/categorical_low/boolean/ordinal/excluded) 자동 분류.

| 검증 항목                    | 설명                                                      |
|:-----------------------------|:----------------------------------------------------------|
| 수치형 분류                  | debit_amount 등 float/int → numeric                       |
| boolean 분류                 | is_weekend 등 bool → boolean                              |
| 도메인 오버라이드            | description_quality → ordinal (자동분류와 다른 배치)      |
| 고카디널리티 오버라이드      | gl_account(4000+종) → categorical_high (사용자 지정)      |
| 저카디널리티 범주형          | source, company_code → categorical_low                    |
| ID/datetime/레이블 제외      | document_id, posting_date, is_fraud → excluded            |
| 고결측률 자동 제외           | 결측률 95% → excluded + 경고 로그                         |
| all_features 무결성          | excluded 미포함 검증                                      |
| 사용자 지정 exclude          | exclude_columns 파라미터 동작                             |
| 중복 배치 방지               | 동일 컬럼이 여러 그룹에 중복 배치되지 않음                |

### transformers.py (8 cases)

커스텀 sklearn Transformer: NullFlagTransformer + SafePowerTransformer.

| 검증 항목                    | 설명                                                      |
|:-----------------------------|:----------------------------------------------------------|
| NaN 플래그 컬럼 추가         | 원본 2컬럼 → 4컬럼 (원본 + is_null 플래그)                |
| NaN → fill_value 대체        | -99.0 대체, 원본값 유지 확인                              |
| 플래그 정확성                | NaN=1.0, 값있음=0.0                                       |
| NaN 없을 때 플래그 전부 0    | 불필요한 플래그 활성화 없음                                |
| Yeo-Johnson skewness 감소    | 변환 후 abs(skew) 감소 확인 (scipy.stats.skew)            |
| 상수 컬럼 안전 처리          | std=0 → PowerTransformer 에러 방지, 원본 유지             |
| 입출력 shape 보존            | transform 후 shape 동일                                   |
| 음수값 처리                  | Yeo-Johnson → 음수(credit_amount) 정상 처리               |

### pipeline_builder.py (6 cases)

XGB/VAE/IF 3개 Pipeline 조립 + fit/predict.

| 검증 항목                    | 설명                                                      |
|:-----------------------------|:----------------------------------------------------------|
| XGBoost Pipeline 생성        | preprocessor + classifier 2단계                           |
| XGBoost fit → predict        | 출력 {0,1} 이진값                                         |
| IF Pipeline 생성             | preprocessor + detector                                   |
| IF fit → predict             | 정상 동작                                                 |
| build_all_pipelines          | 3개 dict 반환 (xgb, vae, if)                              |
| preprocessor 단계 포함 확인  | 모든 Pipeline에 preprocessor 존재                         |

**지도 vs 비지도 전처리 분기:**

```
XGBoost (지도)           VAE/IF (비지도)
├── SimpleImputer        ├── SimpleImputer
├── TargetEncoder        ├── [cat_high DROP]
├── OrdinalEncoder       ├── SafePowerTransformer
└── (스케일링 불필요)    ├── StandardScaler
                         └── OrdinalEncoder
```

### label_strategy.py (9 cases)

3가지 라벨 전략: datasynth(ground truth) / pseudo(룰 기반) / hybrid(우선순위).

| 검증 항목                    | 설명                                                      |
|:-----------------------------|:----------------------------------------------------------|
| DataSynth: is_fraud → y 생성 | label_source 확인, source_breakdown 존재                  |
| DataSynth: 양성률 범위       | 0.0 ≤ positive_rate ≤ 1.0                                 |
| DataSynth: 레이블 컬럼 없음  | 전체 0 반환 (graceful degradation)                        |
| Pseudo: scores → y 생성      | detection_scores 기반 라벨 생성                           |
| Pseudo: threshold 정확성     | ≥ 0.5 → 양성(1) 판정 검증                                 |
| Pseudo: scores 없으면 에러   | ValueError("detection_scores") 발생                       |
| Hybrid: DataSynth 우선       | DataSynth 컬럼 있으면 우선 사용                           |
| Hybrid: pseudo 폴백          | DataSynth 없으면 scores로 폴백                            |
| Hybrid: 양쪽 모두 없음       | 전체 정상(0) — 비지도 전용                                |

### cv_selector.py (7 cases)

StratifiedKFold Pipeline 비교 + GridSearchCV.

| 검증 항목                    | 설명                                                      |
|:-----------------------------|:----------------------------------------------------------|
| int → StratifiedKFold 변환   | cv=5 → StratifiedKFold(n_splits=5) 자동 변환              |
| StratifiedKFold passthrough  | 기존 인스턴스 그대로 반환                                 |
| CVComparisonResult 반환      | 타입 검증                                                 |
| 모든 Pipeline 평가           | shallow, deep 둘 다 results에 포함                        |
| best_pipeline 선택           | mean_f1 최대 Pipeline 자동 선택                           |
| 비교 테이블 구조             | pipeline, mean_f1 컬럼 포함 DataFrame                     |
| fold별 점수 길이             | len(scores) == cv 수                                      |

### transparency.py (4 cases)

전처리 전/후 비교 메타데이터 — White Box 투명성.

| 검증 항목                    | 설명                                                      |
|:-----------------------------|:----------------------------------------------------------|
| dict 반환                    | 반환 타입 검증                                            |
| 필수 키 포함                 | steps, before_stats, after_stats, n_features_in/out       |
| before_stats 컬럼별 통계     | missing_rate 포함 확인                                    |
| Pipeline 단계명 추출         | "preprocessor" 이름 추출 정확성                           |

### model_registry.py (10 cases)

Pipeline 직렬화 + 버전 관리 (joblib + registry.json).

| 검증 항목                    | 설명                                                      |
|:-----------------------------|:----------------------------------------------------------|
| save → .pkl 파일 생성        | 디스크 파일 존재 확인                                     |
| save → ModelMetadata 반환    | model_name, version, mean_f1 필드 확인                    |
| 버전 자동 증가               | 같은 모델 2회 저장 → v1, v2                               |
| latest 로드                  | 최신 버전(v2) 반환                                        |
| 특정 버전 로드               | v1 지정 → 해당 버전 정확 로드                             |
| 없는 모델 → FileNotFoundError | 에러 발생 확인                                            |
| 모델 목록 반환               | 등록된 모델 전체 리스트                                   |
| 버전별 성능 비교             | compare_versions → version, mean_f1 리스트                |
| registry.json 영속성         | 파일 디스크 저장 확인                                     |
| 인스턴스 재생성 시 유지      | 같은 디렉토리 새 ModelRegistry → 기존 데이터 보존         |

### vae_wrapper.py (8 cases)

VAE sklearn BaseEstimator 호환 래퍼 (PyTorch 기반).

| 검증 항목                    | 설명                                                      |
|:-----------------------------|:----------------------------------------------------------|
| fit → self 반환              | sklearn 규약 준수                                         |
| predict shape                | (n_samples,) 출력                                         |
| predict 이진값               | {0, 1} 값만 포함                                          |
| predict_proba shape          | (n_samples, 2) 출력                                       |
| predict_proba 확률 합        | 각 행 합 == 1.0 (atol=1e-6)                               |
| classes_ 속성                | fit 후 [0, 1] 설정                                        |
| 비지도 모드 (y=None)         | 전체 데이터로 학습, predict 정상 동작                     |
| 직렬화 라운드트립            | `__getstate__`/`__setstate__` → threshold_/model_ 보존    |

**VAE 이상 탐지 흐름:**

```
fit: X(정상) → VAE 학습 → reconstruction error 분포 → threshold (percentile)
predict: X → error > threshold → 1(이상) / 0(정상)
predict_proba: sigmoid((error - threshold) / scale) → [P(정상), P(이상)]
```

---

## 3. 발견된 문제점

테스트 실패: 없음. 62개 전 케이스 첫 실행 통과.

### 코드 리뷰 이슈 (Phase 2 detection 구현 시 해결)

| #  | 파일                  | 위치       | 문제                                                 | 분류   | 해결 방향                                              |
|:---|:----------------------|:-----------|:-----------------------------------------------------|:-------|:-------------------------------------------------------|
| 1  | `model_registry.py`   | `load():131` | 경로 순회 취약점 — file_path 검증 없음              | 보안   | `resolve().relative_to()` 검증 삽입                    |
| 2  | `model_registry.py`   | `:21`      | `Path("models")` 상대 경로 → CWD 의존               | 보안   | `get_settings().project_root / "models"` 변경          |
| 3  | `vae_wrapper.py`      | `predict`  | fit 전 predict 호출 시 에러 메시지 불명확            | 견고성 | `check_is_fitted(self, ["model_", "threshold_"])` 추가 |
| 4  | `label_strategy.py`   | `_hybrid():128` | 양성 0건 + scores 있을 때 pseudo 폴백 누락       | 로직   | `positive_rate == 0 and scores` 분기 추가              |
| 5  | `cv_selector.py`      | `compare_pipelines` | VAE Pipeline이 n_jobs>1에서 VRAM 경합         | 견고성 | `_has_vae()` 감지 → n_jobs=1 강제                      |

> 해결 위치: [05-detection §선행이슈](../../docs/pre-plan/05-detection.md#선행-모듈에서-넘어온-미해결-이슈-교차-참조)

---

## 4. 설계 포인트

| 설계 결정                         | 근거                                                               |
|:----------------------------------|:-------------------------------------------------------------------|
| StratifiedKFold 강제              | 이상 전표 1% 미만 극단 불균형 → 기본 KFold 시 Fold별 양성 0건 방지 |
| 지도/비지도 전처리 분기           | XGBoost=TargetEncoder, VAE/IF=고카디널리티 DROP+PowerTransformer   |
| SafePowerTransformer 상수 컬럼 방어 | std=0 컬럼 → PowerTransformer 에러 방지, 원본 유지               |
| NullFlagTransformer 의미있는 결측 | days_backdated NaN = "소급 없음" → 플래그로 정보 보존             |
| VAE 직렬화 이원화                 | sklearn=joblib, torch=state_dict bytes → Pipeline 통합 직렬화     |
| VRAM 순차 정리                    | VAE fit/CV 후 torch.cuda.empty_cache() 호출                       |
| 라벨 전략 3계층                   | DataSynth GT → pseudo(룰) → hybrid(우선순위) 폴백                 |

---

## 5. 후속 고려사항

| 항목                                    | 해결 시점     |
|:----------------------------------------|:-------------|
| tune_best_pipeline (GridSearchCV) 테스트 | Phase 2 detection 구현 시 |
| 실제 DataSynth 1M건 E2E fit/predict     | Phase 2 detection 구현 시 |
| RTX 3070 Ti (8GB) VAE 배치 크기 프로파일 | Phase 2 detection 구현 시 |
| model_registry 삭제 기능                | 디스크 용량 관리 필요 시 |
| after_stats 피처별 상세 통계            | Phase 1c 대시보드 연동 시 |
| score_aggregator → pseudo 전략 연동     | Phase 1b 완료 후          |
| explainer.py (SHAP) 테스트              | Phase 2 SHAP 시각화 구현 시 |

---

## 6. 실행 명령어

```bash
# 전체 preprocessing 테스트
uv run pytest tests/test_preprocessing/ -v

# 개별 모듈
uv run pytest tests/test_preprocessing/test_feature_groups.py -v
uv run pytest tests/test_preprocessing/test_transformers.py -v
uv run pytest tests/test_preprocessing/test_pipeline_builder.py -v
uv run pytest tests/test_preprocessing/test_label_strategy.py -v
uv run pytest tests/test_preprocessing/test_cv_selector.py -v
uv run pytest tests/test_preprocessing/test_transparency.py -v
uv run pytest tests/test_preprocessing/test_model_registry.py -v
uv run pytest tests/test_preprocessing/test_vae_wrapper.py -v
```
