# IC Matcher Redesign — Strategic Plan

## 0. 작업 시작/종료 체크리스트 (CLAUDE.md `### ⚠️ 태스크 시작/종료 시 필수 체크리스트`)

### 시작 시
- [ ] 현재 브랜치 확인. `develop` 또는 신규 feature 브랜치(`feature/ic-matcher-redesign`) 사용. `docs/GIT.md` 브랜치 전략 준수.
- [ ] 활성 plan/context/tasks 위치 — `dev/active/ic-matcher-redesign/` 3 파일.
- [ ] PHASE1 KPI guard 기준선 측정. `feedback_phase1_truth_recall_guard` 의 Layer A/B HARD, Layer C SOFT WARN 임계 확인.
- [ ] DataSynth 재생성 트리거 여부 결정 (Task P4 의존). Rust 수정 필요 시 별도 sub-plan 으로 분리.
- [ ] `config/audit_rules.yaml::patterns.intercompany` 위치 재확인 (IC pair SoT). `config/phase1_case.yaml` 은 case-level 정책만 보유.

### 종료 시
- [ ] `docs/debugging.md` 에 트러블슈팅 기록 (있을 경우).
- [ ] `docs/DETECTION_RULES.md`, `docs/DETECTION_REFERENCE.md`, `docs/RULE_DETAIL_METADATA_V1_LOCK.md`, `docs/PHASE1_TOPIC_SCORING_V1_LOCK.md`, `docs/DECISION.md` 갱신 반영.
- [ ] `CLAUDE.md` 문서 가이드 표 갱신 여부 확인 (lock 문서 신규 항목 추가 시).
- [ ] 완료 산출물 `docs/completed/` 이동 여부 확인.
- [ ] KPI guard 결과 첨부 (Layer A/B HARD 위반 시 plan 중단·사용자 확인).

---

## 1. Executive Summary

`IntercompanyMatcher` 의 IC01 룰은 도메인 휴리스틱이 아닌 DataSynth label generator 가 주입한 `-UNMATCHED` patch signature 를 직접 매칭하는 fitting 잔재(`src/detection/intercompany_rules.py:354`)와 label-derived sidecar(`ic_unmatched_reference`) 직접 참조를 포함한다. 본 plan 은 (a) fitting 코드 제거, (b) IC01 을 도메인 근거 기반으로 재정의 (외부 rule id 는 `IC01` 단일 유지, 내부 evidence level sidecar 로 high/review 구분), (c) 근거 문서를 IFRS 10·K-IFRS 1110·K-IFRS 1024·ISA 600 으로 재정렬, (d) `score_aggregator` floor 정책을 evidence level 에 따라 차별 적용, (e) DataSynth label patch 의 `-UNMATCHED` 패턴 제거, (f) `docs/DECISION.md` D055 supersede 결정문 추가를 수행한다.

PHASE1 truth recall 직접 추구는 금지(메모리 `feedback_phase1_truth_recall_guard`)이며, 본 plan 의 정당화는 도메인 정합성이다. 코드 fitting 제거에 따른 IC01 hit 감소가 발생해도 (1) Layer A HARD 미위반, (2) Layer C SOFT WARN 시 사용자 확인 후 진행, (3) PHASE1 → PHASE2 이관 가능성을 plan 에 명시한다.

## 2. 현재 상태 (Current State)

### 2.1 IC01/IC02/IC03 분리 책임

| Rule | 책임                                                   | 구현 위치                                         |
|------|--------------------------------------------------------|---------------------------------------------------|
| IC01 | 미매칭 IC — 대응 그룹 없음 + 명시적 회사 상대방        | `src/detection/intercompany_rules.py:320~365`     |
| IC02 | 매칭됐으나 금액 차이 > tolerance + cross_currency 억제 | `src/detection/intercompany_rules.py:368~398`     |
| IC03 | 매칭됐으나 전기일 차이 > window                        | `src/detection/intercompany_rules.py:401~431`     |

공유 매칭 엔진: `match_ic_groups()` (`src/detection/intercompany_rules.py:80~217`). 3개 서브룰이 사전 계산된 `match_df` 를 재사용한다.

### 2.2 발견된 Fitting / Leakage 증거

| ID    | 위치                                                  | 증거                                                                                                                                              | 분류                    |
|-------|-------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------|-------------------------|
| F-01  | `src/detection/intercompany_rules.py:354`             | `looks_like_company_partner = partner.str.endswith("-UNMATCHED") \| ~partner.str.contains("-")` 가 DataSynth patch signature 를 직접 매칭         | 코드 fitting            |
| F-02  | `tools/scripts/build_datasynth_v38_ic_exception_labels.py:316` | `unmatched_partner = f"C{...:03d}-UNMATCHED"` 로 trading_partner 를 patch 하여 IC01 휴리스틱에 짝을 맞춘 라벨 주입                          | DataSynth label fitting |
| L-01  | `src/detection/intercompany_rules.py:332~340`         | `ic_unmatched_reference` sidecar 가 IC01 score 의 백업 경로로 직접 사용됨. sidecar 자체는 reference prefix 기반이지만 label 주입 흐름과 결합 운영됨 | sidecar leakage 위험    |
| L-02  | `tools/scripts/profile_phase1_v126.py:198`            | `ic_unmatched_reference = has_ic_reference & ~ic_matched_pair_found` 가 row 단위로 부착되어 `phase1_case_builder` 에서 직접 소비                  | 파이프라인 결합도       |

### 2.3 도메인 근거 불일치

