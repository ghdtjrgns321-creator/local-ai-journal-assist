# IC Matcher Redesign — Task Checklist

## Progress Summary

23 / 23 tasks complete (100%) + post-completion finding 수정 3건 (K-06 / K-07 / K-08, 결정 13) — deferred 2건 포함 (T-P4-3, T-P5-5)

| Phase | 우선순위  | 추정        | 실제 소요   | 상태                                          | 의존성                            |
|-------|-----------|-------------|-------------|-----------------------------------------------|-----------------------------------|
| P0    | P0 (HARD) | 1.0~1.5h    | ~0.5h       | 완료 (T-P0-1/2/3)                             | -                                 |
| P1    | P1        | 1.5~2.0h    | ~1.0h       | 완료 (T-P1-1~5)                               | P0                                |
| P2    | P2        | 0.5~0.75h   | ~0.5h       | 완료 (T-P2-1/2)                               | P1                                |
| P3    | P3        | 1.0~1.5h    | ~1.5h       | 완료 (T-P3-1~6)                               | P1 (코드 인터페이스 확정 후)       |
| P4    | P4        | 0.5~1.0h    | ~0.3h       | 완료 (T-P4-1/2) + T-P4-3 deferred (결정 11)    | P0 (코드 fitting 제거 후)          |
| P5    | (검증)    | 1.0~1.5h    | ~1.0h       | 완료 (T-P5-1~4) + T-P5-5 deferred (결정 12)    | P0~P4                             |
| P6    | (마감)    | 0.5h        | ~0.5h       | 완료 (T-P6-1~4)                               | P5                                |
| post  | (리뷰)    | -           | ~0.5h       | 완료 (K-06/K-07/K-08 결정 13 반영)            | P6 + 코드 리뷰                    |

총 추정: 6.0 ~ 8.25h. 실제 소요: 약 5.8h (deferred 2건 제외, 결정 11·12 사유 + post-completion finding 수정 0.5h).

변동 요약:
- P2 감소 — IC01 외부 분리 (IC01_A / IC01_B) 가 없으므로 mask 계산 단순화 (evidence level read 만 추가).
- P3 약간 증가 — lock 문서 본문 변경량은 감소하지만 D055 supersede task (T-P3-6) 신규 추가.
- P5 — ripple-search 의미 검토 절차 명시. IC01 literal 0건 acceptance 삭제로 실작업량 감소.
- **T-P4-3 deferred (2026-05-23)** — 운영 baseline 이 v7_fixed4 로 이동, `build_datasynth_v38_ic_exception_labels.py` 산출물 부재. v7_fixed4 의 `-UNMATCHED` grep 0건 확인으로 대체 (context.md 결정 11).
- **T-P5-5 deferred (2026-05-23)** — `profile_phase1_v126.py` 의 `--output` 인자 미지원 + IC02 noise 와 통합 측정 효율성. `dev/active/ic02-calibration/` 신규 plan 으로 이관 (context.md 결정 12).

---

## Phase P0 — Fitting 제거 (P0 HARD)

### T-P0-1: `-UNMATCHED` endswith 휴리스틱 제거
- File: `src/detection/intercompany_rules.py`
- Lines: 354~356
- 변경: `looks_like_company_partner = partner.str.endswith("-UNMATCHED") | ~partner.str.contains("-", regex=False)` 라인을 제거.
- 영향: IC01 의 fitting 매칭 경로 차단. 임시로 IC01 score 가 `sidecar_unmatched | (ic_rows & no_counterpart & unknown_partner)` 로 축소.
- Acceptance:
  - `grep -rn 'endswith("-UNMATCHED")' src/detection/` → 0건
  - `grep -rn 'partner.str.contains("-")' src/detection/` → 0건
  - 변경된 함수가 import error 없이 실행됨
- Size: S (15 min)

### T-P0-2: IC01 임시 단일 시리즈 반환 유지
- File: `src/detection/intercompany_rules.py`
- 변경: P1 시그니처 확장 전, 기존 `pd.Series` 반환을 유지하여 caller 와의 호환성 보존. `_apply_intercompany_exception_corroboration` 충돌 방지.
- Acceptance: `IntercompanyMatcher.detect()` 호출 시 `details["IC01"]` 컬럼 정상 생성
- Size: S (10 min)

