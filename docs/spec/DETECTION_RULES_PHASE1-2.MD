# PHASE1-2 Rules — family·macro 구조 단위 탐지 룰

> 2026-06-17 [DETECTION_RULES.md](DETECTION_RULES.md)에서 분리. PHASE1-2는 graph·relational·시계열·거시(macro) 등 **구조/모집단 단위** 전용 탐지기로, 전표 행 단위 PHASE1-1 룰과 독립 surface다(3-surface 불변식: PHASE1-1 룰 / PHASE1-2 family / PHASE2 VAE 비병합).

## 수록 룰

| 룰                       | 이름                                                                    | 단위                       | 코드                                                                                              |
| ------------------------ | ----------------------------------------------------------------------- | -------------------------- | ------------------------------------------------------------------------------------------------- |
| L4-02 / Benford          | Benford 분포 위반                                                       | 계정·월 모집단             | `src/detection` (macro_only, 중화)                                                                |
| L4-05                    | 비정상 시간대 집중                                                      | 행위/시점                  | **양쪽 소속(2026-06-20)**: PHASE1-2 family + PHASE1-1 OFF-TIME set. 코드 registry는 PHASE1-1 잔존 |
| D01                      | 계정과목 거래 활동량 급변                                               | 계정·전기대비              | `src/detection/variance_rules.py`                                                                 |
| D02                      | 월별 분포 패턴 변화                                                     | 월·전기대비                | `src/detection/variance_rules.py`                                                                 |
| IC01                     | UnmatchedIntercompany (관계사 미대사)                                   | 관계사 쌍 대사             | `src/detection/intercompany_*`                                                                    |
| IC02                     | IntercompanyAmountMismatch (금액 불일치)                                | 관계사 쌍 대사             | `src/detection/intercompany_*`                                                                    |
| IC03                     | IntercompanyTimingMismatch (시차 불일치)                                | 관계사 쌍 대사             | `src/detection/intercompany_*`                                                                    |
| GR01                     | CircularTransaction (N-hop 순환)                                        | graph                      | `src/detection/relational_*`/graph                                                                |
| GR03                     | TransferPricingAnomaly (양방향 비대칭)                                  | graph                      | `src/detection/relational_*`/graph                                                                |
| (후보) 한도 직하 밀집도  | 승인한도 직전 거래 밀집(density spike) macro 검정                       | 승인자·한도 모집단         | 추후 구현 — L2-01 보완                                                                            |
| (후보) 분할 회피         | 한 건을 쪼개 합이 원금액/한도에 근접하는 split(structuring)             | 거래처·계정 단위 거래 그룹 | 추후 구현 — 신규(구 L2-03 split_duplicate 이관)                                                   |
| (후보) 라운드넘버 밀집도 | 부자연스러운 둥근 금액(끝자리 0 다수) 비율이 정상 분포 대비 비정상 집중 | 계정·월·작성자 모집단      | 추후 구현 — 신규. L4-05식(macro + case 맥락연결, 단건 룰 아님)                                    |

> **구조화(structuring) — 추후 후보 2종**: 둘 다 "한 전표만 보면 정상이고 **여러 건을 모집단/그룹으로 묶어야** 회피 패턴이 드러나는" 구조 단위 신호라 PHASE1-1 행 단위 룰이 아니다.
> - **한도 직하 밀집도(density spike)**: PHASE1-1 `L2-01 승인한도 직하`(전표 단위 binary, 90~100% 구간, 90% 컷은 휴리스틱)의 통계적 보완. "기대 분포 대비 한도 직하 구간에 건수가 비정상적으로 몰렸는가"를 보는 **승인자·한도 모집단 단위** 검정.
> - **분할 회피(split)**: PHASE1-1 `L2-03 중복 전표`에서 이관(2026-06-19). 같은 거래처·계정에 짧은 기간 여러 건의 합이 원금액/승인한도에 근접하는 **거래 그룹 단위** 패턴. 정상 분할 납품·기성과 구별이 어려워 게이트(기간·합산 근접·정기 cadence 제외)가 필요하며, 행 단위가 아니므로 PHASE1-1에 두지 않는다.
> SoT 연계: [DETECTION_RULES.md](DETECTION_RULES.md) L2-01·L2-03 카드. (둘 다 미구현)

> **라운드넘버 밀집도 — 추후 후보 (신규룰, dual 소속)**: 부자연스럽게 둥근 금액(끝자리 0이 많은, 사람이 지어낸 티가 나는 금액 — 예 5,000,000 / 100,000,000)을 본다. 근거: PCAOB AS2401 §61(e) "round number" 부정 적신호 **명문**. FSS 감리 원문은 금액의 둥근 정도를 기록하지 않아 태깅 0(도구 경계 ≠ 감사 경계). 단건 라운드넘버는 정상 예산·계약에도 흔해 게이트 부적합 → **Benford(L4-02) 계열의 분포 신호**로 다룬다. **L4-05와 같은 dual 소속(예정)**:
> - **PHASE1-2 macro(본체)**: "계정·월·작성자 모집단에서 둥근 금액 비율이 정상 분포 대비 비정상 집중인가"를 보는 밀집도 검정. **전표 1건이 라운드넘버인지 보는 단건 룰은 만들지 않는다** — 단건은 정상 예산·계약에도 흔해 의미가 없고, 모집단 분포로만 본다.
> - **PHASE1-1 연결(L4-05식)**: macro 결과를 case에 **맥락 연결**한다 — case가 "라운드넘버 밀집 계정/월/작성자"에 속하면 within-tier 랭킹을 올리고 UI에 "라운드넘버 다수 발생(계정/사용자)" 배지를 단다. L4-05(작성자 off-hour 집중을 case에 연결)와 **동일 구조**다. tier 게이트 미참여, 점수 병합 금지(3-surface 불변식). 정의 SoT: [HIGH_COMBO_GROUNDING.md](HIGH_COMBO_GROUNDING.md) 보조축 절.
> - 구현 전이므로 현재는 등록만. 신규 룰 구현 시 PHASE1-2 macro로 적재하고 PHASE1-1에는 macro 결과를 case 맥락으로 연결한다(단건 룰 신설 아님).

> IC01~03(관계사 대사)은 PHASE1-2 family다. 상세 동작·평가계약·evidence_level·PHASE2 확률컬럼 서술은 **2026-06-20 본 문서 §IC Matcher로 이관**했다(구 [DETECTION_RULES.md](DETECTION_RULES.md) L3-03 카드 잔존분 정리). L3-03은 PHASE1-1 `is_intercompany` 1/0 context 태그만 남는다.
> macro(L4-02·D01·D02)는 registry에서 `macro_only`(role_factor=0)로 중화되어 PHASE1-1 tier에 0 기여하며, PHASE1-2 surface 재정립 시 이동한다. SoT: rule_scoring.py 주석.

---

<!-- 이하 DETECTION_RULES.md에서 byte-exact 이관된 카드 -->
#### L4-02 — Benford 위반 (BenfordViolation) — 독립 트랙 ✅

