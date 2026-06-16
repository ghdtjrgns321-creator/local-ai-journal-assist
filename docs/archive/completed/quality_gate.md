# DataSynth Quality Gate 분석

> 현재 커버리지, Stage 2/3 갭, 보강 방안 정리.
> 작성일: 2026-04-02 | 기준: Run#16 (FAIL 0, WARNING 판정)

## 현재 상태

- **101개 체크** (5 Tier), Stage 1 데이터(39컬럼, 단일연도 2022)에 최적화
- 경로: `tests/datasynth_quality_gate/`
- 실행: `uv run python -m tests.datasynth_quality_gate --no-stop`

| Tier | 개수 | 영역                                    |
|------|------|-----------------------------------------|
| T1   |   14 | 구조적 무결성 (행수, dtype, NOT NULL 등) |
| T2   |   28 | 값 도메인 + 비즈니스 논리               |
| T3   |   30 | 교차검증 (master data FK, 보조원장 대사) |
| T4   |   21 | 분포 + config 정합                      |
| T5   |   22 | 라벨 품질 + Silent Failure + 메타데이터  |

## Stage 2/3 갭 분석

**결론: 현재 quality gate로는 Stage 2/3 데이터를 테스트할 수 없다.**

핵심 이유 3가지:

1. **새 컬럼 체크 없음** — Stage 2 컬럼(has_attachment, ip_address 등) 검증 전무
2. **다기간 하드코딩** — T1-07이 `fiscal_year=2022` 고정. 3개년 데이터 시 FAIL
3. **change_log.csv 인프라 없음** — 별도 파일 로드/검증 자체가 없음

### Stage 2 컬럼별 필요 체크

| 컬럼                  | 현재 | 필요 체크                                                       |
|-----------------------|------|-----------------------------------------------------------------|
| has_attachment        | X    | NOT NULL, process별 비율, completeness ≥ 80%                    |
| supporting_doc_type   | X    | 도메인 값, process↔doc_type 매핑                                |
| delivery_date         | X    | P2P GR만 존재, posting_date 관계, cutoff 교차검증               |
| invoice_amount        | X    | 양수, debit/credit 정합                                         |
| supply_amount         | X    | 양수, invoice×1.1≈supply (부가세 10%)                           |
| ip_address            | X    | IPv4 형식, company↔IP대역 매핑, completeness ≥ 95%              |
| document_number       | X    | company+year별 순차성, GAP 라벨 정합                            |
| change_log.csv        | X    | 구조 검증, FK정합, 필드 도메인, old/new 타입 정합, 비율         |

### Stage 2 신규 anomaly_type (DETECTION_RULES.md 기준)

| anomaly_type                         | 관련 컬럼                      | quality gate 용도    |
|--------------------------------------|--------------------------------|---------------------|
| `missing_supporting_documentation`   | has_attachment                 | 라벨 제외 조건       |
| `revenue_cutoff_error`               | delivery_date                  | 라벨 제외 조건       |
| `expense_cutoff_error`               | delivery_date                  | 라벨 제외 조건       |
| `invoice_amount_mismatch`            | invoice_amount, supply_amount  | 라벨 제외 조건       |
| `abnormal_access_location`           | ip_address                     | 라벨 제외 조건       |
| `document_number_gap`                | document_number                | 라벨 제외 조건       |
| change_log 관련                      | change_log.csv                 | Rust 측과 합의 필요  |

## 보강 방안

### Phase A: 즉시 수정 (Stage 2 무관)

| 항목 | 내용 | 이유 |
|------|------|------|
| T2-21 | GL prefix 매핑 확장 (P2P에 1400%, 5%, 6% 추가) | 현재 75% 불일치는 매핑 정의가 좁은 quality gate 버그 |
| T5-03 | SelfApproval SQL `IS NOT DISTINCT FROM` 변경 | NULL 비교 문제 가능성 |

### Phase B: Stage 2 Rust 완료 후

#### 기존 체크 수정 (8건)

| 체크                | 변경 내용                                                   |
|---------------------|-------------------------------------------------------------|
| T1-01 행수/컬럼수   | cols 39 → config 기반 동적 판정                             |
| T1-07 기간 범위     | fiscal_year=2022 → config start_date/period_months 기반     |
| T2-14 trading_partner | 기준 95%→60%, WARNING→FAIL (Stage 3-3 기준)               |
| T2-21 GL-process    | 기준 20%→5%, WARNING→FAIL (Stage 3-3 기준)                 |
| T4-03 월별 변동성   | 12개월 → 연도별 분리 또는 36개월 연속                       |
| T4-14 기말 스파이크 | 단일연도 → 각 연도 12월 말                                  |
| T4-21 SA 집중도     | 단일연도 → 각 연도 12월 대비                                |
| T5-03 SelfApproval  | SQL NULL 비교 수정                                          |

#### 신규 체크 추가 (~28건)

**Tier 1 (2건)**

| ID    | 체크                          | 기준                                       |
|-------|-------------------------------|--------------------------------------------|
| T1-15 | change_log 구조               | 필수 7컬럼 존재                            |
| T1-16 | change_log 보호필드 NOT NULL  | document_id, changed_by, change_date       |

**Tier 2 (10건)**

