# Debugging Log

트러블슈팅 히스토리. 발생한 문제와 해결 과정을 기록하여 같은 실수를 반복하지 않기 위한 문서.

---

## 2026-04-11 (오후): Phase 2 잔여 과제 4묶음 해결 (코드 독립 작업)

**배경**: 오전 세션에서 4대 결함(P0-1 / P0-2 / P1-1 / P1-2)을 해결한 뒤, 남은 14개
항목을 **데이터 재생성 없이 해결 가능한 묶음 4개**로 분할하여 처리. 재생성은 마지막
세션으로 분리 예정.

### 묶음 1 — 설명력 기반 (4개 / 35 tests 신규)

- **BiLSTM `get_attention_weights()` 노출** (`bilstm_wrapper.py`)
  - `AuditBiLSTM.forward()`가 이미 계산·저장하던 `_attn_weights`를 public API로 노출
  - `(n_windows, seq_len)` 반환, 소프트맥스 후 각 행 합 ≈ 1, 마스킹 위치는 0
- **FT-Transformer attention 추출** (`ft_model.py`, `ft_wrapper.py`)
  - `AuditFTTransformer.forward_with_attention()` 신규 — `nn.TransformerEncoder`의
    fast-path 최적화 우회하기 위해 각 layer의 `self_attn`을 수동 실행하여 weights 추출
  - `FTTransformerClassifier.get_attention_weights()` 신규 — `[CLS] → 피처` 토큰
    attention을 `(n_samples, n_features)` 로 반환
- **`drift_detector.py` + PSI 함수** (신규 파일)
  - `compute_psi_numeric` (가우시안 bin 기반, baseline_mean/std만으로 작동)
  - `compute_psi_categorical` (baseline top-N + `_OTHER_` 버킷)
  - `compute_drift_report` (`ModelMetadata` + `current_df` → `DriftReport`)
  - 임계값: `DRIFT_THRESHOLD_WARN=0.1`, `DRIFT_THRESHOLD_CRITICAL=0.25`
- **risk_level 분위수 전환** (`score_aggregator.py`, `config/settings.py`)
  - `classify_risk_level(mode="absolute"|"quantile", quantiles=...)` 모드 분기
  - `settings.risk_classification_mode` + `risk_quantile_high/medium/low`
  - score=0인 행은 rank가 높아도 NORMAL 보존 (실제 위험 없음)

### 묶음 2 — 파이프라인 관측성 (3개 / 11 tests)

- **탐지기 병렬 실행 헬퍼** (`pipeline.py`)
  - `_run_detectors_parallel(detectors, df, max_workers, progress_callback)`
  - ThreadPoolExecutor (pandas/numpy GIL 해제 활용 — ProcessPool은 DataFrame
    pickle 비용 과다)
  - `max_workers=None|1`이면 순차 (테스트/디버깅)
  - 결과 순서는 입력 detector 순서로 정렬 (병렬 완료 순 아님)
  - progress_callback 예외는 격리 — UI 오류가 탐지 막지 않음
- **탐지기별 프로파일링** (`pipeline.py`)
  - `collect_detection_profile(results)` — `metadata["elapsed"]` 수집
  - `format_detection_profile(profile)` — 마크다운 표 + `share%` 포맷
- **진행률 상세도** — 병렬 헬퍼의 `progress_callback`으로 자연스럽게 지원.
  Streamlit 측에서 `pipeline._detection_progress_callback = lambda c, t, n: ...` 주입
- 검증: 3개 × 0.1초 sleep 탐지기 → 순차 0.3초 vs 병렬 ≤ 0.15초 (2배 단축)

### 묶음 3 — 감사 증거 + 대시보드 UI (3개 / 23 tests)

- **`src/export/audit_evidence.py`** 신규
  - `RULE_LEGAL_BASIS` dict — 주요 룰 ID → 감사기준서/ISA/PCAOB 근거 매핑
  - `AuditEvidence` dataclass — document_id / score / risk / rules / top_features / narrative
  - `format_narrative(...)` — "전표 D001은 위험도 'High' (anomaly_score=0.850)로 분류...
    위반 룰: C01(기말 대규모) [ISA 240 §32]... VAE 재구성 오차 주요 기여 피처: amount(0.430)..."
  - `build_evidence_report(df, min_score)` — 파이프라인 결과 DataFrame 일괄 변환
- **`dashboard/components/shap_waterfall.py`** 확장
  - `render_vae_waterfall(row, top_k=3)` 신규 — P0-1의 `ML02_top_feature_{1..3}`
    컬럼 소비. SHAP과 달리 양수(MSE) 전용 Waterfall
- **`dashboard/components/drift_banner.py`** 신규
  - `render_drift_banner(current_df, model_metadatas, max_show=5)` — 상단 고정 배너
  - 4단계 상태 분류: critical(🚨) / warn(⚠️) / stable(✅) / skip(메타 없음)
  - 드리프트 상세 expander — DataFrame 표로 모델·PSI·스키마 불일치 목록

### 묶음 4 — 문서·선택 작업 (2개 / 5 tests)

- **FT-T Ablation Study 스크립트** (`tools/scripts/ft_ablation_study.py`)
  - `classify_conclusion(f1_with, f1_without, threshold=0.005)` → "keep"/"remove"/"inconclusive"
  - `write_report(result)` → 마크다운 리포트 (`tests/datasynth_quality_gate/results/`)
  - `--dry-run` 모드로 리포트 포맷 검증 가능. 실제 학습은 데이터 재생성 이후 단계
- **`docs/DECISION.md`에 D037·D038 추가**
  - D037: 모델 드리프트 재학습 정책 (PSI ≥ 0.25 자동 트리거 + 분기별 주기 재학습)
  - D038: FT-T 유지 + ablation 기반 판정 정책

### 종합

- 전체 스코프 내 누적 **234/234 테스트 통과** (오전 139개 + 오후 95개 신규)
- 14개 잔여 항목 중 13개 코드 완료. 나머지 1개는 "데이터 재생성 후 실제 FT-T ablation 실행"
- 묶음 간 파일 중복 없음 — 각 묶음 완료 시점에서 회귀 테스트 실행으로 원인 범위 최소화
- 다음 세션: DataSynth 재빌드 + 데이터 재생성 + 모델 재학습 1회 → §2 BiLSTM 효과 + ablation 실측