- **심각도**: 2
- **근거**: 520§5 기대값-차이 분석, 240-A45(e) 단수/끝자리
- **판정 기준**:

  | 지표       | 적합    | 한계적 적합 | 부적합      | 부적합(강) |
  | ---------- | ------- | ----------- | ----------- | ---------- |
  | MAD        | < 0.006 | 0.006~0.012 | 0.012~0.015 | > 0.015    |
  | KS p-value | > 0.05  | 0.01~0.05   | < 0.01      | —          |

  > MAD 근거: Mark Nigrini, *Benford's Law* (Wiley, 2012). 감사/포렌식 분야 사실상 표준.

- **역할**: 개별 전표 적발 룰이 아니라 **모집단/계정 단위 분포 이상 finding**.
  - Benford는 분포 검정이므로 “이 전표가 위반”을 직접 증명하지 않는다.
  - 행별 전표 목록은 조사 후보(drill-down)로만 사용한다.
  - PHASE1 transaction queue의 `priority_score`와 row-level `anomaly_score`에는 단독으로
    유입하지 않는다. 대신 PHASE1 artifact의 `metadata.macro_findings`에 Account / Process
    Queue 항목으로 저장한다.
- **탐지 로직**:
  1. `company_code + gl_account`별 금액 첫째 자리 분포를 Benford 기대분포와 비교한다.
     `company_code`가 없을 때만 `gl_account` 단독 그룹으로 fallback한다.
  2. 표본 500건 미만 그룹은 계정별 검정에서 제외한다. 100건 안팎의 작은 그룹은 Benford
     오차가 쉽게 커져 과탐 후보를 대량 생성하므로 Phase 1 finding에서 제외한다.
  3. finding 생성 기준은 MAD 중심이다. `MAD <= benford_mad_threshold(기본 0.012)`이면
     chi-square p-value가 낮아도 참고 통계로만 남기고 finding을 만들지 않는다.
  4. `0.012 < MAD <= 0.015`는 `moderate`, `MAD > 0.015`는 `strong` finding으로 본다.
  5. finding 그룹 안에서 `MAD threshold`를 초과한 첫째 자리 digit만 drill-down 후보로 선별한다.
  6. 전체 모집단 Benford 검정은 `benford_result` 요약 통계로만 저장한다. 전역 검정 결과만으로
     drill-down 후보나 행별 플래그를 만들지 않는다.
  7. 결과는 `benford_findings` metadata에 `scope`, `company_code`, `gl_account`, `sample_size`,
     `mad`, `chi2_p_value`, `finding_severity`, `flagged_digits`, `candidate_rows`,
     `candidate_documents`로 저장한다.
  8. 후보는 해당 digit 라인만 보관한다. 같은 `document_id` 전체로 전파하지 않으며,
     기본 행별 `L4-02` 점수와 `anomaly_flags` 반영은 0이다.
  9. PHASE1 case artifact 생성 시 `benford_findings`는 `metadata.macro_findings`로 투영된다.
     각 항목은 `rule_id=L4-02`, `queue_type=account_process_macro`, `company_code`,
     `gl_account`, `sample_size`, `review_score`, `finding_severity`, `candidate_rows/docs`,
     `flagged_digits`, `metrics.mad/chi2_p_value/max_deviation`을 포함한다.
- **구현**: `benford_detector.py` → `BenfordDetector(BaseDetector)`
  - 내부적으로 `anomaly_rules_statistical.py` → `c07_benford_violation()`을 호출한다.
  - 분포 수준 검정이므로 L3/L4 묶음과 별도 가중치를 부여하고, 단독으로 대량 행 플래그를 만들지 않는다.
- **필요 피처**: `debit_amount`, `credit_amount`, `first_digit` (금액에서 파생)
  - `first_digit`이 없으면 BenfordDetector는 graceful skip되어 행별 점수와 finding 후보가 0으로 남는다.
- **DataSynth 상태**: `BenfordViolation` 라벨은 성능 평가용으로 존재할 수 있으나,
  이 룰의 1차 산출물은 라벨 전표 적발이 아니라 분포 finding이다. 따라서 Phase 1 검증에서는
  `BenfordViolation` 라벨 precision/recall보다 finding 수, MAD 강도, 후보 라인 규모, 다른 룰과의
  결합 여부를 우선 본다.
- **DataSynth 평가 계약**:
  - `v52_candidate`부터 L4-02 정답은 전표 단위가 아니라 `fiscal_year + company_code + gl_account` 단위다.
  - `labels/benford_finding_truth*`는 Benford MAD 기준 이상 분포 group truth다.
  - `labels/benford_drilldown_candidates*`는 finding group 안에서 편차 digit에 속한 후보 라인이다.
  - `labels/benford_normal_groups*`는 충분한 표본이 있지만 Benford에 적합한 정상 group control이다.
  - `labels/benford_skipped_small_groups*`는 표본 수 미달로 평가 제외된 group이다.
  - 기존 `BenfordViolation` document label은 legacy 참고값이며, L4-02 precision/recall 분모로 쓰지 않는다.
  - `v54_candidate`부터는 contract truth와 별개로 Benford 강건성 평가용 sidecar를 추가한다.
  - `labels/benford_boundary_groups*`는 MAD 0.011~0.013 근처 경계 group이다.
  - `labels/benford_small_sample_controls*`는 표본 450~550건 근처의 최소 표본 경계 group이다.
  - `labels/benford_business_skew_normal_groups*`와 `labels/benford_company_specific_normals*`는 정상 업무상 digit 쏠림 또는 회사별 정상 차이를 나타낸다.
  - `labels/benford_weak_fraud_holdout*`, `labels/benford_high_mad_normal_controls*`, `labels/benford_broad_digit_findings*`는 룰 기준만으로 100% 맞히기 어려운 holdout/adversarial 평가용이다.
  - `labels/benford_adversarial_holdout*`는 위 sidecar를 합친 파일이며, strict pass/fail 정답이 아니라 실무형 robustness benchmark로만 사용한다.
  - `v120_candidate`부터 Benford sidecar도 `sidecar_role`로 구분한다. `benford_finding_truth*`는 contract truth, `benford_drilldown_candidates*`는 drilldown candidate, `benford_adversarial_holdout*`와 `benford_weak_fraud_holdout*`는 holdout, 정상/경계 group 파일은 normal 또는 boundary context다.