| ID    | 체크                          | 기준                                       |
|-------|-------------------------------|--------------------------------------------|
| T2-29 | has_attachment NOT NULL + bool | NULL=0, true/false만                       |
| T2-30 | supporting_doc_type 도메인    | 허용값 목록                                |
| T2-31 | delivery_date 범위            | P2P GR만, posting_date - 5일 ~ posting_date |
| T2-32 | invoice_amount 양수 + 정합    | > 0, debit/credit 관계                     |
| T2-33 | supply_amount ↔ invoice_amount | supply×1.1 ≈ invoice (KRW ±1)             |
| T2-34 | ip_address 형식               | IPv4 형식                                  |
| T2-35 | document_number 순차성        | company+year별, GAP 라벨 제외              |
| T2-36 | change_log 필드별 형식        | 금액→숫자, 날짜→날짜 형식                   |
| T2-37 | has_attachment ≥ 80%          | Stage 3-3 completeness 기준                |
| T2-38 | ip_address NOT NULL ≥ 95%     | Stage 3-3 completeness 기준                |

**Tier 3 (6건)**

| ID    | 체크                          | 기준                                       |
|-------|-------------------------------|--------------------------------------------|
| T3-31 | ip↔company 대역 매핑          | C001=10.1.x.x 등 (anomaly 제외)           |
| T3-32 | change_log FK 정합            | document_id가 JE에 존재                    |
| T3-33 | change_log changed_field 도메인 | 유효 컬럼명만                            |
| T3-34 | change_log 정상 비율          | 전체 전표의 ~5%에 1~2건                    |
| T3-35 | delivery_date cutoff 정합     | 연도 경계 교차비율 < 1% (anomaly 제외)      |
| T3-36 | change_log new_value ↔ JE 현재 값 | 수정 후 값 = JE 현재 값                |

**Tier 4 (4건)**

| ID    | 체크                          | 기준                                       |
|-------|-------------------------------|--------------------------------------------|
| T4-22 | has_attachment process별 비율  | P2P≥90%, O2C≥85%, R2R≥20%                 |
| T4-23 | 연도별 전표 분포 (다기간)      | 각 연도 비중 25~40%                        |
| T4-24 | ip_address VPN 비율           | 172.16.x.x ≤ 10%                          |
| T4-25 | 계정그룹 YoY 변동률           | 1000s/2000s/4000s/5000s 각 < 50%           |

**Tier 5 (6건)**

| ID     | 체크                          | 기준                                      |
|--------|-------------------------------|-------------------------------------------|
| T5-23a | IP 법인 대역 불일치 라벨 역검증 | 라벨 전표의 ip가 실제 다른 대역인지       |
| T5-23b | 해외 IP 라벨 역검증           | 라벨 전표의 ip가 사설 대역이 아닌지        |
| T5-23c | VPN 오탐 방지                 | VPN IP에 anomaly 라벨이 붙지 않는지        |
| T5-24  | document_number GAP 라벨 정합  | 정방향(라벨→GAP) + 역방향(GAP→라벨)       |
| T5-25  | change_log 사후수정 라벨 정합  | 금액/GL 수정 ↔ 라벨 일치                  |
| T5-26  | TrendBreak 라벨 역검증         | 라벨 전표 계정의 연도 간 잔액 이탈 확인   |

### 하위 호환성

Stage 2 컬럼이 없는 Stage 1 데이터에서도 에러 없이 실행되어야 함.
신규 체크는 **컬럼/파일 존재 여부를 먼저 확인하고, 없으면 SKIP 처리**.

```python
if 'has_attachment' not in columns:
    return CheckResult(..., status="SKIP", actual="컬럼 미존재")
```

## 현재 잔존 WARNING과 Stage 2 관계

Run#16 WARNING 중 Stage 2로 해소 가능한 항목은 거의 없다.

| WARNING                    | Stage 2 영향 | 해소 방법        |
|----------------------------|-------------|------------------|
| T4-10 IC 비율 0.84%       | 무관        | Rust config 튜닝 |
| T4-02 LogNormal μ=9.85    | 무관        | Rust config 튜닝 |
| T2-21 GL prefix 75%       | 무관        | QG 매핑 확장     |
| T5-03 SelfApproval        | 무관        | QG SQL 수정      |
| T4-11/12 round/nice 비율  | 무관        | Rust config 튜닝 |

## 수정 대상 파일

| 파일                                                | 변경                                           |
|-----------------------------------------------------|------------------------------------------------|
| `tests/datasynth_quality_gate/checks/tier1_structural.py` | T1-01/07 동적화 + T1-15/16 change_log 구조 |
| `tests/datasynth_quality_gate/checks/tier2_domain.py`     | T2-29~38 추가 + T2-14/21 기준 강화         |
| `tests/datasynth_quality_gate/checks/tier3_crossref.py`   | T3-31~36 추가                               |
| `tests/datasynth_quality_gate/checks/tier4_distribution.py` | T4-22~25 추가 + T4-03/14/21 다기간 대응  |
| `tests/datasynth_quality_gate/checks/tier5_label.py`      | T5-23~26 추가 + _V dict 확장 + T5-03 수정  |
| `tests/datasynth_quality_gate/expectations.py`            | Stage 2 config 파싱 추가                    |
| `tests/datasynth_quality_gate/runner.py`                  | change_log.csv 조건부 로드 + 다기간 연도    |

## 실행 순서

1. **Phase A** (즉시): T2-21 매핑 확장 + T5-03 SQL 수정 → QG 실행 → WARNING 감소 확인
2. **Stage 2 Rust 구현** → 데이터 재생성
3. **Phase B**: 기존 수정 8건 + 신규 28건 + _V dict 확장 → QG 실행 → 전체 검증
