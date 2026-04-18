# DataSynth-Detection 갭 근본 원인 분석

> 작성일: 2026-03-22 | 갱신일: 2026-03-26 | 근거: Detection E2E 테스트 결과 (DataSynth v1.2.0, 1M행)

## 문제 인식

AUDIT_DOMAIN_FINAL.md가 뿌리다.
한국 감사기준(240호, 외감법, K-SOX)을 근거로 24개 룰을 도출하고,
각 룰의 탐지 로직·피처·임계값을 정의했다.

detection 코드는 이 문서를 구현한 것이고,
DataSynth는 이 룰을 검증할 데이터를 생성하는 도구다.

E2E 테스트에서 24개 중 8개가 0건 → 검증 자체가 안 됨.

## 근본 원인: 설정과 데이터가 각각 다른 세계를 바라보고 있다

### 의존 관계

```
AUDIT_DOMAIN_FINAL.md (뿌리)
  ↓ 도출
settings.py + audit_rules.yaml (설정)
  ↓ 참조
detection 코드 (구현)
  ↓ 테스트
DataSynth 데이터 (검증)
```

문제는 **설정 → 데이터** 사이에 계약이 없다는 것.

### 항목별 갭 대조표

| 항목           | AUDIT_DOMAIN 정의         | settings.py 현재값                                                          | DataSynth v1.2.0 실태                         | v1.2.0 해결 상태 |
|:---------------|:-------------------------|:---------------------------------------------------------------------------|:----------------------------------------------|:-----------------|
| 매출 계정      | "4xxx" (K-IFRS 기준)     | `revenue_account_prefixes: ['4']`                                          | gl_account 4xxx 존재 (20%)                     | ✅ 해결 (engine.py 버그 수정) |
| 승인 한도      | 명시 없음 (회사별)        | `approval_thresholds: [10M, 100M, 1B, 5B, 10B, 50B]` (6단계)              | lognormal mu=14.0 (중앙값 ~120만, 최대 1,000억) | ✅ 해결 (6단계 체계 + 금액 범위 확대) |
| 거래처 식별    | `auxiliary_account_number` | B04에서 사용                                                               | 전부 NULL                                      | ❌ 미해결 (DataSynth Rust 수정 필요) |
| 심야 기준      | 22시~06시                | `midnight_start: 22`                                                       | posting_date datetime (시분초 포함)             | ✅ 해결 (v1.2.0에서 timestamp 추가) |
| 관계사 식별    | GL 계정 prefix 매칭       | `intercompany_identifiers: ['1150', '2050', '4500', '2700']`               | IC GL 1150/2050/4500/2700 존재                  | ✅ 해결 ("C" 접미사 제거 + 확장) |
| 직무분리 임계  | 하이브리드 3단계 SoD      | `sod_toxic_pairs` + `sod_role_thresholds` (audit_rules.yaml)                | 1,365명(마스터 1,422명), automated 제외 + Toxic Pair + Role-based | ✅ 해결 (3.32% 위반률, 2026-04-14 실측) |
| Benford 위반   | MAD > 0.012              | `benford_mad_threshold: 0.012`                                              | 금액 분포가 Benford 적합                        | ⚠️ 미해결 (위반 데이터 미주입) |
| 필수필드 누락  | 9컬럼 NULL 검사           | schema.yaml 참조                                                           | 결측 2% (MCAR 주입)                             | ⚠️ 미해결 (A02 탐지 결과 재검증 필요) |

## 8개 0건 룰의 원인 분류

### 1. DataSynth가 해당 데이터를 아예 생성하지 않음 (구조적 부재)

| 룰  | 부재 데이터               | AUDIT_DOMAIN_FINAL 요구  | v1.2.0 상태                       |
|:----|:-------------------------|:-------------------------|:----------------------------------|
| B04 | auxiliary_account_number | "동일 벤더·금액·기간 내 2건+" | ❌ 여전히 NULL — Rust 수정 대기    |
| C03 | posting_date 시간정보     | "22시~06시"              | ✅ v1.2.0에서 datetime 포함        |

B04는 DataSynth Rust 코드에서 거래처 ID 생성 로직 추가가 필요하다.
C03은 v1.2.0에서 posting_date에 시분초가 포함되어 심야 탐지가 가능해졌다.

### 2. settings.py 임계값이 DataSynth 데이터 범위와 동떨어짐 → v1.2.0에서 해결

