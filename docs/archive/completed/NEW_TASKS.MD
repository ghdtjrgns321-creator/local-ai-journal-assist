# Company-Centric 아키텍처 재설계 태스크

> 기존 "범용 단일 파이프라인"을 "회사별 독립 파이프라인"으로 전면 재설계한다.
> 기존 `docs/TASKS.md`의 Phase 1a/1b 완료 작업물을 최대한 재사용하되, 구조적 전환을 수행한다.

## 1. 목적

### 현재 문제

현재 프로젝트는 **글로벌 싱글톤 설정 구조**로, 모든 회사가 동일한 임계값/룰/CoA를 공유한다.

| 구성요소                    | 현재 구조                           | 문제점                                              |
|-----------------------------|-------------------------------------|-----------------------------------------------------|
| `config/settings.py`        | `@lru_cache` 싱글톤 1개 인스턴스    | 회사별 승인한도, z-score 임계값 등 분리 불가         |
| `config/audit_rules.yaml`   | 글로벌 1개 파일                     | 수기전표 코드, SoD 규칙이 회사마다 다름              |
| `config/chart_of_accounts`  | 글로벌 1개 CSV                      | 회사마다 계정과목표가 다름                           |
| `config/keywords.yaml`      | 글로벌 1개 파일                     | ERP별 컬럼 별칭이 회사마다 다름                      |
| DB                          | `batch_id` 기반 격리                | 회사-연도 차원 분석 불가, 연도 비교 불가             |
| ML 모델 (Phase 2)           | 범용 1개 예정                       | 회사 특유 패턴 학습 불가                             |
| 매핑 프로파일               | fingerprint 기반 (회사 연결 없음)   | 같은 회사의 반복 업로드를 식별 못 함                 |

### 목표 상태

**"회사별로 대응하고 저장"** — 감사 실무의 Engagement File 개념 도입.

- **A회사 (신규)**: 신규 컬럼 매핑 → 회사 특유 설정/룰/CoA 적용 → 회사 전용 DB 저장
- **B회사 (3년차)**: 1~2년차 매핑/설정 자동 재사용 → 새 컬럼/거래처/형식 변동 적발
- **회사별 독립 수치와 로직**: 승인한도, z-score 임계값, 수기전표 코드, SoD 규칙 등

### 기대 효과

1. **탐지 정확도 향상**: 회사별 임계값 튜닝으로 False Positive 대폭 감소
2. **연도별 비교 분석**: 동일 회사의 연도간 위험 추이 추적
3. **업무 효율**: 반복 감사 시 매핑/설정 자동 재사용
4. **ML 고도화**: 회사별 모델 학습/저장/버전 관리 기반 마련

---

## 2. 방법

### 2.1 핵심 설계: Company + Engagement 2계층

```
Company (회사) — 연도 간 공유되는 항목
├── company.yaml            # 메타 정보 + 글로벌 대비 설정 오버라이드
├── chart_of_accounts.csv   # 회사별 계정과목표
├── keywords.yaml           # ERP 컬럼 별칭 오버라이드
├── audit_rules.yaml        # 수기전표 코드, SoD toxic pair 등
├── risk_keywords.yaml      # 회사별 위험 키워드 추가분
├── profiles/               # 매핑 프로파일 (fingerprint 기반 캐시)
│   └── {fingerprint}.json
└── engagements/
    └── {year}/             # Engagement (감사 연도) — 연도별 독립
        ├── engagement.yaml   # 연도 한정 설정 오버라이드 (결산기 등)
        ├── audit.duckdb      # 격리된 DuckDB 파일
        ├── models/           # ML 모델 아티팩트
        └── exports/          # 감사조서 export

config/                     # 글로벌 기본값 (변경 없음 — 폴백용)
├── settings.py             # AuditSettings 기본값
├── schema.yaml             # 표준 39컬럼 스키마 (전사 공통)
├── keywords.yaml           # 기본 ERP 별칭 사전
├── audit_rules.yaml        # 기본 감사 룰
├── risk_keywords.yaml      # 기본 위험 키워드
├── chart_of_accounts.csv   # 범용 CoA (글로벌 폴백)
└── cleaning.yaml           # 타입 캐스팅 규칙 (전사 공통)
```

**파일 시스템 경로**: `data/companies/{company_id}/engagements/{year}/`

