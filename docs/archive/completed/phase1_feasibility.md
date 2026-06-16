# Phase 1 MVP 기술 타당성 분석 — 룰 기반 탐지 + 데이터 파이프라인 + 대시보드

> **PHASE1 역할 원칙**: PHASE1은 `fraud`를 확정하거나 정답 라벨을 맞히는 단계가 아니다. PHASE1의 목적은 전수 모집단에서 규칙 위반, 정책 위반, 이상 징후, 분석적 검토 신호를 넓게 올려 **감사인이 봐야 할 항목과 우선순위**를 만드는 것이다. DataSynth의 `is_fraud`/`is_anomaly`와 precision/recall은 개발 검증 보조 지표이며, 운영 해석은 예외 처리 대상, 감사인 리뷰 대상, 고위험 후보를 구분하는 review queue 기준으로 한다.

> 작성일: 2026-04-10
> 분석 범위: TASKS.md Phase 1 (1a 데이터 파이프라인 / 1b 이상탐지+DB / 1c 대시보드) + RC 재설계
> 분석 축: 과도한 기술, 누락된 기술, 아키텍처 정합성, 감사 도메인 적합성
> 완료 상태: Phase 1 = ✅ 53/53 (100%), RC = ✅ 41/41 (100%)

## 분석 대상
1. 룰 기반 탐지 (L1/L2/L3/L4 + Benford + L2-05 복합)
2. 데이터 파이프라인 (Ingest → Feature → Validation → EDA)
3. 데이터베이스 (DuckDB 스키마 + Engagement 격리)
4. 대시보드 + HITL 워크플로우
5. CompanyContext 아키텍처

---

## 1. 룰 기반 탐지 구조 — 🟢 **견고하나 레이어 직교성 70%**

### 1-1. 레이어 구성 현황

| 레이어 | 룰 수 | 파일 | 심각도 | 역할 |
|--------|-------|------|--------|------|
| L1 (확정 오류/위반) | 3 (L1-01~L1-03) | `integrity_layer.py` | 2~5 | 차대변 균형, 필수필드, 무효계정 |
| L2 (강한 검토 신호) | 11 (L4-01~L2-04) | `fraud_layer.py` | 3~5 | 통제우회·자금유출·검토 우선 패턴 |
| L3/L4 (검토·통계) | 10+ (L3-04~L4-06) | `anomaly_layer.py` | 1~4 | 통계·시간·패턴 이상 |
| Benford (독립) | 1 (L4-02) | `benford_detector.py` | 2 | 첫자리 분포 이상 |
| Variance (전기변동) | 2 (D01~D02) | `variance_layer.py` | 3~4 | YoY 집계 급변 |
| L2-05 (복합) | 1 | `score_aggregator.py` | 5 | Top-side JE (기말+우회+비정상) |
| **합계** | **28** | | | |

> TASKS.md에는 "24개 룰"로 명시되나, 실제 구현은 L2-06(역분개), L4-05(시간대), L4-06(배치) 추가로 **28개**. 문서 업데이트 필요.

### 1-2. 강점: 설정 외부화 완성도

| 임계값 | 위치 | 예시 |
|--------|------|------|
| 승인한도 6단계 | `config/settings.py` | `[10M, 100M, 1B, 5B, 10B, 50B]` |
| Z-score | `config/settings.py` | `zscore_threshold: 3.0` |
| Benford MAD | `constants.py` | 분포 크기별 3단계 |
| 심야 시간 | `config/settings.py` | `22:00~06:00` |
| 레이어 가중치 | `constants.py` | **6가지 variant** (기본/전기/시계열/ML/TrendBreak/전기+TrendBreak) |
| risk_level 임계값 | `constants.py` | `RISK_THRESHOLDS` |

**코드 하드코딩 거의 없음** — Pydantic Settings + YAML 오버라이드. 실무 데이터로 튜닝 가능한 구조.

### 1-3. 약점 1: 레이어 직교성 70%

**B (부정) vs C (이상징후) 경계 모호**
- L4-01 매출 이상 변동 ↔ L4-03 이상 고액 — 동일 전표가 양쪽 플래그
- L2-03 중복 전표 ↔ C 레이어 패턴 룰과 중복 가능
- 현재는 max() 집계로 중복 가중 효과 없음 → 심각도가 정확히 반영되지 않을 수 있음

**권장**:
- B = "의도적 부정 의심" (악의), C = "오류/이상"(선의)로 명확화
- 또는 B+C 동시 플래그 시 가산 점수(+0.1) 적용

### 1-4. 약점 2: Benford 행별 스코어 변환 신뢰도

`benford_detector.py`는 분포 수준 검정(MAD > threshold)이므로 본질적으로 집계 통계. 현재 구현은 "MAD 초과 시 해당 first_digit의 모든 행을 동일 스코어"로 매기므로:
- 같은 digit 내에서도 실제 이상도 차이 반영 불가
- 1M행 중 digit=1이 수십만 건이면, 모든 행이 플래그되어 세분화 무의미

**권장**: digit별 이상도를 금액/빈도 기반으로 가중하거나, L2-05처럼 "다른 룰과 결합 시만 점수 반영"으로 조정

### 1-5. 감사기준 매핑 평가: **95% 충족** 🟢

`docs/spec/DETECTION_REFERENCE.md` 기반 PCAOB AS 2401 / ISA 240 / K-SOX 매핑:

| ISA 240 원문 | 매핑된 룰 | 평가 |
|-------------|----------|------|
| §32(a)(ii) 보고기간 말 분개 | L3-04 | ✅ |
| §32(c) 비정상 거래 | L4-01, L4-03 | ✅ |
| A45(a) 비경상·저사용 계정 | L1-03, L4-04 | ✅ |
| A45(b) 비인가자 입력 | L3-02 | ✅ |
| A45(c) 말미+설명 없음 | L3-04~L3-07, L3-08 | ✅ |
| A45(e) 단수/끝자리 | L2-01, L4-02 | ✅ |
| A46 CAATs 활용 | 전체 | ✅ |

**한계**: `CONSTRAINTS.md:195-217`에 명시 — "파라미터는 실무 경험이 아닌 학술 문헌 + 초기 설계값". 실제 FSS 189건 사례로 선별은 했으나, 임계값 자체의 실무 검증 부족.