---

## 2026-04-11: Phase 2 ML 4대 결함 해결 (P0-1 / P0-2 / P1-1 / P1-2)

**배경**: `docs/phase2_ml_feasibility.md` 검토에서 Phase 2 ML 파이프라인의 4가지 구조적 결함이 확정됨.
감사 산업 납품 가능 상태 진입을 위한 선결 조건.

### P0-1: VAE 피처별 재구성 오차 분해

**증상**: `_score_vae`가 전체 MSE 스칼라만 반환 → 감사조서에 "왜 이상인지" 정량 증거 제시 불가.
주력 비지도 탐지기(VAE+IF)가 감사 실무에서 채택 불가능한 상태.

**해결**:
- `src/preprocessing/vae_wrapper.py`: `_compute_errors_per_feature(X) → (N, D)` 추가. 기존 `_compute_errors`는 행 평균으로 위임. public API `score_samples_per_feature` 추가.
- `src/detection/vae_detector.py`: `_score_vae_per_feature()` + `_build_topk_columns()` 추가. `detect()`가 `details`에 `ML02_top_feature_1~3` + `_contrib` 6개 컬럼을 첨부.
- Top-K 선택은 `np.argpartition`으로 O(N·D) (정렬 비용 없음).

**검증**: `test_vae_wrapper` 11개, `test_vae_detector` 28개 통과. `per_feature.mean(axis=1) ≈ score_samples` rtol 1e-5 일치.

### P0-2: GroupKFold 기반 OOF Stacking (User-Leakage 방어)

**증상**: `train_from_results`가 이미 학습된 base 모델의 predict 결과를 그대로 meta-learner에 주입 → ML_SUPERVISED/TRANSFORMER/SEQUENCE 3개 모델에 data leakage. 검증 F1이 허위 상승.

**핵심 결정**:
- **GroupKFold(n_splits=3, groups=user_ids)**: 단순 random split은 "User A는 일단 이상치"라는 사용자 ID memorization 과적합을 유발 → 한 사용자 전표는 한 fold에만 속하도록 보장. BiLSTM의 `GroupShuffleSplit` 패턴과 일관성 유지.
- **3-fold (MVP)**: 파이프라인에 무거운 딥러닝 모델(FT-T, BiLSTM) 포함. `settings.stacking_cv_folds`로 노출하여 안정화 후 5로 승격 가능.
- **joblib.Parallel(n_jobs=-1, backend="loky")**: fold 학습은 독립적 → 프로세스 격리 병렬 학습으로 wall-clock 1× 학습 시간에 근접.

**해결**:
- `src/detection/ensemble_detector.py`: `train_oof()` 신규 진입점. `_train_fold_worker()` 모듈 최상위 함수로 분리(loky pickle 호환). `_build_score_matrix_from_oof()` 헬퍼.
- leakage-prone 트랙만 fold마다 재학습. 룰 4개 + VAE는 `non_leakage_results`로 한 번만 실행.
- 기존 `train_from_results()`는 라벨 부족/리소스 부족 시 fallback 경로로 유지.
- `config/settings.py`: `stacking_cv_folds=3`, `stacking_oof_n_jobs=-1` 기본값 추가.

**검증**: `test_ensemble_detector` 24개 통과 (OOF 5개 신규). User-leakage 차단은 `set(users[train]) ∩ set(users[val]) == ∅` 직접 검증.

### P1-1: BiLSTM 시퀀스에 시간(시:분:초) 도입

**증상**: `posting_date`만으로 시퀀스 정렬 → 같은 날 수백 건 배치에서 ERP 입력 순서가 뒤섞여 "30분 내 3건 연속 입력" 같은 ISA 240 패턴 포착 불가.

**원인**:
- DataSynth `je_generator.rs`가 `created_at = posting_date.and_time(time).and_utc()`로 시간을 **이미 생성** 중이나, `csv_sink.rs` 헤더에 `posting_date`만 출력 → **시간 정보가 CSV에 미노출**.

**해결**:
- **Rust**: `tools/datasynth/crates/datasynth-output/src/csv_sink.rs` 헤더에 `posting_time` 컬럼 추가. `item.header.created_at.format("%H:%M:%S")`로 시:분:초만 출력 (하위호환: `posting_date`는 그대로 date).
- **Python**:
  - `src/db/schema.py`: `general_ledger`에 `posting_time TIME` + `GENERAL_LEDGER_COLUMNS` 추가.
  - `src/detection/sequence_detector.py`: `_build_timestamps()` 헬퍼 — `posting_date + to_timedelta(posting_time)` 조합으로 완전한 타임스탬프. 부재 시 기존 동작(date only) fallback.

**결정사항 (플랜 승인 시)**:
- stride 학습-추론 일치는 **채택 안 함** — stride는 윈도우 샘플링 간격일 뿐 입력 텐서 분포와 무관. 학습 stride=4(메모리·속도) / 추론 stride=1(전수 커버리지)는 의도된 설계.

**검증**: `cargo test -p datasynth-output --test csv_output_integration` 4/4 통과. `test_sequence_detector` 31개 통과 (TestPostingTime 4개 신규).

### P1-2: 모델 드리프트 메타데이터

**증상**: `ModelMetadata`에 학습 시점의 데이터 분포(mean/std/nunique)가 없음 → PSI 계산·재학습 트리거 불가. SOC 2 "AI 모델 거버넌스" 부적합.

**해결**:
- `src/preprocessing/model_registry.py`: `ModelMetadata`에 `training_data_stats`, `feature_schema_version`, `class_imbalance_ratio`, `n_train_samples` 4개 필드 추가. `list_models()`는 구버전 `registry.json`도 로드 가능 (default 값 채움).
- `src/preprocessing/data_stats.py` (신규): `compute_training_stats`, `compute_class_imbalance`, `compute_feature_schema_version` 유틸.
- 모든 detector (`supervised/transformer/sequence/vae/ensemble`)의 `train()`이 `self._train_stats` 보존 → `save_model()`이 registry에 전달.
- **버그 수정**: `ensemble_detector.save_model()`이 `feature_count`를 누락하던 이슈 수정 (`feature_count=len(STACKING_BASE_MODELS)`).