현재 IC01 근거는 ISA 550 §23 단일 매핑이지만, IC 양측 대사 룰의 실질 근거는 다음으로 재정렬해야 한다.

| 근거                       | 적용                                              | 현재 상태       |
|----------------------------|---------------------------------------------------|-----------------|
| IFRS 10 §B86               | 연결 내부거래 제거 원칙                            | 미명시          |
| K-IFRS 1110                | 연결재무제표 작성 시 내부거래 제거 절차            | 미명시          |
| K-IFRS 1024                | 특수관계자 공시 의무                               | 미명시          |
| KICPA Issue Paper 46       | JET 완전성 — 양측 대사                             | 미명시          |
| ISA 600                    | 그룹감사 — 구성단위 간 잔액 대사                   | 미명시          |
| ISA 550 §23                | 특수관계자 거래 합리성 (보조 근거로 유지)          | 단독 명시       |

### 2.4 IC pair 설정 SoT

IC pair 정의는 `config/audit_rules.yaml::patterns.intercompany.pairs` (≈ line 309) 가 SoT 다. `config/phase1_case.yaml` 은 `patterns.intercompany.pairs` 를 보유하지 않는다. `load_ic_pairs()` (`src/detection/intercompany_rules.py`) 도 `audit_rules.yaml` 구조를 읽도록 구현되어 있다. 본 plan 의 신규 키 (`related_party_master`, `partner_format`) 도 동일 위치 (`config/audit_rules.yaml::patterns.intercompany`) 아래에 둔다. `phase1_case.yaml` 에는 IC 관련 case-level 정책 (`intercompany_exception` topic floor, `intercompany_rules` 분류) 만 유지한다.

### 2.5 D055 (2026-05-18) 와의 충돌

`docs/DECISION.md:514` D055 는 `ic_unmatched_reference=True` 를 IC01 high-confidence unmatched IC evidence 로 수용한다고 명시한다. 본 plan 의 P0 (sidecar 의존 제거) 와 P1 (IC01 재정의) 은 D055 를 정면으로 뒤집는 작업이므로 P3 에서 명시적 supersede 결정문(`D0xx`)을 신규 추가한다.

## 3. Goals / Non-goals

### Goals

- IC01 의 fitting 코드(F-01) 와 label-derived sidecar 직접 의존(L-01) 제거.
- IC01 의 evidence 분류를 외부 rule id 단일 (`IC01`) 유지 + 내부 sidecar column (`ic01_evidence_level`, `ic01_review_reason`) 으로 high/review 분리.
- `score_aggregator` floor 정책을 `ic01_evidence_level == "high"` (Medium) / `ic01_evidence_level == "review"` (Low) 로 차별 적용. IC02/IC03 단독 Low 는 유지.
- 근거 문서(`DETECTION_RULES.md`, `DETECTION_REFERENCE.md`, `RULE_DETAIL_METADATA_V1_LOCK.md`) 의 IFRS 10·K-IFRS 1110·1024·ISA 600 reference 정렬.
- DataSynth label patch 의 `-UNMATCHED` 패턴을 제거하거나, 평가용 sidecar 로 격리하여 detector code 가 직접 참조하지 않도록 분리.
- `docs/DECISION.md` 에 D0xx 신규 결정문 추가하여 D055 supersede 명시.
- PHASE1 ↔ PHASE2 contract (row feature, ml_score 결합) 비호환 변경 없음.

### Non-goals

- **외부 rule id 분리 (IC01_A / IC01_B 등 신규 코드 도입) 는 본 plan 범위 아님.** 외부 rule id 는 `IC01` 단일 유지. 사용자 결정 채택 (요청서 §보정2).
- **severity 재조정 (IC01/IC02/IC03 의 SEVERITY_MAP 점수 변경) 은 본 plan 범위 아님.** `src/detection/constants.py:195` 의 현재 값 (`IC01=3, IC02=2, IC03=2`) 보존. 사용자 결정 채택 (요청서 §보정3). 점수 세기 변경 필요성은 §11 Open Questions 로 미룬다.
- PHASE2 ML detector (Layer A/B/C) 의 IC 관련 feature 재학습. (별도 plan 필요 시 분리)
- Vanna text-to-SQL, Export 등 Phase 3 비범위 영역.
- `GR01/GR03` 그래프 룰 재설계. (관계사 cycle 은 별도 트랙)
- `L3-03` 관계사 모집단 룰 정의 변경. (모집단 신호는 유지)
- `match_ic_groups()` 매칭 엔진의 N:M 알고리즘 자체는 유지. 외부 결과 컬럼만 확장.

## 4. Proposed Solution

### 4.1 IC01 도메인 룰 재정의 (외부 단일 + 내부 evidence level)

외부 rule id 는 `IC01` 단일을 유지하고, evidence level 은 sidecar column 으로 표현한다.

| evidence level   | 정의                                                                                                                                  | floor 정책                | reason code 예시                                            |
|------------------|---------------------------------------------------------------------------------------------------------------------------------------|---------------------------|-------------------------------------------------------------|
| `high`           | IC 모집단 + 그룹 매칭 실패 + 명시적 회사 상대방 코드 존재 + 관계사/그룹 master 에 대사 실패                                            | Medium (0.40)             | `high_confidence_unmatched`                                 |
| `review`         | IC 모집단 + 그룹 매칭 실패 + (trading_partner 결측 OR 형식 비표준 OR master mapping 미정)                                              | Low (0.20)                | `missing_partner`, `nonstandard_format`, `mapping_uncertain` |
| (제외)           | IC 모집단 + counterparty 가 customer/vendor master 또는 외부 거래처 → IC 룰 평가 모집단에서 제외                                       | 0.0 (점수 미산출)         | -                                                           |