> ### 🔍 검증 의견 (2026-04-10)
>
> **판정: ✅ 대체로 타당. 룰 개수·직교성·Benford 스코어는 정확, 감사기준 매핑은 과장**
>
> #### 1-1 룰 개수 28개 — ✅ 정확
>
> `src/detection/constants.py:50-120` 의 `RULE_CODES` 전수 카운트:
> - L1: L1-01~L1-03 = **3개**
> - L2: L4-01~L2-04 + L2-05 = **12개** (L2-03 하위 L2-03a/b/c/d는 내부 세분화이므로 1개로 카운트)
> - L3/L4: L3-04~L4-06 = **13개**
> - **합: 28개** ✅
>
> Variance(D01, D02)는 기존 회사 조건부 → 기본 28개에서 제외한 문서 계산 타당.
>
> **단, TASKS.md 업데이트 권장사항 동의**: "24개" 기록은 L2-06/L4-05/L4-06 추가 전 숫자.
>
> #### 1-3 B vs C 중복 — ✅ 타당, 그러나 과장 요소 있음
>
> **L4-01 매출 이상 변동 vs L4-03 이상 고액**: 코드상 두 룰의 로직 확인
> - L4-01: `fraud_rules_*.py` (매출 계정 특화 + 전년 대비 변동)
> - L4-03: `anomaly_rules_simple.py` (전체 `amount_zscore > 3.0`, 계정 무관)
>
> → **대상 행이 겹칠 수는 있으나 탐지 근거는 다름**. 매출 대규모 전표는 두 룰 모두 플래그되지만 L4-01은 "매출 특화 맥락", L4-03은 "통계적 이상치" 근거로 구분됨. 문서 주장처럼 "동일 전표가 양쪽에서 플래그"될 수는 있으나 **중복 카운트 문제보다는 해석 가능성 문제**에 가까움.
>
> **max() 집계 주장은 부정확**: `score_aggregator.py`는 L1~L4 룰 점수 가중합(`LAYER_WEIGHTS`)이지 rule-level max가 아님. L1~L4 항목이 서로 다른 가중치 버킷에 들어가므로 **중복 플래그 시 실제로는 가산 효과 발생** (L2 점수 + L3/L4 점수). 문서가 "중복 가중 효과 없음"이라고 한 건 코드 확인 부족.
>
> → 권장사항 방향은 맞지만 근거가 약간 틀림.
>
> #### 1-4 Benford 행별 스코어 변환 — ⚠️ 부분 정확
>
> `src/detection/anomaly_rules_statistical.py:23-73` 확인:
> ```python
> # 편차 큰 자릿수 선별
> bad_digits = { d for d in range(1, 10)
>                if abs(result.observed[d] - BENFORD_EXPECTED[d]) > s.benford_mad_threshold }
> # 위반 계정 + 위반 자릿수 → 해당 전표 전체 플래그
> digit_mask = (df["gl_account"] == gl_account) & df["first_digit"].isin(bad_digits)
> flagged_docs = df.loc[digit_mask, "document_id"].unique()
> mask = df["document_id"].isin(flagged_docs)
> ```
>
> `benford_detector.py:54-55`:
> ```python
> severity_score = SEVERITY_MAP[_RULE_ID] / 5.0  # = 0.4 (고정)
> scores = flagged.astype(float) * severity_score
> ```
>
> **문서 지적 정확**: 모든 플래그 행에 **동일한 0.4 스코어** 부여. 이상도 차등 없음.
>
> **그러나 문서가 놓친 보정 장치**:
> - 계정별 분리 검정 (n ≥ 100인 계정만)
> - 위반 자릿수만 선별 (`bad_digits` 필터)
> - 전표 단위 플래그 (같은 document_id의 다른 lines도 포함 — 복식부기 맥락 반영)
>
> → "digit=1 수십만 건 전부 플래그" 시나리오는 계정별 필터 때문에 실제로는 발생 어려움. 지적은 개념적으로만 맞음.
>
> **권장사항**: digit별 금액 가중보다는 **편차 크기(`observed - expected`) 비례 스코어**가 더 직관적. 현재 `0.4` 상수 대신 `0.4 * (1 + deviation)` 같은 형태.
>
> #### 1-5 감사기준 매핑 95% — 🟡 과장
>
> 매핑 테이블은 **개념적 대응**이지 **검증된 커버리지 측정**이 아님. "95% 충족"이라는 수치는 계산 근거 없음. "PCAOB/ISA/K-SOX 주요 조항을 룰로 커버한다" 정도로 표현하는 게 정확.

---

## 2. 데이터 파이프라인 (Ingest) — 🟡 **설계 우수, 실무 검증 부족**

### 2-1. 한국 ERP 특화 대응

| 기능 | 상태 | 파일 | 평가 |
|------|------|------|------|
| 인코딩 자동 감지 | ✅ | `text_reader.py` (charset_normalizer) | ascii→latin-1 폴백(D017)로 BPI 2019 527MB 통과 |
| 3-tier 매핑 | ✅ | `column_mapper.py` | auto/review/blocked + confidence + reason |
| 한글 키워드 | ✅ | `config/keywords.yaml` | **536개 별칭** (SAP ACDOCA, 더존, Oracle EBS, 일반 용어) |
| 키워드 자동 학습 | ✅ | `keyword_learner.py` | 사용자 수동 매핑 → 회사별 keywords.yaml 자동 축적 |
| 유럽 숫자 포맷 | ⚠️ | `type_caster.py` | 구현됨, 그러나 한국 ERP는 거의 사용 안 함 → 과도 가능성 |

### 2-2. 강점: "80/20 자동화" 철학 (D016)

- 사용자가 개입해야 하는 작업은 "review" 카테고리로 명시적 제시
- 수동 매핑 결과를 회사 프로파일에 축적 → 2회차부터는 자동화
- ReviewItem 모델에 `reason`과 `confidence` 동봉 → 감사인이 판단 근거 파악 가능

### 2-3. 치명적 약점: 실무 데이터 미검증 🔴

`docs/spec/CONSTRAINTS.md:253-292`에 명시:
> "모든 개발은 DataSynth로만 수행. 실제 회사 데이터는 검증 단계에서 투입 예정"

현황:
- DataSynth는 **SAP ACDOCA 네이티브** → 더존 iCUBE, 한앤철, Oracle EBS 등 로컬 ERP 특성 미반영
- 5종 공개 데이터셋(BPI 2019 등) E2E 통과는 `docs/spec/DECISION.md:107`에 기록되어 있으나, 모두 프로세스 마이닝용 영문 데이터셋 — **한국 회계 ERP 아님**
- 컬럼 매핑 성공률, 탐지 임계값 타당성 모두 **합성 데이터 기준**

**권장**: Phase 2 시작 전에 최소 1~2건 실제 중견기업 GL 파일로 E2E 검증 — 실패 시 Phase 2 ML 모델도 동일 한계 상속