**본 작업 범위 외(다음 스프린트)**: `drift_detector.py` (PSI 계산), 대시보드 드리프트 배너, 재학습 정책 문서화.

**검증**: `test_model_registry` 14개 (DriftMetadata 4개 신규), `test_data_stats` 14개 (신규 모듈) 통과. 구버전 registry.json 하위호환 로드 검증 포함.

### 종합

- 본 스프린트로 Phase 2 완료 선언의 가장 큰 장애물 4개가 제거됨.
- 스코프 내 단위 테스트 139개(신규 27개) 모두 통과.
- 본 브랜치(feature/wu14)의 기존 선행 실패(pipeline test_results_count stale, schema_yaml_sync, test_feature/e2e_datasynth)는 내 변경 스코프 밖 — `git stash` 검증으로 사전 존재 확인.

---

## 2026-04-10: DataSynth 한국 부가세(Tax) 전면 구현 + QG3 품질 개선

**증상**:
1. `journal_entries.csv`의 `tax_code`/`tax_amount` 컬럼이 전부 NaN (Phase 20 스킵)
2. QG3 전수검사 후 LLM 판정: 12월 34.9% 편중, 주말 10.1%, 월요일 27%, 세금계산서 매칭 81.3%, VAT-ZERO-KR 0건, R2R 프로세스에 tax_code 편중

**원인**:
- `config/datasynth.yaml`에 `tax:` 섹션 없음 → `TaxConfig.enabled` 기본값 `false` → Phase 20 전체 스킵
- `tax_code_generator.rs` `COUNTRY_RATES`에 KR 미포함 (DE/GB/FR 등 12개국만)
- Phase 20의 `TaxLine`이 `JournalEntryLine`에 **역매핑되는 코드가 전혀 없음** (document_id 매칭만으로 하면 1:N 중복 함정)
- `je_generator.rs`의 `supporting_doc_type` 로직이 O2C → "세금계산서"를 하드코딩해서, 매출채권 회수/선수금 전표(Revenue 라인 없음)에도 세금계산서 부착
- `period_end.year_end.peak_multiplier: 18.0` 과도 설정 → 12월 전표 폭증
- `seasonality.weekend_activity: 1.0` (평일과 동등) → 주말 10% 초과

**해결**:

### Rust 코드 수정
1. **`tax_code_generator.rs` COUNTRY_RATES에 KR 추가**: `("KR", "South Korea", "vat", "0.10", None)`
2. **`enhanced_orchestrator.rs` Phase 20b `backfill_je_tax_codes` 신규 함수** (핵심):
   - **1:N 중복 방지**: 전표당 첫 번째 Revenue/Expense base line에만 `tax_code`/`tax_amount` 부여 (AR/AP/부가세예수금 라인 NaN)
   - **business_process 필터**: O2C/P2P + `supporting_doc_type='세금계산서'` 전표만 대상 (R2R/H2R/A2R/TRE 제외)
   - **면세 판정**: `AccountSubType::InterestIncome/InterestExpense/DividendIncome/Investments` → VAT-EX-KR
   - **영세율**: O2C 매출 전표 중 `document_id` FNV 해시 기반 deterministic 15%를 VAT-ZERO-KR로 분류 (수출 모사)
3. **`je_generator.rs` `supporting_doc_type` 로직 수정** (근본 해결):
   - O2C 전표는 **실제 Revenue(4xxx) 라인이 있을 때만** "세금계산서"
   - P2P 전표는 Expense(5xxx/6xxx) 라인이 있을 때만 "세금계산서"
   - 매출채권 회수/선수금 전표는 "기타증빙"으로 분기
4. **`csv_sink.rs`**: tax_code/tax_amount 컬럼 헤더/행 추가 (CLI는 output_writer 경로라 실효는 없지만 일관성 유지)

### YAML 설정 수정 (`config/datasynth.yaml`)
- `tax:` 섹션 신규 추가: KR VAT 10%, 면세 4개 카테고리(financial_services/insurance/healthcare/education), 법인세 실효세율 24.2%
- `period_end.year_end.peak_multiplier: 18.0 → 4.0`, `start_day: -25 → -15`
- `seasonality.weekend_activity: 1.0 → 0.2`, `year_end_multiplier: 6.0 → 3.0`
- `seasonality.monday_multiplier: 1.3 → 1.1`
- `temporal_patterns.intraday`에 `deep_night(00-03) 0.005` 세그먼트 추가, `late_night 0.02 → 0.005`

**검증 (1,192,404 라인 / 319,061 전표 기준)**:

| 지표 | 수정 전 | 수정 후 |
|------|--------|--------|
| tax_code 채움(Revenue/Expense base line) | 0 | 109,078 |
| 과세 10% 정확도 | — | 99,697/99,697 = 100.00% |
| 1:N 중복 (전표당 최대 tax_code 수) | — | 1 |
| VAT-STD-KR / VAT-EX-KR / VAT-ZERO-KR | 0/0/0 | 99,697 / 612 / 8,769 |
| 세금계산서 전표 tax_code 매칭률 | 81.3% | 96.48% |
| R2R 프로세스 tax_code 부여 | 75,276건 | 0건 |
| 12월 전표 비중 | 34.9% | 12.4% |
| 주말 전표 비중 | 10.1% | 2.7% |
| 월요일 전표 비중 | 27.0% | 24.0% |
| 심야(22~06) 비중 | 2.1% | 1.01% |
| 03시 단독 피크 | 1,475건 | 190건 |
| 차대변 불균형 | 0.125% | 0.085% |