### 2.2 CompanyContext — 싱글톤 대체 객체

모든 회사별 리소스를 하나로 번들링하는 불변 컨텍스트 객체.

```python
@dataclass(frozen=True)
class CompanyContext:
    company_id: str                    # 회사 식별자
    engagement_id: str                 # 감사 연도
    settings: AuditSettings            # 3계층 해소 완료 인스턴스
    schema: dict                       # 표준 스키마 (글로벌)
    keywords: dict                     # 글로벌 + 회사별 merge
    audit_rules: dict                  # 글로벌 + 회사별 merge
    risk_keywords: dict                # 글로벌 + 회사별 merge
    cleaning_config: dict              # 타입 캐스팅 (글로벌)
    chart_of_accounts: set[str] | None # 회사별 CoA (우선) or 글로벌 폴백
    profile_dir: Path                  # 회사별 매핑 프로파일 디렉토리
    db_path: Path                      # engagement별 DuckDB 경로
    model_dir: Path                    # engagement별 ML 모델 디렉토리
```

### 2.3 3계층 설정 해소(Resolution) 체인

```
글로벌 기본값 (config/settings.py AuditSettings 기본값)
  ↓ deep_merge
회사 오버라이드 (company.yaml settings_overrides)
  ↓ deep_merge
연도 오버라이드 (engagement.yaml settings_overrides)
  ↓ model_copy(update=)
프리셋/대시보드 슬라이더 (런타임 임시)
  = 최종 AuditSettings 인스턴스
```

- `ContextFactory.create(company_id, engagement_id)` → `CompanyContext`
- `ContextFactory.create_anonymous()` → 글로벌 기본값으로 하위 호환

### 2.4 DB 격리 전략: Engagement별 DB 파일

| 비교 항목    | 단일 DB + 컬럼 구분         | 회사별 DB             | Engagement별 DB (채택) |
|--------------|----------------------------|-----------------------|------------------------|
| 격리 수준    | 낮음 (쿼리 실수 위험)      | 중간                  | 완전 격리              |
| 연도 비교    | JOIN으로 간단               | ATTACH 필요           | ATTACH 필요            |
| 삭제/아카이브 | WHERE 조건 필요            | 디렉토리 삭제         | 디렉토리 삭제          |
| 동시 접근    | DuckDB single-writer 제약  | 회사 간 병렬 가능     | 완전 병렬 가능         |

**채택 이유**: DuckDB는 single-writer 제약이 있어 단일 DB에서 동시 작업 시 락 충돌 발생. Engagement별 격리로 연도 데이터 독립성 보장. 연도 비교 시 `ATTACH` 문으로 교차 쿼리.

### 2.5 파이프라인 변경 방식

기존 `AuditPipeline.__init__(settings=None)` → `AuditPipeline.__init__(context=None, settings=None)`

- `context` 우선 → `settings` 폴백 → `create_anonymous()` 폴백
- 내부 호출 시 `context.settings`, `context.keywords`, `context.audit_rules` 전달
- 이미 파라미터 주입 지원하는 함수가 대부분이므로 호출부만 변경

### 2.6 코드 재사용 전략

#### 변경 없이 유지

| 모듈                              | 이유                                          |
|-----------------------------------|-----------------------------------------------|
| `src/detection/` 전체 탐지기      | `BaseDetector(settings=)` 이미 주입 지원      |
| `src/feature/` 전체 엔진          | `generate_all_features(settings=, rules=)` 지원 |
| `src/ingest/reader_api.py`        | 파일 읽기 — 회사 무관                         |
| `src/ingest/header_detector.py`   | 헤더 탐지 — 회사 무관                         |
| `src/db/schema.py` (DDL)          | engagement_meta만 추가                        |
| `src/db/loader.py`                | DataFrame→DuckDB — 거의 변경 없음            |
| `src/db/queries.py`               | batch_id 기반 쿼리 — 변경 없음               |
| `dashboard/components/charts/`    | 17종 차트 — 변경 없음                         |
| `dashboard/components/filters.py` | 12개 필터 — 변경 없음                         |
| `config/schema.yaml`              | 표준 39컬럼 — 회사별 변경 불필요              |
| `config/cleaning.yaml`            | 타입 캐스팅 규칙 — 범용                       |

