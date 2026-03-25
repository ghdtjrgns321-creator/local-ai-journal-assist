# DataSynth-Detection 갭 근본 원인 분석

> 작성일: 2026-03-22 | 근거: Detection E2E 테스트 결과 (DataSynth 1M행)

## 문제 인식

AUDIT_DOMAIN_FINAL.md가 뿌리다.
한국 감사기준(240호, 외감법, K-SOX)을 근거로 22개 룰을 도출하고,
각 룰의 탐지 로직·피처·임계값을 정의했다.

detection 코드는 이 문서를 구현한 것이고,
DataSynth는 이 룰을 검증할 데이터를 생성하는 도구다.

E2E 테스트에서 22개 중 8개가 0건 → 검증 자체가 안 됨.

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

| 항목                 | AUDIT_DOMAIN_FINAL 정의   | settings.py 현재값                    | DataSynth 실태            | 갭                        |
|:---------------------|:-------------------------|:-------------------------------------|:-------------------------|:--------------------------|
| 매출 계정            | "4xxx" (K-IFRS 기준)     | `revenue_account_prefixes: ['4']`    | gl_account 4xxx 존재 (20%) | ✅ 일치 (engine.py 버그로 0건이었을 뿐) |
| 승인 한도            | 명시 없음 (회사별)        | `approval_threshold: 50,000,000`     | 최대 금액 7,705,200       | ❌ 한도가 데이터 범위 밖   |
| 거래처 식별          | `auxiliary_account_number` | B04에서 사용                        | 전부 NULL                 | ❌ 원천 데이터 없음        |
| 심야 기준            | 22시~06시                | `midnight_start: 22`                 | posting_date 시간 없음     | ❌ 원천 데이터 없음        |
| 관계사 식별          | GL 계정 prefix 매칭        | `intercompany_identifiers: ['1150C', '2050C']` | IC GL 1150C0/2050C0 존재 | ✅ IC 전용 GL prefix 매칭  |
| 직무분리 임계         | 동일인 다단계 프로세스     | `sod_process_threshold: 3`           | 41명, 각각 5개 프로세스    | ❌ 소규모 환경 과탐        |
| Benford 위반         | MAD > 0.012              | `benford_mad_threshold: 0.012`       | 금액 분포가 Benford 적합   | ⚠️ 위반 데이터 미주입     |
| 필수필드 누락         | 9컬럼 NULL 검사           | schema.yaml 참조                    | 결측 0%                   | ⚠️ 정상 (위반 미주입)     |

## 8개 0건 룰의 원인 분류

### 1. DataSynth가 해당 데이터를 아예 생성하지 않음 (구조적 부재)

| 룰  | 부재 데이터               | AUDIT_DOMAIN_FINAL 요구       |
|:----|:-------------------------|:------------------------------|
| B04 | auxiliary_account_number | "동일 벤더·금액·기간 내 2건+"  |
| C03 | posting_date 시간정보     | "22시~06시"                   |

DataSynth가 journal_entries.csv에 거래처 ID와 시간 timestamp를 포함하지 않음.
이 두 룰은 DataSynth 재생성 시 해당 필드를 추가해야 검증 가능.

### 2. settings.py 임계값이 DataSynth 데이터 범위와 동떨어짐

| 룰      | settings.py       | DataSynth 범위         | 원인                                           |
|:--------|:-------------------|:-----------------------|:-----------------------------------------------|
| B02/B08 | 승인한도 5천만원    | 최대 770만             | settings가 한국 대기업 감각, DataSynth가 미국 중견사 |
| B07     | sod_threshold=3    | 41명 전원 5개 프로세스  | 소규모 시뮬레이션에서 전원 해당                   |

AUDIT_DOMAIN_FINAL은 승인한도를 "회사별"로 정의하고 구체 금액을 명시하지 않음.
settings.py가 5천만원으로 하드코딩한 건 한국 감사 실무 감각이지만,
테스트 데이터가 USD 기반 제조사라 범위가 안 맞음.

### 3. audit_rules.yaml 설정이 비어있음

| 룰  | 빈 설정                       | 원인                                        |
|:----|:------------------------------|:-------------------------------------------|
| B10 | `intercompany_identifiers: []` | "회사마다 다름 — UI에서 입력 필수"라고 미뤄둠 |

AUDIT_DOMAIN_FINAL은 B10을 "company_code 간 순환 패턴"으로 정의했는데,
audit_rules.yaml에서 "Phase 1c UI에서 입력"으로 미뤄둔 것.
DataSynth에 C001/C002가 있으므로 테스트용으로라도 채워야 함.

### 4. DataSynth가 해당 anomaly를 주입하지 않음 (의도적)

| 룰  | 상황                                                     |
|:----|:---------------------------------------------------------|
| A02 | DataSynth가 필수필드 100% 생성 → MissingField 주입 안 함  |
| C07 | DataSynth 금액이 자연스러운 Benford 분포 → 위반 없음      |

DataSynth가 "정상 데이터를 현실적으로 생성"하기 때문.
`datasynth.yaml`의 `fraud_type_distribution`에 해당 anomaly 유형 추가 필요.

## 결론

### "설정만 바꾸면 테스트 통과" → 무의미

settings.py의 `approval_threshold`를 770만으로 낮추면 B02가 flagged되겠지만,
그건 "한국 대기업 5천만원 승인한도"라는 실무 시나리오를 검증한 게 아님.
테스트 데이터 쪽이 실무 시나리오를 반영해야 함.

### DataSynth 재생성이 필요한 이유

AUDIT_DOMAIN_FINAL이 정의한 22개 룰을 전부 검증하려면,
DataSynth가 22개 룰 각각에 해당하는 anomaly를 주입해야 함.
현재 `fraud_type_distribution`에 8개 유형만 설정되어 있고,
나머지는 DataSynth가 자체적으로 생성하지만 detection 설정과 안 맞음.

재생성 시 필요한 변경:

```
1. 데이터 구조: auxiliary_account_number에 거래처 ID 포함, posting_date에 timestamp 포함
2. 금액 범위: 한국 기준 승인한도(5천만원) 초과 데이터 포함
3. 사용자 규모: 41명 → 200명+ (SOD 과탐 해소)
4. anomaly 주입: MissingField, BenfordViolation, AfterHours 등 추가
5. intercompany: 3개사 이상 + 순환 패턴 주입
```

### settings.py / audit_rules.yaml은 AUDIT_DOMAIN_FINAL 기준으로 재검증

현재 설정이 AUDIT_DOMAIN_FINAL의 의도를 제대로 반영하는지 전수 점검 필요.
특히 `intercompany_identifiers: []`처럼 "나중에 채우겠다"고 비워둔 항목.

## 관련 문서

- [AUDIT_DOMAIN_FINAL.md](AUDIT_DOMAIN_FINAL.md) — 22개 룰 근거 (뿌리)
- [pre-plan/05-detection.md](pre-plan/05-detection.md) — detection 구현 가이드
- [debugging.md](debugging.md) — engine.py rules 버그 기록
- [E2E 테스트 결과](../tests/test_detection/test-results/e2e-detection-datasynth.md)
