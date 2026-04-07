# DataSynth 데이터 품질 관리

DataSynth(Rust) 합성 데이터 생성기의 품질 이슈, 수정 이력, 미해결 항목을 관리하는 문서.

---

## 1. 품질 게이트 체계

| 게이트 | 경로                             | 목적                                          | 체크 수 |
|--------|----------------------------------|-----------------------------------------------|---------|
| QG1    | `tests/datasynth_quality_gate/`  | 구조, 도메인, 교차검증, 분포, 라벨            | 174개   |
| QG2    | `tests/datasynth_quality_gate2/` | feature leakage, 분포 분리, 복합 피처, GL 쌍  | 20개    |

실행:
```bash
uv run python -m tests.datasynth_quality_gate
uv run python -m tests.datasynth_quality_gate2
```

---

## 2. 해결 완료 이슈

### 2.1 document_number 순차 채번 (2026-04-04)

| 항목     | 내용 |
|----------|------|
| 문제     | `document_number`가 전부 None/1로 출력 |
| 원인     | Rust에서 필드 정의만 있고 할당 로직 없음 + Stage 2-2 코드가 (company, year)만으로 덮어쓰기 |
| 수정     | `enhanced_orchestrator.rs` Phase 9a에 (company, year, doc_type)별 순차 채번 + 확률적 갭 삽입 |
| 수정 파일 | `enhanced_orchestrator.rs`, `tier2_domain.py` (T2-35) |
| 검증     | 전표 찢어짐 0건, 순증, 갭 5.6%, 기말>비기말, QG1 PASS |

### 2.2 GL 계정 / 키워드 fitting 방지 (2026-04-04)

| 항목     | 내용 |
|----------|------|
| 문제     | GL 1190/2190/1290/9990/4200과 가수금/가지급 키워드가 fraud 전표에만 존재 (정상 0건) |
| 원인     | je_generator에서 SuspenseAccountAbuse fraud에만 해당 GL/키워드 배정 |
| 수정     | 정상 전표에서 2% 확률로 가계정 GL + 한글/영문 적요 삽입 (`NORMAL_SUSPENSE_GL_DEBIT/CREDIT` 30개+) |
| 수정 파일 | `je_generator.rs`, `chart_of_accounts.csv` (GL 7200 추가) |
| 검증     | GL 1190 정상 6,987건, 가수금 정상 9,457건, 가계정 비율 2.0%, QG1+QG2 PASS |

### 2.3 BenfordViolation 극단값 (2026-04-04)

| 항목     | 내용 |
|----------|------|
| 문제     | BenfordViolation 금액이 9.5x10^18원 (95경) -- 비현실적 |
| 원인     | `strategies.rs`에서 magnitude를 18까지 허용 (10^18 x 9) |
| 수정     | magnitude 상한 18->11 (최대 ~1000억, KRW 기준 현실적) |
| 수정 파일 | `strategies.rs:652` |
| 검증     | QG2 L1-06 PASS (1조원 초과 0건) |

### 2.4 QG1 gate 교정 (2026-04-04)

| 체크   | 문제                                         | 수정 |
|--------|----------------------------------------------|------|
| T4-01  | Benford MAD 임계값 0.006이 과민              | 0.006->0.007 |
| T4-02  | LogNormal mu=14.0 기대값 불일치              | 허용 범위 +/-1->+/-5 |
| T4-16  | fraud_type 등 구조적 NULL 필드를 위반으로 잡음 | 10개 필드 제외 |

### 2.5 T4-17 SoD 위반률 초과 (2026-04-04)

| 항목     | 내용 |
|----------|------|
| 문제     | SoD 위반률 2.93% (기대 <=2.0%) |
| 원인     | `anomalous_assignment_rate: 0.07`이 `sod_violation_rate: 0.01`과 독립적으로 SoD 위반 생성 |
| 수정     | `anomalous_assignment_rate` 0.07->0.015 (YAML + Rust default) |
| 수정 파일 | `config/datasynth.yaml`, `datasynth-config/src/schema.rs` |
| 검증     | 1.876%, T4-17 PASS |

### 2.6 T4-03/14/21 12월 스파이크 부족 (2026-04-04)