#### 리팩토링 (수정)

| 파일                                      | 변경 내용                               | 규모 |
|-------------------------------------------|-----------------------------------------|------|
| `config/settings.py`                      | ContextFactory 통합, get_* 폴백화       | 중   |
| `src/pipeline.py`                         | context 파라미터 + 내부 전달            | 중   |
| `src/db/connection.py`                    | 싱글톤 → ConnectionManager              | 대   |
| `src/ingest/mapping_profile.py`           | profile_dir 파라미터화                  | 중   |
| `src/ingest/type_caster.py`               | cleaning_config 파라미터 추가           | 소   |
| `src/detection/fraud_rules_access.py`     | lru_cache 제거, rules 파라미터화        | 중   |
| `src/feature/text_features.py`            | risk_kw 호출부 변경 (파라미터 이미 있음) | 소  |
| `src/validation/schema_validator.py`      | schema, settings 파라미터 추가          | 소   |
| `dashboard/app.py`                        | 진입 플로우 재설계                      | 대   |
| `dashboard/_state.py`                     | 회사/engagement 키 추가                 | 소   |
| `dashboard/components/data_uploader.py`   | context 전달 구조                       | 중   |
| `dashboard/components/preset_selector.py` | 회사별 프리셋 통합                      | 중   |

#### 신규 생성

| 파일                                              | 목적                              |
|---------------------------------------------------|-----------------------------------|
| `src/context.py`                                  | CompanyContext + ContextFactory    |
| `src/company/__init__.py`                         | 패키지 초기화                     |
| `src/company/models.py`                           | CompanyProfile, EngagementProfile |
| `src/company/repository.py`                       | YAML CRUD, 디렉토리 관리         |
| `src/company/merger.py`                           | 3계층 deep_merge 로직             |
| `dashboard/page_company.py`                       | 회사 선택/생성 화면               |
| `dashboard/components/company_manager.py`         | 회사 CRUD 컴포넌트                |
| `dashboard/components/engagement_selector.py`     | 연도 선택 컴포넌트                |
| `dashboard/tab_comparison.py`                     | 연도 비교 탭                      |
| `tests/test_company/`                             | Company 관련 테스트               |

#### 삭제/이동

| 대상               | 처리                                           |
|--------------------|------------------------------------------------|
| `data/audit.duckdb` | `data/companies/_legacy/` 로 마이그레이션     |
| `data/profiles/`   | 회사별 `profiles/`로 이동                      |

---

## 3. 진행순서

### 의존 관계 다이어그램

```
RC-0 (Company 인프라)  ── 반드시 최초 실행
 │
 ├── RC-1 (파이프라인 Context 주입)
 │    │
 │    └── RC-2 (싱글톤 직접 호출 제거)
 │         │
 │         └── RC-3 (DB 격리 + ConnectionManager)
 │              │
 │              └── RC-4 (대시보드 재설계)
 │                   │
 │                   └── RC-5 (매핑 프로파일 + 고급 기능)
 │
 └── RC-T (테스트 — 각 Phase 완료 후 즉시 실행)
```

> RC = Restructure Company-centric

**상태 범례**: ✅ 완료 / 🔄 진행중 / ⬜ 미착수
**복잡도**: S = 소형 / M = 중형 / L = 대형

---

### RC-0: Company 인프라 `[L]` ✅

> CompanyContext + ContextFactory + Company CRUD.
> 이 단계가 완료되면 `ContextFactory.create("acme", "2025")`로 CompanyContext 생성 가능.