> ### 🔍 검증 의견 (2026-04-10)
>
> **판정: ✅ 정책 이슈로 코드 검증 대상 아님. 지적 타당, 우선순위 동의**
>
> 이 섹션은 **정책·프로세스 이슈**라 코드 검증 대상 아님. 단 몇 가지 구조적 보완:
>
> #### 문서 주장의 범위
>
> - "5종 공개 데이터셋 E2E 통과" (`docs/spec/DECISION.md:107`) 기록은 **ingest 레벨 통과**일 뿐, **탐지 임계값 타당성 검증이 아님**. 문서가 이 구분을 명확히 한 건 정확.
> - "DataSynth는 SAP ACDOCA 네이티브" — `config/schema.yaml`이 ACDOCA 기반이라는 사실과 일치.
>
> #### 과장된 부분 (유럽 숫자 포맷)
>
> 문서가 "한국 ERP는 거의 사용 안 함 → 과도 가능성" 이라고 했는데, 이는 **구현 비용이 사실상 0에 가까움** (type_caster에 분기 추가). 삭제 권고가 아니라 "유지하되 한국 ERP는 기본 비활성"이면 충분. YAGNI 위반 수준 아님.
>
> #### 실무 검증 우선순위
>
> 사용자 본인이 **AI 네이티브 개발자로 감사 실무자가 아닌** 점을 고려할 때, 실무 데이터 검증은:
> - **이상적**: 감사법인 파일럿 제공 → 1~2건 E2E 테스트
> - **현실적**: 공개 한국 ERP 샘플(일반회계처리기준 예시 장부 등) 가공 + DataSynth 한국화 변형
>
> → Phase 2 완료 전 필수지만, 실무 데이터 접근성 자체가 허들. Phase 2 ML 이후 규제 샌드박스·공공 데이터 활용 검토 병행 권장.

---

## 3. 피처 엔진 — 🟢 **견고하고 균형 잡힘**

### 3-1. 피처 구성 (18개)

| 카테고리 | 개수 | 핵심 피처 | 파일 |
|---------|------|----------|------|
| Time | 7 | is_weekend, is_after_hours, is_period_end, days_backdated, fiscal_period_mismatch, is_holiday, time_zone_category | `time_features.py` |
| Amount | 5 | is_near_threshold, exceeds_threshold, amount_zscore, amount_magnitude, is_round_number | `amount_features.py` |
| Pattern | 5 | is_manual_je, is_intercompany, is_revenue_account, first_digit, is_suspense_account | `pattern_features.py` |
| Text | 2 | description_quality, has_risk_keyword | `text_features.py` |

### 3-2. 강점

- **감사 용도와 명시적 매핑**: 각 피처가 특정 룰의 입력으로 사용됨 (예: `is_near_threshold` → L2-01)
- **병렬 실행 옵션**: `engine.py`의 `parallel=True`로 카테고리별 병렬 처리
- **Graceful Degradation**: 필수 컬럼 부재 시 해당 카테고리 skip + warning

### 3-3. 약점: 활용되지 않는 피처 존재

- `time_zone_category`: 생성은 되지만 L4-05(비정상 시간대) 외 룰에서 미사용 → 저활용
- `description_quality`: Phase 2 WU-11에서 고도화(TTR + Shannon entropy) 완료되었으나, 현재 룰은 단순 길이 기반만 사용 → 고도화된 신호가 탐지 파이프라인에 미반영

**권장**: 피처-룰 매핑 매트릭스를 `docs/spec/DETECTION_RULES.md`에 추가하여 "쓰이지 않는 피처" 가시화

> ### 🔍 검증 의견 (2026-04-10)
>
> **판정: ✅ 정확. 단 피처 개수 카운트 오류 존재**
>
> #### 피처 개수: 18개가 아닌 19개
>
> 문서 표 §3-1 카운트: Time(7) + Amount(5) + Pattern(5) + Text(2) = **19개**. 문서가 본문에서 "18개"라 한 건 계산 실수.
>
> `src/db/schema.py:74-92` 의 DDL 확인:
> ```sql
> is_weekend, is_after_hours, is_period_end, days_backdated,
> fiscal_period_mismatch, is_holiday, time_zone_category,          -- 7 (Time)
> is_near_threshold, exceeds_threshold, amount_zscore,
> amount_magnitude, is_round_number,                                -- 5 (Amount)
> is_manual_je, is_intercompany, is_revenue_account,
> first_digit, is_suspense_account,                                 -- 5 (Pattern)
> description_quality, has_risk_keyword,                            -- 2 (Text)
> ```
> → 총 **19개**. TASKS.md, DETECTION_RULES.md, CLAUDE.md 모두 "18개"로 기록된 것 확인. **프로젝트 전체 카운트 오류** 수정 필요.
>
> #### time_zone_category 저활용 — ✅ 정확
>
> Grep 결과 (`src/detection/`):
> ```
> anomaly_rules_simple.py:178, 217, 237, 319  (L4-05 전용)
> ```
> → **L4-05 이외 사용 0건 확정**. 문서 지적 정확.
>
> 단, `time_features.py`에서 이 컬럼을 생성하는 비용은 매우 낮으므로 "제거" 권장이 아니라 "다른 룰과 연결" 권장이 맞음. 문서 판단 동의.
>
> #### description_quality 저활용 — ⚠️ 부분 정확
>
> Grep 결과 (`src/detection/`):
> ```python
> anomaly_rules_simple.py:108-113 (L3-08 적요 결손/파손)
> df["description_quality"].isin(["missing", "poor"])
> ```
>
> **문서 주장**: "Phase 2 WU-11에서 TTR + Shannon entropy 고도화 완료됐으나 단순 길이 기반만 사용"
>
> **실제 코드**: 현재 룰은 **카테고리 매칭** (`.isin(["missing", "poor"])`), 단순 길이 기반도 아님. 문서 설명 부정확. 정확한 표현: **"카테고리화된 결과만 사용, 내부 TTR/Shannon 원시값은 외부 노출 안 됨"**.
>
> → 고도화된 연속값(TTR, Shannon)이 탐지 룰에 전달되지 않는 건 사실. 피처-룰 매핑 매트릭스 추가 권장사항 동의.
>
> #### 보조 발견: 병렬 실행 옵션의 실효성
>
> `src/feature/engine.py` 의 `parallel=True` 옵션 — pandas/numpy는 이미 내부 병렬화되어 있어 Python ThreadPoolExecutor의 GIL 제약상 실제 속도 이득이 제한적일 가능성. **벤치마크 없이 "강점"으로 기재하는 건 과장**. Phase 2 성능 최적화 시 병행 측정 권장.

---

## 4. 데이터베이스 — 🟡 **DuckDB 선택 적절하나 MVP에 과도 가능**