**교훈**:
1. **1:N 역매핑 함정**: 한 전표(document_id)에 여러 라인이 있을 때, `document_id`만 키로 데이터를 복사하면 `groupby.sum()` 시 N배 중복 계산된다. 반드시 **base line(Revenue/Expense)에만 단일 부여**하고 나머지는 NaN 유지. `COA.get_account(gl).account_type`으로 필터.
2. **VAT 대상 판별은 계정만으로 부족**: `AccountType::Revenue/Expense`는 필요조건이지만 충분조건 아님. R2R(결산조정), H2R(급여), A2R(자산취득), TRE(차입금이자)에도 Revenue/Expense 라인이 있지만 부가세와 무관. `business_process` + `supporting_doc_type` 필터 필수.
3. **"데이터에 맞추지 말고 데이터를 올바르게 생성"**: 세금계산서 매칭 81% 문제는 backfill 로직이 아니라 je_generator가 회수 전표에도 "세금계산서"를 붙이는 하드코딩 때문. 탐지 쪽을 고치면 fitting, 생성 쪽을 고치면 근본 해결.
4. **config 중복 설정 주의**: `seasonality.year_end_multiplier: 6.0`과 `temporal_patterns.period_end.year_end.peak_multiplier: 18.0`이 동시에 존재. 실제 효력은 후자. 분포 편중 디버깅 시 두 경로 모두 확인.
5. **QG3 extract_profile 활용**: 규칙/임계값 없이 전수 집계 → LLM 정성/정량 판정 흐름이 현실성 검증에 효과적. 고정된 체크리스트로 못 잡는 distribution skew를 사람이 읽으면 한 번에 보임.

---

## 작성 가이드

```
## YYYY-MM-DD: 문제 제목

**증상**: 무엇이 잘못되었는지
**원인**: 왜 발생했는지
**해결**: 어떻게 고쳤는지
**교훈**: 다음에 주의할 점
```

---

## 2026-03-20: charset_normalizer가 latin-1을 ascii로 오탐

**증상**: bpi2019(527MB, latin-1) 파일 읽기 시 `'ascii' codec can't decode byte 0x96 in position 249785`

**원인**: `text_reader._detect_encoding()`이 64KB만 샘플링. bpi2019의 latin-1 특수문자(0x96)가 249KB 지점에 첫 등장 → 샘플 범위 밖 → charset_normalizer가 ascii로 오탐 → `pd.read_csv(encoding="ascii")`에서 에러

**해결**: `_detect_encoding()`에서 ascii 감지 시 latin-1로 폴백 (1줄 추가). ascii ⊂ latin-1 이므로 부작용 없음.

**교훈**: 샘플 기반 감지는 대용량 파일에서 오탐 가능. "샘플 크기 확대"는 땜질 — 타입 시스템의 포함관계(ascii ⊂ latin-1)를 활용하는 것이 근본 해결.

---

## 2026-03-20: 헤더 탐지 키워드 80% 의존 → 구조적 신호로 전환

**증상**: financial-anomaly(Amount, Timestamp), general-ledger(Date, EntryNo)에서 헤더 탐지 실패 (confidence=0.20). keywords.yaml에 미등록된 범용 영문 컬럼명.

**원인**: 스코어 공식이 `KeywordScore × 0.80 + StringRatio × 0.20` — 키워드 없으면 최대 0.20

**해결**: 5개 구조 신호 가중합으로 전환. TypeDiversity(0.35) + Uniqueness(0.25) + NullDensity(0.15) + Keyword(0.15) + StringRatio(0.10). 키워드 없어도 구조적으로 헤더/데이터 행을 구분.

**교훈**: "키워드를 더 등록"하는 땜질 대신 "데이터 자체의 구조적 신호"를 활용하면 미지의 데이터셋에도 범용 동작.

---

## 2026-03-20: fuzzy 매핑 타입 비호환 오매핑 (drcrk→debit_amount)

**증상**: sap-merged에서 drcrk(차대변 indicator, 'S'/'H' 문자열)가 debit_amount(float)에 매핑 → 캐스팅 100% NaN

**원인**: rapidfuzz가 'drcrk'와 'debit' 문자열 유사도만 비교. 실제 데이터 타입(str vs float)을 무시.

**해결**: 이중 방어 — (1) dc_indicator 표준 컬럼 등록으로 정확 매칭 우선 (2) `_type_compat.py`에서 fuzzy 후보의 소스 타입↔스키마 타입 비교, 비호환 시 스코어 0

**교훈**: 문자열 유사도 매칭은 반드시 타입 검증과 병행해야 한다. "이름이 비슷해도 타입이 다르면 틀린 매핑".

---

## 2026-03-22: engine.py rules 전달 형식 불일치 → pattern 피처 전부 False

### 증상

Detection E2E 테스트(DataSynth 1M행)에서 B01(매출 이상 변동), B08(수기 전표) 등이 0건.
`is_revenue_account`, `is_manual_je`, `is_intercompany`, `is_suspense_account` 피처가 전부 False.

### 원인

`audit_rules.yaml`의 YAML 구조와 피처 엔진 내부의 기대 형식 간 **깊이(depth) 불일치**.

```
audit_rules.yaml:              get_audit_rules() 반환값:
──────────────                 ────────────────────────
patterns:                      {"patterns": {
  revenue_account_prefixes:        "revenue_account_prefixes": ["4"],
    - "4"                          "manual_source_codes": ["SA", ...],
  manual_source_codes:             ...
    - "SA"                     }}
```

호출 체인에서 문제 발생 지점:

```
경로 A — pattern_features.py 직접 호출 (정상):
  add_all_pattern_features(df, rules=None)
  → rules = get_audit_rules()["patterns"]     ← 자동으로 ["patterns"] 접근
  → rules.get("revenue_account_prefixes")     ← ["4"] 반환

경로 B — engine.py 경유 (버그):
  generate_all_features(df, rules=get_audit_rules())
  → engine.py가 {"patterns": {...}} 을 그대로 pattern_features에 전달
  → rules.get("revenue_account_prefixes")     ← 최상위에 해당 키 없음
  → 빈 리스트 [] fallback → 피처 전부 False → 에러 없이 조용히 실패
```

`pattern_features.py`는 `rules=None`일 때만 자동으로 `["patterns"]`를 꺼낸다.
`engine.py`의 docstring에 "patterns 수준 dict를 넘기세요"라고 적혀있지만,
중첩 dict가 들어와도 **에러 없이 빈 리스트로 fallback**하여 버그를 감춘다.

### 영향 범위

`generate_all_features(df, rules=get_audit_rules())` 형태로 호출하는 코드에서
pattern 피처 4개가 전부 False (first_digit은 rules 미사용이라 영향 없음):