| #      | 태스크                          | 파일                             | 상태 |
|--------|---------------------------------|----------------------------------|------|
| RC-0-1 | CompanyProfile Pydantic 모델    | `src/company/models.py`          | ✅   |
|        | — company.yaml 스키마 정의      |                                  |      |
|        | — company_id, display_name, industry, erp_system, fiscal_year_start, currency |  | |
|        | — settings_overrides (dict), has_custom_coa/keywords/rules/risk_keywords (bool) |  | |
| RC-0-2 | EngagementProfile Pydantic 모델 | `src/company/models.py`          | ✅   |
|        | — engagement.yaml 스키마 정의   |                                  |      |
|        | — engagement_id, company_id, fiscal_year, period_start/end |  | |
|        | — settings_overrides (dict), status (draft/in_progress/completed/archived) |  | |
| RC-0-3 | 3계층 deep_merge 로직           | `src/company/merger.py`          | ✅   |
|        | — 글로벌 + 회사 + 연도 → AuditSettings 인스턴스 생성 |  | |
|        | — 규칙: 키 존재 시 전체 교체 (리스트는 replace, append 아님) |  | |
|        | — YAML dict deep_merge + AuditSettings.model_copy(update=) 활용 |  | |
| RC-0-4 | CompanyRepository YAML CRUD     | `src/company/repository.py`      | ✅   |
|        | — `create_company(profile)`: 디렉토리 + company.yaml 생성 |  | |
|        | — `create_engagement(company_id, profile)`: engagements/{year}/ 생성 |  | |
|        | — `get_company()`, `list_companies()`, `update_company()`, `delete_company()` |  | |
|        | — `get_engagement()`, `list_engagements()`, `update_engagement()` |  | |
|        | — 회사별 CoA/keywords/rules 로드 (없으면 None → 글로벌 폴백) |  | |
|        | — Atomic Write (tmp → os.replace) + Path Traversal 방어 |  | |
| RC-0-5 | CompanyContext dataclass         | `src/context.py`                 | ✅   |
|        | — frozen=True 불변 객체, 12개 필드 |  | |
|        | — `clone_with_settings()` UI 슬라이더용 초고속 복제 |  | |
| RC-0-6 | ContextFactory                   | `src/context.py`                 | ✅   |
|        | — `create(company_id, engagement_id, preset_overrides=, runtime_overrides=)` |  | |
|        | — `create_anonymous()` → 글로벌 기본값 (하위 호환) |  | |
|        | — `from_settings(settings)` → 레거시 AuditSettings 래핑 |  | |
|        | — 메모리 캐시 + `invalidate()` (Streamlit re-run 최적화) |  | |
| RC-0-7 | 단위 테스트 (61개 통과)          | `tests/test_company/`            | ✅   |
|        | — test_models.py: 직렬화/역직렬화 |  | |
|        | — test_merger.py: 3계층 머지 edge case |  | |
|        | — test_repository.py: CRUD + 중복 방지 |  | |
|        | — test_context.py: create(), create_anonymous(), from_settings() |  | |

**완료 기준**: `ContextFactory.create("acme_corp", "2025")` 호출 시 올바른 CompanyContext 반환. 3계층 머지 테스트 통과.

---

### RC-1: 파이프라인 Context 주입 `[M]` ✅

> AuditPipeline이 CompanyContext를 받아 실행하도록 변경.
> 기존 `settings=None` 인터페이스 유지하여 하위 호환 보장.

| #      | 태스크                              | 파일                                              | 상태 |
|--------|-------------------------------------|---------------------------------------------------|------|
| RC-1-1 | AuditPipeline 시그니처 변경         | `src/pipeline.py`                                 | ✅   |
|        | — `__init__(context=None, settings=None, ...)` |                                        |      |
|        | — context 우선 → settings 폴백 → create_anonymous() 폴백 |                             |      |
| RC-1-2 | `_ingest()` context 전달            | `src/pipeline.py`                                 | ✅   |
|        | — `auto_map_columns(schema=ctx.schema, keywords=ctx.keywords)` |                       |      |
|        | — 매핑 프로파일 경로: `ctx.profile_dir` (RC-2에서 활용)  |                              |      |
| RC-1-3 | `_generate_features()` context 전달 | `src/pipeline.py`                                 | ✅   |
|        | — `generate_all_features(df, settings=ctx.settings, rules=ctx.audit_rules)` |          |      |
| RC-1-4 | `_run_detection()` context 전달     | `src/pipeline.py`                                 | ✅   |
|        | — IntegrityDetector에 ctx.settings + ctx.chart_of_accounts 전달 |                      |      |
| RC-1-5 | `_load_db()` context 전달           | `src/pipeline.py`                                 | ✅   |
|        | — 회사 context → `ctx.db_path`, 익명/레거시 → `:memory:` 방어 |                        |      |
| RC-1-6 | batch_id에 engagement 접두사        | `src/pipeline.py`                                 | ✅   |
|        | — `_make_batch_id()` 헬퍼 + 특수문자 sanitize (`re.sub`) |                              |      |
| RC-1-7 | 통합 테스트 (10개)                  | `tests/modules/test_pipeline/test_pipeline_context.py` | ✅   |
|        | — 하위호환(2) + context 주입(3) + batch_id(4) + 익명DB(1)  |                            |      |