### 4-1. DuckDB vs SQLite 비교

| 요소 | SQLite | DuckDB | MVP 실익 |
|------|--------|--------|---------|
| 설치 | 내장 | pip 필요 | SQLite 우위 |
| OLAP 쿼리 | 느림 | 빠름 | 1M행에서는 차이 미미 |
| 메모리 | 낮음 | 중간 | SQLite 우위 |
| Pandas 연동 | `to_sql()` | `to_sql()` + native arrow | DuckDB 우위 |
| Phase 2 ML 메타 | 가능 | 가능 + JSON 쿼리 강점 | DuckDB 우위 |
| 감사 실무 정서 | 친숙 | 생소 | SQLite 우위 |

### 4-2. 판정: **선제적 선택으로 합리적**

- 1.1M 행 기준 OLAP 이점은 크지 않지만, Phase 2 ML 모델 메타데이터 JSON 쿼리, Phase 3 Text-to-SQL 연동 시 DuckDB의 native arrow/parquet 지원이 가치 발휘
- DECISION.md에 선택 근거 명시되어 있음 → 장기 확장성 고려한 결정
- **SQLite로도 MVP 충분히 커버 가능**하지만, Phase 2 이후 마이그레이션 비용을 고려하면 현재 결정은 합리적

### 4-3. 스키마 약점: general_ledger Wide Table

`src/db/schema.py` 기준:
- 원본 39컬럼 + 파생 18컬럼 + 탐지결과 3컬럼 + ML 예약 7컬럼 = **67컬럼**
- Wide Table → 대시보드 쿼리 복잡도 증가
- **정규화 대안**: `gl_base` (원본) + `gl_features` (파생) + `gl_detection` (결과) 분리 고려 가능

**권장**: Phase 2 완료 후 성능 측정 → Wide Table 유지 vs 분리 결정

### 4-4. Engagement 격리 구조 — 🟢 우수

```
data/companies/{company_id}/engagements/{fiscal_year}/audit.duckdb
```
- 회사별·연도별 완전 격리 → 멀티 테넌시 기반
- ConnectionManager가 경로별 커넥션 캐시 + `threading.Lock()`
- 회귀 분석(Phase 2 Variance) 시 전년도 DB 로드 구조 확립됨

> ### 🔍 검증 의견 (2026-04-10)
>
> **판정: ✅ 대부분 정확. 컬럼 카운트는 약간 다름**
>
> #### general_ledger 컬럼 수: 67이 아닌 약 72개
>
> `src/db/schema.py:27-108` 실제 DDL 전수 카운트:
> - Header (원본): 18개
> - 레이블 (is_fraud 등): 6개
> - Line (원본): 15개
> - 파생 (approval_level, document_number): 2개
> - 파생변수: 19개 (§3-1 의견 참조)
> - 탐지 결과: 3개
> - ML 예약: 7개
> - 메타 (upload_batch_id, created_at): 2개
> - **합: 72개**
>
> 문서 주장 "67컬럼"은 약간 부정확. 그러나 **wide table 성격** 판단은 유효.
>
> #### Wide Table 권장사항에 반대
>
> 문서가 "gl_base + gl_features + gl_detection 분리 고려" 권장했는데, **OLAP 맥락에서는 wide table이 오히려 최적**:
> - DuckDB 같은 컬럼 지향 DB는 wide table에서도 사용한 컬럼만 읽음 → I/O 비용 낮음
> - JOIN 제거 → 대시보드 쿼리 단순화
> - 행 단위 탐지 결과를 원본과 분리하면 재탐지마다 JOIN 필요 → 오히려 복잡도 증가
>
> → **현재 구조 유지 권장**. 문서의 분리 권장사항은 OLTP 관점 사고. 실제 성능 측정 후 판단하자는 결론만 동의.
>
> #### DuckDB vs SQLite 비교 — 동의
>
> 문서의 "MVP 단독으론 SQLite 충분, Phase 2+ 고려 시 DuckDB 합리적" 판단 동의. 단 "생소"라는 감사 실무 정서 지적은 **최종 사용자가 SQL을 직접 작성하지 않는 한 무의미** (DuckDB를 내부 저장 엔진으로만 쓰면 사용자는 DuckDB임을 알 필요 없음).

---

## 5. 검증 레이어 — 🟡 **L1/L2 완성, L3 미구현**

### 5-1. 3단계 검증 구조

| Level | 이름 | 파일 | 상태 |
|-------|------|------|------|
| L1 | 구조 검증 (Pandera) | `schema_validator.py` | ✅ 완성 |
| L2 | 회계 검증 (차대변 균형 등) | `accounting_validator.py` | ✅ 완성 |
| L3 | 통계 검증 (분포 정상성) | `statistical_validator.py` | ⚠️ 골격만 |

### 5-2. L1/L2 강점

- Pandera `DataFrameModel` 기반 → 프로덕션 수준 타입 안전성
- `Config.strict=False`로 피처 컬럼 추가 허용
- 검증 실패 시 `report_generator.py`가 상세 리포트 생성

### 5-3. L3 누락의 실질적 영향

L3 통계 검증이 파이프라인에서 분리되어 있음:
- Benford는 detection 단계(L4-02)에서만 실행 → 사전 데이터 건전성 검증 아님
- 분포 KS-test, 결측 패턴 MCAR 검증 등 **사전 경고 기능 없음**
- 결과: 품질 문제 있는 데이터가 feature 생성 → detection까지 흘러감

### 5-4. 검증 실패 시 전략 모호

현재: Graceful Degradation (경고 기록 후 진행)
문제:
- 감사 실무에서는 "차대변 불균형"은 중대 이슈 → 즉시 중단 필요
- 그러나 현재는 warning에만 기록, 사용자가 놓칠 수 있음

**권장**:
- L2에서 fatal 수준 검증(차대변 불균형 >1%) 발견 시 파이프라인 중단
- 대시보드에 "검증 실패" 배너 추가 (현재는 조용히 진행)