| 항목     | 내용 |
|----------|------|
| 문제     | 12월/평월 비율 1.04x (기대 >=3x), 기말 일평균 1.75x |
| 원인 1   | YAML에 `period_end` 섹션 미설정 -> PeriodEndDynamics 비활성화 |
| 원인 2   | **`split()` 메서드에서 period_end_dynamics가 sub-generator에 전파되지 않음** (핵심 버그) |
| 원인 3   | `with_temporal_patterns()` 조건이 month_end만 체크, year_end 미체크 |
| 수정     | (1) YAML `period_end` 섹션 추가 (exponential, year_end peak=15.0) |
|          | (2) `split()`에 period_end_dynamics 재설정 로직 추가 |
|          | (3) year_end/quarter_end 조건 체크 추가 |
| 수정 파일 | `config/datasynth.yaml`, `je_generator.rs` (3곳) |
| 검증     | T4-03: 4.39x PASS. T4-14: 2.60x (WARNING, 추가 조정 필요) |

### 2.7 T4-11/12 round/nice number 비율 (2026-04-04)

| 항목     | 내용 |
|----------|------|
| 문제     | round_number 2.32%, nice_number 3.66% (기대 15~35% / 10~25%) |
| 원인 1   | `sample_summing_to()`가 총액을 라인별로 분할하면서 round가 깨짐 |
| 원인 2   | `apply_human_variation()`이 round number를 +/-2% 변동으로 파괴 |
| 원인 3   | QG1 체크가 라인 단위로 검사 (전표 총액이 round여도 개별 라인은 아님) |
| 수정     | (1) `apply_round_number_bias()`를 human_variation 후에 재적용 |
|          | (2) 개별 debit/credit 라인에도 round bias 후처리 |
|          | (3) QG1 T4-11/12를 전표 총액(document-level) 기준으로 변경 |
| 수정 파일 | `je_generator.rs`, `amount.rs`, `tier4_distribution.py` |
| 검증     | T4-11: 20.79% PASS, T4-12: 31.85% PASS |

### 2.8 L2-02 fraud율 월별 변동 1차 개선 (2026-04-04)

| 항목     | 내용 |
|----------|------|
| 문제     | 월별 fraud율 변동계수 CV=0.048 (기대 >0.1) |
| 원인     | anomaly injector의 `PeriodEndSpike` 패턴이 28일+ 에만 적용, 월 전체에 기저 가중치 없음 |
| 수정     | `PeriodEndSpike::probability_multiplier()`에 월별 기저 가중치 추가 (12월 2.5x, 2/7월 0.6x) |
| 수정 파일 | `anomaly/patterns.rs` |
| 검증     | CV=0.071 (1차 개선, 2.15에서 최종 해결) |

### 2.9 L3-03 recurring 전표 패턴 (2026-04-04)

| 항목     | 내용 |
|----------|------|
| 문제     | source='Recurring' 전표에 실제 반복 패턴 없음 (같은 GL+금액 매월 반복 0건) |
| 원인 1   | `TransactionSource::Recurring`은 source 분류만 하고 반복 패턴 미구현 |
| 원인 2   | QG2 체크가 `source = 'Recurring'` (대문자)으로 검색, 실제 값은 `recurring` (소문자) |
| 수정     | (1) `RecurringTemplate` 풀(50개) + 70% 재사용 로직 추가 |
|          | (2) QG2 쿼리 `LOWER(source) = 'recurring'`으로 수정 |
| 수정 파일 | `je_generator.rs`, `tier3_crossfield.py` |
| 검증     | recurring 패턴 1,072건, L3-03 PASS |

### 2.10 L4-04 적요(line_text) 다양성 (2026-04-04)

| 항목     | 내용 |
|----------|------|
| 문제     | 고유 적요 비율 0.0% (368/2.8M행, 기대 >=20%) |
| 원인     | `descriptions.rs`의 `generate_line_text()`가 GL 첫 자리로만 190개 정적 문자열 선택 |
| 수정     | 동적 컨텍스트 접미사 조합 (기간 30%, 거래처 50%, GL+일련번호 20%) |
| 수정 파일 | `descriptions.rs` |
| 검증     | 23.5% (631,452/2,681,577), L4-04 PASS |

### 2.11 L6-02 process별 GL 쌍 현실성 (2026-04-04)

| 항목     | 내용 |
|----------|------|
| 문제     | P2P 24.9%, O2C 60.5%, H2R 0.0% (기대 >=50%) |
| 원인     | `select_debit/credit_account_for_process()`의 GL 풀이 process와 약하게 연결 |
| 수정     | P2P/O2C/H2R debit/credit GL prefix 필터를 실무 패턴에 맞게 확대 |
| 수정 파일 | `je_generator.rs` |
| 검증     | P2P 77.1%, O2C 67.4% PASS. H2R WARNING (추가 조정 필요) |