**완료 기준**: `AuditPipeline(context=ctx).run(path)` 회사별 설정 탐지 완료. `AuditPipeline().run(path)` 기존과 동일.

**추가 구현 사항** (계획 외):
- `CompanyContext.is_anonymous` 프로퍼티 + `ANONYMOUS_ID`/`LEGACY_ID` 상수 (`src/context.py`)
- 익명/레거시 context → `:memory:` DB 강제 (파일 잠금 충돌 방지)
- `close_connection()` 싱글톤 리셋에 `TODO(RC-3)` 주석 추가

---

### RC-2: 싱글톤 직접 호출 제거 `[L]` ✅

> `src/` 내 19개 파일의 `get_settings()`, `get_audit_rules()` 등 직접 호출을 파라미터 주입으로 전환.
> `get_*()` 함수는 삭제하지 않고 "폴백 전용"으로 유지 (테스트, CLI 단독 실행).

**우선순위**: 파이프라인 호출 경로 → 탐지 → 피처 → 기타

| #      | 태스크                             | 파일                                        | 상태 |
|--------|------------------------------------|---------------------------------------------|------|
| RC-2-1 | type_caster 파라미터화             | `src/ingest/type_caster.py`                 | ✅   |
|        | — `cast_dataframe(df, schema=, settings=, cleaning_config=)` |  | |
|        | — 내부 8함수 `cleaning_config=None` 폴백, `@lru_cache` 제거 |  | |
| RC-2-2 | schema_validator 파라미터화        | `src/validation/schema_validator.py`        | ✅   |
|        | — `validate_schema(df, schema=None, settings=None)` |  | |
|        | — 모듈 수준 `_HIGH_NULL_THRESHOLD` → 함수 내부 지연 로딩 전환 |  | |
| RC-2-3 | fraud_rules_access 파라미터화      | `src/detection/fraud_rules_access.py`       | ✅   |
|        | — `@lru_cache` 제거 → `audit_rules` 파라미터 수신 |  | |
|        | — `FraudLayer.__init__`에서 미리 추출 (성능 방어) |  | |
| RC-2-4 | text_features 호출부 변경          | `src/feature/text_features.py`              | ✅   |
|        | — `add_all_text_features(df, settings=, risk_kw=)` |  | |
|        | — engine.py에서 `risk_keywords` 파라미터 전달 체인 |  | |
| RC-2-5 | integrity_layer CoA 로딩 변경      | `src/detection/integrity_layer.py`          | ✅   |
|        | — `__init__(schema=None)` → `self._schema` 인스턴스 변수 |  | |
| RC-2-6 | mapping_profile 경로 파라미터화    | `src/ingest/mapping_profile.py`             | ✅   |
|        | — `save_profile(result, ..., profile_dir=None)` |  | |
|        | — `load_profile(source_columns, profile_dir=None)` |  | |
| RC-2-7 | pipeline.py 내부 호출 전면 정리    | `src/pipeline.py`                           | ✅   |
|        | — `_ingest` → `cast_dataframe(schema, settings, cleaning_config)` |  | |
|        | — `_validate` → `validate_schema(schema, settings)` |  | |
|        | — `_generate_features` → `risk_keywords` 전달 |  | |
|        | — `_run_detection` → `IntegrityDetector(schema=)`, `FraudLayer(audit_rules=)` |  | |
| RC-2-8 | 기존 테스트 fixture 업데이트       | `tests/test_company/conftest.py`            | ✅   |
|        | — `cx_factory`, `cx_context`, `cx_anonymous` fixture 추가 |  | |
|        | — 695개 관련 테스트 전체 통과 확인 (폴백 호환) |  | |

**완료 기준**: `src/` 내 `get_settings()` 직접 호출이 "폴백 전용"에만 잔존. 기존 120+ 테스트 전체 통과.

---

### RC-3: DB 격리 + ConnectionManager `[M]` ✅

> Engagement별 DB 파일 격리 + 글로벌 싱글톤 커넥션 → 경로별 커넥션 관리.