**핵심 변경**:

- 현재 `endswith("-UNMATCHED")` 패턴 매칭(F-01) 은 evidence level 판정에서 완전히 제거하고, 대신 **관계사 master** 와의 명시적 대사 결과(가능 시 `related_party_master`, 폴백 시 `company_code` set) 에 기반한다.
- `IC01` 외부 score: evidence=`high` 만 `score = 1.0`. evidence=`review` 는 `score = 0.0` 으로 confirmed violation 격상 차단. evidence_level/review_reason 는 두 분기 모두 채워진다.
- sidecar 두 컬럼 (`ic01_evidence_level`, `ic01_review_reason`) 의 저장 위치: `DetectionResult.metadata["row_sidecar"]: dict[str, pd.Series]`. `DetectionResult.details` 에는 numeric rule-score (IC01/IC02/IC03 float64) 만 유지한다. 근거: `metrics/ground_truth_evaluator.py:1152, 1537` 의 `details > 0` 비교에서 TypeError 방지 + `AGENTS.md` "review-only signals must not become confirmed violations".
- `ic01_evidence_level` 값: `"high"` / `"review"` / `""`. `ic01_review_reason` 값: review level 일 때 사유 코드, 그 외 빈 문자열.

### 4.2 IC02 / IC03 보강

- **IC02**: 기존 `match_df["diff_ratio"] > amount_tolerance` 유지. `cross_currency=True` 일 때 FX 환산 테이블 부재 시 별도 reason code `ic02_fx_table_missing` 부여 (점수 억제는 유지).
- **IC03**: 기존 `date_diff_days > date_window_days` 유지. 결산 경계(±`period_end_margin_days`) 에 걸리면 reason code `ic03_period_boundary_adjacent` 부여 (점수 가중치는 변경 없음, 감사인 우선순위 표시용).

### 4.3 코드 인터페이스 변경

#### `intercompany_rules.py` — `ic01_unmatched_intercompany()`

기존:

```python
def ic01_unmatched_intercompany(df, *, match_df) -> pd.Series:
    ...
    # F-01 fitting line
    looks_like_company_partner = partner.str.endswith("-UNMATCHED") | ~partner.str.contains("-", regex=False)
    # L-01 sidecar 직접 의존
    sidecar_unmatched = df["ic_unmatched_reference"] & ic_rows
    target = sidecar_unmatched | (ic_rows & no_counterpart & unknown_partner & looks_like_company_partner)
    return target.map(...)
```

변경 후 (signature 확장, 외부 단일 score + 내부 sidecar 반환):

```python
def ic01_unmatched_intercompany(
    df: pd.DataFrame,
    *,
    match_df: pd.DataFrame,
    related_party_master: set[str] | None = None,
    partner_format_policy: dict | None = None,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """반환: (score, evidence_level, review_reason).

    - score: high 만 1.0, review 와 미해당은 0.0 (confirmed violation 격상 차단).
    - evidence_level: 각 row 의 evidence 분류 ("high" / "review" / "")
    - review_reason: review level 일 때 사유 코드, 그 외 빈 문자열
    """
```

#### `intercompany_matcher.py` — `_build_registry()` / `_build_result()`

- `rule_results` 의 `IC01` entry 는 **단일 series** 그대로 등록. (외부 id 변경 없음)
- `_build_result()` 에서 `details` 는 numeric rule-score (IC01/IC02/IC03 `float64`) matrix 만 유지. 두 sidecar series (`ic01_evidence_level`, `ic01_review_reason`) 는 `DetectionResult.metadata["row_sidecar"]: dict[str, pd.Series]` 로 부착한다.
- `details["IC01"]`, `rule_flags` 의 `IC01` 항목은 그대로 단일 유지. dashboard / export 표시 맵 변경 불필요.
- 런타임 계약: `result.details.columns == ['IC01', 'IC02', 'IC03']`, dtypes 전부 `float64`, `(result.details > 0).any().any()` 정상 동작. review 행은 `details["IC01"] == 0.0` + `metadata["row_sidecar"]["ic01_evidence_level"] == "review"`.

#### `score_aggregator.py` — `_apply_intercompany_exception_corroboration()`

`exception_rules = ["IC01", "IC02", "IC03"]` 그대로 유지. 단, IC01 hit 판정과 evidence level 은 다음과 같이 분리한다:

- **IC01 hit 판정**: `combined["IC01"] > 0` (high 만 score 1.0). review-level 은 `details["IC01"] = 0` 이므로 hit 으로 잡히지 않는다.
- **Evidence level read**: `_extract_ic01_evidence_level()` 헬퍼가 `DetectionResult.metadata["row_sidecar"]["ic01_evidence_level"]` 에서 read. 구버전 호환을 위해 `combined["ic01_evidence_level"]` (details fallback) 도 지원.
- **Review-only floor 적용**: review row 는 `details["IC01"] = 0` 이지만 sidecar evidence="review" 가 존재하므로 별도 mask 로 Low floor (0.20) 만 부여. confirmed 격상 (`flagged_rules` / case seed / GT 평가) 은 발생하지 않는다.