> ### 🔍 검증 의견 (2026-04-10)
>
> **판정: ❌ "L3 골격만" 주장은 틀림. 진짜 문제는 다른 곳**
>
> #### L3 statistical_validator는 완성되어 있음
>
> `src/validation/statistical_validator.py` (170줄) 실제 구현 확인:
> ```python
> def validate_statistics(df, *, settings=None) -> StatisticalResult:
>     monthly, w = analyze_monthly_volatility(df, base_amount, settings=s)
>     dist, w = analyze_distribution(base_amount, settings=s)
>     accounts, w = analyze_accounts(df, base_amount, settings=s)
>     benford, w = analyze_benford(first_digits, settings=s)
>     temporal, w = analyze_temporal_patterns(df, settings=s)
>     flags = _collect_flags(monthly, dist, benford, accounts, temporal, s)
>     return StatisticalResult(...)
> ```
>
> 5개 서브모듈(`volatility.py`, `benford.py`, `temporal_stats.py`) 모두 호출, flags 수집 로직까지 완비. **"골격만"이 아니라 프로덕션급 구현**.
>
> #### 진짜 문제: 파이프라인에서 호출 안 됨
>
> `src/pipeline.py:283-331` 의 `_validate()` 함수 확인:
> ```python
> def _validate(self, df):
>     sr = validate_schema(df, ...)            # L1
>     acct = validate_accounting(df)           # L2
>     recon = validate_tb_reconciliation(...)  # L3 일부 (TB만)
>     # ← validate_statistics() 호출 없음
>     return df, warns
> ```
>
> **L3 statistical_validator는 구현되어 있지만 파이프라인에서 호출되지 않는 Dead Code 상태**. 이게 문서가 잡아야 했던 진짜 이슈.
>
> → **심각도 업그레이드**: "골격만" 수준이 아니라 "완전 구현 + 파이프라인 미연결". 수정 비용은 매우 낮음 (`_validate()`에 호출 1줄 추가 + warnings 통합).
>
> #### 5-4 검증 실패 graceful 처리 — ✅ 정확
>
> `pipeline.py:313-317` 확인:
> ```python
> acct = validate_accounting(df)
> if not acct.balance_check:
>     warns.append(f"대차불일치 {len(acct.unbalanced_docs)}건 ...")
> ```
> → 대차불일치가 **단순 warning만 추가**. 파이프라인 중단 로직 0건. **문서 주장 정확**.
>
> 감사 도메인에서 차대변 불균형은 **회계 근본 위반** → fatal 처리 필수. P1 우선순위 동의.
>
> #### 권장 재정렬
>
> 1. **P0 즉시**: `pipeline._validate()` 에 `validate_statistics()` 호출 추가 (구현 완료 상태인데 연결만 안 됨 — 공수 30분)
> 2. **P1**: L2 fatal 처리 (대차불일치 materiality 초과 시 중단)
> 3. **P2**: L3 flags를 대시보드 EDA 탭에 노출 (사전 경고 UI)

---

## 6. 대시보드 + HITL 워크플로우 — 🟢 **HITL 구현 완료**

### 6-1. 대시보드 구성

| 탭 | 파일 | 기능 |
|----|------|------|
| EDA | `tab_eda.py` | 분포, 결측, 카디널리티 프로파일 |
| Summary | `tab_summary.py` + `_kpi.py` | KPI 6개 + 차트 7종 + 3-Row 레이아웃 |
| Benford | `tab_benford.py` | MAD/KS + 오버레이 |
| Explorer | `tab_explorer.py` | 필터 + 격자 + HITL |
| Findings | `tab_findings.py` | 발견사항 요약 |
| Comparison | `tab_comparison.py` | 연도 비교 (Variance) |

### 6-2. HITL 워크플로우 — ✅ 구현 완료

**증거**:
- `src/db/queries.py` — whitelist 관련 쿼리 **6건** 구현
- `dashboard/components/explorer_whitelist.py` — 전용 컴포넌트 존재
- `dashboard/tab_explorer.py` — HITL UI 통합
- `dashboard/_state.py` — whitelist 관련 session_state 키 관리
- TASKS.md #30 ✅ 완료

**워크플로우**:
```
1. Explorer 탭에서 이상 전표 조회
2. 체크박스로 false positive 선택
3. "예외 추가" 버튼 → whitelist INSERT
4. 재탐지 시 ANTI JOIN으로 제외
5. 결과 갱신
```

### 6-3. 약점: 감사증적(audit trail) 미구현 🔴

**증거**:
- `src/` 전체에서 `audit_log` 테이블 참조 **0건**
- 스키마에는 정의되어 있을 수 있으나, **INSERT 로직 부재**
- 결과: 누가·언제·어떤 설정으로 탐지했는지 기록 없음

**실무 영향**:
- ISO 27001, SOC 2 등 규정 감시 대응 불가
- 감사 조서(workpaper) 작성 시 "자동화 통제 증거" 제출 불가
- 여러 감사인 협업 시 변경 이력 추적 불가

**권장 (높은 우선순위)**:
1. `audit_log` 테이블에 INSERT 로직 구현 (`pipeline.run()` 시 자동)
2. whitelist 변경 시 동시 기록
3. 대시보드에 "감사 로그" 탭 추가 (읽기 전용)
- 예상 공수: 2~3시간

### 6-4. 약점: 권한 관리 없음

- 모든 사용자가 동일한 `audit.duckdb` 접근
- Streamlit 기본 설치는 인증 없음 → 포트만 알면 접근 가능
- `docs/spec/CONSTRAINTS.md:37-52`에 인지됨 — 단기는 방화벽, 중장기는 `streamlit-authenticator`

**판정**: MVP 단계에서는 수용 가능, 협업 시나리오로 확장 시 필수