| #      | 태스크                          | 파일                          | 상태 |
|--------|---------------------------------|-------------------------------|------|
| RC-3-1 | ConnectionManager 클래스        | `src/db/connection.py`        | ✅   |
|        | — 경로별 커넥션 캐시 (`dict[str, conn]`) + 스레드 안전성 |  | |
|        | — `get(db_path)`, `close(db_path)`, `close_all()` |  | |
|        | — 기존 `get_connection(path=None)` 시그니처 유지 (하위 호환) |  | |
|        | — `:memory:` 비캐시 (매번 새 커넥션, 테스트 격리) |  | |
| RC-3-2 | engagement_meta 테이블 추가     | `src/db/schema.py`            | ✅   |
|        | — `CREATE TABLE engagement_meta (company_id, engagement_id, created_at, schema_version)` |  | |
|        | — `UNIQUE (company_id, engagement_id)` 제약 + `ON CONFLICT DO NOTHING` |  | |
| RC-3-3 | 마이그레이션 스크립트            | `src/company/migration.py`    | ✅   |
|        | — 기존 `data/audit.duckdb` → `data/companies/_legacy/engagements/unknown/` 이동 |  | |
|        | — 기존 `data/profiles/` → `_legacy/profiles/` 이동 |  | |
|        | — WAL 파일 동반 이동 + YAML 스텁 자동 생성 |  | |
| RC-3-4 | 연도 비교 ATTACH 헬퍼           | `src/db/queries.py`           | ✅   |
|        | — `attached_engagement()` 컨텍스트 매니저 (finally: DETACH 강제) |  | |
|        | — 절대 경로 강제 (`Path.resolve()`) + single-quote 이스케이프 |  | |
|        | — READ_ONLY + alias sanitize (SQL injection 방어) |  | |
|        | — `compare_engagements()`: 건수/금액/위험분포 YoY 비교 |  | |
| RC-3-5 | pipeline.py DB 연동 최종 정리   | `src/pipeline.py`             | ✅   |
|        | — anonymous만 직접 close, named DB는 ConnectionManager 관리 |  | |
|        | — `_upsert_engagement_meta()` ON CONFLICT DO NOTHING |  | |
| RC-3-6 | 단위 테스트 (48개)              | `tests/modules/test_db/`, `tests/test_company/` | ✅   |
|        | — ConnectionManager 멀티 경로(10), schema(4), ATTACH(5), 마이그레이션(8) |  | |
|        | — 통합: 2회사×2연도 4개 독립 DB + ATTACH 교차 쿼리 |  | |
|        | — 파이프라인 회귀 23개 전체 통과 |  | |

**완료 기준**: 두 회사 × 두 연도 → 4개 독립 DB 파일 생성 + ATTACH 교차 쿼리 성공. ✅

**RC-4로 이관된 개선 사항** (코드 리뷰 권장):
- `migration.py` 기본값을 `settings.data_dir` 기반 절대 경로로 변경
- `queries.py`의 `import time` 파일 상단 이동 + backoff 주석 정정 (linear → exponential 또는 주석 수정)
- `conn.cursor()` 커서 분리 패턴 적용 (멀티 세션 스레드 안전성, 대시보드 재설계 시)

---

### RC-4: 대시보드 재설계 `[L]` ✅

> 회사 선택 → Engagement 선택 → 업로드/매핑 → 5탭 분석(EDA, 요약, Benford, 탐색기, 연도비교).
> "범용 모드" (회사 없이 즉시 분석) 하위 호환 유지.

**실행 순서:**

```
RC-4-8 (state 키)
 → RC-4-1~3 (회사/연도 선택 UI) ── 병렬 구현
   → RC-4-4 (app.py 진입 플로우)
     → RC-4-5 (data_uploader context 통합)
       → RC-4-6 (preset_selector 회사 통합)
   → RC-4-7 (연도 비교 탭) ── RC-3-4 ATTACH 헬퍼 의존
```