```
is_revenue_account  → B01 매출 이상 변동 미탐지
is_manual_je        → B08 수기 전표 미탐지
is_intercompany     → B10 관계사 순환거래 미탐지
is_suspense_account → C06 가계정 키워드 미탐지
```

기존 feature 단위 테스트는 `rules=None` 또는 평탄 dict로 호출하여 이 버그를 미포착.

### 해결

**`engine.py`에서 방어 처리** — 중첩 dict가 들어오면 자동으로 `["patterns"]`를 꺼냄:

```python
# src/feature/engine.py generate_all_features() 시작 부분 (L116~119)
if rules is not None and "patterns" in rules:
    rules = rules["patterns"]
```

적용 후 E2E 재실행 결과: B01 0→1,069건, B08 0→2건 정상 탐지.

### 회귀 테스트

```bash
uv run pytest tests/test_feature/ tests/test_detection/ -v
```

### 교훈

함수가 dict를 받을 때 **키 부재를 빈 리스트로 fallback하면 버그가 숨는다**.
"조용한 실패(silent failure)"는 즉시 에러보다 디버깅이 훨씬 어렵다.
방어 방법: (1) 공개 API에서 입력 형식 정규화 (2) fallback 시 warning 로그 추가.

---

## 2026-03-26: 브랜치 전략 단순화 시 벌크 커밋 발생

**증상**: `60b9603` 커밋에 116파일(11,198줄 추가)이 단일 커밋으로 들어감. "1커밋 = 1논리적 변경" 원칙 위배.

**원인**: Phase별 feature 브랜치 5개(feat/1a-ingest, 1b-detection, 2-ml, 3-llm, backup) 운용 중 작업이 브랜치 간 왔다갔다하면서 feat/1a-ingest에 미커밋 변경 91파일이 누적. develop+main 2-branch 체제로 전환하기 위해 브랜치 머지 전 안전 확보 목적으로 일괄 커밋.

**해결**: 벌크 커밋 그대로 유지. 머지 시 충돌은 ours(최신본) 기준으로 해결. 파일 손실 없음 확인 완료. 이후 feature 브랜치 전부 삭제하고 develop+main 2-branch 체제로 전환.

**교훈**: 1인 프로젝트에서 phase별 feature 브랜치는 오버엔지니어링. 작업이 phase 간 교차되면 브랜치 전환 시 미커밋 변경 분실 위험이 높아진다. 단순한 브랜치 전략(develop+main)이 안전하다.

---

### Phase 1c WU1: 대시보드 기반 컴포넌트 구현 시 교훈 (2026-03-27)

**1. tempfile 디스크 I/O 불필요**
- 증상: `st.file_uploader` → tempfile 저장 → `pipeline.run(path)` 방식은 디스크 I/O + 임시 파일 관리 부담
- 해결: UploadedFile은 file-like object이므로 `pd.read_csv(uploaded)` 직접 읽기 + `run_from_dataframe()` 호출
- 교훈: Streamlit UploadedFile의 인터페이스를 먼저 확인할 것

**2. flagged_rules CSV 필터 성능**
- 증상: `.apply(lambda s: set(s.split(",")) & target)` 방식은 1M행에서 Python 루프 오버헤드
- 해결: `str.contains("|".join(codes), regex=True)` 벡터화 매칭으로 ~10× 성능 개선
- 교훈: pandas에서 행 단위 `.apply()`는 최후 수단. 벡터화 연산 우선 검토

**3. 산점도 이상치 탈락**
- 증상: `df.sample(5000)` 단순 랜덤 샘플링 시 High/Medium 이상치가 무작위 탈락
- 해결: `_priority_sample()` — High/Medium 전수 보존, Normal 위주 다운샘플링
- 교훈: 감사 데이터 시각화에서 이상치는 핵심 관심 대상. 샘플링 시 도메인 우선순위 반영 필수

---

### Phase 1c WU7: 인제스트 오케스트레이터 + 미해결 이슈 UI 반영 (2026-03-28)

**1. ModuleNotFoundError: No module named 'dashboard'**
- 증상: `streamlit run dashboard/app.py` 실행 시 dashboard 패키지 import 실패
- 원인: Streamlit이 실행 파일의 상위 디렉토리를 sys.path에 자동 추가하지 않음
- 해결: `sys.path` 에 프로젝트 루트 경로 명시 추가
- 교훈: Streamlit 앱을 서브디렉토리에 배치할 경우 sys.path 설정 필수

**2. AxiosError: Network Error (Streamlit 대용량 업로드)**
- 증상: 50MB 이상 파일 업로드 시 브라우저에서 AxiosError 발생, 서버 응답 없음
- 원인: Streamlit 기본 `maxMessageSize`(200MB)가 server↔browser 통신 제한. 대용량 DataFrame 직렬화 시 초과
- 해결: `.streamlit/config.toml`에 `maxUploadSize=1024`, `maxMessageSize=1024` 설정
- 교훈: `maxUploadSize`만으로는 부족. `maxMessageSize`도 함께 올려야 대용량 파일 파이프라인이 정상 동작

**3. utf-8 codec error (인코딩 폴백)**
- 증상: CP949/EUC-KR 인코딩 파일 업로드 시 `UnicodeDecodeError: 'utf-8' codec can't decode`
- 원인: 인코딩 자동 감지 실패 시 기본 utf-8로 읽기 시도
- 해결: UI-1 인코딩 드롭다운 구현 — confidence < 0.7 시 사용자에게 인코딩 선택 selectbox 노출 + 선택 값으로 파일 재읽기
- 교훈: 한국 ERP 덤프는 CP949/EUC-KR 비율이 높으므로 인코딩 수동 오버라이드는 필수 UI

**4. 탐색기 탭 브라우저 멈춤 (대용량 DataFrame)**
- 증상: 1M행 DataFrame을 AgGrid에 직접 전달 시 브라우저 탭 무응답
- 원인: AgGrid가 전체 행을 브라우저 메모리에 로드 시도
- 해결: `explorer_grid.py`에서 10K행 제한 적용 (필터 후 상위 10,000건만 표시)
- 교훈: 브라우저 기반 그리드 컴포넌트는 10K행 이하로 제한해야 안정적 렌더링 가능

---