```python
# 변경 후 의사코드 (sidecar 는 metadata["row_sidecar"] 에서 read)
ic01_evidence = _extract_ic01_evidence_level(result)  # metadata 우선, details fallback
ic01_high_hit = combined["IC01"] > 0                  # high 만 score>0
ic01_review_mask = (ic01_evidence == "review")        # details["IC01"] == 0 이지만 sidecar 로 판별
ic01_hit = ic01_high_hit | ic01_review_mask           # floor 산정용 통합 mask
ic01_high = ic01_high_hit
ic01_review = ic01_review_mask & ~ic01_high_hit

ic02_hit = exception_hits["IC02"]
ic03_hit = exception_hits["IC03"]
exception_count = ic01_hit.astype(int) + ic02_hit.astype(int) + ic03_hit.astype(int)

# floor 정책 (4.4 참조)
medium_mask = ic01_high | (exception_count >= 2)
low_mask = (ic01_review | ic02_hit | ic03_hit) & ~medium_mask
```

### 4.4 score_aggregator floor 정책 변경표

| 조건                                              | 기존 floor         | 변경 후 floor    | 비고                                            |
|---------------------------------------------------|--------------------|------------------|-------------------------------------------------|
| IC01 hit, evidence=`high`, 단독                   | Medium 0.40        | Medium 0.40      | 명시적 미대사 근거                              |
| IC01 hit, evidence=`review`, 단독                 | Medium 0.40        | Low 0.20         | review-only data quality                        |
| IC02 단독                                         | Low 0.20           | Low 0.20         | 변경 없음                                       |
| IC03 단독                                         | Low 0.20           | Low 0.20         | 변경 없음                                       |
| IC01(`high`) + IC02 / IC03                        | Medium 0.40        | Medium 0.40      | 변경 없음                                       |
| IC01(`review`) + IC02 / IC03                      | Medium 0.40        | Medium 0.40      | 2개 이상 IC 예외 결합 → Medium (기존 유지)      |
| IC02 + IC03 (IC01 없음)                           | Medium 0.40        | Medium 0.40      | 2개 이상 IC 예외 결합 → Medium (기존 유지)      |

**핵심 원칙**: `SEVERITY_MAP` 의 점수 세기 (severity) 는 보존하고, floor 차별은 `score_aggregator` 단계에서 evidence level sidecar 를 보아 처리한다. severity 보존과 floor 차별 정책은 책임 분리상 양립한다.

**Review-level confirmed 격상 방지 (2026-05-23 보정)**:

- `intercompany_rules.ic01_unmatched_intercompany` 의 review 분기는 `score = 0.0` 반환. high 만 `score = 1.0`.
- 결과: `details["IC01"] == 0.0` (review row), `metadata["row_sidecar"]["ic01_evidence_level"] == "review"`.
- `flagged_rules` (`combined[rule_id] > 0`) / case seed / ground-truth 평가 (`result.details > 0`) 는 review row 를 confirmed violation 으로 보지 않는다.
- 단, `score_aggregator._apply_intercompany_exception_corroboration()` 은 `metadata["row_sidecar"]` 에서 evidence_level 을 별도 read 하여 row-level `anomaly_score` 의 Low floor (0.20) 만 부여한다.
- 근거: `AGENTS.md` "review-only signals must not become confirmed violations".

### 4.5 YAML 설정 변경

#### `config/audit_rules.yaml::patterns.intercompany` (line 309 근방)

```yaml
patterns:
  intercompany:
    pairs:                              # 기존 유지
      - receivable: "1150"
        payable: "2050"
      - receivable: "4500"
        payable: "2700"
    related_party_master:               # 신규. Optional. 빈 list 시 dataset 의 company_code set 으로 폴백
      - C001
      - C002
      - C003
    partner_format:                     # 신규. Optional
      ic_partner_regex: "^C\\d{3}$"        # 회사 코드 형식 (사용자 클라이언트별 조정)
      customer_partner_regex: "^C-\\d+$"   # IC 룰 제외 대상
      vendor_partner_regex: "^V-\\d+$"     # IC 룰 제외 대상
```

#### `config/phase1_case.yaml`

`patterns.intercompany.pairs` 는 SoT 가 아니므로 **변경 지시 없음**. case-level 정책만 유지/조정.

- `phase1_case.intercompany_rules` 리스트: `[L3-03, IC01, IC02, IC03]` (기존 유지, 외부 rule id 단일).
- `phase1_case.topic_floors.intercompany_exception` 항목: 기존 단일 값을 유지하되, `score_aggregator` 가 evidence level 을 보고 row 단위 floor 를 결정하도록 변경. YAML 키 분리 불필요.

#### `config/settings.py`

```python
ic_use_related_party_master: bool = True   # False 시 dataset company_code 폴백
ic_period_boundary_days: int = 5            # IC03 reason code 부착용 (기본값 = period_end_margin_days)
```

### 4.6 DataSynth Label 격리

`tools/scripts/build_datasynth_v38_ic_exception_labels.py:316` 의 `f"C{n}-UNMATCHED"` patch 를 다음 중 하나로 변경:

| 옵션 | 변경 내용                                                                                            | 트레이드오프                                                |
|------|------------------------------------------------------------------------------------------------------|-------------------------------------------------------------|
| A    | trading_partner 를 그룹 외부의 실재 company code 로 변경 (`C9XX`, master 미등록)                     | 가장 도메인 정합. 추가 master mapping 정의 필요.            |
| B    | trading_partner 를 그대로 두고 `_label_sidecar.csv` 에만 `unmatched_truth_id` 기록                   | detector 코드 변경 최소. 단, scenario truth 의 field 일관성이 약해짐. |
| C    | 두 가지 모두 적용 (외부 코드 patch + sidecar 라벨 기록)                                              | 가장 robust. 작업량 큼.                                     |