| #      | 태스크                           | 파일                                             | 상태 |
|--------|----------------------------------|--------------------------------------------------|------|
| RC-4-1 | 회사 선택/생성 화면              | `dashboard/page_company.py`                      | ✅   |
|        | — 카드 목록 + 새 회사 등록 폼 + "범용 모드" 버튼 |  | |
| RC-4-2 | 회사 CRUD 컴포넌트               | `dashboard/components/company_manager.py`         | ✅   |
|        | — 설정 편집(3개 핵심 필드), CoA 업로드, 삭제 이중확인 |  | |
| RC-4-3 | 연도 선택 컴포넌트               | `dashboard/components/engagement_selector.py`     | ✅   |
|        | — 연도 목록, 새 연도 생성, 상태 표시 |  | |
| RC-4-4 | app.py 진입 플로우 재설계        | `dashboard/app.py`                               | ✅   |
|        | — page_company → engagement → 업로드/분석 |  | |
|        | — session_state에 company_id, engagement_id, context |  | |
|        | — 사이드바 "현재 회사: {name} / {year}" + 회사 변경 버튼 |  | |
| RC-4-5 | data_uploader context 통합       | `dashboard/components/data_uploader.py`           | ✅   |
|        | — `AuditPipeline(context=ctx)` 호출 + 업로더 key 동적 결합 |  | |
| RC-4-6 | preset_selector 회사 프리셋 통합 | `dashboard/components/preset_selector.py`         | ✅   |
|        | — "회사 기본값" 프리셋 옵션 삽입 (ctx.settings 기반) |  | |
| RC-4-7 | 연도 비교 탭                     | `dashboard/tab_comparison.py`                     | ✅   |
|        | — 두 engagement 선택 + ATTACH 비교 차트 5종 |  | |
|        | — 건수/금액 YoY, 위험 분포, 룰별 변동, 신규 계정 |  | |
|        | — SQL 집계 위임 (메모리 폭발 방지) |  | |
| RC-4-8 | _state.py 키 추가                | `dashboard/_state.py`                             | ✅   |
|        | — KEY_COMPANY_ID, KEY_ENGAGEMENT_ID, KEY_COMPANY_CONTEXT |  | |

**완료 기준**: 회사 생성 → 업로드 → 분석 → 다른 회사 전환 가능. 범용 모드 정상.

**Streamlit 함정 방어 3종:**
1. 유령 파일 — `file_uploader` key에 engagement_id 동적 결합
2. Form 타이밍 — `st.rerun()` 전 session_state에 ID 즉시 저장
3. 메모리 폭발 — 비교 쿼리 집계를 DuckDB SQL에 위임, 요약표만 Pandas로 전달

---

### RC-5: 매핑 프로파일 회사 연결 + 고급 기능 `[M]` ✅

> 매핑 프로파일의 회사별 격리 + "B회사 3년차" 시나리오 구현.

| #      | 태스크                           | 파일                                              | 상태 |
|--------|----------------------------------|---------------------------------------------------|------|
| RC-5-1 | 매핑 프로파일 회사별 격리         | `src/ingest/mapping_profile.py`                   | ✅   |
|        | — profile_dir을 ctx.profile_dir로 |  | |
| RC-5-2 | 사용자 매핑 → 회사 키워드 학습   | `src/ingest/keyword_learner.py` + `repository.py` | ✅   |
|        | — 수동 매핑 → keywords.yaml 자동 추가 |  | |
| RC-5-3 | 회사별 CoA 관리 UI               | `dashboard/components/company_manager.py`          | ✅   |
|        | — CSV 업로드 + 편집 + L1-03 자동 반영 |  | |
| RC-5-4 | 회사 설정 export/import           | `src/company/repository.py`                       | ✅   |
|        | — ZIP 아카이브 (company.yaml + CoA + keywords + rules + profiles) |  | |
| RC-5-5 | "B회사 3년차" E2E 시나리오 테스트 | `tests/test_company/`                              | ✅   |
|        | — 1년차: 최초 매핑 + 프로파일 + 탐지 |  | |
|        | — 2년차: 프로파일 자동 적용 + 설정 유지 |  | |
|        | — 3년차: 새 컬럼 review + 연도 비교 |  | |

**완료 기준**: B회사 1년차 매핑이 3년차에서 자동 적용. 새 컬럼 review 분류. 연도 비교 3개년 추이.

---

## 진행 현황 요약