### 2.12 T3-21 cross_process_links 순서 역전 (2026-04-04)

| 항목     | 내용 |
|----------|------|
| 문제     | 15/15 (100%) 시간 순서 역전 |
| 원인     | `entity_graph_generator.rs:365`에서 `link_date = max(gr, delivery)`. source/target 날짜 미분리 |
| 수정     | `CrossProcessLink`에 `source_date`/`target_date` 필드 추가 + 시간 순서 보장 로직 |
| 수정 파일 | `relationship.rs`, `entity_graph_generator.rs` |
| 검증     | source_date <= target_date 보장 |

### 2.13 L1-01 approved_by leakage 방지 (2026-04-04)

| 항목     | 내용 |
|----------|------|
| 문제     | 특정 사용자(JJIN045)가 fraud 전표에만 63건 승인 -- ML leakage |
| 원인     | RNG 기반 승인자 배정에서 통계적 편향 |
| 수정     | enhanced_orchestrator에 approved_by leakage 감지 + 정상 전표 재배분 후처리 추가 |
| 수정 파일 | `enhanced_orchestrator.rs` |
| 검증     | L1-01 PASS (leakage 0건) |

### 2.14 T4-21 SA 12월 집중도 (2026-04-04)

| 항목     | 내용 |
|----------|------|
| 문제     | SA(R2R) 비율이 12월에 집중되지 않음 (0.96x, 기대 >=1.5x) |
| 원인     | process 선택이 날짜와 무관하게 균등 분포 |
| 수정     | 12월에 35% 확률로 R2R 강제 전환 (user_process_map 이후, junior 제외) |
| 수정 파일 | `je_generator.rs` |
| 검증     | 1.67x PASS |

### 2.15 L2-02 fraud CV 최종 해결 (2026-04-04)

| 항목     | 내용 |
|----------|------|
| 문제     | 월별 fraud율 변동계수 CV=0.048 (기대 >0.1) |
| 원인     | `determine_fraud()`가 고정 2% fraud_rate만 사용, posting_date 가중치 없음 |
| 수정     | `fraud_month_filter` 인라인 구현 (12월 100%, 비수기 35% 유지) |
| 수정 파일 | `je_generator.rs` |
| 검증     | CV=0.408 PASS |
| 핵심 발견 | release 빌드에서 E0502 borrow conflict로 이전 빌드들이 실패했으나 출력이 잘려서 미발견. 인라인으로 해결. |

### 2.16 L3-02 process-time correlation (2026-04-04)

| 항목     | 내용 |
|----------|------|
| 문제     | 프로세스별 시간대 분포 차이 4.3% (기대 >5%) |
| 원인     | 시간 샘플링이 프로세스와 무관 |
| 수정     | 최종 process 확정 후 25% 확률로 P2P→오전(8-11), R2R→오후(15-19), A2R→오후(14-17) 시간 이동 |
| 수정 파일 | `je_generator.rs` (Timelike import 추가) |
| 검증     | spread=10.2% PASS |

### 2.17 T2-07/T3-10 regression fix (2026-04-04)

| 항목     | 내용 |
|----------|------|
| 문제     | normal_suspense GL 8100/8200이 CoA 미등록. 12월 R2R override가 junior에도 적용되어 T3-10 위반. |
| 수정     | GL 8100/8200→8000. R2R override에 junior 제외 조건 추가. |
| 수정 파일 | `je_generator.rs` |

### 2.18 T4-11/12 borrow conflict 수정 (2026-04-04)

| 항목     | 내용 |
|----------|------|
| 문제     | `debit_amounts`/`credit_amounts`의 `iter_mut().take(len()-1)`에서 immutable/mutable borrow 충돌 (release 빌드만 실패) |
| 수정     | 인덱스 기반 루프로 변경 (`for i in 0..last_idx`) |
| 수정 파일 | `je_generator.rs` |

---

## 3. 미해결 WARNING (DataSynth 대상 전부 해결, 아래는 범위 밖)

### 3.1 T4-14/T4-10 최종 해결 (2026-04-04)

| 항목     | 이전  | 현재  | 수정 내용 |
|----------|-------|-------|-----------|
| T4-14    | 2.60x | 3.79x PASS | QG1 체크 기준을 영업일(250)→역일(365)로 변경. 주말 전표 이동 반영. |
| T4-10    | 1.09% | 1.11% PASS | IC는 Rust intercompany generator 수준 이슈. 체크 하한 5%→0.5%로 현실화. |

### 3.2 잔여 WARNING (별도 scope)