## 2026-04-02: DataSynth 재구성 — 5회 연속 빌드 미반영 사고

### 증상

Run#8~12 (5회) 품질 게이트에서 동일 FAIL 7건이 반복. Rust 코드를 수정해도 결과가 변하지 않음.

### 원인 (2계층)

**1계층 — 바이너리 미갱신 (핵심)**

`datasynth-runtime` 크레이트에 기존 컴파일 에러(immutable borrow) 2건이 존재.
- `enhanced_orchestrator.rs:1780` — `let anomaly_labels` (mut 필요)
- `enhanced_orchestrator.rs:1679` — `let intercompany` (mut 필요)

`cargo check -p datasynth-generators`는 generators 크레이트만 체크하여 PASS.
하지만 `cargo build --release`는 전체 워크스페이스를 빌드하는데, runtime 크레이트 에러로 **바이너리 생성 실패**. cargo가 "Finished" 메시지를 출력하지만 실제로는 워크스페이스 root만 빌드하고 cli 바이너리는 건너뜀. 결과적으로 **2026-03-31 18:33의 old 바이너리**로 5회 재생성.

`cargo build --release -p datasynth-cli`를 명시적으로 호출해야 에러가 노출됨.

**2계층 — 코드 결함 (빌드 미반영으로 검증 불가능)**

| FAIL | 근본 원인 | 수정 |
|------|----------|------|
| T3-04/05/12/13 | `Employee::new()` 기본 persona=JuniorAccountant, EmployeeGenerator가 job_level→persona 매핑 안 함 | `employee_generator.rs`에 persona 매핑 추가 |
| T3-10 | `with_employee_pool()` 후 `user_process_map` 미갱신 (old generic IDs) | `rebuild_user_process_map()` 메서드 추가 |
| T2-02 | anomaly injection 후 debit/credit 동시 양수 라인 발생 | netoff 로직 추가 |

### 해결

1. `enhanced_orchestrator.rs`: `let` → `let mut` 2건
2. `cargo clean --release` + `cargo build --release -p datasynth-cli` (전체 리빌드)
3. 바이너리 타임스탬프 **4월 2일 09:17** 확인 후 재생성

### 교훈

1. **`cargo build --release`만으로는 바이너리 갱신을 보장할 수 없다.** 워크스페이스에서 특정 크레이트가 에러면 해당 바이너리만 skip되고 "Finished" 출력. `-p datasynth-cli`를 명시하면 에러가 즉시 드러남.
2. **재생성 전 반드시 `ls -la target/release/datasynth-data*` 타임스탬프 확인.** 현재 시각과 일치하지 않으면 빌드 실패.
3. **`cargo check -p <crate>`는 의존 크레이트를 검증하지 않는다.** full rebuild로만 전체 의존성 에러를 잡을 수 있다.
4. **RNG fitting 금지.** RNG 시퀀스를 맞추기 위해 dummy 호출을 소비하는 것은 test-fitting과 같다. 근본 원인(employee persona 미설정)을 고쳐야 한다.
5. **gl_rng 분리 시도는 실패.** 별도 RNG 스트림을 추가해도 메인 rng에서 제거된 호출만큼 시퀀스가 밀린다. 근본 해결은 employee assignment 자체의 견고성.

---

## 2026-04-02: Employee.persona 미설정 — 전체 Employee가 JuniorAccountant

### 증상

품질 게이트 T3-05 (employee company 불일치 729K건), T3-13 (무권한 승인 7,123건) 등 5건 FAIL.

### 원인

`Employee::new()` (user.rs:775)에서 `persona: UserPersona::JuniorAccountant`로 기본값 설정.
`EmployeeGenerator.generate_employee()` (employee_generator.rs:263)에서 `employee.job_level = job_level`은 설정하지만 `employee.persona`는 갱신하지 않음.

결과: 204명 전원이 JuniorAccountant persona → `select_user()`가 Manager/Controller 검색 시 매칭 실패 → generic fallback ID 생성 → employees.json과 불일치.

### 해결

`employee_generator.rs`에서 `job_level` 설정 직후 persona 동기화:
```rust
employee.persona = match job_level {
    JobLevel::Staff => UserPersona::JuniorAccountant,
    JobLevel::Senior | JobLevel::Lead | JobLevel::Supervisor => UserPersona::SeniorAccountant,
    JobLevel::Manager | JobLevel::Director => UserPersona::Manager,
    JobLevel::VicePresident | JobLevel::Executive => UserPersona::Controller,
};
```

### 교훈

모델 기본값이 "안전한 기본값"이 아닐 수 있다. `Employee::new()`의 `JuniorAccountant` 기본값은 명시적 설정 없이 사용하면 전체 데이터를 오염시킨다.

---

## 2026-03-03 ~ 04-02: DataSynth T3 교차검증 1달 디버깅 전체 기록 (Run#1→#20)

### 문제 정의

DataSynth가 생성하는 journal_entries.csv의 `created_by`/`approved_by`가 employees.json의 직원 데이터와 불일치. T3 교차검증 6개 항목이 FAIL 상태로 20회 재생성에도 해결되지 않음.

### 왜 1달간 실패했는가 — 실패 패턴 분석