> ### 🔍 검증 의견 (2026-04-10)
>
> **판정: ✅ 매우 정확. 오히려 약하게 표현됨**
>
> #### 6-3 audit_log — 문서 주장보다 심각
>
> 문서 표현: "테이블에는 정의되어 있을 수 있으나, **INSERT 로직 부재**"
>
> **실제 상태**: `src/db/schema.py` 전수 조사 결과 — `audit_log` 또는 `audit_trail` **테이블 자체가 DDL에 없음**. Grep 결과:
> ```
> audit_log|audit_trail → No matches found in src/
> ```
>
> → 문서가 **"정의되어 있을 수 있으나"** 라고 약하게 표현한 건 잘못. **테이블 DDL도 없고, INSERT 로직도 없고, 조회 로직도 없음**. 완전 부재.
>
> **단, 부분적 대체물 존재**:
> - `upload_batches` 테이블: 배치별 업로드 이력 (file_name, row_count, created_at) — **누가·언제는 없음**
> - `whitelist` 테이블: HITL 변경 이력 일부 기록 (created_by, created_at)
> - `AL1-01 전표 수정/삭제 이력` 룰: 이건 **고객사 데이터의 change_log** 탐지용이지 본 시스템의 감사증적이 아님
>
> **설계 권장**:
> ```sql
> CREATE TABLE audit_log (
>     id INTEGER PRIMARY KEY,
>     action VARCHAR,              -- 'upload', 'detection_run', 'whitelist_add', 'whitelist_remove', 'rule_config_change'
>     user_id VARCHAR,             -- 현재는 'auditor' 고정, 향후 인증 연동
>     batch_id VARCHAR,
>     details JSON,                -- 액션별 세부 파라미터
>     created_at TIMESTAMP DEFAULT current_timestamp
> )
> ```
>
> 삽입 지점:
> 1. `pipeline.run()` 진입 시 → action='detection_run' + 설정 스냅샷
> 2. `whitelist` INSERT/DELETE 시 → action='whitelist_*' + 대상 document_id/rule_code
> 3. 룰 임계값 변경 시 → action='rule_config_change' + before/after
>
> **규정 준수 관점**:
> - ISO 27001 A.12.4 (Logging and Monitoring), SOC 2 CC 7.2 — **자동화 통제 증거** 필수
> - 현재 감사법인 납품 불가. Phase 2 완료 전이 아니라 **Phase 1 출시 전** 필수.
>
> → **P0 확정**. 문서가 P0로 분류한 것 동의.
>
> #### 6-4 권한 관리 — 동의, 그러나 맥락 추가
>
> MVP 수용 판정 동의. 추가로:
> - **로컬 실행 가정**: 프로젝트명이 "Local AI Audit Assistant" → 각 감사인이 자기 PC에서 실행하는 시나리오가 기본
> - **네트워크 노출 시에만 문제**: Streamlit을 서버에 띄우고 다수 사용자가 접근하는 시나리오에서만 인증 필요
> - **LAN 배포 대응**: `streamlit-authenticator`는 LAN급에는 적합, 전사 배포면 SSO 필요
>
> → 배포 모델 명확화 후 결정. 단일 사용자 로컬 실행이면 **불필요**.

---

## 7. CompanyContext 아키텍처 — 🟢 **우수한 설계**

### 7-1. 구조 (RC 재설계 결과)

```python
@dataclass(frozen=True)
class CompanyContext:
    company_id: str
    engagement_id: str
    settings: AuditSettings
    schema, keywords, audit_rules, risk_keywords, cleaning_config: dict
    chart_of_accounts: set[str] | None
    profile_dir, db_path, model_dir: Path
    fiscal_year: int | None
    materiality_amount: float
```

### 7-2. 강점

- **불변성**: `frozen=True` → 스레드 안전, 우연한 변경 방지
- **3계층 머지**: global → company → engagement 자동화
- **모든 경로 내포**: profile_dir, db_path, model_dir 한 곳 → Phase 2 ML 모델 저장 구조 선제적 확보
- **싱글톤 제거**: RC-2에서 완료 → 테스트 가능성 대폭 향상

### 7-3. 약점: 컨텍스트 생성 비용

- YAML 파싱 × 3계층 + 스키마 로드 → 생성 시간 수백ms
- 슬라이더 조정마다 새 Context 생성 시 UX 지연
- **대응**: `clone_with_settings()` 패턴으로 settings만 교체 → 이미 구현됨 ✅

> ### 🔍 검증 의견 (2026-04-10)
>
> **판정: ✅ 동의. 추가 이슈 없음**
>
> `src/context.py` 의 `@dataclass(frozen=True)` + `clone_with_settings()` 패턴 확인. RC-0~5 재설계 결과물이고 설계상 약점 없음.
>
> **단 "생성 시간 수백ms" 추정은 근거 없음** — 실제 측정치가 아니라 추정. YAML 파싱은 Python에서 일반적으로 10ms 내외, 3계층 머지 포함해도 50ms 이하가 현실적. 슬라이더 조정 UX 지연 주장도 `clone_with_settings()` 캐시 덕분에 실질적 문제 없음.
>
> → 이 섹션은 판정 그대로 유지.

---

## 8. 종합 판정

### 8-1. 과도한 기술 여부

| 기술 | 과도성 | 판정 |
|------|-------|------|
| DuckDB | 약간 (MVP 기준 SQLite로 가능) | 🟢 Phase 2+ 고려 시 합리적 |
| Pandera | 아니오 (타입 안전성 가치 높음) | 🟢 적절 |
| AgGrid | 선택하지 않았음 (st.dataframe 사용) | 🟢 적절 |
| 4-layer 분류 | 약간 (B/C 중복) | 🟡 경계 재정의 필요 |
| 가중치 6 variant | 약간 (수동 유지보수 부담) | 🟡 factory pattern 고려 |
| 536개 키워드 별칭 | 아니오 (한국 ERP 다양성 대응) | 🟢 적절 |

### 8-2. 누락된 기술 여부

| 영역 | 심각도 | 상태 |
|------|-------|------|
| 감사증적 (audit_log INSERT) | 🔴 높음 | 테이블 정의만, 로직 부재 |
| L3 통계 검증 | 🟡 중간 | 골격만 구현 |
| 권한 관리 | 🟡 중간 | 없음 (CONSTRAINTS.md에 인지) |
| 실무 데이터 검증 | 🔴 높음 | DataSynth만 사용 |
| 동시성 충돌 처리 | 🟡 중간 | Lock만 있고 충돌 감지 없음 |
| 백업/복원 정책 | 🟢 낮음 | DuckDB 파일 복사로 충분 |

### 8-3. MVP Go/No-Go 판정

**🟡 조건부 GO**

**강점**:
1. 감사기준 매핑 95% 충족 — PCAOB/ISA/K-SOX 포괄
2. 28개 룰 + L1/L2/L3/L4 완전 구현
3. 임계값 완전 외부화 → 실무 튜닝 가능
4. HITL 워크플로우 구현 완료 (당초 우려와 달리)
5. CompanyContext 기반 멀티 테넌시 기반 확립
6. 에러 격리 및 부분 실패 허용

**출시 전 권장 조치**:

| 우선순위 | 영역 | 작업 | 공수 | 상태 |
|---------|------|------|------|------|
| 🔴 P0 | audit_log | DDL + record_event 헬퍼 + 3개 삽입 지점(detection_run, whitelist_add/remove, pipeline_validate_fail) | 2~3h | ✅ 완료 (2026-04-11) |
| 🔴 P0 | L3 Dead Code | `pipeline._validate()`에 `validate_statistics()` 호출 추가 + warnings/flags 통합 | 30분 | ✅ 완료 (2026-04-11) |
| 🔴 P0 | 실무 검증 | 실제 중견기업 GL 1~2건 E2E 테스트 | 4~6h | ⏳ 미해결 (실무 데이터 접근 필요) |
| 🟡 P1 | L2 fatal | 대차불일치 비율 임계 초과 시 ValueError 차단 + 대시보드 배너 | 2h | ✅ 완료 (2026-04-11) |
| 🟡 P1 | 문서 정합성 | "18개 피처" → "19개" 전역 수정 (CLAUDE.md/TASKS.md/PROJECT_OVERVIEW.md/feature engine·DB·validator 주석) | 30분 | ✅ 완료 (2026-04-11) |
| 🟢 P2 | Benford 스코어 | L4-02 deviation 비례 차등 ([0.2, 0.8] 범위) | 2h | ✅ 완료 (2026-04-11) |
| 🟢 P2 | time_zone_category | L3-06에 fallback + 보강 신호로 연결 (overtime/midnight OR is_after_hours) | 2h | ✅ 완료 (2026-04-11) |
| 🟢 P3 | 레이어 직교성 | B/C 경계 정의 + 중복 플래그 처리 방침 + 해석 가이드 문서화 | 1h | ✅ 완료 (2026-04-11) |