| 룰      | v1.2.0 이전                          | v1.2.0 현재                                                  |
|:--------|:-------------------------------------|:-------------------------------------------------------------|
| B02/B08 | 단일 승인한도 5천만원, 최대 금액 770만 | 6단계 `[10M, 100M, 1B, 5B, 10B, 50B]`, lognormal mu=14.0    |
| B07     | 41명 전원 5개 프로세스 → 전원 SOD 해당 | 150명, 6개 프로세스, SOD 위반률 1%로 현실적 분포              |

v1.2.0에서 한국 중견 제조 그룹사(3법인, KRW 단일 통화) 기준으로 전환되어
승인한도와 금액 범위가 정합한다. SOD도 150명 규모에서 과탐이 해소되었다.

### 3. audit_rules.yaml 설정이 비어있음 → v1.2.0에서 해결

| 룰  | v1.2.0 이전                          | v1.2.0 현재                                                  |
|:----|:-------------------------------------|:-------------------------------------------------------------|
| B10 | `intercompany_identifiers: []`       | `['1150', '2050', '4500', '2700']` (IC Receivable/Payable/Revenue/Accrued) |

3법인(C001/C002/C003) 간 IC 거래에 대해 GL prefix 매칭으로 관계사 식별이 가능해졌다.

### 4. DataSynth가 해당 anomaly를 주입하지 않음 (의도적)

| 룰  | 상황                                                     | v1.2.0 상태         |
|:----|:---------------------------------------------------------|:--------------------|
| A02 | DataSynth가 필수필드 100% 생성 → MissingField 주입 안 함  | ⚠️ MCAR 2% 주입 추가, 재검증 필요 |
| C07 | DataSynth 금액이 자연스러운 Benford 분포 → 위반 없음      | ⚠️ 미해결 (위반 주입 미구현) |

A02는 v1.2.0에서 `data_quality.missing_values.rate: 0.02` (MCAR) 설정이 추가되었으나,
protected_fields(document_id, company_code, posting_date)는 제외되므로 탐지 결과 재검증이 필요하다.
C07은 Benford 위반 금액을 의도적으로 주입하는 로직이 아직 미구현이다.

## 결론

### 해결 완료 (v1.2.0, 2026-03-26)

| 항목 | 원인 | 조치 | 파일 |
|:-----|:-----|:-----|:-----|
| B02/B08 승인한도 불일치 | 단일 한도 + USD 금액 범위 | KRW 6단계 승인한도 + lognormal mu=14.0 | `settings.py`, `datasynth.yaml` |
| B07 SOD 과탐 | 41명 소규모 시뮬레이션 | 150명 확대, SOD 위반률 1% | `datasynth.yaml` |
| B10 관계사 미식별 | `intercompany_identifiers: []` | IC GL prefix 4개 등록 | `audit_rules.yaml` |
| C03 심야 미탐지 | posting_date 시간정보 없음 | datetime (시분초 포함) 전환 | `schema.yaml`, DataSynth |
| `is_suspense_account` all-False | 한글 키워드만 매칭 | 하이브리드: 텍스트 키워드 OR GL 코드 prefix | `pattern_features.py`, `audit_rules.yaml` |
| `is_round_number` all-False | float 소수점 꼬리 | `base.round(0) % unit` 허용 | `amount_features.py` |

### 미해결 (DataSynth Rust 수정 또는 Phase 2)

| 항목 | 원인 | 필요 조치 | 대상 |
|:-----|:-----|:---------|:-----|
| B04 거래처 중복 | auxiliary_account_number NULL | DataSynth Rust에서 거래처 ID 생성 | `je_generator.rs` |
| A02 필수필드 누락 | MCAR 2% 주입 추가됨, 탐지 결과 재검증 필요 | E2E 테스트 재실행 | `test_e2e_detection.py` |
| C07 Benford 위반 | 위반 금액 미주입 | fraud_type_distribution에 BenfordViolation 추가 | `datasynth.yaml`, Rust |
| SuspenseAccountAbuse 적요 | 적요에 가계정 키워드 미주입 | ~30% 확률로 키워드 주입 | DataSynth Rust |
| round number 클램핑 | 금액 생성기 로직 | round number 클램핑 확인 | DataSynth Rust |

## 관련 문서

- [AUDIT_DOMAIN_FINAL.md](AUDIT_DOMAIN_FINAL.md) — 24개 룰 근거 (뿌리)
- [pre-plan/05-detection.md](pre-plan/05-detection.md) — detection 구현 가이드
- [debugging.md](debugging.md) — engine.py rules 버그 기록
- [E2E 테스트 결과](../tests/test_detection/test-results/e2e-detection-datasynth.md)