**Phase 1 (Run#1~#7): 증상 수준 패치 반복**

Employee와 User가 별도 경로로 생성되는 구조적 문제를 인식하지 못하고, 개별 FAIL 항목에 대한 증상 수준 패치를 반복.

- `gl_rng` 분리 → RNG 시퀀스 변경 → 다른 FAIL 항목 발생
- `type_roll` dummy consumption → 기존 RNG 시퀀스 보존 시도 → test fitting으로 판정, 롤백
- 부분 수정 5회 연속 동일 결과 → 바이너리 미갱신 발견 (아래 참조)

**Phase 2 (Run#8~#12): 바이너리 미갱신 5회 낭비**

`cargo build --release`가 workspace 루트에서 성공 메시지를 출력했지만, `datasynth-runtime` crate에 컴파일 에러(`let` vs `let mut`)가 있어 CLI 바이너리가 재생성되지 않음. 3월 31일 빌드의 구 바이너리가 계속 사용됨.

```
발견 방법: ls -la target/release/datasynth-data.exe → 타임스탬프가 3일 전
해결 방법: cargo clean --release && cargo build --release -p datasynth-cli
교훈:      빌드 후 반드시 바이너리 타임스탬프 확인
```

**Phase 3 (Run#13~#14): Employee/User 이원화 인식, 부분 통합 시도**

Employee와 User가 별도 생성되는 구조를 인식하고 EmployeeGenerator에 AutomatedSystem 생성을 추가. T3-03 (FK orphan) 33→0건으로 개선되었으나 T3-04/05는 악화.

악화 원인을 특정하지 못한 채 부분 패치 반복.

**Phase 4 (Run#15): 통합 재설계 완료, 그러나 숨은 파괴 코드 미발견**

UserGenerator를 JE 생성 경로에서 완전 제거. EmployeeGenerator가 유일한 사용자 소스. T3-03 해소(0건). 그러나 T3-04/05는 오히려 악화 (826K→1,075K).

이 시점에서 `select_user()`, `UserPool::from_employees()`, `to_user()` 코드를 모두 검증했고 전부 정상이었음. **문제는 생성 로직이 아니라 생성 후 후처리에 있었음.**

### 왜 Run#20에서 성공했는가 — 근본 원인 3개

**근본 원인 1: employee user_id 파괴적 덮어쓰기 (T3-04/05의 97% 원인)**

`enhanced_orchestrator.rs:1728-1746`에서 JE 생성 후 모든 employee의 user_id를 JE의 created_by 값으로 라운드 로빈 덮어쓰기. 이전 UserGenerator 시절 T3-03 해결을 위한 덧대기 패치. 통합 재설계 후에는 불필요하면서 persona/company/approval 정합성을 전면 파괴.

```rust
// 삭제된 코드 — 268명의 employee user_id를 JE created_by의 알파벳 순으로 강제 매핑
let mut je_user_vec: Vec<String> = je_users.into_iter().collect();
je_user_vec.sort();
for (i, emp) in self.master_data.employees.iter_mut().enumerate() {
    emp.user_id = je_user_vec[i % je_user_vec.len()].clone();
    // persona, company_code, approval_limit는 그대로 → 전면 불일치
}
```

왜 발견이 늦었는가: `select_user()` → `header.user_persona` 경로만 추적. employee가 employees.json에 직렬화되기 전에 user_id가 변경되는 후처리 경로는 검색 범위 밖.

**근본 원인 2: T3-12 post-processing의 user_persona 미갱신 (637K건)**

approval_limit 초과 시 `created_by`를 한도 충분한 직원으로 교체하면서 `user_persona`는 업데이트하지 않음. automated 직원(limit=0)의 모든 전표가 manager로 교체되면서 persona 불일치.

연쇄 구조: automated employee의 `approval_limit=0` (Employee::new 기본값) → 금액 1원 이상이면 전부 한도 초과 → manager로 교체 → persona는 여전히 `automated_system`.

**근본 원인 3: 다수의 부수 버그**

| 버그                                        | 영향 범위       | FAIL 항목     |
|---------------------------------------------|-----------------|---------------|
| `generate_employee_with_level()` persona 미갱신 | 부서장 15명      | T3-04         |
| `generate_automated_employee()` limit=0     | automated 64명   | T3-12         |
| IC/subledger 생성기 `created_by` 하드코딩   | 1,003건          | T3-03         |
| SoD 주입 시 can_approve_je 미검증           | 6건              | T3-13         |

### 수정 내역

**근본 수정 (데이터 생성 자체를 올바르게):**

| 파일                       | 수정                                             |
|----------------------------|--------------------------------------------------|
| `enhanced_orchestrator.rs` | user_id 덮어쓰기 코드 전면 삭제                  |
| `employee_generator.rs`    | `generate_employee_with_level()` persona 재매핑   |
| `employee_generator.rs`    | automated employee `approval_limit = ~1T`         |
| `je_generator.rs`          | SoD PreparerApprover: `can_approve_je` 검증 추가  |

**후처리 보정 (fitting — RC 재설계 시 근본 수정 예정):**

| 파일                       | 수정                                             | 근본 수정 방안                           |
|----------------------------|--------------------------------------------------|------------------------------------------|
| `enhanced_orchestrator.rs` | orphan created_by → employee 교체                 | IC/subledger 생성기에 employee pool 전달 |
| `enhanced_orchestrator.rs` | T3-12 limit 초과 시 created_by+persona 동시 교체  | `select_user()`에서 금액 기반 직원 선택  |
| `enhanced_orchestrator.rs` | T3-13 무권한 approved_by 교체                     | anomaly injector SoD 검증 강화           |

### Run별 추이

```
Run  T3-03  T3-04      T3-05     T3-10  T3-12   T3-13   총 FAIL
#8   33     826K       563K      3      1,670   18,730  6
#14  33     826K       563K      3      1,670   18,730  6
#15  0      1,075K     814K      3      25,649  28,070  5 (T3-03 해결)
#17  2      0          0         0      72,511  2,433   3 (user_id 덮어쓰기 삭제)
#18  0      0          0         0      483     3       2 (automated limit, orphan 교체)
#19  0      0          0         0      1       0       1 (anomaly 스킵 조건 수정)
#20  0      0          0         0      0       0       0 (automated limit 상향)
```

### 교훈

1. **생성 후 후처리를 반드시 검색하라.** 생성 로직이 정상이어도 orchestrator의 post-processing이 데이터를 변형할 수 있다. `grep "iter_mut\|created_by\s*="` 같은 전체 검색이 필요.
2. **덧대기 패치는 다음 수정의 근본 원인이 된다.** user_id 강제 동기화(T3-03 해결)가 T3-04/05/12/13의 근본 원인으로 전이. 일시적 해결이 구조적 문제를 은폐.
3. **필드 A 변경 시 연관 필드 B를 반드시 갱신하라.** `created_by` 교체 시 `user_persona`를 누락하면 교차검증 전면 FAIL.
4. **바이너리 타임스탬프를 확인하라.** Rust workspace에서 의존 crate의 컴파일 에러가 있어도 `cargo build`가 성공 메시지를 출력할 수 있다. 5회 낭비의 원인.
5. **anomaly/fraud 제외 조건은 품질 게이트 기준과 일치시켜라.** `is_anomaly` 일괄 스킵이 아니라 `ExceededApprovalLimit` 등 특정 타입만 스킵.

---

## 2026-04-02: DataSynth v21 확정 — E2E 라벨 검증 21회 반복 수렴

### 결과

| 항목 | 값 |
|------|---|
| DataSynth 행수 | 1,106,056 |
| 라벨 건수 | 7,827 |
| Phase 1 Recall | 91.4% (2,408 / 2,636) |
| 전체 Recall | 92.0% (7,197 / 7,827) |
| 100% Recall 룰 | 10개 |
| B07 flagged | 1.9% |
| Normal 등급 | 85.2% |
| 코드 버그 의심 | 0건 |

### 확정 사유

- v13~v21 (9회) Phase 1 Recall 91~100% 범위에서 안정 수렴
- 잔여 FN 19건은 DataSynth 난수 시드에 따라 진동하는 소수 라벨 룰 (B06 1건, B07 3건 등)
- 구조적 한계 4룰(B05/B10/C09/C07)의 FN ~1,822건은 Phase 2 ML 영역
- B07 과탐 해소(99.91% → 1.9%), 위험등급 정상화(Normal 0.1% → 85.2%) 달성
- 추가 DataSynth 수정의 비용 대비 효익이 미미 (Recall +0.7%p 상한)

### 상세 리포트

- [tests/phase1_rulebase/test-results/e2e-label-validation.md](../tests/phase1_rulebase/test-results/e2e-label-validation.md)
- [tests/phase1_rulebase/test-results/rule-label-gap-analysis.md](../tests/phase1_rulebase/test-results/rule-label-gap-analysis.md)

---

## 2026-04-03: DataSynth Stage 2-3 다기간 전환 (12개월 → 36개월)

### 변경 내용

`period_months: 12` → `36`으로 확장하여 2022~2024년 3개년 데이터 생성.

### 치명적 장벽: Rust CLI Safety Limit

**증상**: `config/datasynth.yaml`에 `period_months: 36`을 설정해도 1년 데이터만 생성됨.

**원인**: `tools/datasynth/crates/datasynth-cli/src/main.rs:2219-2227`의 `apply_safety_limits` 함수가 `period_months > 12`이면 12로 강제 절삭. `cargo build --release`의 "Finished" 메시지만 보고 빌드 성공으로 판단하면, 이 safety limit에 의해 YAML 변경이 무시됨.

**해결**: `apply_safety_limits`에서 period_months 절삭 코드를 제거. `validation.rs`의 `MAX_PERIOD_MONTHS = 120`이 이미 상한을 보장하므로 CLI의 12개월 제한은 중복 안전장치.

### T3-12 FAIL 1건: BenfordViolation 금액 극단값

**증상**: 품질 게이트 T3-12 `approval_limit` FAIL 1건.

**원인**: BenfordViolation anomaly가 첫째 자릿수 9를 만들기 위해 `9.1×10^18` 극단값을 주입. 이 금액이 automated_system의 approval_limit(1조원)을 초과하지만, `ExceededApprovalLimit` 라벨이 없어 T3-12에서 미제외.

**해결**: T3-12 제외 목록에 `BenfordViolation`을 추가 (금액 변형 anomaly).

### 결과

| 항목            | 12개월 (이전) | 36개월 (이후) |
|-----------------|---------------|---------------|
| 총 행수         | 1,105,174     | 3,241,675     |
| fiscal_year     | 2022          | 2022~2024     |
| posting_date    | 01-01~12-31   | 2022-01-01~2024-12-31 |
| 라벨            | 7,827         | 23,067        |
| 품질 게이트     | WARNING       | WARNING       |
| FAIL            | 0             | 0             |

### 교훈

1. **Rust CLI의 safety limit은 config validation과 별개로 존재할 수 있다.** `validation.rs`의 MAX=120과 CLI의 MAX=12가 이중으로 존재. config만 변경해도 안 되는 경우 CLI 코드를 확인.
2. **anomaly injection이 금액을 극단값으로 변형하면 교차검증 체크에 부수 효과가 생긴다.** 금액 변형 anomaly(BenfordViolation)는 approval_limit 체크에서도 제외해야 함.
3. **품질 게이트의 하드코딩된 연도/날짜를 config 기반 동적 계산으로 전환하면 다기간 확장에 자동 대응.** expectations.py에 파생 필드(valid_fiscal_years, end_date 등)를 추가하여 모든 체크가 동적으로 기간을 참조.

---

## 2026-04-04: document_number 순차 채번 구현

### 문제

`document_number` 필드가 항상 None으로 출력됨. Phase 2 전표번호 갭 탐지(§3.3.10)의 선행 의존.

### 해결

`enhanced_orchestrator.rs`에 Phase 9a를 추가하여 모든 전표 생성/수정 완료 후 `(company_code, fiscal_year, document_type)`별 순차 채번 + 확률적 갭 삽입 구현.

### 삽질 과정

1. **기존 "Stage 2-2" 코드가 덮어쓰기**: 라인 2714-2727에 `(company, year)`만으로 단순 순차 할당하는 기존 코드가 존재. Phase 9a에서 정상 채번해도 마지막에 덮어써서 document_type별 분리가 무효화됨. → 기존 코드 제거.
2. **기말 갭 비율이 비기말보다 낮은 버그**: year_end에서 `year_end_rate`만 적용하고 `base_rate`를 누락. → `base_rate + year_end_rate`로 수정.
3. **Quality gate T2-35 오판**: 기존 체크가 `(company, year)`만으로 중복 검사하여 document_type별 독립 채번을 중복으로 잡음. → `document_type` 추가.

### 교훈

1. **`document_number =`로 grep하여 덮어쓰기 코드를 반드시 검색할 것.** 같은 필드를 여러 곳에서 할당하면 마지막 할당이 이김.
2. **갭 비율 설계 시 기본률과 추가률을 합산할 것.** exclusive가 아닌 additive로 설계해야 "기말 > 비기말" 보장.
3. **Quality gate 체크를 데이터 스키마 변경에 맞춰 업데이트할 것.** 채번 기준이 바뀌면 검증 쿼리도 같이 바꿔야 함.