**권장: 옵션 A**. evidence `high` 정의에 부합하는 자연스러운 도메인 시나리오를 만든다 (그룹 master 에 없는 회사 코드).

Python 스크립트로 직접 patch 가능 (Rust 재생성 불필요). DataSynth Rust 측은 `intercompany_normal_controls` 와 `intercompany_population_truth` 만 책임지고, v38 exception label 은 Python 후처리이므로 본 task 범위 내에서 수정 가능.

### 4.7 문서 정렬 (Spec & Lock)

| 문서                                            | 변경                                                                                                                                  |
|-------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------|
| `docs/DETECTION_RULES.md:1085~1132` (L3-03 절)  | IC01 단일 표기 유지. evidence level (`high` / `review`) sidecar 정책 절 추가. 근거 IFRS 10 / K-IFRS 1110·1024 / ISA 600 명시. ISA 550 §23 보조 근거.|
| `docs/DETECTION_REFERENCE.md:153~241`           | §2.5 ISA 550 §23 본문 유지 + IFRS 10 §B86 / K-IFRS 1110 / 1024 / ISA 600 신규 절 추가.                                                |
| `docs/RULE_DETAIL_METADATA_V1_LOCK.md`          | Excluded list `IC01, IC02, IC03` 유지 (변경 없음). evidence level sidecar 정책만 신규 절 추가. canonical 32 count 영향 없음.          |
| `docs/PHASE1_TOPIC_SCORING_V1_LOCK.md`          | 관계사·내부거래·순환구조 topic Primary rules `IC01, IC02, IC03` 유지. floor 차별이 evidence level 기반임을 보조 절에 명시.            |
| `docs/PHASE1_RULE_RELATIONSHIP_MAP.md`          | intercompany_structure evidence type 표 `L3-03 IC01 IC02 IC03` 유지. mermaid 표기 변경 없음.                                          |
| `docs/DECISION.md`                              | **신규**: D0xx supersede 결정문 추가. D055 (2026-05-18) 본문 상단에 "Superseded by D0xx (YYYY-MM-DD)" 라인 추가.                       |

## 5. Implementation Phases

### Phase P0 — Fitting 제거 (1.0 ~ 1.5h)

**Goal**: F-01 (`-UNMATCHED` endswith) 코드 제거 + 기존 IC01 임시 도메인 분기로 대체.

**Tasks**:
- [ ] T-P0-1: `intercompany_rules.py:354` 의 `looks_like_company_partner` 휴리스틱 제거 — File: `src/detection/intercompany_rules.py` — Size: S
- [ ] T-P0-2: `ic01_unmatched_intercompany` 임시 단일 시리즈 반환 유지 (다음 phase 에서 시그니처 확장) — File: `src/detection/intercompany_rules.py` — Size: S
- [ ] T-P0-3: 회귀 테스트 실행 — `tests/modules/test_detection/test_intercompany_matcher.py` 전체 통과 확인 — Size: S

### Phase P1 — IC01 evidence level 재정의 (1.5 ~ 2.0h)

**Goal**: 외부 단일 `IC01` score + 내부 `ic01_evidence_level` / `ic01_review_reason` sidecar 분류 구현.

**Tasks**:
- [ ] T-P1-1: `ic01_unmatched_intercompany()` 시그니처 확장 — `related_party_master`, `partner_format_policy` 인자 추가, `(score, evidence_level, review_reason)` 튜플 반환 — File: `src/detection/intercompany_rules.py` — Size: M
- [ ] T-P1-2: `IntercompanyMatcher._build_registry()` 가 `IC01` 단일 entry 유지 + sidecar column 부착 경로 추가 — File: `src/detection/intercompany_matcher.py` — Size: S
- [ ] T-P1-3: `_build_result()` 가 `ic01_evidence_level`, `ic01_review_reason` 두 sidecar column 을 결과 DataFrame 에 동시 부착 — File: `src/detection/intercompany_matcher.py` — Size: S
- [ ] T-P1-4: `config/audit_rules.yaml::patterns.intercompany` 에 `related_party_master`, `partner_format` 신규 키 추가 — File: `config/audit_rules.yaml` — Size: S
- [ ] T-P1-5: `config/settings.py` 에 `ic_use_related_party_master`, `ic_period_boundary_days` 옵션 추가 — File: `config/settings.py` — Size: S