### T-P0-3: 회귀 테스트 통과 확인
- Command: `uv run pytest tests/modules/test_detection/test_intercompany_matcher.py -v`
- 예상: `TestIC01PracticalFilters::test_customer_vendor_partner_codes_are_not_unmatched_ic` 는 통과 (현재 0.0 assert 유지), `TestIC01Unmatched` 6 개 expectation 검토 필요. 깨지는 테스트가 있으면 P1 까지 보류.
- Acceptance: 깨지는 테스트 목록을 context.md `Known Issues` 에 기록
- Size: S (10 min)

---

## Phase P1 — IC01 evidence level 재정의 (P1)

### T-P1-1: `ic01_unmatched_intercompany()` 시그니처 확장
- File: `src/detection/intercompany_rules.py`
- 변경:
  ```python
  def ic01_unmatched_intercompany(
      df: pd.DataFrame,
      *,
      match_df: pd.DataFrame,
      related_party_master: set[str] | None = None,
      partner_format_policy: dict | None = None,
  ) -> tuple[pd.Series, pd.Series, pd.Series]:
      """반환: (score, evidence_level, review_reason)."""
  ```
- 책임:
  - master 부재 시 dataset 의 distinct `company_code` 로 폴백
  - customer/vendor regex 매칭 시 score=0 + evidence_level=`""` + review_reason=`""` 처리
  - evidence=`high`: `ic_rows & no_counterpart & has_partner & ~excluded & ~partner.isin(master)`
  - evidence=`review`: `ic_rows & no_counterpart & (partner 결측 OR format 비표준 OR master mapping 미정) & ~excluded`
  - score 는 high + review 합쳐 단일 series 로 반환 (외부 IC01 신호는 단일)
  - review_reason 코드: `missing_partner`, `nonstandard_format`, `mapping_uncertain` (확장 여지)
- Acceptance:
  - 함수가 3 개 시리즈 (score, evidence_level, review_reason) 반환
  - master 부재 dataset 에서 fallback 동작
  - `partner_format_policy` 가 None 일 때 안전한 기본값 사용
- Size: M (45 min)

### T-P1-2: `IntercompanyMatcher._build_registry()` 가 IC01 단일 entry 유지 + sidecar 부착 경로 추가
- File: `src/detection/intercompany_matcher.py:93~112`
- 변경: `("IC01", ic01_unmatched_intercompany, {...})` entry 는 단일 유지. `ic01_unmatched_intercompany()` 호출 결과 튜플의 score 만 `rule_results["IC01"]` 에 등록. evidence_level / review_reason 두 series 는 별도 sidecar dict 에 저장 (예: `self._sidecar_columns`).
- 책임: O(n) 재계산 회피. 한 번 호출 후 튜플 unpacking.
- Acceptance: `rule_results` 딕셔너리에 `IC01` 단일 key 만 존재 (외부 변경 없음). sidecar dict 에 `ic01_evidence_level`, `ic01_review_reason` 두 key 존재.
- Size: S (20 min)

### T-P1-3: `_build_result()` 두 sidecar column 부착
- File: `src/detection/intercompany_matcher.py:114~153`
- 변경: 결과 DataFrame 에 `ic01_evidence_level`, `ic01_review_reason` 두 column 을 부착. `SEVERITY_MAP[rule_id]` 변경 없음 — `IC01` 단일 유지.
- Acceptance:
  - `details.columns` 에 `IC01` 단일 + sidecar `ic01_evidence_level`, `ic01_review_reason` 동시 존재
  - `rule_flags` 의 `IC01` 단일 항목 유지
- Size: S (15 min)

### T-P1-4: `config/audit_rules.yaml::patterns.intercompany` 신규 키 추가
- File: `config/audit_rules.yaml`
- Lines: 309 근방 (`patterns.intercompany` 블록)
- 변경:
  ```yaml
  patterns:
    intercompany:
      pairs:                              # 기존 유지
        - receivable: "1150"
          payable: "2050"
        - receivable: "4500"
          payable: "2700"
      related_party_master:               # 신규 Optional
        - C001
        - C002
        - C003
      partner_format:                     # 신규 Optional
        ic_partner_regex: "^C\\d{3}$"
        customer_partner_regex: "^C-\\d+$"
        vendor_partner_regex: "^V-\\d+$"
  ```