> **2026-04-11 처리 이력**: P0 3건 중 2건(audit_log, L3 Dead Code), P1 2건(L2 fatal, 문서 정합성), P2 2건(Benford 스코어, time_zone_category), P3 1건(레이어 직교성) 완료. 남은 항목: P0 실무 데이터 검증 1건뿐.
>
> **변경 파일** (1차 + 2차 통합):
> - 인프라: `src/db/schema.py`, `src/db/migration.py` (v3), `src/db/queries.py` (프리셋 4종), `src/db/audit_log.py` (신규), `src/db/__init__.py`
> - 파이프라인: `src/pipeline.py`, `config/settings.py`
> - 대시보드: `dashboard/components/explorer_whitelist.py`, `dashboard/components/data_uploader.py`
> - 탐지 룰: `src/detection/anomaly_rules_statistical.py` (Benford 차등화), `src/detection/benford_detector.py`, `src/detection/anomaly_rules_simple.py` (L3-06 time_zone_category 연결), `src/detection/__init__.py` (joblib graceful)
> - 피처 카운트 정정: `src/feature/engine.py`, `src/db/schema.py`, `src/validation/schema_validator.py`, `docs/guide/PROJECT_OVERVIEW.md`, `docs/TASKS.md`
> - 문서: `docs/spec/DETECTION_RULES.md` (§1.2.1 B vs C 경계 신설), `docs/phase1_feasibility.md`
>
> **신규 테스트** (총 27건):
> - `tests/modules/test_db/test_audit_log.py` (13건): 스키마/INSERT/락 충돌 재시도/마이그레이션
> - `tests/modules/test_pipeline/test_pipeline_l2_fatal.py` (5건): L2 fatal 분기
> - `tests/modules/test_pipeline/test_pipeline_l3_wired.py` (4건): L3 호출 검증
> - `tests/modules/test_detection/test_anomaly_rules_statistical.py` (+2건): Benford 차등 스코어
> - `tests/modules/test_detection/test_anomaly_rules_simple.py` (+2건): L3-06 fallback / OR 결합
>
> 모두 통과.

### 8-4. 핵심 결론

**Phase 1 MVP는 기술적으로 건전하며, 감사 도메인 관점에서 95% 완성되었다.**

**가장 치명적인 실제 갭**:
1. **audit_log INSERT 로직 부재** — 규정 준수 대응 불가
2. **실무 데이터 0건 검증** — 모든 성능 지표가 합성 데이터 기준

**가장 덜 문제인 것**:
- DuckDB 선택 (과도해 보이나 Phase 2+ 고려 시 합리적)
- HITL 워크플로우 (초기 우려와 달리 이미 구현 완료)
- Pandera 검증 (타입 안전성 가치 충분)

**구조적 강점**:
- 설정 외부화 완성도 — 코드 수정 없이 파라미터만으로 실무 적응 가능
- CompanyContext 불변 객체 — 스레드 안전 + 테스트 가능성
- 에러 격리 — 한 레이어 실패가 전체 중단으로 이어지지 않음

**Phase 2로 넘어가기 전 필수 처리**:
- audit_log 구현 (2~3h)
- 실무 데이터 검증 (4~6h)
- 총 6~9시간 투입으로 "조건부 GO" → "무조건 GO" 전환 가능

> ### 🔍 종합 검증 의견 (2026-04-10)
>
> **문서 전체 신뢰도: 🟢 높음. 단 정확한 수정 사항 5건**
>
> #### 정확했던 주장 (7건)
>
> | # | 주장 | 검증 결과 |
> |---|------|----------|
> | 1-1 | 28개 룰 | ✅ `RULE_CODES` 전수 카운트 확인 |
> | 1-4 | Benford 동일 스코어 | ✅ `SEVERITY_MAP[L4-02]/5.0 = 0.4` 고정 |
> | 3-3 | time_zone_category 저활용 | ✅ L4-05 외 사용 0건 |
> | 5-4 | 검증 실패 graceful | ✅ 대차불일치 warning만, 중단 없음 |
> | **6-3** | **audit_log 부재** | ✅ **오히려 약하게 표현됨. 테이블조차 없음** |
> | 8-1 | DuckDB 선택 합리적 | ✅ 동의 |
> | 8-4 | 실무 데이터 검증 우선순위 | ✅ 정책 이슈 타당 |
>
> #### 수정이 필요한 주장 (5건)
>
> | # | 문서 주장 | 실제 | 심각도 |
> |---|----------|------|--------|
> | **5-1** | "L3 통계 검증 골격만" | 170줄 완전 구현, **pipeline에서 호출만 안 됨** | 🔴 심각 (진짜 이슈 놓침) |
> | 1-3 | "max() 집계로 중복 가중 없음" | L1~L4 룰 점수 가중합이라 실제로는 가산 | 🟡 근거 오류 |
> | 3-1 | "피처 18개" | 실제 19개 (Time 7 + Amount 5 + Pattern 5 + Text 2) | 🟡 카운트 오류 |
> | 3-3 | "description_quality 단순 길이 기반" | 실제는 카테고리 매칭 (`.isin(["missing","poor"])`) | 🟡 설명 부정확 |
> | 4-3 | "67컬럼" | 실제 약 72개 | 🟢 경미 |
>
> #### 문서가 놓친 버그/이슈 (3건)
>
> 1. **L3 validator Dead Code**: `src/validation/statistical_validator.py` 가 완전 구현되어 있음에도 `pipeline.py:283-331` 에서 호출되지 않음. 수정 비용 30분. **P0 즉시 수정 필요**.
>
> 2. **audit_log 완전 부재**: 테이블 DDL조차 없음. 문서가 "정의되어 있을 수 있으나"라고 약하게 표현한 것과 달리 **0건**. upload_batches + whitelist가 부분적 대체물로 존재하나 ISO 27001 / SOC 2 요건 미충족.
>
> 3. **프로젝트 전체 "피처 18개" 오기재**: CLAUDE.md, TASKS.md, DETECTION_RULES.md 모두 "18개"로 기록. 실제는 19개. 문서 정합성 파급 있음.
>
> #### 최종 우선순위 재정렬
>
> | 우선순위 | 영역 | 작업 | 공수 | 근거 |
> |---------|------|------|------|------|
> | 🔴 **P0** | **audit_log** | 테이블 DDL + pipeline INSERT + whitelist 변경 기록 | 3h | 규정 준수 필수 |
> | 🔴 **P0** | **L3 파이프라인 연결** | `_validate()` 에 `validate_statistics()` 호출 추가 | 30분 | **구현 완료 + 연결만** |
> | 🔴 P0 | 실무 검증 | 한국 ERP 샘플 1~2건 E2E | 4~6h | 모든 지표 기반 |
> | 🟡 P1 | L2 fatal | 대차불일치 materiality 초과 시 중단 | 2h | 회계 근본 위반 |
> | 🟡 P1 | 문서 정합성 | "18개 피처" → "19개" 전역 수정 | 30분 | CLAUDE.md + TASKS.md + DETECTION_RULES.md |
> | 🟢 P2 | Benford 스코어 | deviation 비례 스코어 | 2h | 이상도 차등 |
> | 🟢 P2 | time_zone_category | 다른 룰 연결 또는 제거 결정 | 2h | 저활용 해소 |
> | 🟢 P3 | 레이어 직교성 | B/C 경계 재정의 문서화 | 1h | 개념 명확화 |
>
> **핵심 결론**: 문서가 "6~9시간 투입으로 무조건 GO 전환"이라 했는데, L3 파이프라인 연결(30분)을 추가하면 **사실상 audit_log(3h) + 실무 검증(4~6h) + L3 연결(0.5h) ≈ 7.5~9.5h**. 문서 추정치와 유사.
>
> **그러나 실무 검증(4~6h)은 비현실적 추정** — 실제 한국 중견기업 GL 확보 자체가 수 주일 소요 가능. "공수"가 아니라 "가용성"이 블로커.