| Phase                            | 태스크 수 | 완료 | 진행률 |
|----------------------------------|-----------|------|--------|
| RC-0 Company 인프라              | 7         | 7    | 100%   |
| RC-1 파이프라인 Context 주입     | 7         | 7    | 100%   |
| RC-2 싱글톤 직접 호출 제거       | 8         | 8    | 100%   |
| RC-3 DB 격리 + ConnectionManager | 6         | 6    | 100%   |
| RC-4 대시보드 재설계             | 8         | 8    | 100%   |
| RC-5 매핑 프로파일 + 고급 기능   | 5         | 5    | 100%   |
| **합계**                         | **41**    | **41** | **100%** |

---

## 검증 방법

| 검증 항목                | 방법                                                              | Phase |
|--------------------------|-------------------------------------------------------------------|-------|
| 3계층 설정 머지           | pytest — 오버라이드, 빈값, 리스트 교체 edge case                  | RC-0  |
| Company CRUD             | pytest — 생성/조회/수정/삭제/중복 방지                            | RC-0  |
| 하위 호환                | `AuditPipeline()` (context 없이) → 기존 동작 ✅                  | RC-1  |
| 회사별 탐지 차이          | 동일 데이터 + 다른 context → 결과 상이 ✅                        | RC-1  |
| 기존 테스트 전체 통과     | `uv run pytest tests/ -v` — 120+ 테스트                          | RC-2  |
| DB 파일 격리              | 두 회사 x 두 연도 → 4개 독립 DB                                  | RC-3  |
| ATTACH 교차 쿼리          | 두 engagement DB JOIN → 비교 통계                                | RC-3  |
| 대시보드 E2E              | 회사 생성 → 업로드 → 분석 → 전환 → 연도 비교                    | RC-4  |
| 범용 모드 호환            | 회사 미선택 → 즉시 분석                                          | RC-4  |
| B회사 3년차 시나리오      | 매핑 재사용 + 새 컬럼 review + 연도 비교                         | RC-5  |

## 🚨 보완해야 할 3가지 아키텍처 디테일
1. 불변성(frozen=True)과 Streamlit UI 슬라이더의 충돌 (RC-0)
문제: CompanyContext를 frozen=True(불변 객체)로 설계하신 것은 매우 좋습니다. 하지만 대시보드(WU5)에서 사용자가 'Z-score 슬라이더'를 움직이면 설정값이 실시간으로 바뀌어야 합니다. 객체가 불변이면 에러가 납니다.

해결책 (계획 수정): src/context.py에 CompanyContext의 상태를 복제하면서 일부 설정만 교체하는 메서드(예: clone_with_runtime_overrides(new_settings))를 추가해야 합니다. UI에서 슬라이더를 조작하면, 기존 Context를 덮어쓰는 게 아니라 새로운 설정이 반영된 새로운 Context 인스턴스를 생성해서 session_state에 교체해 주는 패턴이 필요합니다.

2. DuckDB ATTACH 로직의 리소스 누수 (RC-3-4)
문제: 연도별 비교를 위해 두 개의 DB를 ATTACH로 연결하는 아이디어는 완벽합니다. 하지만 Streamlit은 버튼을 누를 때마다 스크립트가 처음부터 다시 실행(Re-run)됩니다. 이전에 ATTACH 했던 DB를 명시적으로 DETACH 하거나 커넥션을 닫지 않고 화면이 새로고침되면, **"Database already attached" 에러나 심각한 File Lock(락 충돌)**이 발생해 앱이 죽어버립니다.

해결책 (계획 수정): src/db/queries.py의 attach_engagement 헬퍼 함수를 작성하실 때, 반드시 파이썬의 컨텍스트 매니저(with 구문)나 try...finally 블록을 활용하여 쿼리가 끝나면 무조건 DETACH database_alias;가 실행되도록 강제하는 방어 로직을 태스크에 명시해야 합니다.

3. 테넌트(Tenant) 격리형 로깅 (RC-0 누락분)
문제: 이제 모든 탐지와 에러가 '회사 단위'로 발생합니다. 나중에 터미널이나 서버 로그를 봤을 때 [ERROR] Type validation failed 라고만 찍히면, 이게 A회사 데이터에서 난 건지 B회사에서 난 건지 알 길이 없습니다.

해결책 (계획 추가): 파이프라인의 핵심 로거(Logger)에 현재 실행 중인 company_id와 engagement_id를 접두사로 붙이는 태스크를 RC-1(파이프라인 Context 주입) 단계에 추가하세요. (예: [INFO] [acme_corp] [2025] Pipeline completed...)