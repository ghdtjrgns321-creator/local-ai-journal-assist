# UX 데이터 흐름 & 설계 원칙 [공통 — Phase 1a~1c]

> **이 문서는 전체 UX 설계의 기준 문서(Single Source of Truth)**입니다.
> 각 모듈별 상세 구현은 하단 [교차 참조](#교차-참조-상세-문서) 링크를 따라가세요.

---

## 전체 UX 데이터 흐름도

```
[사용자 파일 업로드]
       ↓
━━━ UX 1단계: 데이터 수집 및 전처리 (Ingest) ━━━  ← Phase 1a ✅ + UI ✅
│  ① 파일 업로드 (메인 영역) + 데이터 미리보기 (Top 10)
│     └ 인코딩 수동 선택 (confidence < 0.7 시) + 데이터 시트 선택
│  ② 통합 매핑 드롭다운 (좌우 분할: 왼쪽 매핑 / 오른쪽 미리보기)
│     └ 한글 라벨 + 필수 우선 정렬 + 샘플값 3개 표시
│     └ 매핑 엄격도 슬라이더 + 중복 금액 퀵픽스
│     └ 미매핑 영향 통합 expander (필수+권장 합침)
│  ③ 타입 캐스팅 (자동 완료)
│     └ 금액 ZWSP/콤마/통화 제거, 날짜 포맷 통일, Null 3단계 분기
│  → 표준 DataFrame 출력 → 4탭 대시보드 자동 전환
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
       ↓
━━━ UX 2단계: 감사 룰 세팅 & 파생변수 생성 (Feature) ━━━  ← Phase 1a ✅ (엔진) + Phase 1c ⬜ (UI)
│  ④ 감사 룰 조종석 (Control Panel) 세팅
│     └ 시간 기준: 심야 시간대(22~06), 기말 마진(5일)
│     └ 금액 기준: 다단계 승인 한도(6레벨), Z-score(3.0)
│     └ 패턴/키워드: 수기 전표 코드, 가계정/위험 키워드
│     └ 저장된 프로파일 로드 가능
│  ⑤ 파생변수 생성 (자동)
│     └ 4개 피처 엔진 → 18개 파생변수 일괄 생성
│       ├ time_features (6개): is_weekend, is_after_hours, is_period_end, ...
│       ├ amount_features (5개): is_near_threshold, amount_zscore, ...
│       ├ pattern_features (5개): is_manual_je, first_digit, ...
│       └ text_features (2개): has_risk_keyword, description_quality
│  → 피처 보강된 DataFrame 출력
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
       ↓
━━━ UX 3단계: 전처리 투명성 & EDA (Preprocessing) ━━━  ← Phase 1a ⬜ (EDA) + Phase 2 ⬜ (ML Pipeline)
│  ⑥ EDA 프로파일링 (Phase 1a)
│     └ 전체 수준: 행수, 컬럼수, 메모리, 중복행
│     └ 컬럼별: dtype, 결측률, 유니크수, 분포
│  ⑦ 전처리 설정 패널 (Phase 2)
│     └ 결측치/인코딩/스케일링 옵션 — 기본값 자동 적용 + 변경 가능
│     └ Pipeline별 성능 비교 (F1/AUC)
│  → ML-ready DataFrame 출력
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
       ↓
━━━ UX 4단계: 인터랙티브 민감도 조절 & HITL 피드백 ━━━  ← Phase 1c ⬜
│  ⑧ 실시간 파라미터 튜닝 (Dynamic Threshold Tuning)
│     └ 사이드바 슬라이더로 탐지 기준 조정 → 즉시 결과 갱신
│  ⑨ 화이트리스트 & HITL 피드백 (Mark as False Positive)
│     └ AgGrid 체크박스로 오탐 전표 예외 처리 → DuckDB whitelist 저장
│  ⑩ 산업별/시즌별 프리셋 (Environment Presets)
│     └ 드롭다운 선택만으로 기준값 세트 일괄 전환
│  → 감사인 맞춤 탐지 결과 출력
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
       ↓
[Detection → DuckDB → Streamlit 대시보드]
```

---

## 대상 데이터 프로파일

> DataSynth v1.2.0 기준. 실 감사 데이터는 규모·컬럼이 다를 수 있으나, UX 설계의 기준선으로 사용한다.
> 상세: [generation_principles.md](../../data/journal/primary/datasynth/generation_principles.md), [PREVIEW.md](../../data/journal/primary/datasynth/PREVIEW.md)

### 데이터 규모

| 항목               | 값                                            |
|:-------------------|:----------------------------------------------|
| 전표(document_id)  | 106,489건                                     |
| 라인아이템         | 1,104,914건 (전표당 평균 10.4라인)            |
| 컬럼               | 39개 (필수 10 + 권장 11 + 레이블 6 + 라인 12) |
| 파일 크기          | 319 MB                                        |
| 회사코드           | C001(본사), C002(울산), C003(천안) — 3법인    |
| 통화               | KRW (단일)                                    |
| 회계연도           | 2022 (1~12월)                                 |

### 스키마 3계층 (config/schema.yaml)

| 계층      | 컬럼 수 | 매핑 필수 여부 | 주요 컬럼                                                  |
|:----------|:--------|:--------------|:----------------------------------------------------------|
| 필수      | 10개    | 진행 차단     | document_id, company_code, posting_date, document_type, gl_account, debit/credit_amount 등 |
| 권장      | 11개    | 경고 + 룰 비활성화 | created_by, source, business_process, approved_by, reference 등 |
| 레이블    | 6개     | 무시 (실 감사 데이터에 없음) | is_fraud, fraud_type, is_anomaly, anomaly_type, sod_violation, sod_conflict_type |
| 라인      | 12개    | 선택          | line_number, local_amount, cost_center, line_text, trading_partner 등 |

### 비즈니스 프로세스 비중

```
R2R  26.5%   결산(SA/IC) — controller 87%, manager 76% 집중
O2C  25.9%   매출(WL→DR→DZ)
P2P  23.3%   매입(WE→KR→KZ) — 3-Way Matching 95%
H2R   8.9%   급여(HR)
TRE   8.5%   자금(KZ/SA) — Junior 접근 불가
A2R   6.9%   자산(AA)
```

### 사용자 페르소나 & 전표 소스

```
페르소나              전표 비율    소스               비율
automated_system      68.0%       Automated          61.8%
junior_accountant     12.8%       Manual             29.4%
senior_accountant      9.6%       Recurring           6.2%
controller             4.9%       Adjustment          2.6%
manager                4.8%
```

### 이상징후·부정·통제 비율 (UX 예상 알림량)

| 지표              | 건수    | 비율   | UX 영향                              |
|:------------------|:--------|:-------|:-------------------------------------|
| 이상징후 전표     | 8,001   | 7.5%   | 탐지 결과 목록의 기본 볼륨           |
| 부정 전표         | 2,046   | 1.9%   | 고위험 플래그 대상                   |
| SoD 위반          | 12,419  | 11.7%  | 통제 위반 탭 대상                    |
| 차대변 불일치     | 45      | 0.04%  | A01 무결성 검증 대상                 |

### 시계열 특성 (탐지 기준 캘리브레이션용)

```
시간대              비율     탐지 관련
새벽(0~6)           0.8%    C03 심야 전기(22~06) 기준 시 야근대 포함 → 예상 탐지량 ~1,700건
오전피크(8:30~11:30) 36.8%   정상 업무 시간
마감러시(16~18:30)  22.1%   정상 업무 시간
야근(18:30~22)       8.1%   경계 영역
주말                 9.5%    C02 주말 기표 — ~10,098건
12월(연말 결산)     ×1.4    결산기 프리셋 근거
```

---

## UX 1단계: 데이터 수집 및 전처리 (Ingest) — ✅ 백엔드 + UI 구현 완료

**목적**: 다양한 형태의 ERP 엑셀/CSV 원본을 표준 DataFrame으로 변환

### 화면 레이아웃

```
┌─────────────────────────────────────────────────────────┐
│  메인 영역 (전체 너비)                                   │
│                                                         │
│  [파일 업로드 위젯]                                      │
│       ↓ 업로드 완료                                      │
│  ┌─────────────────┬───────────────────────────────────┐ │
│  │  왼쪽: 매핑 UI  │  오른쪽: 데이터 미리보기 (Top 10)  │ │
│  │                 │                                   │ │
│  │  통합 드롭다운  │  원본 데이터 테이블               │ │
│  │  (필수→권장→   │  (전체 N행 × M열)                 │ │
│  │   기타 정렬)   │                                   │ │
│  │                 │                                   │ │
│  │  [미매핑 영향]  │                                   │ │
│  │  (접힌 expander)│                                   │ │
│  │                 │                                   │ │
│  │  [매핑 확인]    │                                   │ │
│  └─────────────────┴───────────────────────────────────┘ │
│       ↓ 매핑 확인 후                                      │
│  파이프라인 실행 → 4탭 대시보드로 전환                     │
└─────────────────────────────────────────────────────────┘
```

### 흐름

1. **파일 업로드 (메인 영역)**: 사용자가 메인 화면에서 원본 파일을 업로드한다.
   인코딩 감지 신뢰도가 낮으면(< 0.7) **[인코딩 수동 선택]** UI를 노출하고,
   멀티시트 파일이면 **[데이터 시트 선택]** UI를 제공한다.

2. **데이터 미리보기 + AI 매핑 (좌우 분할)**:
   오른쪽에 원본 데이터 상위 10행을 표시하여 컬럼 구조를 파악할 수 있게 한다.
   왼쪽에 통합 매핑 드롭다운을 표시한다.
   - 드롭다운 선택지는 **필수 → 권장 → 나머지** 순으로 정렬
   - 한글 라벨 포함: `전표번호 (document_id) ★필수`
   - 샘플 값 3개 표시: `[JE2025-0001, JE2025-0002, JE2025-0003…] 전표번호 →`
   - 이미 매핑된 컬럼은 다른 드롭다운에서 자동 제외 (중복 방지)

3. **미매핑 영향 안내 (접힌 expander)**:
   필수/권장 미매핑 항목을 하나의 expander로 합쳐 표시한다.
   - 필수: "전기일자 (posting_date) — 주말(C02)·심야(C03)·백데이팅(C04) 전부 비활성"
   - 권장: "작성자 (created_by) — B06 자기승인 · B07 SoD 위반 탐지 비활성화"

4. **타입 캐스팅 (자동)**: 매핑 확정 후 `type_caster.py`가
   금액 포맷 정규화(콤마/통화기호/ZWSP 제거), 날짜 포맷 통일, Null 분류를 수행한다.

5. **결과 화면 전환**: 파이프라인 완료 후 4탭 대시보드로 자동 전환.
   상단에 "다른 파일 분석" 버튼으로 업로드 화면 복귀 가능.

### 구현 상태

| 구현 항목                                    | 상태 | 위치                                        |
|:---------------------------------------------|:-----|:-------------------------------------------|
| 5단계 파일 검증                              | ✅   | `file_validator.py`                        |
| 10개 확장자 읽기 + python 엔진 폴백          | ✅   | `reader_api.py`, `text_reader.py`          |
| Sniffer 검증 + prescan 컬럼 수 파악          | ✅   | `text_reader._detect_separator`, `_prescan_max_columns` |
| 구조적 헤더 탐지 (v2)                        | ✅   | `header_detector.py`                       |
| Fuzzy+타입검증 컬럼 매핑 (v2)                | ✅   | `column_mapper.py`                         |
| 5단계 타입 캐스팅 + ZWSP 제거 + Null 3분기   | ✅   | `type_caster.py`                           |
| 매핑 프로파일 저장/로드                       | ✅   | `mapping_profile.py`                       |
| ReviewItem 투명성 모델                        | ✅   | `models.py:ReviewItem`                     |
| 인코딩 오버라이드 + confidence                | ✅   | `text_reader.py`                           |
| 시트 품질 스코어링                            | ✅   | `sheet_scorer.py`                          |
| 중복 금액 퀵픽스                              | ✅   | `column_mapper._suggest_amount_split()`    |
| 메인 영역 업로드 + 좌우 분할 레이아웃         | ✅   | `data_uploader.py`                         |
| 통합 매핑 드롭다운 (한글 라벨 + 필수 정렬)    | ✅   | `mapping_review.py`                        |
| 데이터 미리보기 (Top 10)                      | ✅   | `data_uploader._render_review_with_preview()` |
| 미매핑 영향 통합 expander                     | ✅   | `mapping_review.py`                        |
| 차트 컬럼 guard (누락 시 빈 차트)             | ✅   | `risk_charts.py` 외 6개 차트 모듈          |
| 스트레스 테스트 (28파일 64케이스)             | ✅   | `tests/phase1_ingest/` (64 passed)         |

### 매핑 대상 스키마 & 미매핑 시 동작

매핑 대상은 `config/schema.yaml`에 정의된 39개 컬럼이며, 3계층으로 분류된다.
([대상 데이터 프로파일 → 스키마 3계층](#스키마-3계층-configschemayaml) 참조)

| 계층   | 미매핑 시 동작                                                                    |
|:-------|:---------------------------------------------------------------------------------|
| 필수   | **진행 차단** — 미매핑 컬럼명 + 사유("차변/대변 금액 없이 차대균형 검증 불가" 등) 안내 |
| 권장   | **경고** — "created_by 미매핑 → B06 자기승인·B07 SoD 탐지 비활성화" 식으로 영향 범위 표시 |
| 레이블 | **무시** — DataSynth 전용 컬럼(is_fraud 등). 실 감사 데이터에는 존재하지 않으므로 매핑 UI에서 숨김 |
| 라인   | **선택** — 누락 시 해당 라인 피처(cost_center별 분석 등) 생략                      |

### UI 스펙 (8건)

| UI 요소                              | 트리거                              | 백엔드 연동                                |
|:-------------------------------------|:------------------------------------|:------------------------------------------|
| UI-1. 인코딩 드롭다운                | `encoding_confidence < 0.7`         | `read_file(encoding_override=)`           |
| UI-2. 시트 선택 테이블               | 멀티시트 Excel                      | `sheet_scorer.score_sheets()`             |
| UI-3. Fuzzy 엄격도 슬라이더         | 매핑 확인 UI                        | `auto_map_columns(settings_override=)`    |
| UI-4. 중복 금액 퀵픽스 버튼         | 인접 '금액' 2개 감지                | `_suggest_amount_split()` → ReviewItem    |
| UI-5. 데이터 미리보기 (Top 10)       | 파일 업로드 후                      | `data_df.head(10)` + source_columns       |
| UI-6. 통합 매핑 드롭다운 (한글 라벨) | 매핑 확인 UI                        | `_COLUMN_LABELS` + `_format_option()`     |
| UI-7. 미매핑 영향 통합 expander      | 필수/권장 미매핑 존재 시            | `_REQUIRED_REASONS` + `_RECOMMENDED_IMPACT` |
| UI-8. 드롭다운 필수 우선 정렬        | 매핑 확인 UI                        | `_sort_options(required→recommended→etc)` |

> 상세: [02-ingest.md → Phase 1c UI 스펙](02-ingest.md#phase-1c-ui-스펙--피드백-반영-4건)

---

## UX 2단계: 감사 룰 세팅 & 파생변수 생성 (Feature) — ✅ 엔진 구현 완료, ⬜ UI 예정

**목적**: 표준 DataFrame에 감사 도메인 기준(시간/금액/패턴/텍스트)을 적용하여 이상탐지용 파생변수를 생성

### 감사 룰 조종석 (Control Panel) 세팅

전처리 완료된 데이터를 대상으로 분석 기준을 설정한다.

| 카테고리     | 설정 항목                                            | 기본값 (스마트 디폴트)                 | DataSynth 실측 참고               |
|:-------------|:----------------------------------------------------|:--------------------------------------|:----------------------------------|
| 시간 기준    | 심야 기표 시간대                                     | 22:00 ~ 06:00                         | 심야 0.8% (~850건)                |
|              | 기말 판정 마진                                       | 5일                                    | 월말 ×2.5, 분기말 ×4.0 스파이크   |
| 금액 기준    | 다단계 승인 한도 (6레벨)                             | 1천만→1억→10억→50억→100억→500억        | 한국 중견 제조업 전결규정 기반     |
|              | 임계값 직하 비율 (near_threshold_ratio)              | 0.90                                   | B02 분할승인회피 282건             |
|              | 이상치 Z-score 임계값                                | 3.0                                    | LogNormal(μ=14, σ=2.5) 분포      |
|              | round 금액 판정 단위                                 | 100만 원                               | 라운드넘버 25%, Nice number 15%   |
| 패턴/키워드  | 수기 전표 코드                                       | `audit_rules.yaml` 로드               | Manual 29.4%, Adjustment 2.6%     |
|              | 매출 계정 prefix                                     | `["4"]`                                | O2C 25.9%, 4000~4020 계정         |
|              | 가계정/위험 키워드 리스트                             | `risk_keywords.yaml` 로드             |                                   |
|              | 관계사 식별자                                        | 빈 리스트 (고객사별 입력)              | IC 98쌍, C001↔C002↔C003          |

> **다단계 승인 한도**: 기존 단일값(5천만)에서 settings.py `approval_thresholds` 6단계 리스트로 변경.
> UI에서는 Level별 슬라이더 또는 테이블 편집기로 노출한다.
> 상세: [generation_principles.md §11 승인 한도 체계](../../data/journal/primary/datasynth/generation_principles.md)

### 파생변수 생성 (자동)

설정값을 4개의 피처 엔진이 수신하여 **18개 파생변수**를 DataFrame에 일괄 추가한다.

| 엔진              | 변수 수 | 주요 변수                                                | 대응 룰           |
|:------------------|:--------|:---------------------------------------------------------|:-----------------|
| time_features     | 6개     | is_weekend, is_after_hours, is_period_end, ...           | C01~C05          |
| amount_features   | 5개     | is_near_threshold, amount_zscore, is_round_number, ...   | B02~B04, C08     |
| pattern_features  | 5개     | is_manual_je, first_digit, is_suspense_account, ...      | B01,B08~B11, C07 |
| text_features     | 2개     | has_risk_keyword, description_quality                    | C06              |

### Data Flywheel (audit_rules.yaml ↔ UI ↔ Profile)

```
[config/audit_rules.yaml] ← 기본값 (K-IFRS 표준)
        ↓ 로드
[Streamlit UI] — 감사인이 고객사별 커스터마이징
        ↓ 저장
[data/profiles/customer_A.json] ← mapping_profile + audit_rules 통합
        ↓ 다음 감사 시 자동 로드
```

> 상세: [03-feature.md → Data Flywheel](03-feature.md#d-phase-1c-data-flywheel-audit_rulesyaml--ui--profile)

---

## UX 3단계: 전처리 투명성 & EDA (Preprocessing) — ⬜ 구현 예정

**목적**: 데이터 현황을 투명하게 보여주고, ML Pipeline 전처리 과정을 사용자가 확인·변경할 수 있게 하는 과정

| 항목                     | Phase   | 내용                                                         |
|:-------------------------|:--------|:------------------------------------------------------------|
| EDA 프로파일링           | 1a      | `profiler.py` → 행수/컬럼수/결측률/분포/이상치 프로파일     |
| 대시보드 EDA 탭          | 1c      | 프로파일링 결과 시각화 (컬럼 카드, 히트맵, 박스플롯)         |
| sklearn Pipeline 설정    | 2       | 결측치/인코딩/스케일링 옵션 — 기본값 자동 + 변경 UI         |
| Pipeline 성능 비교       | 2       | F1/AUC 바 차트 + 신뢰구간                                    |
| LLM 전처리 제안          | 3       | EDAProfile(JSON) → Ollama → 전처리 전략 추천                 |

> 상세: [03a-preprocessing.md → UX 3단계](03a-preprocessing.md#ux-3단계-전처리-투명성)

---

## UX 4단계: 인터랙티브 민감도 조절 & HITL 피드백 — ⬜ Phase 1c

**목적**: 감사인이 코드/설정 파일 없이 화면에서 직접 탐지 기준을 조정하고,
오탐(False Positive)을 관리하며, 업종/시즌별 프리셋으로 즉시 전환하는 실무 UX

### A. 실시간 파라미터 튜닝 (Dynamic Threshold Tuning) — 흐름도 ⑧

`config/settings.py`의 AuditSettings 23개 threshold를 Streamlit 사이드바 위젯으로 노출한다.
슬라이더 조작 → AuditSettings 오버라이드 → 탐지 재실행 → 차트/표 즉시 갱신.

| 설정 키                          | 기본값                          | 룰      | 위젯 형태          | 범위                |
|:---------------------------------|:-------------------------------|:--------|:-------------------|:-------------------|
| `midnight_start`                 | 22                             | C03     | `st.slider`        | 0 ~ 24             |
| `midnight_end`                   | 6                              | C03     | `st.slider`        | 0 ~ 8              |
| `approval_thresholds`            | [10M,100M,1B,5B,10B,50B]      | B02/B03 | 테이블 편집기      | Level별 자유 입력  |
| `near_threshold_ratio`           | 0.90                           | B02     | `st.slider`        | 0.80 ~ 0.99        |
| `zscore_threshold`               | 3.0                            | B01/C08 | `st.slider`        | 2.0 ~ 5.0          |
| `backdated_threshold_days`       | 30                             | C04     | `st.slider`        | 7 ~ 90              |
| `period_end_margin_days`         | 5                              | C01     | `st.slider`        | 1 ~ 15              |
| `benford_mad_threshold`          | 0.012                          | C07     | `st.slider`        | 0.006 ~ 0.025      |
| `round_unit`                     | 1,000,000                      | B04     | `st.selectbox`     | 10만 ~ 1,000만     |
| `duplicate_payment_window_days`  | 30                             | B04     | `st.slider`        | 7 ~ 90              |
| `sod_process_threshold`          | 3                              | B07     | `st.slider`        | 2 ~ 5               |
| `account_pair_rare_percentile`   | 0.01                           | C09     | `st.slider`        | 0.005 ~ 0.05        |
| `period_end_amount_quantile`     | 0.75                           | C01     | `st.slider`        | 0.50 ~ 0.95         |

**구현 패턴:**
- `dashboard/components/threshold_sidebar.py` 신규 생성
- AuditSettings를 복사 → 슬라이더 값으로 오버라이드 → `session_state`에 캐싱
- 값 변경 시 feature + detection 재실행 (DuckDB 재적재 포함)
- [원칙 2: 점진적 공개](#원칙-2-점진적-공개-progressive-disclosure) 적용: `st.expander("⚙️ 탐지 기준 상세 설정", expanded=False)` 안에 배치

**기반 아키텍처 (이미 완성):**
```
config/settings.py (Pydantic BaseSettings, 23개 threshold)
        ↓
    AuditSettings 인스턴스 (get_settings())
        ↓
    generate_all_features(settings=s)  ← 명시적 파라미터 주입, 하드코딩 0개
        ↓
    detection layers (settings=s)     ← 동일 패턴
```

### B. 화이트리스트 & HITL 피드백 루프 (Mark as False Positive) — 흐름도 ⑨ ✅

탐지 결과에서 감사인이 "정상"으로 판정한 전표를 예외 처리하여 영구적으로 알람에서 제외한다.

**동작 흐름:**

```
[tab_explorer: AgGrid 이상 전표 목록]
       ↓ 사용자가 "예외 처리" 체크박스 선택
[예외 저장] 버튼 클릭
       ↓
DuckDB whitelist 테이블에 INSERT
  (batch_id, document_id, rule_code, reason, created_by, created_at)
       ↓
다음 탐지 실행 시 anomaly_flags에서 whitelist ANTI JOIN으로 제외
       ↓
감사인이 정상 판정한 패턴은 반복 알람 발생하지 않음
```

**DB 스키마 (`src/db/schema.py`에 구현 완료):**

| 컬럼           | 타입        | 설명                                 |
|:--------------|:-----------|:------------------------------------|
| `id`          | INTEGER PK | 자동 증가                            |
| `batch_id`    | VARCHAR    | 업로드 배치 식별자                    |
| `document_id` | VARCHAR    | 예외 처리된 전표 번호                 |
| `rule_code`   | VARCHAR    | 예외 대상 룰 (예: "B02", "C03")      |
| `reason`      | VARCHAR    | 감사인 기입 예외 사유                 |
| `created_by`  | VARCHAR    | 예외 처리자                          |
| `created_at`  | TIMESTAMP  | 예외 처리 시점 (DEFAULT current_timestamp) |

### C. 산업별/시즌별 프리셋 (Environment Presets) — 흐름도 ⑩

감사인이 개별 슬라이더를 조작하지 않아도, 드롭다운 선택만으로 적절한 기준값 세트를 일괄 적용한다.

**기본 제공 프리셋:**

| 프리셋       | 주요 변경 항목                                                                  | 대상 시나리오           | 실측 근거                                        |
|:------------|:------------------------------------------------------------------------------|:----------------------|:------------------------------------------------|
| 평시 모드    | 기본값 그대로                                                                  | 일반 감사              | —                                                |
| 결산기 모드  | `midnight_start`=2, `zscore_threshold`=4.0, `period_end_margin_days`=10       | 결산기(12월/3월) 감사  | 12월 ×1.4 볼륨, 야근 8.1% → 22~02시 전표를 정상 허용 |
| 건설업 모드  | `period_end_margin_days`=10, `round_unit`=10,000,000                          | 건설/조선 대형 프로젝트 | 대형 공사 선급금·기성 특성                        |

**구현 패턴:**
- `config/presets/` 디렉토리에 YAML 파일로 프리셋 정의
- `load_preset(name) → AuditSettings` 반환
- `dashboard/components/preset_selector.py` — `st.selectbox`에서 프리셋 선택 → 슬라이더 값 일괄 갱신
- 사용자 커스텀 프리셋 저장/로드 (원칙 3 "프로파일 재사용"과 통합)

> 상세: [07-dashboard.md → threshold_sidebar](07-dashboard.md#componentsthreshold_sidebarpy--실시간-임계값-튜닝-ux-4단계-a), [preset_selector](07-dashboard.md#componentspreset_selectorpy--산업별시즌별-프리셋-ux-4단계-c)

---

## UX 설계 배경: 감사 업무의 두 가지 상충 요구

감사 도구 UX는 **통제 요구와 간결성 요구가 상충**하는 환경에서 설계되어야 한다.

### 1. 통제 요구 — 판단 근거의 투명성

감사인은 분석 결과에 대해 최종 책임을 진다(PCAOB AS 1201, 감사인의 전문가적 판단).
따라서 AI가 자동 처리한 항목이라도 **판단 근거와 신뢰도를 확인·수정할 수 있어야** 도구를 신뢰한다.
통제권이 없는 블랙박스 도구는 감리 리스크 때문에 실무에서 채택되지 않는다.

→ **대응**: ReviewItem에 판단 근거(reason) + 신뢰도(confidence) 투명 노출.
모든 매핑·설정에 사용자 오버라이드 제공.

### 2. 간결성 요구 — 초기 설정 부담 최소화

반면, 업로드 직후 10개 이상의 설정 항목을 요구하면 기존 도구(Excel 피벗) 대비 이점이 사라진다.
설정 항목이 많을수록 사용자 이탈률이 높아지므로, **최소한의 입력으로 즉시 분석을 시작**할 수 있어야 한다.

→ **대응**: 스마트 디폴트 + 점진적 공개로 초기 진입 장벽 최소화.

---

## 3가지 UX 디자인 원칙

Phase 1c (Streamlit UI) 구현 시 적용할 원칙. 위 두 가지 상충 요구를 동시에 충족하는 설계 전략.

### 원칙 1: 스마트 디폴트 (Smart Defaults)

사용자 입력 없이 **[다음] 버튼만으로 전체 파이프라인이 실행**되어야 한다.
모든 설정 항목에 업계 표준 기본값을 사전 적용한다.

- 승인 한도: 6단계(1천만~500억) / Z-score: 3.0 / 매출 계정 prefix: 4 / 인코딩: Auto
- 기본값만으로 유의미한 분석 결과를 제공 → 사용자가 필요에 따라 조정

**적용 위치:**

| UX 단계 | 적용 항목                                                    |
|:--------|:------------------------------------------------------------|
| 1단계   | 인코딩=Auto, 시트=최고점수 자동선택, fuzzy_threshold=80/40, 드롭다운 기본값=추천값 |
| 2단계   | `config/settings.py`의 모든 설정에 업계 표준 기본값           |
| 3단계   | 전처리 옵션 자동 선택 — 결측치→중앙값, 스케일링→StandardScaler |

### 원칙 2: 점진적 공개 (Progressive Disclosure)

설정 UI를 **기본/전문가 2계층**으로 분리하여 초기 인지 부하를 줄인다.

- **기본 모드 (Basic)**: 파일 업로드 + 시트 선택 + 저신뢰 컬럼 매핑 확정 → 즉시 분석 시작
- **전문가 모드 (Advanced)**: 접이식 패널(Accordion) 내부에 배치
  - Z-score 민감도, Benford 단위, 수기 전표 코드, 가계정 키워드 등

**적용 위치:**

| UX 단계 | 적용 항목                                                    |
|:--------|:------------------------------------------------------------|
| 1단계   | confidence ≥ 0.7이면 인코딩 드롭다운 숨김, 미매핑 영향은 접힌 expander |
| 2단계   | 기본=디폴트 사용 / Advanced=audit_rules 직접 편집             |
| 3단계   | EDA 요약만 기본 노출 / Pipeline 옵션은 접이식                 |

### 원칙 3: 프로파일 재사용 (One-Time Setup)

초기 설정 비용을 **프로파일 저장 → 재사용** 구조로 상쇄한다.
동일 고객사의 반복 감사 시 이전 설정을 자동 로드하여 설정 단계를 최소화한다.

- UI 안내 문구: "현재 설정은 프로파일로 저장됩니다. 이후 감사 시 자동 적용됩니다."
- `mapping_profile`(컬럼 매핑) + `audit_rules`(감사 기준) 통합 프로파일

**적용 위치:**

| UX 단계 | 적용 항목                                                    |
|:--------|:------------------------------------------------------------|
| 1단계   | `mapping_profile.save_profile()` — 컬럼 매핑 자동 저장/로드  |
| 2단계   | `audit_rules` 고객사별 프로파일 저장 (Data Flywheel)          |
| 3단계   | Pipeline 설정 프로파일 (Phase 2)                              |

---

## UX 단계별 요약

| UX 단계 | 목적                            | Phase 구현          | 투명성 모델                              | 상세 문서                                     |
|:--------|:--------------------------------|:--------------------|:----------------------------------------|:---------------------------------------------|
| 1단계   | 데이터 수집 투명성              | 1a ✅ + UI ✅       | ReviewItem + 통합 드롭다운 + 미리보기    | [02-ingest.md](02-ingest.md)                 |
| 2단계   | 감사 룰 세팅 + 파생변수         | 1a ✅ + 1c UI ⬜    | audit_rules.yaml + settings + profile   | [03-feature.md](03-feature.md)               |
| 3단계   | 전처리 투명성 + EDA             | 1a ⬜ + 2 ⬜        | EDAProfile(JSON) + Pipeline 설정         | [03a-preprocessing.md](03a-preprocessing.md) |
| 4단계   | 민감도 조절 + HITL + 프리셋     | 1c (B ✅ / A,C ⬜)  | AuditSettings 오버라이드 + whitelist 테이블 ✅ + preset YAML | [07-dashboard.md](07-dashboard.md)           |

---

## 교차 참조: 상세 문서

| 문서                                           | UX 관련 내용                                                    |
|:-----------------------------------------------|:---------------------------------------------------------------|
| [02-ingest.md](02-ingest.md)                   | UX 1단계 상세 구현, ReviewItem, Phase 1c UI 스펙 4건            |
| [03-feature.md](03-feature.md)                 | UX 2단계 엔진, 18개 파생변수, Data Flywheel, audit_rules       |
| [03a-preprocessing.md](03a-preprocessing.md)   | UX 3단계 EDA 프로파일링, ML Pipeline 전처리 투명성              |
| [07-dashboard.md](07-dashboard.md)             | Streamlit 5탭 UI 설계, UX 1단계 잔여 과제, UX 4단계 컴포넌트    |
| [DECISION.md](../DECISION.md)                  | D016: UX 1단계 설계 결정 로그                                   |
| [generation_principles.md](../../data/journal/primary/datasynth/generation_principles.md) | 비즈니스 프로세스 흐름, 페르소나, 이상징후 주입 전략, 승인 한도 |
| [PREVIEW.md](../../data/journal/primary/datasynth/PREVIEW.md) | 39개 컬럼 사전, 전표유형↔프로세스 매핑, 분포 요약              |
| [schema.yaml](../../config/schema.yaml)        | 매핑 대상 표준 스키마 (필수 10 + 권장 11 + 레이블 6 + 라인 12) |