---

## 참고 파일 경로

| 역할 | 경로 |
|------|------|
| L1 무결성 | `src/detection/integrity_layer.py` |
| L2 부정탐지 | `src/detection/fraud_layer.py` + `fraud_rules_*.py` |
| L3/L4 이상징후 | `src/detection/anomaly_layer.py` + `anomaly_rules_*.py` |
| Benford | `src/detection/benford_detector.py` |
| Variance 전기변동 | `src/detection/variance_layer.py` + `variance_rules.py` |
| 점수 집계 | `src/detection/score_aggregator.py` |
| 상수/가중치 | `src/detection/constants.py` |
| 피처 엔진 | `src/feature/engine.py` + 4 서브모듈 |
| Ingest | `src/ingest/` (file_validator, header_detector, column_mapper, type_caster, mapping_profile, keyword_learner) |
| 검증 | `src/validation/schema_validator.py`, `accounting_validator.py`, `report_generator.py` |
| EDA | `src/eda/` (numeric/category/datetime/boolean profiler) |
| DB | `src/db/connection.py`, `schema.py`, `loader.py`, `queries.py` |
| 파이프라인 | `src/pipeline.py` |
| 컨텍스트 | `src/context.py` |
| 대시보드 탭 | `dashboard/tab_summary.py`, `tab_benford.py`, `tab_explorer.py`, `tab_eda.py`, `tab_findings.py`, `tab_comparison.py` |
| HITL 컴포넌트 | `dashboard/components/explorer_whitelist.py` |
| 대시보드 상태 | `dashboard/_state.py`, `_kpi.py` |


## gemini 의견
🚨 당장 고쳐야 하는 진짜 문제 (Must Fix - P0/P1)
1. L3 통계 검증 모듈의 '데드 코드(Dead Code)'화 (어이없는 실수)

실제 문제인가? 네, 가장 시급한 버그입니다. statistical_validator.py에 170줄짜리 완벽한 통계 검증 코드를 다 짜두셨는데, 정작 오케스트레이터인 pipeline.py에서 이 함수를 호출(Call)하는 코드를 빼먹었습니다.

해결책: _validate() 함수 안에 validate_statistics(df) 호출 딱 한 줄만 추가하면 끝나는 아주 쉬운 작업이지만, 파급력은 시스템 전체 데이터 건전성을 좌우할 만큼 큽니다.

2. 감사 로그(Audit Log) 완전 부재 (컴플라이언스 위반)

실제 문제인가? 네, B2B 엔터프라이즈 솔루션에서 가장 치명적인 결함입니다. 감사 법인에 이 시스템을 납품하려면 ISO 27001이나 SOC 2 같은 보안 인증을 받아야 하는데, "누가 언제 로그인해서 어떤 전표를 화이트리스트 처리했는지" 남기는 DB 테이블 자체가 아예 없습니다.

해결책: schema.py에 audit_log 테이블 DDL을 추가하고, 파이프라인이 돌거나 사용자가 예외 처리를 할 때마다 INSERT 하도록 로직을 짜야 합니다.

3. 대차불일치(차변 ≠ 대변)를 경고만 하고 넘김 (회계 도메인 위반)

실제 문제인가? 네. 일반 IT 데이터면 빈칸이 있어도 경고(Warning)만 띄우고 분석을 돌려도 되지만, 회계 데이터에서 '차변과 대변의 합이 안 맞는다'는 것은 장부 자체가 깨졌다는 뜻입니다.

해결책: L2 검증 단계에서 대차불일치가 특정 기준을 넘으면, 파이프라인을 그 즉시 중단(Fatal Error)시키고 사용자에게 에러를 뿜도록 방어선을 높여야 합니다.

😌 알면서도 일단 안고 가도 되는 문제 (Can Wait - P2/P3)
실무 데이터 검증 부재: DataSynth(합성 데이터)로만 테스트해서 실전 투입이 불안하다는 지적입니다. 이건 100% 맞는 말이지만, 당장 코딩으로 해결할 수 있는 문제가 아니라 진짜 기업 데이터를 구해와야 하는 영업적/보안적 허들입니다. 일단 지금은 넘어갑니다.

문서 오기재 (18개 vs 19개 피처): 기획서엔 18개인데 코드를 세어보니 19개라는 지적입니다. 시간 날 때 문서의 숫자만 고치면 됩니다.

벤포드 법칙 점수 차등화: 벤포드 법칙에 걸린 전표들에 모두 0.4점을 일괄 부여하는 것을 더 정밀하게 나누라는 지적입니다. 좋긴 하지만 우선순위는 밀립니다.