- **리포트 표시 정책**:
  - 일반 Rule Metrics의 `L4-02` 문서 라벨 precision/recall은 acceptance metric으로 사용하지 않는다. legacy `BenfordViolation` document label은 L4-02 직접 정답 분모에서 제외한다.
  - `PerformanceReport.benford_benchmarks`에 별도 Benford Population Benchmark를 표시한다.
  - PHASE1에서는 `build_phase1_case_queue()` 결과가 아니라
    `build_phase1_macro_finding_queue()` / `metadata.macro_findings` 결과로 표시한다.
    이 queue는 계정/모집단 검토 목록이며 transaction case High/Medium/Low 승격 근거가 아니다.
  - Benford sidecar가 없는 후보 데이터에서는 `sidecars_missing` benchmark를 표시한다. 이 상태는 L4-02 실패가 아니라 평가 계약 부재이며, row-level `L4-02` 점수 0으로 합불격을 판단하지 않는다.
  - 필수 지표는 `contract_findings`, `normal_group_controls`, `drilldown_candidate_rows/docs`다.
  - `v54` sidecar가 있으면 `adversarial_holdout`, `weak_fraud_holdout`, `boundary_groups`,
    `business_skew_normal_groups`, `company_specific_normals`, `high_mad_normal_controls`,
    `small_sample_controls`, `skipped_small_groups`를 함께 표시한다.
  - `high_mad_normal_controls` hit는 “오탐 확정”이 아니라 정상 사유 확인이 필요한 finding으로 해석한다.

  추가 검정 (Phase 2): Chi-square, Anderson-Darling


---

#### L4-05 — 비정상 시간대 집중 (AbnormalHoursConcentration) ✅ 【OFF-HOUR 트랙】

> **양쪽 소속(2026-06-20)**: 본 룰은 PHASE1-2 family(사용자 행동 집계 단위)이면서 동시에 PHASE1-1 **OFF-TIME set**(L3-05 주말·L3-06 심야와 함께 시간 보조축) 멤버다. 제거가 아니라 dual-membership. OFF-TIME set에서는 case 보조축으로만 쓴다 — tier 게이트 미참여, within-tier 정렬·UI 표시 전용, PHASE1-1 case 점수와 병합 금지(작성자 `created_by`가 L4-05 집중 사용자명단에 있으면 case에 맥락 태그로 연결). 정의 SoT: [HIGH_COMBO_GROUNDING.md](HIGH_COMBO_GROUNDING.md) OFF-TIME 보조축 절. 3-surface 불변식과 호환(점수 비병합).

