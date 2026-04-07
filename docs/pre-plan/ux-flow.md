# UX 데이터 흐름 & 설계 원칙 [Company-Centric — Phase 1a~1c]

> **이 문서는 전체 UX 설계의 기준 문서(Single Source of Truth)**이다.
> Company-Centric 아키텍처(TS-4) 전환 후 **"신규 회사 vs 기존 회사" 분기**가 UX 최상위 진입점이다.
> 각 모듈별 상세 구현은 하단 [교차 참조](#교차-참조-상세-문서) 링크를 참조한다.
> 아키텍처 전환 상세: [NEW_TASKS.MD](../completed/NEW_TASKS.MD) | [TROUBLESHOOT.md §TS-4](../TROUBLESHOOT.md#ts-4-글로벌-싱글톤--company-centric-전면-재설계)

---

## 전체 UX 데이터 흐름도

```
[앱 시작: 회사 선택 화면 (page_company.py)]
       ↓
┌──────────────────────────────────────────┐
│     UX 0단계: 회사/Engagement 선택        │
│        (UX 최상위 진입점)                 │
│                                          │
│   [신규 회사 등록]    [기존 회사 선택]      │
└───────┬──────────────────────┬───────────┘
        ↓                      ↓
┌─ 신규 회사 트랙 ──────┐  ┌─ 기존 회사 트랙 ──────┐
│                        │  │                        │
│ ① 회사 등록            │  │ ① 회사 선택            │
│   (company.yaml 생성)  │  │   → Engagement 선택    │
│                        │  │     (연도)              │
│ ② Engagement 생성      │  │                        │
│   (연도 지정)          │  │ ② 달라진 컬럼 확인     │
│                        │  │   (이전 매핑 대비 diff) │
│ ③ 데이터 업로드        │  │                        │
│                        │  │ ③ 데이터 업로드         │
│ ④ DataSynth 기반       │  │   (매핑 프로파일       │
│   컬럼 매칭            │  │    자동 로드)          │
│   + 사용자 직접 확인   │  │                        │
│                        │  │ ④ 신규/변경 컬럼       │
│ ⑤ 미매핑 영향 경고     │  │   경고 + 확인          │
└───────┬────────────────┘  └───────┬────────────────┘
        ↓                          ↓
━━━ 공통 UX 1단계: Ingest (타입캐스팅 + 표준화) ━━━  ← Phase 1a ✅ + UI ✅
│  ⑥ 타입 캐스팅 (자동): 금액 ZWSP/콤마/통화 제거, 날짜 통일, Null 3단계 분기
│  → 표준 DataFrame 출력
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
       ↓
━━━ 공통 UX 2단계: 감사 룰 세팅 & 파생변수 생성 ━━━  ← Phase 1a ✅ + 1c ⬜
│  신규: 스마트 디폴트 적용 (전 항목 안내, 커스터마이징 유도)
│  기존: 저장된 프로파일 자동 로드 (변경점만 확인)
│  → 18개 파생변수 일괄 생성
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
       ↓
━━━ 공통 UX 3단계: 전처리 투명성 & EDA ━━━  ← Phase 1a ⬜ + Phase 2 ⬜
│  신규: EDA 하나하나 보여주며 전처리 진행 + 기준선(Baseline) 저장
│  기존: 기존 EDA와 비교 방향으로 진행 (T-1 대비 YoY diff 강조)
│  → ML-ready DataFrame 출력
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
       ↓
━━━ 탐지 투트랙 분기 ━━━
│
│  ┌─ 신규 회사 ─────────────────────────┐
│  │ 룰기반 24개 룰 단독 (ML 데이터 부족) │
│  │ → UX 4단계: HITL + 프리셋            │
│  │ → 감사인 피드백 = ML 학습 데이터 축적 │
│  └─────────────────────────────────────┘
│
│  ┌─ 기존 회사 ─────────────────────────┐
│  │ 룰기반 + ML/DL 병행                  │
│  │ T-1, T-2 과거 데이터 대비 변동 강조   │
│  │ → UX 4단계: HITL + 연도비교 탭        │
│  └─────────────────────────────────────┘
       ↓
[CompanyContext → Engagement DuckDB → Streamlit 대시보드]
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
| 회사코드           | C001(본사), C002(울산), C003(천안) — 3법인 (실 운영 시 각 법인이 별도 company_id로 관리) |
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

### 신규 회사 vs 기존 회사 데이터 특성 차이

| 구분       | 신규 회사                                      | 기존 회사 (2년차+)                           |
|:-----------|:----------------------------------------------|:--------------------------------------------|
| 컬럼 매핑  | DataSynth 기준 자동매칭 + 수동 확인 필수        | 저장된 매핑 프로파일 자동 로드                |
| CoA        | 글로벌 CoA 폴백 또는 수동 업로드                | 회사별 `chart_of_accounts.csv` 존재          |
| 감사 룰    | 스마트 디폴트 (K-IFRS 표준)                    | 회사별 `audit_rules.yaml` 커스터마이징 완료  |
| EDA 기준선 | 없음 (첫 프로파일링)                            | T-1 EDA 프로파일과 비교 가능                 |
| ML 모델    | 불가 (데이터 부족) → 룰기반 전용                | 회사별 모델 학습 가능 (`models/` 디렉토리)   |
| 탐지 전략  | 룰기반 24개 룰 단독                            | 룰기반 + ML/DL 투트랙                        |

---

## UX 1단계: 데이터 수집 및 전처리 (Ingest) — ✅ 백엔드 + UI 구현 완료

**목적**: 다양한 형태의 ERP 엑셀/CSV 원본을 표준 DataFrame으로 변환

### 신규/기존 회사별 Ingest 분기

#### 신규 회사 Ingest 플로우

1. **회사 등록**: `page_company.py` → `CompanyRepository.create_company()` 호출
   - company_id, display_name, industry, erp_system, currency 입력
   - `data/companies/{company_id}/company.yaml` 생성
2. **Engagement 생성**: 감사 연도 선택 → `create_engagement()` 호출
   - `data/companies/{company_id}/engagements/{year}/` 디렉토리 초기화
   - `engagement.yaml`, `audit.duckdb`, `models/`, `exports/` 생성
3. **데이터 업로드 + DataSynth 기반 컬럼 매칭**:
   - `column_mapper.py`가 DataSynth 39컬럼 스키마를 기준으로 업로드된 컬럼을 자동 매칭
   - 매칭 결과를 **한 컬럼씩** 사용자에게 확인 요청 (기존 통합 드롭다운 UI 활용)
   - 사용자가 직접 지정 가능 (드롭다운 수동 선택)
4. **미매핑 컬럼 영향 경고**:
   - 필수 컬럼 미매핑: "이 컬럼 없이는 차대균형 검증이 불가합니다" → **진행 차단**
   - 권장 컬럼 미매핑: "이 분석은 어려울 수 있습니다" / "해당 회사 컬럼에 맞게 로직 재구성 필요"
   - 영향 범위를 구체적으로 명시 (기존 `_REQUIRED_REASONS`, `_RECOMMENDED_IMPACT` 활용)
5. **매핑 프로파일 저장**: `mapping_profile.save_profile()` → `data/companies/{company_id}/profiles/`

#### 기존 회사 Ingest 플로우

1. **회사 선택 + Engagement 선택**: `page_company.py` → `engagement_selector.py`
   - 기존 회사 목록에서 선택 → 연도 선택 (신규 연도 생성 가능)
2. **데이터 업로드 + 매핑 프로파일 자동 로드**:
   - `mapping_profile.load_profile()` → 이전 매핑 자동 적용
   - 사용자는 "확인" 클릭만으로 진행 가능
3. **신규/변경 컬럼 감지 (Diff)**:
   - 이전 업로드 컬럼과 현재 업로드 컬럼을 비교
   - 새로 추가된 컬럼: "신규 컬럼 N개 발견 — 매핑이 필요합니다"
   - 사라진 컬럼: "이전에 매핑된 X 컬럼이 없습니다 — 관련 탐지 룰 비활성화"
   - 달라진 컬럼(이름/타입 변경): 경고 + 재매핑 유도
4. **CompanyContext 생성**: `ContextFactory.create(company_id, engagement_id)` → 3계층 설정 해소 완료

> 신규 회사는 매핑 화면이 전체 표시되고, 기존 회사는 자동 로드 후 변경점만 표시된다.

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

### 신규/기존 회사별 룰 세팅 분기

| 구분     | 신규 회사                                              | 기존 회사                                         |
|:---------|:------------------------------------------------------|:--------------------------------------------------|
| 초기값   | 글로벌 기본값 (K-IFRS 표준 스마트 디폴트)               | 회사별 `audit_rules.yaml` + `settings_overrides`   |
| UI 모드  | 전 항목 노출 (설정 필요성 안내)                          | 변경된 항목만 하이라이트 (이전값 대비 diff)         |
| 프로파일 | 최초 저장 → Data Flywheel 시작                         | 기존 프로파일 자동 로드 → 수정만                   |
| CoA      | 글로벌 폴백 CoA 또는 수동 업로드 유도                   | 회사별 `chart_of_accounts.csv` 자동 적용           |

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
[config/audit_rules.yaml] ← 글로벌 기본값 (K-IFRS 표준, 폴백)
        ↓ 3계층 머지 (merger.py)
[data/companies/{id}/audit_rules.yaml] ← 회사별 오버라이드
        ↓ ContextFactory.create()
[CompanyContext.audit_rules] ← 해소 완료 인스턴스
        ↓
[Streamlit UI] — 감사인이 해당 회사 기준 커스터마이징
        ↓ 저장
[data/companies/{id}/profiles/] ← 매핑+감사룰 통합 프로파일
        ↓ 다음 Engagement 시 자동 로드
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

### 신규/기존 회사별 EDA 분기

#### 신규 회사 EDA

- **EDA 하나하나 보여주며 전처리 진행**: 각 컬럼별 프로파일링 결과를 순차적으로 표시
  - 컬럼별 카드: dtype, 결측률, 유니크수, 분포 히스토그램
  - 이상치 박스플롯, 상관관계 히트맵
  - 각 단계마다 사용자 확인 → "이 분포가 예상과 맞습니까?"
- **전처리 제안**: 결측률 높은 컬럼에 대해 처리 방안 안내
- **기준선(Baseline) 저장**: 이번 EDA 결과를 Engagement DB에 저장 → 다음 연도 비교 기준

#### 기존 회사 EDA

- **기존 EDA와 비교 방향으로 진행**: T-1(전년도) 프로파일과 현재 프로파일 자동 비교
  - 분포 변화 하이라이트 (KS-test p-value 등)
  - 새로 나타난 이상 패턴 강조
  - "전년 대비 결측률 X% → Y% 증가" 식 변동 알림
- **연도간 추이 시각화**: 대시보드 연도비교 탭과 연동

> 상세: [03a-preprocessing.md → UX 3단계](03a-preprocessing.md#ux-3단계-전처리-투명성)

---

## 탐지 투트랙: 룰기반 vs ML/DL

> 신규 회사와 기존 회사에서 탐지 접근법이 구조적으로 다르다.
> 이 분기는 Phase 2의 `label_strategy.select_learning_mode()`와 연동된다.

### 신규 회사 탐지 전략

```
[표준 DataFrame + 18개 파생변수]
       ↓
━━━ 룰기반 24개 룰 (Phase 1b) ━━━
│  3-Layer 탐지: A(무결성) + B(부정) + C(이상징후)
│  → anomaly_score + risk_level
       ↓
[ML/DL: 비활성]
│  사유: 과거 데이터 부족 (T=0)
│  UI 안내: "축적 데이터 부족으로 ML 탐지는 비활성화됩니다.
│            2년차부터 ML 탐지가 활성화됩니다."
       ↓
[UX 4단계: HITL 피드백]
│  → 감사인 피드백이 ML 학습 데이터로 축적됨
```

### 기존 회사 탐지 전략

```
[표준 DataFrame + 18개 파생변수]
       ↓
━━━ Track 1: 룰기반 24개 룰 ━━━
│  동일 룰, 회사별 임계값 적용 (CompanyContext.settings)
       ↓
━━━ Track 2: ML/DL (Phase 2) ━━━
│  VAE+IF (비지도) + XGBoost/LGBM (지도, 축적 데이터 활용)
│  models/ 디렉토리에 회사별 모델 저장
       ↓
━━━ 연도간 비교 강조 ━━━
│  T-1, T-2 과거 탐지 결과와 diff
│  → "전년 대비 심야 전표 +32% 증가" 식 변동 알림
│  → 신규 이상 패턴 vs 반복 이상 패턴 구분
       ↓
[UX 4단계: HITL + 연도비교 탭]
```

### 투트랙 전환 조건

| 조건                         | 탐지 모드               | UI 표시                                           |
|:-----------------------------|:-----------------------|:--------------------------------------------------|
| 신규 회사 또는 T=0            | 룰기반 단독            | "ML 탐지 비활성 — 데이터 축적 후 활성화"            |
| T=1 (첫 반복)                | 룰기반 + 비지도(VAE+IF) | "비지도 ML 활성화 — 지도학습은 데이터 추가 축적 중"  |
| T>=2 (2회 이상 반복)          | 룰기반 + 전체 ML/DL    | "전체 ML/DL 탐지 활성"                              |

---

## UX 4단계: 인터랙티브 민감도 조절 & HITL 피드백 — ⬜ Phase 1c

**목적**: 감사인이 코드/설정 파일 없이 화면에서 직접 탐지 기준을 조정하고,
오탐(False Positive)을 관리하며, 업종/시즌별 프리셋으로 즉시 전환하는 실무 UX

### A. 실시간 파라미터 튜닝 (Dynamic Threshold Tuning) — 흐름도 ⑧

`CompanyContext.settings`(3계층 해소 완료)의 AuditSettings 23개 threshold를 Streamlit 사이드바 위젯으로 노출한다.
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
Engagement별 DuckDB (`{company_id}/engagements/{year}/audit.duckdb`) whitelist 테이블에 INSERT
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

### 원칙 3: 프로파일 재사용 (One-Time Setup) → Company-Centric 자동 재사용

초기 설정 비용을 **회사별 프로파일 자동 저장 → Engagement 간 재사용** 구조로 상쇄한다.
동일 회사의 반복 감사(T+1) 시 `CompanyContext`가 이전 설정을 자동 로드하여 설정 단계를 최소화한다.

- UI 안내 문구: "현재 설정은 {display_name} 회사 프로파일로 저장됩니다. 다음 감사 연도에 자동 적용됩니다."
- `mapping_profile`(컬럼 매핑) + `audit_rules`(감사 기준) + `settings_overrides`(임계값) 통합
- 저장 경로: `data/companies/{company_id}/` 하위

**적용 위치:**

| UX 단계 | 적용 항목                                                           |
|:--------|:-------------------------------------------------------------------|
| 1단계   | `data/companies/{id}/profiles/` — 컬럼 매핑 회사별 자동 저장/로드   |
| 2단계   | `data/companies/{id}/audit_rules.yaml` — 회사별 감사 룰 영속       |
| 3단계   | Engagement DB에 EDA 기준선 저장 → 다음 연도 비교 기준               |
| 4단계   | Engagement DB whitelist — 회사-연도별 오탐 예외 축적                |

---

## UX 단계별 요약

| UX 단계 | 목적                       | 신규 회사                          | 기존 회사                            | Phase          |
|:--------|:---------------------------|:-----------------------------------|:-------------------------------------|:---------------|
| 0단계   | 회사/Engagement 선택        | 회사 등록 + Engagement 생성         | 회사 선택 + Engagement 선택/생성      | RC-0~4 ✅      |
| 1단계   | 데이터 수집 투명성           | DataSynth 기반 전체 컬럼 매칭       | 매핑 자동 로드 + 변경 컬럼 diff       | 1a ✅ + UI ✅  |
| 2단계   | 감사 룰 세팅 + 파생변수      | 스마트 디폴트 전 항목 안내           | 저장 프로파일 로드 + 변경점 확인      | 1a ✅ + 1c ⬜  |
| 3단계   | 전처리 투명성 + EDA          | 컬럼별 순차 EDA + 기준선 저장       | T-1 대비 비교 EDA + 변동 강조         | 1a ⬜ + 2 ⬜   |
| 탐지    | 이상탐지 (투트랙)            | 룰기반 24개 단독                    | 룰기반 + ML/DL + 연도간 비교          | 1b ✅ + 2 ⬜   |
| 4단계   | 민감도 조절 + HITL + 프리셋  | HITL 피드백 → ML 데이터 축적        | HITL + 연도비교 탭 + ML 재학습        | 1c ⬜          |

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
| [NEW_TASKS.MD](../completed/NEW_TASKS.MD)      | TS-4 Company-Centric 아키텍처 전환 태스크 (RC-0~5)             |
| [context.py](../../src/context.py)              | CompanyContext + ContextFactory 구현                             |
| [company/repository.py](../../src/company/repository.py) | 회사/Engagement CRUD, 디렉토리 구조                     |
| [company/models.py](../../src/company/models.py) | CompanyProfile, EngagementProfile Pydantic 모델               |