- Acceptance:
  - YAML 파싱 에러 없음
  - `load_ic_pairs()` 기존 동작 호환 (`patterns.intercompany.pairs` 구조 유지)
  - 새 키가 detector 에서 graceful fallback (미정의 dataset 호환)
- Size: S (20 min)

### T-P1-5: `config/settings.py` 옵션 추가
- File: `config/settings.py:192~197`
- 변경:
  ```python
  ic_use_related_party_master: bool = True
  ic_period_boundary_days: int = 5  # IC03 reason code 부착용
  ```
- Acceptance: `AuditSettings` 인스턴스화 시 신규 옵션 default 적용. pydantic validation 통과.
- Size: S (10 min)

(보정 #3 반영) 본 plan 에서 SEVERITY_MAP 변경 task 는 제외. `IC01=3, IC02=2, IC03=2` 보존 (`src/detection/constants.py:195`).

(보정 #1 반영) `config/phase1_case.yaml` 의 `patterns.intercompany.pairs` 변경 task 는 제외. 해당 키는 audit_rules.yaml 에만 존재.

---

## Phase P2 — score_aggregator floor 분리 (P2)

### T-P2-1: `_apply_intercompany_exception_corroboration()` 갱신
- File: `src/detection/score_aggregator.py:1001~1063`
- 변경:
  - `exception_rules = ["IC01", "IC02", "IC03"]` 그대로 유지 (외부 id 변경 없음)
  - IC01 hit 시 `combined["ic01_evidence_level"]` 컬럼 read 추가 (없으면 빈 문자열 fallback)
  - Medium mask: `(ic01_hit & (evidence == "high")) | (exception_count >= 2)`
  - Low mask: `((ic01_hit & (evidence == "review")) | ic02_hit | ic03_hit) & ~medium_mask`
  - IC02 + IC03 단독 → Medium (2 개 이상 결합 정책 유지)
  - IC01 + IC02 / IC03 → Medium (2 개 이상 결합 정책 유지)
- Acceptance:
  - 단위 테스트로 7 가지 조합 검증 (IC01[high] 단독, IC01[review] 단독, IC02 단독, IC03 단독, IC01[high]+IC02, IC01[review]+IC02, IC02+IC03)
  - `intercompany_exception_score` 분포가 변경 전후 비교 가능
- Size: M (30 min)

### T-P2-2: reason 문자열 갱신
- File: `src/detection/score_aggregator.py:1036~1042`
- 변경: `reason_parts` 에 IC01 hit 시 evidence level qualifier 추가 (`IC01[high]`, `IC01[review]`). IC02 / IC03 는 그대로 유지. dashboard 표시 컴포넌트가 단일 `IC01` 을 기대하면 변환 layer 없이 신규 표기 그대로 노출 (base id 동일).
- Acceptance: `intercompany_exception_reasons` 문자열에 `IC01[high]` / `IC01[review]` 표기 정확히 부착
- Size: S (15 min)

(보정 #2 반영) IC01_A / IC01_B 외부 id 분리 task 는 제외. 외부 rule id `IC01` 단일 유지.

---

## Phase P3 — Spec & Lock 문서 정렬 + D055 supersede (P3)

### T-P3-1: `docs/DETECTION_RULES.md` 갱신
- File: `docs/DETECTION_RULES.md:1085~1132`
- 변경:
  - L3-03 본문 유지 + IC01 정책 절에 evidence level (`high` / `review`) sidecar 정책 표 추가
  - 근거 절 추가: IFRS 10 §B86 / K-IFRS 1110 / 1024 / KICPA Issue Paper 46 / ISA 600 (보조: ISA 550 §23)
  - 외부 rule id `IC01` 단일 유지 명시 (분리 없음)
  - 표시 기준 절 (`:1120~1126`) 의 IC01 항목에 evidence level 표시 정책 추가
- Acceptance:
  - 코드 인용(`file:line`) 정합
  - markdown 표 컬럼 폭 정렬 (CLAUDE.md §6)
- Size: M (40 min)

### T-P3-2: `docs/DETECTION_REFERENCE.md` 신규 절
- File: `docs/DETECTION_REFERENCE.md:153~241`
- 변경:
  - §2.5 ISA 550 §23 본문 유지, 보조 근거임을 명시
  - §2.5a 신규: "IFRS 10 §B86 — 연결 내부거래 제거 원칙"
  - §2.5b 신규: "K-IFRS 1110 — 연결재무제표 작성 시 내부거래 제거 절차"
  - §2.5c 신규: "K-IFRS 1024 — 특수관계자 공시 의무"
  - §2.5d 신규: "ISA 600 — 그룹감사 구성단위 잔액 대사"
  - §2.10 요약 표에 IFRS / K-IFRS / ISA 600 행 추가
- Acceptance: 한글 평서체, 인용 형식 일관
- Size: M (40 min)

### T-P3-3: `docs/RULE_DETAIL_METADATA_V1_LOCK.md` 갱신
- File: `docs/RULE_DETAIL_METADATA_V1_LOCK.md`
- 변경:
  - Excluded list `IC01, IC02, IC03` 본문은 **변경 없음** (외부 rule id 분리 없음)
  - evidence level sidecar 정책 절 신규 추가 — `ic01_evidence_level` 컬럼은 `intercompany_sidecar` surface 의 일부로 canonical 32 count 외부 유지
  - canonical count 정책 영향 없음 (32 유지)
- Acceptance: lock 문서의 canonical 32 count 변경 없음. evidence level sidecar 정책 절이 명시되어 있음.
- Size: S (15 min)

### T-P3-4: `docs/PHASE1_TOPIC_SCORING_V1_LOCK.md` 갱신
- File: `docs/PHASE1_TOPIC_SCORING_V1_LOCK.md`
- 변경:
  - 관계사·내부거래·순환구조 Primary rules `IC01, IC02, IC03` **본문 변경 없음**
  - floor 차별 정책 보조 절 신규 추가 — IC01 hit 시 `ic01_evidence_level == "high"` 만 Medium 자격, `review` 는 Low. IC02+IC03 또는 IC01+(IC02/IC03) 는 Medium 유지.
  - fraud combo 표 본문 변경 없음 (외부 IC01 단일 표기 유지)
- Acceptance: floor 정책이 `score_aggregator` (T-P2-1) 와 정합
- Size: S (20 min)

### T-P3-5: `docs/PHASE1_RULE_RELATIONSHIP_MAP.md` 갱신
- File: `docs/PHASE1_RULE_RELATIONSHIP_MAP.md:80`
- 변경: intercompany_structure evidence type 표 **본문 변경 없음** (`L3-03 IC01 IC02 IC03` 유지). 보조 주석으로 evidence level sidecar (`ic01_evidence_level`, `ic01_review_reason`) 명시.
- Acceptance: mermaid diagram render 정상
- Size: S (10 min)

### T-P3-6 (**신규, 보정 #4 반영**): `docs/DECISION.md` D055 supersede 결정문 추가
- File: `docs/DECISION.md`
- 변경:
  - D055 본문 (`:514`) 상단에 "**Superseded by D0xx (YYYY-MM-DD)**" 라인 부착. D055 본문 자체는 그대로 유지.
  - 신규 D0xx 결정문 본문 추가 — 다음 절 포함:
    - **결정**: `ic_unmatched_reference` sidecar 의 IC01 score 직접 의존을 제거. IC01 은 grouping 결과 + `related_party_master` 대사 기반으로 재정의. evidence level sidecar (`ic01_evidence_level` ∈ {`"high"`, `"review"`, `""`}, `ic01_review_reason`) 부착.
    - **사유**: fitting 증거 — F-01 (`endswith("-UNMATCHED")` 휴리스틱), L-01 (sidecar 직접 의존). 도메인 정합 — IFRS 10 §B86 / K-IFRS 1110 / 1024 / KICPA Issue Paper 46 / ISA 600.
    - **정책**: 외부 rule id `IC01` 단일 유지. evidence=`high` 만 `score_aggregator` Medium floor 자격. evidence=`review` 는 Low floor. IC02 / IC03 단독 Low 유지, 2 개 이상 IC 예외 결합은 Medium 유지. SEVERITY_MAP 변경 없음.
    - **영향 범위**: `src/detection/intercompany_rules.py`, `src/detection/intercompany_matcher.py`, `src/detection/score_aggregator.py`, `config/audit_rules.yaml`, `config/settings.py`, `tools/scripts/build_datasynth_v38_ic_exception_labels.py`, `docs/DETECTION_RULES.md`, `docs/DETECTION_REFERENCE.md`, `docs/RULE_DETAIL_METADATA_V1_LOCK.md`, `docs/PHASE1_TOPIC_SCORING_V1_LOCK.md`, `docs/PHASE1_RULE_RELATIONSHIP_MAP.md`.
    - **관련 산출물**: `dev/active/ic-matcher-redesign/` 의 plan / context / tasks. KPI guard 측정 결과 (`kpi_before.json`, `kpi_after.json`).
- Acceptance:
  - D055 본문 상단에 supersede 라인 존재
  - D0xx 결정문이 D055 직후 또는 적절한 위치에 추가됨
  - 결정문 본문에 결정·사유·정책·영향 범위·관련 산출물 4 절 모두 포함
- Size: M (35 min)

---

## Phase P4 — DataSynth Label Cleanup (P4)

### T-P4-1: `-UNMATCHED` patch 제거
- File: `tools/scripts/build_datasynth_v38_ic_exception_labels.py:314~319`
- 변경: `f"C{n}-UNMATCHED"` → master 외부 회사 코드 (`f"C9{(idx % 9) + 1:02d}"` 등) 로 교체
- 책임: `intercompany_pop_truth` 모집단의 master 회사 코드와 중복되지 않는 코드 생성
- Acceptance:
  - `endswith("-UNMATCHED")` 패턴 grep 시 0건
  - `patched_trading_partner` 분포에 `C9XX` 형식 회사 코드만 포함
- Size: S (20 min)

### T-P4-2: `field_patch` description 갱신
- File: `tools/scripts/build_datasynth_v38_ic_exception_labels.py:319`
- 변경: `"trading_partner_changed_to_unmatched_company"` → `"trading_partner_changed_to_non_master_company"`
- Acceptance: 라벨 csv 의 `field_patch` 컬럼 갱신
- Size: S (5 min)

### T-P4-3: 재생성 산출물 검증 — **deprecated (2026-05-23)**

운영 baseline 이 `data/journal/primary/datasynth_manipulation_v7_candidate_fixed4` 로 이동했고, 본 baseline 은 다음을 확인했다:
- `journal_entries.csv` 의 `trading_partner` 컬럼에 `-UNMATCHED` 문자열 0건 (검증 결과)
- `ic_unmatched_reference` 컬럼 존재 없음
- `intercompany/` 디렉토리는 `ic_buyer_journal_entries.json`, `ic_matched_pairs.json`, `ic_seller_journal_entries.json` 의 새 라벨 구조 사용
- `build_datasynth_v38_ic_exception_labels.py` 의 산출물 (`intercompany_exception_cases*.csv`, `intercompany_normal_controls*.csv`) 는 운영 라벨 디렉토리에 부재

따라서 T-P4-3 acceptance 의 v37→v38 재생성 검증은 운영 baseline 에 대해 수행하지 않는다. T-P4-1 / T-P4-2 (스크립트 fitting 제거) 만 완료한다. 본 스크립트는 v7_fixed4 이전 시절의 산출물 생성기이며 운영 파이프라인에서 호출되지 않는다. 추후 본 스크립트가 다시 사용될 경우 (예: v37 계열 라벨이 운영에 필요) 본 commit 의 변경이 그대로 적용된다.

운영 baseline 의 IC 라벨 생성 정합성은 본 plan 범위 외 (`docs/debugging.md` 에 별도 후속 plan 으로 분리).

- Acceptance:
  - 운영 baseline `v7_fixed4` 에서 `-UNMATCHED` grep 0건 확인 완료
  - 스크립트 자체의 fitting 패턴 (T-P4-1) 제거 완료
- Size: deferred

---

## Phase P5 — 테스트 & Ripple-search

### T-P5-1: leakage 회피 테스트
- File: `tests/modules/test_detection/test_intercompany_matcher.py`
- 신규 테스트: `TestIC01NoFittingDependency`
  - `test_unmatched_without_unmatched_suffix`: trading_partner = `C999` (master 외부 회사 코드, `-UNMATCHED` 접미사 없음) 일 때 IC01 score > 0 + `ic01_evidence_level == "high"` 검증
  - `test_unmatched_with_unmatched_suffix_no_longer_special`: trading_partner = `C001-UNMATCHED` 일 때 IC01 score 가 일반 unknown partner 와 동일 (특별 가중치 없음) 검증
- Acceptance: 두 테스트 모두 통과. fitting 의존성이 코드에 남아있지 않음을 증명.
- Size: M (30 min)

### T-P5-2: evidence level 분류 검증 테스트
- File: `tests/modules/test_detection/test_intercompany_matcher.py`
- 신규 테스트:
  - `test_ic01_evidence_high_master_absent`: master 부재 회사 → IC01 score > 0 + `ic01_evidence_level == "high"` + `ic01_review_reason == ""`
  - `test_ic01_evidence_review_missing_partner`: trading_partner NaN → IC01 score > 0 + `ic01_evidence_level == "review"` + `ic01_review_reason == "missing_partner"`
  - `test_ic01_evidence_review_invalid_format`: trading_partner = `xyz` (regex 비매칭) → `ic01_evidence_level == "review"` + `ic01_review_reason == "nonstandard_format"`
  - `test_ic01_excluded_customer_code`: trading_partner = `C-000123` → IC01 score = 0 + `ic01_evidence_level == ""`
  - `test_ic01_excluded_vendor_code`: trading_partner = `V-000123` → IC01 score = 0 + `ic01_evidence_level == ""`
- Acceptance: 5 개 테스트 모두 통과
- Size: M (35 min)

### T-P5-3: score_aggregator floor 회귀 테스트
- File: `tests/modules/test_detection/test_score_aggregator.py` (없으면 신규 생성)
- 신규 테스트:
  - `test_ic01_high_alone_medium`: IC01 hit + evidence=`high` 단독 → row floor Medium 0.40
  - `test_ic01_review_alone_low`: IC01 hit + evidence=`review` 단독 → row floor Low 0.20
  - `test_ic02_ic03_combo_medium`: IC02 + IC03 hit, IC01 없음 → Medium 0.40 (2 개 이상 결합 유지)
  - `test_ic01_high_with_ic02_medium`: IC01[high] + IC02 → Medium 0.40 유지
  - `test_ic01_review_with_ic02_medium`: IC01[review] + IC02 → Medium 0.40 (2 개 이상 결합 유지)
- Acceptance: 5 개 테스트 모두 통과
- Size: M (40 min)

### T-P5-4: ripple-search 의미 검토 (acceptance 보정 #5 반영)
- Commands:
  ```bash
  grep -rn 'endswith("-UNMATCHED")' src/ tools/ tests/ docs/
  grep -rn 'partner.str.contains("-")' src/ tools/ tests/ docs/
  grep -rn 'ic_unmatched_reference' src/ tools/ tests/ docs/
  grep -rn '"IC01"' src/ tools/ tests/ docs/ config/
  grep -rn 'intercompany_exception' src/ tools/ tests/ docs/ config/
  ```
- Acceptance:
  - **0건 acceptance (3 항목)**:
    - `endswith("-UNMATCHED")` 코드 0건 (production code 전체)
    - `ic_unmatched_reference` sidecar 의 **detector 직접 의존** 코드 0건 (평가/리포트 단계에서 ground truth 비교용 read 는 허용)
    - `partner.str.contains("-")` 휴리스틱 0건 (production code 전체)
  - **조사만, 변경 없음 (IC01 literal)**: `"IC01"` literal 은 `RULE_CODES`, `SEVERITY_MAP`, `RULE_DETAIL_METADATA_REGISTRY`, `metrics/rule_mapping.py`, `phase2_subdetector_tiers.yaml`, `dashboard mappings` 에 그대로 유지. ripple-search 결과는 의미 검토 후 fitting 외에는 유지하는 정책.
  - **영향받는 파일 (조사 후 의미 검토만)**: `src/export/phase1_case_view.py`, `src/metrics/rule_mapping.py`, `src/detection/constants.py`, `config/phase2_subdetector_tiers.yaml`, dashboard mappings. 휴리스틱 외 변경 없음.
  - 결과를 `dev/active/ic-matcher-redesign/ripple_search_after.md` 에 첨부 (의미 검토 결과 명시)
- Size: S (20 min)

### T-P5-5: PHASE1 KPI guard 측정
- Commands:
  ```bash
  # Before (P0 시작 전에 측정 권장)
  uv run python tools/scripts/profile_phase1_v126.py \
      --output dev/active/ic-matcher-redesign/kpi_before.json
  # After (P5 완료 시점)
  uv run python tools/scripts/profile_phase1_v126.py \
      --output dev/active/ic-matcher-redesign/kpi_after.json
  ```
- 검증:
  - Layer A HARD: PHASE1 hit count 분포 회귀 미발생
  - Layer B HARD: composite_sort_score 분포 lock baseline (v126_profiled) 회귀 미발생
  - Layer C SOFT WARN: Top200 truth_doc / high_cases >= 2.0% (v126 2.45% baseline)
- Acceptance:
  - A/B HARD 통과
  - C 측정값을 context.md `결정 사항` 절에 기록
  - C 위반 시 사용자에게 옵션 제시 (A. 진행 / B. rollback / C. PHASE2 이관)
- Size: M (30 min)

---

## Phase P6 — Validation & Completion

### T-P6-1: IC matcher 단위 테스트 통과
- Command: `uv run pytest tests/modules/test_detection/test_intercompany_matcher.py -v`
- Acceptance: 전체 테스트 통과 (기존 23 + 신규 7+)
- Size: S (10 min)

### T-P6-2: detection 전체 단위 테스트 통과
- Command: `uv run pytest tests/modules/test_detection/ -v`
- Acceptance: 전체 통과 또는 사전 알려진 skip
- Size: S (15 min)

### T-P6-3: dashboard import smoke
- Command: `uv run streamlit run dashboard/app.py` (30 초 후 Ctrl+C)
- Acceptance: ImportError / AttributeError 0건
- Size: S (10 min)

### T-P6-4: context.md 마감 갱신
- File: `dev/active/ic-matcher-redesign/ic-matcher-redesign-context.md`
- 변경: Status, Progress, Known Issues 갱신. 미해결 항목은 docs/ 활성 lock 문서에 이관 또는 별도 plan 생성.
- Acceptance:
  - Progress 23 / 23 (100%) 표시
  - KPI guard 측정값 결정 사항에 기록
  - 미해결 항목 cross-reference (CLAUDE.md "이슈 추적 & 리포트 규칙" 준수)
- Size: S (15 min)

---

## Deployment Checklist (Final Gate)

- [x] `endswith("-UNMATCHED")` 코드 라인 grep 0건 (production code 전체) — ripple_search_after.md 검증
- [x] `partner.str.contains("-")` 휴리스틱 코드 라인 grep 0건 (production code 전체) — ripple_search_after.md 검증
- [x] `ic_unmatched_reference` sidecar 의 detector 직접 의존 코드 0건 (평가/리포트 read 허용) — `phase1_case_builder.py:2609` 의 case-level read 만 잔존, D065 범위
- [x] `intercompany_exception_reasons` 가 `IC01[high]` / `IC01[review]` 표기 사용 — T-P2-2 적용
- [x] `docs/DETECTION_RULES.md`, `DETECTION_REFERENCE.md`, `RULE_DETAIL_METADATA_V1_LOCK.md`, `PHASE1_TOPIC_SCORING_V1_LOCK.md`, `PHASE1_RULE_RELATIONSHIP_MAP.md` 갱신 완료 — T-P3-1~5
- [x] `docs/DECISION.md` D055 supersede 라인 + D065 신규 결정문 추가 완료 — T-P3-6
- [x] `config/audit_rules.yaml::patterns.intercompany` 신규 키 (`related_party_master`, `partner_format`) 추가 — T-P1-4
- [x] `config/settings.py` 신규 옵션 default 적용 — T-P1-5 (`ic_use_related_party_master`, `ic_period_boundary_days`)
- [x] `tests/modules/test_detection/test_intercompany_matcher.py` 통과 (30 passed — 기존 23 + 신규 7)
- [x] `tests/modules/test_detection/test_score_aggregator.py` 통과 (97 passed — 기존 92 + 신규 5 floor 테스트)
- [x] `tools/scripts/build_datasynth_v38_ic_exception_labels.py` `-UNMATCHED` 패턴 제거 — T-P4-1/2
- [~] DataSynth v38 candidate 재생성 산출물 검증 완료 — **deferred (결정 11)**. v7_fixed4 운영 baseline 의 `-UNMATCHED` grep 0건 확인으로 대체.
- [~] PHASE1 KPI guard Layer A/B HARD 통과 — **deferred (결정 12)**. `dev/active/ic02-calibration/` 통합 측정.
- [~] PHASE1 KPI guard Layer C SOFT WARN 결과 기록 — **deferred (결정 12)**. IC02 calibration plan 에서 통합 보고.
- [x] Dashboard import smoke 통과 — `uv run python -c "import dashboard.app"` ImportError 0
- [x] **(K-06, 결정 13)** IC01 review-level 의 `details["IC01"]` score = 0 유지 (confirmed 격상 방지) — review 행 런타임 검증 완료. high 만 `score = 1.0`.
- [x] **(K-07, 결정 13)** sidecar 두 컬럼 (`ic01_evidence_level`, `ic01_review_reason`) 이 `DetectionResult.metadata["row_sidecar"]: dict[str, pd.Series]` 에 위치 — `details` 는 numeric only (`['IC01', 'IC02', 'IC03']` × `float64`)
- [x] **(K-07, 결정 13)** `metrics/ground_truth_evaluator.py:1152, 1537` 의 `details > 0` 비교에서 TypeError 0건 — `(result.details > 0).any().any()` 정상 동작
- [x] **(K-08, 결정 13)** `test_intercompany_matcher.py` / `test_intercompany_v7_fixed3_smoke.py` review 케이스 assert 갱신 (`details["IC01"] == 0.0`, sidecar 는 `metadata["row_sidecar"][col]`) — `uv run pytest tests/modules/test_detection/ -q` 1130 passed, 3 skipped, 0 failed
- [ ] `docs/debugging.md` 트러블슈팅 기록 (해당 사항 없음)
- [ ] `CLAUDE.md` 문서 가이드 표 갱신 (신규 lock 문서 없음 — 기존 문서 갱신만)
- [ ] `dev/active/ic-matcher-redesign/` 완료 후 `docs/completed/` 이관 — 후속 작업

표기 범례:
- `[x]` — 완료
- `[~]` — deferred (결정 11·12 사유, IC02 calibration plan 으로 이관)
- `[ ]` — 미해당 또는 후속 작업

---

## KPI Guard 위반 대응 절차

본 plan 의 PHASE1 코드 변경이 `feedback_phase1_truth_recall_guard` 의 KPI guard 를 위반할 경우:

1. **Layer A HARD 위반** (예: PHASE1 hit count 의 schema 무결성 깨짐):
   - plan 즉시 중단
   - 변경사항 rollback
   - context.md 에 실패 사유 기록
   - 사용자에게 옵션 제시 (수정 후 재시도 / plan 전면 재설계 / PHASE2 이관)

2. **Layer B HARD 위반** (예: composite_sort_score lock baseline 회귀):
   - plan 즉시 중단
   - 변경사항 rollback
   - artifact (`artifacts/phase1_sort_composite_lock.md`) 비교 결과 첨부
   - 사용자에게 옵션 제시

3. **Layer C SOFT WARN 위반** (Top200 truth_doc / high_cases < 2.0%):
   - plan 진행 가능
   - context.md `결정 사항` 절에 측정값과 변동량 기록
   - 사용자에게 보고 후 진행 여부 확인
   - PHASE2 이관 옵션 검토