- **심각도**: 3
- **운영 성격**: 확정 부정 판정이 아니라 Phase 1 후보 선별 룰이다. 특정 사용자의 감시 취약 시간대 입력 습관, 심야 다건 입력, 심야 급속 승인을 넓게 올린 뒤 금액·계정·승인·기말 신호와 함께 triage한다.
- **근거**: KLCA IT 체크리스트 — 특정 사용자가 감시 취약 시간대에 반복 입력하는 패턴은 단건 심야/주말 플래그보다 강한 행동 징후다.
- **탐지 로직**: 사용자별 비정상 시간대 입력 비율 이상치 + 실사용자 심야 다건 + 급속 승인 신호
  1. `time_zone_category in {"midnight", "overtime"}` 또는 주말/공휴일을 비정상 시간대로 본다.
  2. 자동/시스템 계정(`auto_entry_sources`, `automated_system`, `SYSTEM`, `IC_GENERATOR`)은 사용자 행동 통계, 소표본 심야 보완, 급속 승인 보조 신호에서 제외한다. 비교는 대소문자와 공백 차이를 정규화한다. 단 **위장 의심 행(`source_trust.lone_automated_mask` 기준 단독 자동)은 source 기반 제외를 받지 못하고 행동 통계 모집단에 남는다** (2026-06-13, OPEN_ISSUES #18 — source 위조로 시간대 분석 전체를 빠져나가는 회피 차단). persona/created_by 기반 제외는 게이트 대상이 아니다.
  3. `created_by`별 비정상 시간대 비율을 계산하고, 평균 대비 `abnormal_sigma_threshold` 이상인 사용자를 찾는다. 기본값은 Phase 1 후보 탐지 목적에 맞춰 `2.5σ`로 둔다.
  4. 절대 비율이 `min_abnormal_ratio` 미만이면 제외한다.
  5. sigma 이상치가 아니어도 실사용자의 심야 입력이 `min_high_context_midnight_entries` 이상이면 해당 사용자의 `midnight` 전표만 후보로 올린다. 기본값은 `100`건이다. 이 보완은 실제로 발생 가능한 심야 다건 사용자 케이스를 잡기 위한 것이며 `overtime`에는 적용하지 않는다.
  6. 사용자 수가 적으면 sigma 대신 `min_midnight_entries`와 비율 기준으로 fallback하고, 최소 사용자 전표 수 미만이어도 심야 입력이 충분히 반복되면 해당 심야 전표만 후보로 올린다.
  7. 수기 전표가 비정상 시간대에 입력되고 `rapid_approval_minutes` 이내 승인되면 별도 플래그한다. 미탐을 줄이기 위해 금액 하한은 두지 않으며, 자동 전표 source와 `automated_system`은 과탐 방지를 위해 제외한다.
- **구현**: `anomaly_rules_simple.py` → `c12_abnormal_hours_concentration()`
- **필요 피처**: `created_by`, `posting_date`, `time_zone_category`, `is_weekend`, `is_holiday`, `approval_date`, `approved_by`, `is_manual_je` 또는 `source`
- **L3-05/L3-06과의 관계**: L3-05는 주말/공휴일 단건, L3-06은 감사인이 설정한 심야 구간 단건만 잡는다. L4-05는 사용자의 overtime·심야·비근무일 입력이 한 사람에게 집중되는지를 보는 상위 패턴 룰이다.
- **튜닝 파라미터**: `abnormal_sigma_threshold`, `rapid_approval_minutes`, `min_abnormal_ratio`, `min_midnight_entries`, `min_user_entries`, `min_high_context_midnight_entries`, `auto_entry_sources`
- **기본값**: `abnormal_sigma_threshold=2.5`, `rapid_approval_minutes=5`, `min_abnormal_ratio=0.1`, `min_midnight_entries=3`, `min_user_entries=10`, `min_high_context_midnight_entries=100`.
- **해석 주의**: `min_high_context_midnight_entries` 보완은 recall을 높이는 대신 후보 수를 크게 늘릴 수 있다. 따라서 L4-05 단독 hit는 사용자 질의·업무 배경 확인 대상으로 보고, 고액·민감 계정·기말·승인통제·수기전표 신호와 겹칠 때 우선순위를 높인다.
- **PHASE1 점수 유입 원칙**: L4-05의 내부 band 점수는 확정 부정 확률이 아니라 Phase1 `timing_anomaly` 신호 강도다. `system_context_review(0.25) < sigma_outlier(0.45) < low_volume_midnight(0.50) < high_context_midnight(0.55) < rapid_approval(0.65)` 순서가 `rule_scoring.py`의 `normalized_score`까지 보존되도록 raw band를 직접 signal strength로 사용한다. 다만 evidence strength는 `weak`, timing weight는 0.15이므로 L4-05 단독으로 High/Medium case를 만들기보다 L1 승인통제, L3 기말·cutoff, L4 고액·희소 계정쌍, 수기전표 신호와 결합될 때 triage 우선순위를 올린다.
- **DataSynth 계약**: `v53_candidate` 기준 `AbnormalHoursConcentration`은 확정 라벨 subset으로 관리한다. 자동/반복 source와 `automated_system`은 라벨 주입 대상에서 제외하며, `normal_after_hours_context`와 중복되지 않아야 한다.
- **평가 계약**:
  - L4-05는 strict pass/fail 룰이 아니라 `coverage_anchor`다. 확정 `AbnormalHoursConcentration` 라벨은 direct subset이고, raw hit는 사용자 행동 검토 큐다.
  - `v111_candidate`부터 DataSynth strict L4-05 rule truth는 2022~2024를 통합한 사용자 행동 통계 컨텍스트에서 detector를 1회 실행한 뒤 `fiscal_year`로 나눈 결과다. 연도별 단독 실행은 사용자별 abnormal ratio, midnight count, sigma 기준이 달라지므로 robustness check로만 사용하고 strict FP/FN 평가에는 쓰지 않는다.
  - `labels/rule_truth_L4_05*`와 `labels/abnormal_hours_behavior_review_population*`은 동일한 raw behavior review universe다. `labels/abnormal_hours_concentration_cases*`는 confirmed anomaly subset이다.
  - `v120_candidate`부터 `labels/abnormal_hours_behavior_detector_universe*`는 `labels/abnormal_hours_behavior_review_population*`의 명시적 alias다. 둘 다 detector-contract universe이며 독립 현실성 sidecar로 쓰지 않는다.
  - `score_bands`는 `behavior_review_docs`, `sigma_outlier_docs`, `low_volume_midnight_docs`, `high_context_midnight_docs`, `rapid_approval_docs`로 나눈다.
  - `review_queue_docs`는 확정 라벨 기준 FP가 아니라 `behavior_review_docs`를 우선 사용한다.
  - detector는 row annotation에 `reason_codes`와 `primary_reason`을 남긴다. 동일 행이 사용자 집중과 급속 승인에 동시에 걸릴 수 있으므로 하위 band 합계는 전체 review 문서 수와 일치하지 않을 수 있다.

---


---

### 2.5 Variance 독립 트랙: 전기 대비 변동 (2개, 기존회사 전용)

`enable_variance_detection=True`로 켠 기존회사에서만 실행한다.
신규회사(anonymous), `fiscal_year` 없음, repository 미주입, 전기 engagement 미존재, 전기 summary 로드 실패 시 자동 스킵한다.
즉, 전기(fiscal_year - 1) engagement 데이터는 필요조건이지만 충분조건은 아니며, 기본 설정은 비활성화(`False`)다.

D01/D02는 PHASE1 Transaction Queue의 row/document-level 탐지 룰이 아니라 `Analytical Review Signals`
독립 섹션으로 리포팅한다. 즉, 단일 전표 precision·FP·FN 분모에 포함하지 않고
`fiscal_year + company_code + gl_account` 계정 group 단위의 review population coverage로 평가한다.
정상 사업 변화, 계절성, 배치성 처리, 계정체계 변경도 같은 신호를 만들 수 있으므로,
D01/D02 단독 hit는 부정 또는 오류 결론이 아니라 계정 검토 큐로 본다. L1~L4 row/document-level 룰과
겹치는 전표는 drill-down 및 case priority 보강 근거로만 사용한다.

PHASE1 정책상 D01/D02는 recall 우선으로 넓게 포착한다. 정상 사업 변화나 반복 배치 패턴이 함께
올라오는 것은 detector threshold를 높여 제거할 대상이 아니라, Account / Process Queue의
`macro_priority_score`, `queue_bucket`, `normal_likelihood`로 분리할 대상이다. 따라서
`review_score`는 원 raw 측정치(`weighted_variance`, `jsd`)로 보존하고, 사용자 큐 정렬은 보정된
`macro_priority_score`를 우선 사용한다. D01/D02는 여전히 row-level `anomaly_score`에는 0으로 남긴다.

PHASE1 전체 case 결과로 흘러갈 때도 같은 원칙을 유지한다. D01/D02는 같은
`fiscal_year + company_code + gl_account`에 속한 Transaction Queue case에 `macro_contexts`로만 붙는다.
`confirmed_*` bucket은 case priority에 작은 보강값을 줄 수 있고, `corroborated_*` bucket은 더 약한 보강값만
줄 수 있다. `normal_*`, `auxiliary_non_*`, `analytical_review` bucket은 설명 context로만 표시하며
priority 보너스를 주지 않는다. 이 설계는 정상 사업 변화가 큰 계정을 row-level 고위험으로 오해하지 않으면서,
기말·고액·승인통제 등 L1~L4 신호가 같은 계정에서 발생할 때는 분석적 절차 맥락을 잃지 않기 위한 것이다.

| Rule ID | 룰 이름                   | Severity | 감사기준서                | 구현 파일                         |
| ------- | ------------------------- | :------: | ------------------------- | --------------------------------- |
| D01     | 계정과목 거래 활동량 급변 |    4     | ISA 520 §5, PCAOB AS 2305 | `src/detection/variance_rules.py` |
| D02     | 월별 분포 패턴 변화       |    3     | ISA 520 §5                | `src/detection/variance_rules.py` |

#### D01 — 계정과목 거래 활동량 급변 (AccountActivityVariance)✅

- **입력**: 당기 DataFrame + `PriorSummary.account_aggregates`
- **성격**: Phase 1 분석적 검토용 스크리닝 룰. 단독 부정 판정이 아니라 계정 레벨 attention signal로 사용한다.
- **판정 로직**:
  - 당기/전기 `gl_account`별 거래 활동량 집계 비교 (`debit_amount + credit_amount` 기준 total_amount, count, avg_amount)
  - 가중평균 변동률 = `total_var × 0.5 + count_var × 0.3 + avg_var × 0.2`
  - 임계값: `variance_threshold` (기본 0.5 = 50%) 초과 시 해당 계정을 review population으로 기록
  - 신규 계정(전기 미존재): review population으로 기록 (변동률 = 1.0)
  - `company_code`가 있으면 `company_code::gl_account` prior를 우선 조회하고, 없으면 `gl_account` prior로 fallback한다.
- **잡아내는 신호**: 전기 대비 계정의 총 거래 활동량, 전표 건수, 평균 전표 금액이 급변한 경우. 신규 계정 등장도 포함한다.
- **출력 정책**: D01은 row-level anomaly score를 만들지 않는다. `details["D01"] = 0.0`으로 유지하고, `metadata.account_activity_variance`에 계정 단위 근거를 저장한다.
  - `RuleFlag.flagged_count`는 D01 review account에 속한 당기 행 수로 표시될 수 있지만, 최종 `DetectionResult.flagged_count`는 row score가 0이므로 증가하지 않는다.
- **운영 해석**: D01 단독은 `계정 검토 큐` 수준으로 보고, 고액 이상치·희귀 계정쌍·결산 전표·권한/승인 룰 등과 결합될 때 case priority와 drill-down 설명을 보강한다.
- **Account Queue 점수화**:
  - `review_score`: raw `weighted_variance`를 보존한다. 이 값은 활동량 변동의 크기이며 부정 가능성 점수가 아니다.
  - `macro_priority_score`: `evaluation_bucket`, `precision_policy`, `d01_target_document_count`, `business_event_type`을 반영한 Account Queue 정렬 점수다.
  - `queue_bucket=confirmed_account_shift`: DataSynth truth 또는 D01 target 문서로 보강된 계정. 기본 High review 후보로 정렬한다.
  - `queue_bucket=corroborated_account_shift`: runtime에서 target 문서 수 등 보강 근거가 있으나 truth sidecar 수준의 확정 metadata는 없는 계정.
  - `queue_bucket=normal_business_review`: 가격 상승, 물량 증가, capex/운전자본, 고거래량 운영, recurring/system volume shift 등 정상 사업 이벤트. raw 변동률이 커도 priority cap을 낮게 둔다.
  - `queue_bucket=auxiliary_non_d01_context`: 문서-level anomaly 문맥은 있으나 D01 계정 활동 변동 truth가 아닌 보조 문맥.
  - `queue_bucket=analytical_review`: 증거가 부족한 일반 분석 검토 큐. FP가 아니라 후속 설명/자료 확인 대상이다.
- **PHASE1 case 반영**:
  - 같은 `fiscal_year + company_code + gl_account`의 Transaction Queue case에는 D01 finding을 `macro_contexts`로 첨부한다.
  - `confirmed_account_shift`는 `macro_context=D01:confirmed_account_shift+0.06` 보강 사유를 남기고 case priority에 소폭 가산할 수 있다.
  - `corroborated_account_shift`는 더 약한 보강만 허용한다.
  - `normal_business_review`, `auxiliary_non_d01_context`, `analytical_review`는 case 설명과 evidence tag에만 남기며 priority 보너스를 주지 않는다.
- **한계**: 이 룰은 기말 잔액 변동 탐지가 아니라 총 거래 활동량 변동 탐지다. 전기에는 있었지만 당기에 사라진 계정은 당기 행이 없어 직접 플래그하지 못한다.
- **결측 계정 처리**: `gl_account`가 비어 있거나 `nan/null`류 토큰이면 D01 집계에서 제외한다. 계정 결측은 무결성 룰에서 다룬다.
- **DataSynth 평가 계약**:
  - 운영 DataSynth `v58` 기준 D01 정답은 전표 단위가 아니라 `fiscal_year + company_code + gl_account` 단위다.
  - 구현도 `company_code`가 있는 원장에서는 `company_code + gl_account` 단위로 전기 대비 활동량을 비교한다. `company_code`가 없는 단일 회사 원장은 기존처럼 `gl_account` 단위로 비교한다.
  - `labels/account_activity_variance_truth*`는 D01 true-positive 계정 group이다.
  - `labels/account_activity_variance_normal_controls*`는 D01 raw flag가 가능하지만 정상 사업 변화, 고거래량 계정 변동, 비-D01 문서 이상 등으로 해석해야 하는 normal control이다.
  - `labels/account_activity_variance_review_population*`은 D01이 검토 대상으로 올릴 수 있는 전체 계정 group 모집단이다.
  - `v121_candidate`부터 `labels/account_activity_variance_stable_controls*`는 활동량 변동이 낮은 안정 계정 group guardrail이고, `labels/account_activity_variance_near_threshold_controls*`는 D01 임계값 바로 아래의 경계 group이다.
  - `v121_candidate`부터 `labels/account_activity_variance_exclusions*`는 blank/null GL 등 입력 품질상 D01 계정 group 평가에서 제외할 row-level context다.
  - `expected_d01_flag`는 계정 활동량 기준 raw D01 flag 여부이고, `is_true_positive_account`는 D01 truth 여부다. 두 값을 분리해서 precision 해석을 왜곡하지 않는다.
  - 운영 DataSynth `v58` 기준 D01 sidecar에 `business_event_type`, `evaluation_bucket`, `precision_policy`를 포함한다. `v121_candidate`부터는 `expected_macro_priority_band`, `macro_truth_role`, `sidecar_role`도 포함한다.
  - `evaluation_bucket=confirmed_truth`는 D01 정답, `normal_business_control`은 정상 사업 이벤트, `review_queue`는 FP가 아니라 분석적 검토 큐, `auxiliary_non_d01_context`는 D01 precision 분모에서 분리할 보조 문맥이다.
  - 정상 사업 이벤트는 `price_increase`, `volume_growth`, `capex_investment_event`, `working_capital_timing`, `entity_process_expansion`, `high_volume_operations`, `recurring_or_system_volume_shift` 등으로 표준화한다.
  - `account_activity_variance_normal_controls*`는 detector negative set이 아니다. 전부 `expected_d01_flag=True`인 raw-positive normal/review context이며, confirmed D01 truth에서만 제외한다.
  - 2023은 2022와 비교하고, 2024는 2023과 비교한다. 2022는 전기 2021 baseline이 없으므로 기본 D01 평가 대상에서 제외한다.

#### D02 — 월별 분포 패턴 변화 (MonthlyPatternVariance)✅

- **입력**: 당기 DataFrame + `PriorSummary.monthly_patterns`
- **판정 로직**:
  - Jensen-Shannon Divergence(JSD)로 전기/당기 월별 금액 분포 비교
  - 평가 단위: 기본 `d02_group_keys=["company_code", "gl_account"]`. `company_code`가 있으면 회사별 계정 group을 비교하고, 없으면 기존처럼 `gl_account` 단위로 fallback한다.
  - 임계값: `monthly_pattern_threshold` (기본 0.3) 초과 시 해당 회사/계정 group의 모든 행을 review signal로 표시
  - 전기/당기 모두 `min_monthly_data_months`개월 이상 데이터 존재해야 비교 수행, 미만이면 스킵
  - 당기 계정 문서 수가 `d02_min_account_docs` 미만이면 스킵한다. `document_id`가 있으면 distinct document 수, 없으면 행 수를 사용한다.
  - 당기 계정 활동금액이 `d02_min_annual_amount` 미만이면 스킵
  - 전기/당기 최대월 비중 차이가 `d02_min_top_month_delta` 미만이면 스킵
  - 전기 또는 당기 월별 금액 합계가 0이면 분포를 계산할 수 없으므로 스킵한다.
- **출력 정책**:
  - D02는 단독 부정 결론이 아니라 account-level review signal이다.
  - D02는 row-level anomaly score를 만들지 않는다. `details["D02"] = 0.0`으로 유지하고, 계정 group 근거는 `metadata.d02_account_diagnostics`에 저장한다.
  - `RuleFlag.flagged_count`는 D02 review group에 속한 당기 행 수로 표시될 수 있지만, 최종 `DetectionResult.flagged_count`는 row score가 0이므로 증가하지 않는다.
  - group별 `d02_group_key`, `company_code`, `gl_account`, `jsd`, 비교 월수, 당기 문서 수, 당기 활동금액, 전기/당기 최대월과 비중 차이는 `d02_account_diagnostics` metadata에 보관한다.
- **Account Queue 점수화**:
  - `review_score`: raw `jsd`를 보존한다. 이 값은 월별 분포 차이의 크기이며 부정 가능성 점수가 아니다.
  - `macro_priority_score`: `scenario_type`, `d02_target_document_count`, `normal_context_document_count`, `sources`, `top_month_delta`를 반영한 Account Queue 정렬 점수다.
  - `queue_bucket=confirmed_monthly_shift`: target anomaly 월별 집중 또는 기말 수익/비용 집중 truth. 기본 High review 후보로 정렬한다.
  - `queue_bucket=corroborated_monthly_shift`: target 문서가 있으나 confirmed scenario metadata가 부족한 계정.
  - `queue_bucket=normal_pattern_review`: 정상 계절성, project/bonus timing, recurring/automated/interface/batch/system 패턴. raw JSD가 커도 priority cap을 낮게 둔다.
  - `queue_bucket=auxiliary_non_d02_context`: 문서-level 문맥은 있으나 D02 월별 패턴 truth가 아닌 보조 문맥.
  - `queue_bucket=analytical_review`: 증거가 부족한 일반 월별 패턴 검토 큐다.
- **PHASE1 case 반영**:
  - 같은 `fiscal_year + company_code + gl_account`의 Transaction Queue case에는 D02 finding을 `macro_contexts`로 첨부한다.
  - `confirmed_monthly_shift`는 `macro_context=D02:confirmed_monthly_shift+0.06` 보강 사유를 남기고 case priority에 소폭 가산할 수 있다.
  - `corroborated_monthly_shift`는 더 약한 보강만 허용한다.
  - `normal_pattern_review`, `auxiliary_non_d02_context`, `analytical_review`는 case 설명과 evidence tag에만 남기며 priority 보너스를 주지 않는다.
- **잡아내는 신호**: 전기에는 고르게 발생하던 계정이 당기에는 결산월, 특정 분기, 특정 프로젝트 월에 몰리는 경우.
- **위험도가 높아지는 결합 신호**

  | 결합                      | 실무 해석                                                       | 운영 우선순위 |
  | ------------------------- | --------------------------------------------------------------- | ------------- |
  | `D02 + L3-04/L3-07/L1-08` | 월별 집중 변화가 기말 전표, 전기일 괴리, 회계기간 불일치와 결합 | High 후보     |
  | `D02 + L4-03/L4-04`       | 패턴 변화 월에 고액 또는 희귀 계정 조합이 동반                  | Medium 이상   |
  | `D02 + L3-08`             | 패턴 변화 계정의 적요가 비어 있거나 깨져 있음                   | 보조 가점     |
  | `D02 + L2-05`             | 특정 월 집중 후 역분개·대체·정리 패턴이 동반                    | High 후보     |
  | `D02 + D01`               | 월별 배치뿐 아니라 계정 활동량 자체도 급변                      | Medium 이상   |

- **한계**
  - 계정 단위 분석 신호이므로 특정 전표 1건을 확정 부정으로 지목하지 않는다.
  - 계절성, 사업 개편, 신규 프로젝트, ERP/계정체계 변경, 정상 결산 정책 변경도 동일한 신호를 만들 수 있다.
  - 전기 데이터 품질이 낮거나 `fiscal_period`가 누락/오류이면 비교 결과의 신뢰도가 낮다.
  - 신규 계정은 D02에서 스킵된다. 신규 계정 검토는 D01이 담당한다.
- **DataSynth 평가 계약**:
  - 운영 DataSynth `v58` 기준 D02 정답은 전표 단위가 아니라 `fiscal_year + company_code + gl_account` 단위다.
  - 구현도 `company_code`가 있는 원장에서는 `company_code::gl_account` prior pattern을 우선 사용한다. 전기 summary가 legacy `gl_account` key만 제공하면 호환을 위해 계정 key로 fallback한다.
  - `labels/monthly_pattern_shift_confirmed_anomalies*`는 D02 true-positive 계정 group이다.
  - `v121_candidate`부터 `labels/monthly_pattern_shift_truth*`는 confirmed D02 macro truth의 명시적 alias다.
  - `labels/monthly_pattern_shift_review_population*`은 D02가 raw review 대상으로 올릴 수 있는 전체 계정 group이다.
  - `labels/monthly_pattern_shift_normal_controls*`는 정상 계절성, 프로젝트성 비용, 반복/인터페이스 배치, 안정적 월별 profile control이다.
  - `v121_candidate`부터 `labels/monthly_pattern_shift_raw_positive_normal_contexts*`는 D02가 잡아야 하는 raw-positive 정상 맥락이다. confirmed anomaly가 아니므로 precision 분모에서 분리한다.
  - `v121_candidate`부터 `labels/monthly_pattern_shift_guardrail_negative_controls*`는 `expected_d02_flag=False`인 guardrail negative control이다.
  - `labels/monthly_pattern_shift_exclusions*`는 `gl_account` 결측, 전기 없음, 당기 없음, 비교 월수/문서 수 부족, 최대월 변화 미미 등으로 D02 평가에서 제외할 group이다.
  - `expected_d02_flag`는 JSD와 guardrail 기준 raw D02 flag 여부이고, `is_true_positive_account`는 D02 truth 여부다. 두 값을 분리해서 정상 계절성/배치 계정을 FP로 오해하지 않는다.
  - `v121_candidate`부터 D02 sidecar에 `evaluation_bucket`, `precision_policy`, `business_event_type`, `expected_macro_priority_band`, `macro_truth_role`, `sidecar_role`을 포함한다.
  - 반복/인터페이스/배치/시스템성 정상 패턴은 `normal_recurring_or_interface_batch` 등 정상 macro context로 분리한다. 이는 D02 raw hit일 수 있지만 confirmed anomaly는 아니다.
  - 2023은 2022와 비교하고, 2024는 2023과 비교한다. 2022는 전기 2021 baseline이 없으므로 기본 D02 평가 대상에서 제외한다.
- **DataSynth 운영본 관찰 결과**
  - `2023 vs 2022`, `2024 vs 2023`에서 기본 `JSD > 0.3`만 적용하면 문서의 대부분이 플래그되어 실무 큐로 사용할 수 없다.
  - 원인은 정상 계정의 연도별 월별 분포가 너무 독립적으로 흔들리는 합성데이터 생성 특성이다.
  - 따라서 D02 평가는 단순 `is_fraud/is_anomaly` 라벨 precision이 아니라 전용 sidecar가 필요하다.
  - 원장을 smoothing하면 D01, Benford, 고액/희소계정쌍, 계절성까지 동시에 훼손될 수 있으므로 v58은 원장 보정이 아니라 sidecar 평가 계약을 우선 적용한다.


---

### 4.4 IC Matcher — 관계사 대사 예외 (IC01 / IC02 / IC03)

> 2026-06-20 [DETECTION_RULES.md](DETECTION_RULES.md) L3-03 카드에서 이관. IC01/IC02/IC03은 관계사 쌍 대사 예외 family로, PHASE1-1 `L3-03`(관계사 계정 사용 binary context 태그)와 독립이다. 구현: `src/detection`의 `IntercompanyMatcher`.

- **근거**: IFRS 10 §B86 연결 내부거래 제거, K-IFRS 1110/1024, KICPA Issue Paper 46 (JET 완전성), ISA 600 그룹감사 구성단위 잔액 대사. IC 양측 대사 룰의 회계적 필연성은 이 근거에서 도출된다.
- **DataSynth 예외 라벨**: `v38_candidate`부터 IC01/IC02/IC03/GR01/GR03 검증용 소량 truth를 `labels/intercompany_exception_cases*.csv/json`에 둔다. 이 라벨은 detector 결과를 역으로 채운 것이 아니라 정상 IC pair 일부에 거래상대 불일치, 금액 차이, 전기일 차이, 순환 seed, 가격 비대칭을 작게 주입한 scenario truth다. 정상 대조군은 `labels/intercompany_normal_controls*.csv/json`에 별도로 둔다.
- **IC01/IC02/IC03 평가 계약**: `intercompany_exception_cases` 전체를 한꺼번에 정답으로 쓰지 않는다. IC01은 `UnmatchedIntercompany`, IC02는 `IntercompanyAmountMismatch`, IC03은 `IntercompanyTimingMismatch`만 각각 평가한다. `target_document_id`가 주입 대상이며, counterpart 문서는 룰 성격에 따라 같이 flag될 수 있는 보조 문서다.
- **IC02 금액 대사 정책**: 기본 금액 차이 허용 오차는 `ic_amount_tolerance=0.05` (5%)다. IC02는 대응 관계가 확인된 관계사 쌍의 금액 차이를 검토 후보로 표시하되, 통화가 다른 쌍 또는 통화 정보가 약한 상태에서 금액비가 `ic_cross_currency_ratio_threshold=20.0`을 초과하는 쌍은 FX 환산 기준 없이는 비교 가능한 금액으로 보지 않고 점수를 억제한다. 통화가 다른 쌍은 대응 관계 자체를 미대사로 보지 않기 위해 `currency`를 매칭 키로 쓰지 않고 `cross_currency` sidecar로 분리한다.
- **IC01 실무 기준**: 고객/벤더 코드(`C-000123`, `V-000123`)가 IC 계정에 들어온 경우는 DataSynth 현실성 노이즈로 보고 미대사 예외에서 제외한다. IC01은 명시적 회사 상대방 코드가 존재하지만 실제 회사코드와 대사되지 않는 고확신 케이스를 우선 flag한다.
- **IC01 외부 rule id 단일 유지**: 외부 rule id 는 `IC01` 단일을 유지한다. `IC01_A` / `IC01_B` 와 같은 분리는 도입하지 않으며, `RULE_CODES`, `SEVERITY_MAP`, `RULE_DETAIL_METADATA_REGISTRY`, dashboard / export 표시 맵은 모두 단일 `IC01` 기준으로 일관 운영한다 (D065 결정 반영).
- **IC01 evidence level sidecar 정책**: IC01 hit 의 신뢰도는 detector 결과 DataFrame 의 두 sidecar column (`ic01_evidence_level`, `ic01_review_reason`) 으로 분류한다. 두 column 은 canonical 30 rule count 외부의 `intercompany_sidecar` surface 산출물이다.
- **PHASE2 internal probabilistic columns (2026-05-24)**: IC01/IC02/IC03 hard-threshold 룰을 보존하면서 `IntercompanyMatcher.details` 에 `ic_unmatched_prob` / `ic_amount_prob` / `ic_timing_prob` 3개 0~1 raw probability column 을 additive 로 추가한다. canonical rule id (IC04 등) 는 신설하지 않으며 `RULE_CODES` / `SEVERITY_MAP` / `RULE_DETAIL_METADATA_REGISTRY` / `_RULE_STYLE_SUB_DETECTORS` / `config/phase2_subdetector_tiers.yaml` 모두 변경 없다. 신규 column 은 PHASE2 family overlay 의 zero-preserving ECDF + Noisy-OR 에 자연 흡수되며 PHASE1 case priority 나 PHASE1 ↔ PHASE2 queue 순서를 바꾸지 않는다. 데이터 계약 3-tier (`L1_exact` / `L2_aggregate` / `L3_insufficient`) 와 cross-currency 시 amount term 0 (weight 재정규화 없음), `ic_unmatched_prob=1.0` 의 user-facing 표현 ("unmatched review signal") 은 [docs/spec/phase2_reorgani.md §5](phase2_reorgani.md) 단일 출처. Phase 1 rule hit / DataSynth truth / `document_id` 식별자는 입력으로 사용하지 않는다.

  ```
  evidence_level     정의                                                            floor 정책      reason code 예시
  ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
  high               IC 모집단 + 그룹 매칭 실패 + 명시적 회사 상대방 코드 +          Medium 0.40     (review_reason 미부착)
                     관계사/그룹 master 에 대사 실패
  review             IC 모집단 + 그룹 매칭 실패 + (trading_partner 결측 OR           Low 0.20        missing_partner /
                     형식 비표준 OR master mapping 미정)                                             nonstandard_format /
                                                                                                     mapping_uncertain
  ""                 IC 모집단 + counterparty 가 customer/vendor master 또는        0.0 (평가 제외)  (해당 없음)
                     외부 거래처. IC 룰 평가 모집단에서 제외.
  ```

  - `ic01_evidence_level == "high"` 또는 `"review_stale"` 단독 → row Medium floor (`RISK_THRESHOLDS[MEDIUM]=0.40`) 자격
  - `ic01_evidence_level == "review"` 단독 → row Low floor (`RISK_THRESHOLDS[LOW]=0.20`)
  - IC02 단독, IC03 단독 → Low floor (기존 유지)
  - IC01 + IC02 / IC03 또는 IC02 + IC03 (2 개 이상 IC 예외 결합) → Medium floor (기존 유지)
  - 위 floor 정책은 `src/detection/score_aggregator.py::_apply_intercompany_exception_corroboration()` 와 정합한다.
  - `intercompany_exception_reasons` 문자열은 IC01 hit 시 `IC01[high]` / `IC01[review_stale]` / `IC01[review]` qualifier 를 부착한다. base rule id 는 그대로 `IC01` 이다.
- **표시 기준**:
  - `IC01`: 미대사 예외 후보. evidence level sidecar (`ic01_evidence_level`) 로 신뢰도 분류 — `high` 는 master 미대사 확정, `review_stale` 은 결산기 근접으로 설명되지 않는 미대사 review 상향, `review` 는 partner 결측 / 형식 비표준 / master mapping 미정. dashboard / export 표시 시 외부 rule id 는 `IC01` 단일을 유지하고, 상세 panel 에서만 evidence level 을 노출한다.
  - `IC02`: 금액 불일치 검토 후보
  - `IC03`: 시차 불일치 검토 후보
- **PHASE2 native IC role lock (2026-05-29)**: `IntercompanyMatcher`의 native pair case는 broad TOP500/TOP1000 recall expansion family가 아니라 `ic_specific_evidence_strengthening` family로 해석한다. PHASE1 TOP100에 없던 circular/reciprocal review candidate를 IC TOP100에 올리고, PHASE1 generic reason과 별도로 `reciprocal_flow`, paired row_refs, counterparty pair, amount symmetry evidence를 제공한다. `production_adoption=false` 또는 `new_policy_adopted=false`는 새 ranking/gate 정책을 도입하지 않았다는 뜻이며 IC family 비활성화가 아니다. unmatched/timing-only 후보는 자동 case 승격하지 않는다.

---

### 4.5 Graph Detector (WU-22) — networkx 기반 순환·이전가격

> **근거**: ISA 550 §23 특수관계자 사업상 합리성 · FSS 순환거래 페이퍼컴퍼니 패턴.
> **차별화**: L3-03(관계사 거래 검토 후보) 및 R03(그룹 편차 통계)의 한계를 그래프 토폴로지로 보완.

#### GR01 — CircularTransaction (N-hop 순환)

- **심각도**: 4
- **알고리즘**: networkx `simple_cycles(G, length_bound=max_cycle_length)` (Johnson)
- **그래프 구성**:
  - 노드: `(company_code, trading_partner)` 튜플
  - 엣지: `credit > 0` → `company → partner`, `debit > 0` → `partner → company`
  - 자료구조: `MultiDiGraph` (다중 엣지 보존 → 원본 행 인덱스 역매핑)
- **`trading_partner` NULL fallback**: 동일 `document_id` 그룹의 다른 `company_code`로 implicit IC pair 추론 (DataSynth 640건 NULL 복구 목적)
- **점수화**: binary 1.0 × `severity_factor(0.8)` (연속 점수화는 튜닝 단계로 이연)
- **L3-03과의 관계**: L3-03은 `is_intercompany` 기반 관계사 거래 후보만 반환한다. GR01이 실제 N-hop 순환 탐지를 담당한다.
- **DataSynth truth 해석**: v39 기준 GR01은 두 층으로 평가한다. `graph_gr01_review_population`은 룰이 구조적 순환 후보를 올리는지 보는 coverage truth이고, `CircularTransaction`/`graph_gr01_confirmed_anomalies`는 확정 이상 truth다. `graph_gr01_normal_cycle_controls`는 정상 내부거래 순환도 존재한다는 negative-control이므로 raw GR01 hit를 전부 FP로 계산하지 않는다.

#### GR03 — TransferPricingAnomaly (양방향 price asymmetry)

- **심각도**: 4
- **알고리즘**: pandas groupby 기반 양방향 쌍 식별 + 차이율 계산
  1. IC 행만 필터
  2. `reference`가 있는 경우 같은 reference의 상호 회사쌍 문서를 먼저 비교한다. IC 채권/채무 GL이 서로 달라도 문서 최대금액 기준 비대칭을 계산한다.
  3. reference-pair 비교 후, 보조 신호로 `(src_company, dst_company, gl_account)` 그룹 평균 amount와 역방향 그룹을 비교한다.
  4. `deviation = |amount_fwd - amount_rev| / min(amount_fwd, amount_rev) > threshold(20%)`
  5. 점수 = `min(1.0, deviation / (threshold × 3))`
- **V39 보정**: `TransferPricingAnomaly` 라벨은 한쪽 문서의 전체 거래금액을 scaling하므로, IC 라인 금액만 비교하면 세금/손익 라인 때문에 미탐이 생긴다. GR03 reference-pair 경로는 문서 최대금액을 사용해 이 라벨 구조와 실제 대사 관점을 맞춘다.
- **R03과의 차별화**:

| 항목        | R03 (Relational)                    | GR03 (Graph)                          |
| ----------- | ----------------------------------- | ------------------------------------- |
| 접근        | `(partner, account)` 그룹 편차 통계 | **방향성 + 양방향성** 엣지 분석       |
| 수식        | `\|x - μ\| / μ > 15%`               | `\|mean_fwd - mean_rev\| / min > 20%` |
| 포착 대상   | 단일 그룹 내 outlier 금액           | 매출/매입 가격 **비대칭** 패턴        |
| 중복 플래그 | MAX 패턴으로 severity 동일(4) 흡수  | 동일                                  |

#### OOM 방어 3중 장치 ⚠️

회계 장부 100만+ 행에서 `iterrows() + add_edge` 루프는 **수십 분 지연 + RAM OOM**. 필수 방어:

1. **사전 필터 (pandas 벡터화)**: `is_intercompany == True AND max(debit, credit) ≥ min_amount(1천만원)` → 목표 ≤ 50,000 행
2. **`nx.from_pandas_edgelist`로 C-레벨 변환**: `np.where`로 `src`/`dst` 컬럼을 먼저 생성. `for ... add_edge()` 루프/`apply`/`iterrows` 금지
3. **엣지 수 안전장치**: `len(edges_df) > graph_gr01_max_edges(50,000)` 시 `quantile` 기반 `min_amount` 자동 상향 + warning. 추가로 `weakly_connected_components`로 분리 후 컴포넌트별 `simple_cycles` 호출. 컴포넌트는 노드 수와 엣지 수가 모두 임계값을 넘을 때만 skip한다.

**벤치마크**: 100k 행 DataFrame에서 실행 시간 1.3초 (목표 15초 이내).

#### Settings 파라미터 (`config/settings.py`)

```python
graph_gr01_max_cycle_length: int = 5          # Johnson length_bound
graph_gr01_min_amount: float = 10_000_000.0   # 엣지 최소 금액 (materiality, 1천만원)
graph_gr01_max_edges: int = 50_000            # 엣지 수 상한 (초과 시 자동 상향)
graph_gr01_max_component_size: int = 500      # component 노드 임계
graph_gr01_max_component_edges: int = 5_000   # component 엣지 임계
graph_gr03_min_path_length: int = 2           # 경로 최소 노드 수
graph_gr03_price_deviation_threshold: float = 0.20  # 양방향 가격 편차 허용
```

#### Metadata 출력

`DetectionResult.metadata`에 관측 지표 누적:
- `gr01_edges_prefiltered`, `gr01_edges_built`, `gr01_min_amount_effective`, `gr01_max_edges_raised`
- `gr01_implicit_edges` (document_id fallback 복구 건수)
- `gr01_cycles_found`, `gr01_skipped_components`
- `gr03_bidirectional_pairs`, `gr03_flagged_pairs`

#### 제외된 룰

**GR02 (CentralityAnomaly)**: DataSynth 그래프 규모(회사 3개, 거래처 수십 개)에서 betweenness centrality 분석이 통계적으로 무의미. 실데이터 유입 후 재검토.

---

