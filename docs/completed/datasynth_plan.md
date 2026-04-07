# DataSynth 재구성 계획

## 개요

DataSynth(Rust, tools/datasynth/ v1.2.0) 데이터 품질 개선 및 Phase 2/3 확장 계획.
 사용자 요구: 테스트에 데이터를 끼워 맞추지(fitting) 말고, 데이터 자체를 올바르게 생성하라.
 - 정상 데이터 → 100% 정상 수치 (차대변 균형, 양수 금액, 기간 범위 내)
 - 비정상 데이터 → 의도적 비정상 + 라벨로 완전 추적
 - rust로 근본부터 제대로 설계, python으로 덧대기 패치 금지

## Stage 1: 데이터 정확성 (완료)

| 항목  | 내용                                  | 수정 파일                     | 상태 |
|-------|--------------------------------------|-------------------------------|------|
| 1-1   | GL ↔ process 매핑 강제               | je_generator.rs               | 완료 |
| 1-2   | doctype ↔ process 일관성             | je_generator.rs (기존 올바름) | 확인 |
| 1-3   | trading_partner 생성 강화            | je_generator.rs               | 완료 |
| 1-4   | zero amount 제거                     | je_generator.rs (기존 코드)   | 확인 |
| 1-5   | automated 승인 로직 수정             | je_generator.rs               | 완료 |
| 1-6/7 | 라벨 주입/동기화                     | config 튜닝 필요              | 확인 |

## Stage 2: Phase 2/3 확장 컬럼 (2-1/2-2 완료, 2-3 미착수)

### 2-1. 증빙 컬럼 (WU-14 블로커) — 완료

**필요 컬럼:**

| 컬럼                 | 타입   | 용도                      |
|---------------------|--------|---------------------------|
| has_attachment      | bool   | 증빙 존재 여부            |
| supporting_doc_type | str    | 증빙 유형 (발주서/송장 등) |
| delivery_date       | date   | 납품일 (컷오프 검증용)     |
| invoice_amount      | float  | 세금계산서 금액            |
| supply_amount       | float  | 공급가액                  |

**구현 위치:**

- Rust: `crates/datasynth-core/src/models/acdoca.rs` (필드 추가)
- Rust: `crates/datasynth-generators/src/je_generator.rs` (생성 로직)
  - `has_attachment`: P2P 95%, O2C 90%, R2R 30%, 기타 50%
  - `supporting_doc_type`: process별 매핑 (P2P→발주서/수입장, O2C→세금계산서)
  - `delivery_date`: P2P GR 거래만, posting_date - 1~5일
- Python: `config/schema.yaml`, `src/ingest/models.py`

### 2-2. IP/수정이력/문서번호 (WU-15 블로커) — 완료

**필요 컬럼:**

| 컬럼             | 타입     | 용도                    |
|-----------------|----------|-------------------------|
| ip_address      | str      | 접근 IP (지역/시간 이상) |
| document_number | int      | 순차 문서번호            |
| changed_by      | str      | 수정자 (별도 CSV)        |
| change_date     | datetime | 수정일시 (별도 CSV)      |
| changed_field   | str      | 수정 필드 (별도 CSV)     |
| old_value       | str      | 변경 전 값 (별도 CSV)    |
| new_value       | str      | 변경 후 값 (별도 CSV)    |

**구현 방안:**

- `ip_address`: 사용자 persona + company별 IP 대역 할당
  - 본사 C001: 10.1.x.x, 울산 C002: 10.2.x.x, 천안 C003: 10.3.x.x
  - VPN: 172.16.x.x (재택/출장)
  - anomaly: 비정상 IP (다른 법인 대역, 해외 IP)
- `document_number`: company_code + fiscal_year + 순차번호 (의도적 GAP 주입)
- 수정이력: `change_log.csv` 별도 파일 생성
  - 정상: 5% 전표에 1~2건 수정이력
  - 비정상: 금액/GL/날짜 필드 사후 수정 라벨

### 2-3. 다기간 생성 (WU-16 블로커)

**현재:** 1개년 (2022-01-01 ~ 2022-12-31)
**목표:** 3개년 (2020-01-01 ~ 2022-12-31)

**config/datasynth.yaml 변경:**

```yaml
global:
  start_date: "2020-01-01"
  period_months: 36
```

**주의사항:**
- 기존 코드는 period_months 120까지 지원 → 설정 변경만으로 가능
- 3개년 × 3법인 → 약 3.3M rows (생성 시간/파일 크기 확인 필요)
- TrendBreak 탐지: 연도별 추정치 계정 잔액 비교 필요

## Stage 3: Python 호환성 + 검증 (완료)

### 3-1. config/schema.yaml 업데이트 — 완료

Stage 2에서 추가하는 모든 컬럼을 schema.yaml에 반영:

```yaml
- name: has_attachment
  type: bool
  required: false
- name: supporting_doc_type
  type: str
  required: false
- name: delivery_date
  type: date
  required: false
- name: ip_address
  type: str
  required: false
- name: document_number
  type: int
  required: false
```

### 3-2. Python ingest 호환성

| 파일                        | 변경 내용                    |
|-----------------------------|------------------------------|
| `src/ingest/models.py`      | 새 컬럼 인식                 |
| `src/ingest/type_caster.py` | 새 타입 캐스팅               |
| `config/keywords.yaml`      | 새 컬럼 별칭                 |

### 3-3. 품질 게이트 업데이트

| 게이트                    | 기준                           |
|--------------------------|--------------------------------|
| trading_partner NULL     | ≤ 60% (현재 99.3%)             |
| GL-process 불일치        | ≤ 5% (현재 68%)                |
| doctype-process 위반     | = 0 (현재 38%)                 |
| 새 컬럼 completeness     | has_attachment ≥ 80%, ip ≥ 95% |

### 3-4. 재생성 + 전체 테스트

```bash
# 1. Rust 빌드
cd tools/datasynth && cargo build --release

# 2. 데이터 재생성
./target/release/datasynth-data generate \
  -c ../../config/datasynth.yaml \
  -o ../../data/journal/primary/datasynth \
  --seed 2024 --verbose

# 3. Python 테스트
cd ../..
uv run pytest tests/ -v
uv run pytest tests/datasynth_quality_gate/ -v
```

## 의존성 그래프

```
Stage 2-1 (증빙) ─┐
Stage 2-2 (IP)   ─┤── Stage 3-1 (schema) ── Stage 3-2 (ingest)
Stage 2-3 (다기간) ┘                          └── Stage 3-3 (품질 게이트) ── Stage 3-4 (재생성)
```

## 라벨 튜닝 (별도 작업)

Stage 1에서 확인된 라벨 이슈:

| 룰   | 상태                            | 조치                                    |
|------|---------------------------------|----------------------------------------|
| B08  | ManualOverride 라벨 0건        | anomaly_injection rates 증가 필요       |
| C10  | SuspenseAccountAbuse 라벨 0건  | fraud_type_distribution에 추가          |
| C12  | AbnormalHoursConc. 라벨 0건    | 사용자별 시간 집중도 라벨 로직 추가 필요 |
| C03  | AfterHours 31건 FN             | CSV 시간 필드 직렬화 확인 필요           |