(보정 #3) SEVERITY_MAP 변경 task 는 본 plan 에서 제외. `IC01=3, IC02=2, IC03=2` 보존.

### Phase P2 — score_aggregator floor 분리 (0.5 ~ 0.75h)

**Goal**: evidence level (`high` / `review`) 에 따라 IC01 floor 차별 적용. IC02/IC03 단독 Low 는 유지.

**Tasks**:
- [ ] T-P2-1: `_apply_intercompany_exception_corroboration()` 의 IC01 hit 처리 로직에 `ic01_evidence_level` 컬럼 read 추가 → medium/low mask 재계산 — File: `src/detection/score_aggregator.py:1001~1063` — Size: M
- [ ] T-P2-2: `intercompany_exception_reasons` 문자열에 evidence level 표기 (예: `IC01[high]`, `IC01[review]`) 추가 — File: `src/detection/score_aggregator.py` — Size: S

(보정 #2) IC01 외부 코드 분리 task 는 본 plan 에서 제외. 외부 rule id 는 `IC01` 단일.

### Phase P3 — Spec & Lock 문서 정렬 + D055 supersede (1.0 ~ 1.5h)

**Goal**: 도메인 근거 재정렬 + evidence level sidecar 정책 명시 + D055 supersede 결정문 추가.

**Tasks**:
- [ ] T-P3-1: `docs/DETECTION_RULES.md` L3-03 절 + evidence level sidecar 정책 표 추가 — File: `docs/DETECTION_RULES.md` — Size: M
- [ ] T-P3-2: `docs/DETECTION_REFERENCE.md` IFRS 10 / K-IFRS 1110 / 1024 / ISA 600 절 추가 — File: `docs/DETECTION_REFERENCE.md` — Size: M
- [ ] T-P3-3: `docs/RULE_DETAIL_METADATA_V1_LOCK.md` evidence level sidecar 정책 절 추가 (Excluded list 본문은 변경 없음) — File: `docs/RULE_DETAIL_METADATA_V1_LOCK.md` — Size: S
- [ ] T-P3-4: `docs/PHASE1_TOPIC_SCORING_V1_LOCK.md` floor 차별 정책 보조 절 추가 (Primary rules 본문은 변경 없음) — File: `docs/PHASE1_TOPIC_SCORING_V1_LOCK.md` — Size: S
- [ ] T-P3-5: `docs/PHASE1_RULE_RELATIONSHIP_MAP.md` 본문 변경 없음. 보조 주석으로 evidence level sidecar 명시 — File: `docs/PHASE1_RULE_RELATIONSHIP_MAP.md` — Size: S
- [ ] T-P3-6 (**신규**): `docs/DECISION.md` 에 D0xx 신규 결정문 추가 — "D055 superseded by D0xx. `ic_unmatched_reference` sidecar 의존 제거, IC01 grouping 결과 + `related_party_master` 대사 기반으로 재정의. evidence level sidecar (`high`/`review`) 부착." 변경 사유 (fitting 증거 F-01/L-01, IFRS 10 B86 / K-IFRS 1110 / KICPA JET / ISA 600 도메인 정합), 정책, 영향 범위, 관련 산출물 명시. D055 본문은 그대로 두되 상단에 "Superseded by D0xx (YYYY-MM-DD)" 라인 추가 — File: `docs/DECISION.md` — Size: M

### Phase P4 — DataSynth Label Cleanup (0.5 ~ 1.0h)

**Goal**: `-UNMATCHED` patch 패턴 제거 + 라벨 sidecar 격리.

**Tasks**:
- [ ] T-P4-1: `build_datasynth_v38_ic_exception_labels.py:316` 의 `f"C{n}-UNMATCHED"` 를 그룹 외부 회사 코드(`C9XX`) 패치로 변경 — File: `tools/scripts/build_datasynth_v38_ic_exception_labels.py` — Size: S
- [ ] T-P4-2: `cases["field_patch"]` description 갱신 (`trading_partner_changed_to_non_master_company`) — File: 동일 — Size: S
- [ ] T-P4-3: 재생성 산출물 검증 — `labels/intercompany_exception_cases*.csv` 의 `patched_trading_partner` 분포 확인 — Size: S

### Phase P5 — 테스트 & Ripple-search (1.0 ~ 1.5h)

**Goal**: leakage 회피 검증 + evidence level 분류 검증 + 회귀.

**Tasks**:
- [ ] T-P5-1: `test_intercompany_matcher.py` 신규 테스트 — `endswith("-UNMATCHED")` 의존 제거 확인 (synthetic patch 없는 데이터에서 IC01 evidence=high 발현) — File: `tests/modules/test_detection/test_intercompany_matcher.py` — Size: M
- [ ] T-P5-2: evidence level 분류 테스트 — high (master 부재) / review (partner 결측) / 제외 (`C-000123`) 각각 검증 — Size: M
- [ ] T-P5-3: `score_aggregator` floor 회귀 테스트 — IC01[high] Medium / IC01[review] Low / IC02+IC03 Medium 케이스 — File: `tests/modules/test_detection/test_score_aggregator.py` — Size: M
- [ ] T-P5-4: **ripple-search 의미 검토** — 다음 키워드 검색 + 의미 분류 (fitting vs 유지). 결과를 `dev/active/ic-matcher-redesign/ripple_search_after.md` 에 첨부 — Size: S
  - `endswith("-UNMATCHED")` (acceptance: 0건)
  - `ic_unmatched_reference` (acceptance: detector 직접 의존 0건. 평가/리포트 단계 read 는 허용)
  - `partner.str.contains("-")` (acceptance: 0건 — fitting 휴리스틱)
  - `"IC01"` literal — 조사만, RULE_CODES / SEVERITY_MAP / registry / dashboard / metrics 모두 유지. 변경 없음.
- [ ] T-P5-5: PHASE1 KPI guard 측정 — Layer A/B HARD 통과 여부 확인, Layer C SOFT WARN 결과 첨부 — Size: M

### Phase P6 — Validation & Completion (0.5h)

**Goal**: 완료 증거 수집 + plan 마감.

**Tasks**:
- [ ] T-P6-1: `uv run pytest tests/modules/test_detection/test_intercompany_matcher.py -v` 통과 — Size: S
- [ ] T-P6-2: `uv run pytest tests/modules/test_detection/ -v` 전체 통과 — Size: S
- [ ] T-P6-3: dashboard import smoke — `uv run streamlit run dashboard/app.py` 30 초 ImportError 0 — Size: S
- [ ] T-P6-4: `dev/active/ic-matcher-redesign/ic-matcher-redesign-context.md` 마감 갱신 — Size: S

## 6. Risk Assessment

| Risk                                                                                       | Severity | Mitigation                                                                                                     |
|--------------------------------------------------------------------------------------------|----------|----------------------------------------------------------------------------------------------------------------|
| Fitting 제거로 IC01 hit 감소 → PHASE1 KPI guard Layer A/B HARD 위반                        | High     | T-P5-5 에서 측정. HARD 위반 시 plan 중단·사용자 확인. PHASE2 이관 옵션 검토.                                  |
| `related_party_master` 미정의 dataset 에서 IC01 evidence=high 분기 불가                    | Medium   | `ic_use_related_party_master=False` 폴백 — dataset 의 distinct `company_code` set 으로 master 대체.            |
| `ic_unmatched_reference` sidecar 의 `phase1_case_builder` 직접 소비(`:2609`) 호환성 손상   | Medium   | P0 에서는 sidecar 유지. P1 이후 sidecar 는 IC01 점수 백업 경로가 아닌, `review` evidence reason 보조로만 사용. |
| DataSynth label 변경으로 v38 candidate 데이터 재생성 필요                                  | Low      | Python script 직접 patch 가능 (Rust 재생성 불필요). 작업량 < 30 min.                                          |
| D055 supersede 결정문 누락 → DECISION 로그 추적성 손상                                     | Medium   | T-P3-6 으로 명시적 supersede 결정문 추가. D055 본문 상단에 supersede 라인 부착.                                |
| 기존 테스트 22 개 중 `TestIC01Unmatched` 6 개의 expectation 변경 필요                      | Medium   | T-P5-1/T-P5-2 에서 기존 테스트 update + 신규 evidence level 테스트 추가. assertion 명시화.                    |

## 7. Success Metrics

| Metric                                                                | 기준                                                       |
|-----------------------------------------------------------------------|------------------------------------------------------------|
| `endswith("-UNMATCHED")` 코드 라인 grep                              | 0건 (production code)                                      |
| `partner.str.contains("-")` 휴리스틱 코드 라인                       | 0건 (production code)                                      |
| `ic_unmatched_reference` detector 직접 의존                          | 0건. 평가/리포트 read 는 허용.                              |
| `tests/modules/test_detection/test_intercompany_matcher.py` 통과     | 100%                                                       |
| Layer A HARD KPI guard                                                | 미위반                                                     |
| Layer B HARD KPI guard                                                | 미위반                                                     |
| Layer C SOFT WARN — Top200 truth_doc / high_cases                     | 측정 + plan-context.md 에 기록 (변동 시 사용자 확인)       |
| `IntercompanyMatcher` import 시간                                      | < 100 ms (변경 전후 회귀)                                  |
| `result.details.dtypes` 모두 `float64`                                | review row 포함 전수 확인                                  |
| `(result.details > 0).any().any()` TypeError                          | 0건 (sidecar 가 details 에 섞이지 않음)                    |
| review row 의 `details["IC01"]`                                       | `== 0.0` (confirmed 격상 차단)                             |
| review row 의 `metadata["row_sidecar"]["ic01_evidence_level"]`        | `== "review"`                                              |

## 8. Dependencies

### Code
- `src/detection/base.py` (`BaseDetector`, `DetectionResult`)
- `src/detection/constants.py` (`SEVERITY_MAP` — 변경 없음, IC01/IC02/IC03 점수 보존)
- `src/detection/score_aggregator.py:_apply_intercompany_exception_corroboration`
- `src/detection/phase1_case_builder.py:2609` (`ic_unmatched_reference` 직접 소비)
- `tools/scripts/profile_phase1_v126.py:198` (sidecar 생성 위치, 변경 없음 권장)

### Config
- `config/audit_rules.yaml::patterns.intercompany` (line 309 근방, IC pair SoT)
- `config/phase1_case.yaml` (case-level 정책만)
- `config/settings.py`

### Docs
- `docs/DETECTION_RULES.md`
- `docs/DETECTION_REFERENCE.md`
- `docs/RULE_DETAIL_METADATA_V1_LOCK.md`
- `docs/PHASE1_TOPIC_SCORING_V1_LOCK.md`
- `docs/PHASE1_RULE_RELATIONSHIP_MAP.md`
- `docs/DECISION.md` (D055 supersede)

### Tests
- `tests/modules/test_detection/test_intercompany_matcher.py`
- `tests/modules/test_detection/test_score_aggregator.py` (있는 경우)
- `tests/modules/test_detection/test_intercompany_v7_fixed3_smoke.py`

### External
- 없음. 외부 API 호출 없음.

## 9. Migration / Compatibility

| 항목                                            | 처리                                                                                                                                |
|-------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------|
| 기존 `IC01` ruleflag 소비자                     | 외부 id `IC01` 단일 유지. consumer 코드 변경 없음. evidence level 은 sidecar column 으로만 노출.                                    |
| `intercompany_exception_reasons` 문자열 포맷    | `IC01` → `IC01[high]` / `IC01[review]` 표기로 변경 (qualifier 추가, base id 동일). dashboard 표시 컴포넌트 정합 확인.               |
| `phase1_case_builder._compute_topic_scores()`   | `ic_unmatched` 변수는 그대로 유지. 의미는 "IC01 hit" 로 동일. floor 분기는 `score_aggregator` 가 evidence level sidecar 로 처리. |
| DataSynth v38 candidate 데이터셋                | T-P4 적용 후 1 회 재생성. 기존 v38 candidate 는 quarantine.                                                                          |
| `RULE_DETAIL_METADATA_V1_LOCK.md` canonical 정책 | 외부 id `IC01` 단일 유지, `presenter_surface=intercompany_sidecar`, `include_in_l1_l4_transaction_count=False` 유지. canonical 32 count 영향 없음. |
| D055 (2026-05-18)                              | T-P3-6 에서 명시적 supersede. 본문 상단에 "Superseded by D0xx" 라인 + D0xx 신규 결정문 본문.                                       |
| `SEVERITY_MAP` (constants.py:195)               | **변경 없음**. IC01=3 / IC02=2 / IC03=2 보존. (보정 #3)                                                                              |

## 10. KPI Guard 절차 (PHASE1 truth recall 보호)

본 plan 은 PHASE1 직접 수정에 해당하므로 `feedback_phase1_truth_recall_guard` 의 3 계층 KPI guard 를 따른다.

| Layer | 가드 항목                                              | 위반 시 절차                                                                                  |
|-------|--------------------------------------------------------|-----------------------------------------------------------------------------------------------|
| A     | PHASE1 hit count, 룰 family weight, schema 무결성      | HARD. 위반 시 plan 즉시 중단, 사용자에게 옵션 제시.                                          |
| B     | composite_sort_score 분포, 정렬 lock 회귀              | HARD. 위반 시 plan 중단.                                                                      |
| C     | Top200 truth_doc / high_cases ≥ 2.0% (v126 baseline 2.45%) | SOFT WARN. 위반 시 측정값을 plan-context.md 에 기록하고 사용자 확인 후 진행.                |

측정 명령(예):

```bash
uv run python tools/scripts/profile_phase1_v126.py --output dev/active/ic-matcher-redesign/kpi_guard_after.json
uv run python tools/scripts/audit_decision_ids.py --baseline kpi_guard_before.json --candidate kpi_guard_after.json
```

## 11. Open Questions / Unresolved

1. `related_party_master` 의 우선 소스 — engagement settings vs YAML config vs profile sidecar 중 어디를 SoT 로 둘지. (제안: YAML `patterns.intercompany.related_party_master` 우선, 미정의 시 dataset company_code 폴백)
2. IC01 evidence=`review` 의 standalone Low floor 가 PHASE1 review queue 에서 너무 많이 뜨는지 측정 필요. 측정 후 floor 미적용(reason-only) 으로 전환 가능성.
3. **(추가)** IC01 review reason 코드 enum 의 최종 분류 합의 — 현재 제안 (`missing_partner`, `nonstandard_format`, `mapping_uncertain`) 외 추가 코드 (예: `partner_master_outdated`, `format_legacy`) 필요 여부.
4. **(추가)** IC01 / IC02 / IC03 severity 재조정 필요성 — 본 plan 에서 SEVERITY_MAP 변경은 비범위로 명시. 점수 세기 변경이 필요하다면 별도 plan 으로 분리. 후속 plan 시 KPI guard 영향 분석 필수.
5. DataSynth label 옵션 A 적용 시 그룹 외부 회사 코드(`C9XX`) 정의를 어디에 둘지 — `intercompany_exception_cases` schema 확장 또는 별도 sidecar.

### 본 plan 내 처리 완료된 finding (2026-05-23 코드 리뷰)

| Finding                                                                                     | Severity | 처리 결과                                                                                       |
|---------------------------------------------------------------------------------------------|----------|-------------------------------------------------------------------------------------------------|
| IC01 review-level 이 `details["IC01"]` 양수 score 로 들어가 `flagged_rules` / case seed / GT 평가에서 confirmed violation 으로 격상 | High     | `intercompany_rules.ic01_unmatched_intercompany` 의 review 분기를 `score = 0.0` 으로 변경. high 만 `score = 1.0`. |
| 문자열 sidecar (`ic01_evidence_level`, `ic01_review_reason`) 가 `DetectionResult.details` 에 섞여 `metrics/ground_truth_evaluator.py:1152, 1537` 의 `> 0` 비교에서 TypeError 위험 | High     | sidecar 를 `DetectionResult.metadata["row_sidecar"]` 로 이동. `details` 는 numeric only matrix 계약 유지. `score_aggregator._extract_ic01_evidence_level` 가 metadata 우선 + details fallback read. |
| review-level IC01 이 ground-truth IC01 검증 (rule score > 0 = 탐지 hit) 에서 false positive | Medium   | review row 의 `details["IC01"] == 0.0` 으로 유지되어 GT 평가 hit 조건 (`> 0`) 에서 자연 제외.    |

## 12. 예상 소요 시간

(보정 반영 후 재추정)

| Phase | 추정     | 변동 사유                                                                          |
|-------|----------|------------------------------------------------------------------------------------|
| P0    | 1.0~1.5h | 변경 없음                                                                          |
| P1    | 1.5~2.0h | 변경 없음 (외부 분리 없이도 sidecar 부착 작업량 동일)                              |
| P2    | 0.5~0.75h| **감소**. IC01 외부 분리 없으므로 mask 계산 단순화 (evidence level read 만 추가)   |
| P3    | 1.0~1.5h | 변경 없음. lock 문서 본문 변경량은 감소하지만 D055 supersede task (T-P3-6) 추가.   |
| P4    | 0.5~1.0h | 변경 없음                                                                          |
| P5    | 1.0~1.5h | ripple-search 의미 검토 절차 명시. IC01 literal 0건 acceptance 삭제로 실작업 감소.|
| P6    | 0.5h     | 변경 없음                                                                          |
| **합계** | **6.0 ~ 8.25h** | 기존 6.5~9.0h 대비 약 0.5~0.75h 감소. P2 단순화, P3 약간 증가.                |