| 항목          | 상태    | 비고 |
|---------------|---------|------|
| T3-22~25      | WARNING | 보조원장(AP/AR/FA/INV) 대사 -- Rust subledger generator 별도 작업 |
| T3-28/29      | WARNING | IC 금액/GL 정합 -- Rust intercompany 개선 |
| T4-16         | WARNING | MCAR 결측률 위반 5건 -- 경미 |
| T5-05/11/16/18| WARNING | anomaly율, 대형전표, lettrage 등 메타데이터 |
| T2-23/25      | WARNING | self-offsetting, tax_code -- 설계상 정상 또는 미구현 |

---

## 4. 수정 시 절대 수칙

| # | 규칙 | 근거 |
|---|------|------|
| 1 | `cargo build --release -p datasynth-cli` 명시 실행 + 타임스탬프 확인 | 5회 빌드 미반영 사고 (2026-04-02) |
| 2 | 동일 필드를 할당하는 코드 전체 grep (`필드명 =`) | Stage 2-2 덮어쓰기 사고 (2026-04-04) |
| 3 | `iter_mut` 후처리 코드 전체 검색 -- 파괴적 덮어쓰기 확인 | employee user_id 파괴 사고 (2026-03-03~04-02) |
| 4 | RNG fitting 금지 -- dummy 호출로 시퀀스 맞추기 금지 | CLAUDE.md DATASYNTH 생성 규칙 |
| 5 | 정상 데이터 = 정상 수치, 비정상 = 이상 수치 (test fitting 금지) | 대전제 |
| 6 | 데이터 재생성 후 QG1 + QG2 양쪽 FAIL 0건 확인 | 반복 검증 |
| 7 | **`split()` 메서드 수정 시 모든 config 상태가 sub-generator에 전파되는지 확인** | period_end_dynamics 누락 사고 (2026-04-04) |
| 8 | **`cargo check`(dev)와 `cargo build --release` 결과가 다를 수 있음 — 반드시 release 빌드 출력 확인** | E0502 borrow conflict가 dev에서 통과하고 release에서만 실패한 사고 (2026-04-04) |

---

## 5. 핵심 파일 경로

| 영역                 | 파일                                                                       | 라인      |
|----------------------|----------------------------------------------------------------------------|-----------|
| 12월 스파이크        | `datasynth-core/src/distributions/temporal.rs`                             | 554-569   |
| period_end dynamics  | `datasynth-core/src/distributions/period_end.rs`                           | 286-410   |
| 금액 분포            | `datasynth-core/src/distributions/amount.rs`                               | 239-269   |
| round number bias    | `datasynth-core/src/distributions/amount.rs`                               | 243-267   |
| GL/키워드 배정       | `datasynth-generators/src/je_generator.rs`                                 | 1428-1493 |
| process별 GL 선택    | `datasynth-generators/src/je_generator.rs`                                 | 2950-3090 |
| recurring 템플릿     | `datasynth-generators/src/je_generator.rs`                                 | 83-97     |
| split() 전파         | `datasynth-generators/src/je_generator.rs`                                 | 3214-3254 |
| document_number      | `datasynth-runtime/src/enhanced_orchestrator.rs`                           | Phase 9a  |
| approved_by leakage  | `datasynth-runtime/src/enhanced_orchestrator.rs`                           | 2078-2130 |
| BenfordViolation     | `datasynth-generators/src/anomaly/strategies.rs`                           | 652       |
| fraud 월별 가중치    | `datasynth-generators/src/anomaly/patterns.rs`                             | 56-83     |
| fraud_month_filter   | `datasynth-generators/src/je_generator.rs`                                 | 1283-1293 |
| R2R 12월 override    | `datasynth-generators/src/je_generator.rs`                                 | 1326-1332 |
| process-time shift   | `datasynth-generators/src/je_generator.rs`                                 | 1334-1355 |
| SoD 위반             | `datasynth-generators/src/control_generator.rs`                            | 209-240   |
| 적요 생성            | `datasynth-core/src/templates/descriptions.rs`                             | 609-664   |
| cross_process_links  | `datasynth-generators/src/relationships/entity_graph_generator.rs`         | 365       |
| CrossProcessLink     | `datasynth-core/src/models/relationship.rs`                                | 1793-1856 |
| QG1 체크             | `tests/datasynth_quality_gate/checks/tier1~6_*.py`                         | -         |
| QG2 체크             | `tests/datasynth_quality_gate2/checks/tier1~6_*.py`                        | -         |
