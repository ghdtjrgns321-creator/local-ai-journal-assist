# PHASE1-2 Rules — 분석적 검토 신호 (자기 큐 + 배지)

> 2026-06-21 재설계. **단일 법인(single legal entity) 확정**으로 회사를 가로지르는 탐지(관계사 대사 IC01~03·순환거래 GR01)는 **범위 외**([CONSTRAINTS.md §단일 법인 분석으로 한정](CONSTRAINTS.md)). 남은 PHASE1-2 = "전표 한 장으론 안 보이는, 계정·거래처·사용자를 **모아서** 봐야 드러나는 **분석적 검토 신호**"(ISA 520 분석적 절차). 전표 행 단위 PHASE1-1 룰·PHASE2 VAE와 비병합(3-surface 불변식: PHASE1-1 룰 / PHASE1-2 분석적 검토 / PHASE2 VAE).
>
> **운영 2종 — 자기 큐 vs 배지** (2026-06-30 grill 종결; 근거 [HIGH_COMBO_GROUNDING.md](HIGH_COMBO_GROUNDING.md) §2·§5.3 + 통과문 3조건):
> - **자기 큐(별도 목록 화면, 고액/대량 정렬)** — **Benford(L4-02)·D01·D02 + 라운드넘버 밀집도·첫등장/희소 거래처·시계열 당기내 집중.** "전표 한 장으론 안 보이고 계정/거래처/시점을 모아야 보이는" 분석적 검토 신호. PHASE1-1 전표가 안 떠도 "이 계정/거래처/시점이 통째로 이상"을 독립 검토 표면으로 올린다(전표 tier에는 미참여 = 0). 채점 — 운영 정렬은 신호 강도(MAD·JSD·변동폭·합계금액·건수), 개발 검증은 coverage(precision/recall 아님).
> - **배지(PHASE1-1 전표 등급 줄의 맥락 꼬리표, 점수 비병합)** — **L4-05·L4-06·L3-12 + 라운드넘버 단건·첫등장/희소 거래처 전표.** 정상 업무에 흔해(HIGH_COMBO CONTEXT) 단독 전표 큐는 노이즈 → PHASE1-1 HIGH/MEDIUM/LOW 전표가 그 신호의 더미에 속하면 배지로만 표시(전표 등급 안 바꿈).
> - **dual(자기 큐 + 배지)**: **라운드넘버**(밀집도=자기 큐 / 단건=배지)·**첫등장/희소 거래처**(거래처 전수 목록=자기 큐 / 그 거래처 전표=배지). 라운드넘버 자기 큐는 절대 금액 게이트 없이 모집단 분포로, 첫등장/희소 자기 큐는 금액 게이트 없이 전수 + 거래내용별 묶음 + 고액/대량 정렬(§3 절대 임계 리터럴 회피).
>
> **UI**: PHASE1 1회 실행 → 한 결과창 소분류 — 검토 케이스(등급 + 배지) / 데이터 정합성 / 분석적 검토(Benford·D01/D02·라운드넘버·첫등장·희소·시계열 자기 큐). PHASE2(VAE)는 별도 실행·별도 표시.

## 수록 룰

| 룰                        | 이름                          | 단위                  | 운영 역할          | 근거 / 비고                                                                |
| ------------------------- | ----------------------------- | --------------------- | ------------------ | -------------------------------------------------------------------------- |
| L4-02 / Benford           | Benford 분포 위반             | 계정·월 모집단        | **자기 큐**        | ISA 520 + Nigrini(포렌식 표준)                                             |
| D01                       | 계정과목 거래 활동량 급변     | 계정·전기대비         | **자기 큐**        | ISA 520 §5 (전기 대비 = 분석적 절차)                                       |
| D02                       | 월별 분포 패턴 변화           | 계정·전기대비         | **자기 큐**        | ISA 520 §5                                                                 |
| 라운드넘버 밀집도 [신규]  | 둥근 금액 비정상 집중         | 계정·월·작성자 모집단 | **자기 큐 + 배지** | AS2401 §61(e); 밀집도=자기큐, 단건=배지                                    |
| 첫등장/희소 거래처 [신규] | 원장 첫 등장·희소(rare)       | 거래처                | **자기 큐 + 배지** | HIGH-6 GL-only 약근사(커버 비주장); 전수 목록·거래내용 묶음·고액/대량 정렬 |
| 시계열 당기내 집중 [신규] | 특정 시점 거래 몰림           | 계정·시점(일/주/월)   | **자기 큐**        | ACFE 집중; D01/D02 전기비교를 당기내로 보완                                |
| L4-05                     | 비정상 시간대 집중            | 사용자                | **배지**(OFF-TIME) | AS2401 §61(c) + ACFE, CONTEXT                                              |
| L4-06 / BatchAnomaly      | 배치성 자동 전표 검토 신호    | 배치·일자·금액 모집단 | **배지**(보조)     | 정상 자동배치 흔함 → CONTEXT                                               |
| L3-12                     | 업무범위 집중 검토            | 사용자·연도 집계      | **배지**           | K-SOX 접근권한, review-only                                                |
| IC01·02·03                | 관계사 대사(미대사·금액·시차) | 관계사 쌍             | **완전 삭제**      | 단일법인 한계 → [CONSTRAINTS.md](CONSTRAINTS.md). L3-03 꼬리표만 잔존      |
| GR01·GR03                 | 순환·이전가격                 | graph                 | **완전 삭제**      | dead path 제거(주석 보존 안 함)                                            |
| (중복) duplicate          | 중복지급                      | 전표 짝               | **PHASE1-1 소관**  | L2-03(거래처+금액+근접기간 확장). PHASE1-2 신설 없음, fuzzy·split 드롭     |
| R02·R04·R06               | 휴면계정·문서흐름·degree      | —                     | **드롭**           | 근거 약함/중복                                                             |

> 자기 큐 6종(Benford·D01·D02·라운드넘버 밀집도·첫등장/희소·시계열 당기내 집중)은 계정/거래처/시점 단위 별도 검토 목록을 만들고, 배지 신호는 PHASE1-1 전표 등급 줄에 맥락 꼬리표로만 붙는다(점수 비병합). 재설계 SoT: `dev/active/phase1-2-code-rework/PLAN.md`.

> **라운드넘버 밀집도 — 신규(dual: 자기 큐 + 배지)**: 부자연스럽게 둥근 금액(끝자리 0 다수 — 예 5,000,000 / 100,000,000). 근거 PCAOB AS2401 §61(e) **명문**(FSS 원문은 둥근 정도 미기록 → 태깅 0, 도구 경계 ≠ 감사 경계). **밀집도(계정·월·작성자 모집단의 둥근 금액 비율 집중) = 자기 큐**(Benford 동렬), **단건 라운드넘버 = 배지**(전표 꼬리표). `round_amount_score` 코드 재활용.

> **드롭/취소·보류된 구 후보 (2026-06-21~30 grill)**:
> - **duplicate 유사(fuzzy)·split**: PHASE2 duplicate에서 PHASE1-2로 건지려다 **취소**(근거가 기법 보완이지 수법 명문 약함; split은 HIGH_COMBO에서 FSS 0·외부 약). **중복지급은 PHASE1-1 `L2-03` 소관**(매칭을 거래처+금액+근접기간으로 확장해 시차중복 흡수). PHASE1-2엔 중복 신설 없음 — 단일법인 한계가 아니라 전표 짝 룰이라 PHASE1-1 영역.
> - **한도 직하 밀집도·매출 특화 시계열**: 미구현 후보로 **보류**(우선순위 낮음). ※ "당기 내 거래 집중" 시계열은 보류가 아니라 **자기 큐 신규로 채택**(위 표) — D01/D02 전기비교가 못 보는 당기 내 시점 집중을 본다.

> **IC01~03·GR01·GR03 (완전 삭제 — 2026-06-30)**: 관계사 대사·순환거래는 회사를 가로질러야 성립 → 단일 법인 확정으로 **영구 불가**. 죽은 코드를 보존하지 않고 검사기·registry·phase2 배선을 **삭제**한다(GR은 이미 호출되지 않는 dead path). 위험 근거 자체는 유효하나(도구 경계 ≠ 감사 경계) 데이터·분석 표면이 단일 법인 밖이다. 그룹감사 재도입은 발전방향(doc only) — SoT [CONSTRAINTS.md §단일 법인 분석으로 한정](CONSTRAINTS.md). **단 L3-03 `is_intercompany` 관계사 거래 꼬리표는 PHASE1-1 조합(관계사+역분개 등)용이라 잔존**. 아래 §IC Matcher·§Graph Detector 카드는 **삭제 대상 코드의 과거 명세**이며 현행 운영 surface 아님.
> **Benford(L4-02)·D01·D02 (자기 큐)**: `macro_findings` / 계정 단위 review queue가 이들의 산출물이다. 전표 행 점수에는 0(전표 tier 미참여)이되, 계정 단위 분석적 검토 surface로 독립 운영한다. 구 "macro_only 중화 후 surface 재정립" 메모는 본 재설계로 종결.

---

## 가공거래처(HIGH-6) — GL-only 약근사 경계 (2026-06-20 결정)

> 등급·근거 SoT: [HIGH_COMBO_GROUNDING.md HIGH-6](HIGH_COMBO_GROUNDING.md) · 범위 SoT: [CONSTRAINTS.md §GL-only](CONSTRAINTS.md).

HIGH-6 가공거래처(페이퍼·차명회사)는 3축 근거(감사기준·FSS 16건·ACFE)상 **HIGH 등급**이지만, 본 프로젝트는 **GL journal 단일 소스**로 한정하고 **거래처 마스터(등록일·사업자번호·은행계좌·주소)를 의도적으로 비보유**한다. 가공거래처를 가르는 강신호(사업자번호 위조·직원-거래처 공유계좌/주소·등록 직후 거래)는 마스터가 있어야 보이므로 **범위 외**이고, **PHASE1-1에 가공거래처 primary 룰을 신설하지 않는다**.

PHASE1-2 **배지 신호(첫등장/희소 거래처)**는 **GL 전표를 거래처 코드(`trading_partner`·`auxiliary_account_number`)로 group by 한 집계**만으로 만들 수 있는 **약근사** 두 가지를 검토 신호로 surface한다. 이는 마스터 데이터가 아니라 원장 집계이므로 GL-only 경계를 깨지 않는다(단일 법인 범위 내 — 거래처 단위라 형제 회사 불필요). 단독 큐 부적격(정상 신규 공급처도 첫 등장) → PHASE1-1 전표에 **배지로만** 연결.

| 약근사 신호(정명)                             | GL 파생 방식                                               | 기존 코드                                                            | 한계 → 해석                                                |
| --------------------------------------------- | ---------------------------------------------------------- | -------------------------------------------------------------------- | ---------------------------------------------------------- |
| **원장 첫 등장(first-seen-in-ledger) + 고액** | 거래처 코드별 원장 최초 전기일이 lookback 이내 + 대액 분위 | `relational_rules.py::r01_new_counterparty`                          | 정상 신규 공급처도 원장 첫 등장 → **검토 신호**, 적발 아님 |
| **원장 희소(rare-in-ledger) 거래처**          | 거래처 코드가 극소수 전표/특정 계정에만 등장(희소 edge)    | `r05_rare_account_partner_edge` / `r07_dormant_partner_reactivation` | 정상 일회성 거래와 경계 모호 → **검토 신호**, 적발 아님    |

**명명·주장 규율**:
- 코드/문서에서 "**신규 거래처**"가 아니라 "**원장 첫 등장(first-seen-in-ledger)**"으로 부른다. 마스터 등록일을 보는 게 아니라 우리 원장에 처음 찍힌 날을 보는 것이므로, "신규 거래처"는 마스터 보유를 오인하게 한다.
- 두 약근사 모두 **HIGH-6 커버리지로 주장하지 않는다**. "가공거래처 적발/탐지 완료"가 아니라 "가공거래처 검토 후보를 GL 범위 내에서 일부 surface"로만 표기한다.
- **검증 주의**: `first-seen`은 단일 연도 파일로 돌리면 거의 모든 거래처가 "첫 등장"이 되어 무의미하다. 진짜 신규는 **전기(2022·2023) 미등장 + 당기(2024) 등장** 교차로만 판정한다(연도 파일 통합 실행).

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

> **배지 신호 (OFF-TIME, 2026-06-21 재분류)**: 본 룰은 PHASE1-2 **배지**다. 사용자(`created_by`) 행동 집계 단위라 단독 검토 큐를 만들지 않고, 작성자가 L4-05 집중 명단에 있으면 그 작성자의 PHASE1-1 전표(HIGH/MEDIUM/LOW)에 **OFF-TIME 배지로만** 연결한다(점수 비병합, 전표 등급 안 바꿈). PHASE1-1 **OFF-TIME set**(L3-05 주말·L3-06 심야)과 같은 시간 보조축이다. 정의 SoT: [HIGH_COMBO_GROUNDING.md](HIGH_COMBO_GROUNDING.md) OFF-TIME 보조축 절. 3-surface 불변식과 호환.

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

#### L4-06 — 배치성 자동 전표 검토 신호 (BatchAnomaly) ✅

> 2026-06-21 [DETECTION_RULES.md](DETECTION_RULES.md)에서 PHASE1-2 macro로 이관. 모집단(배치·일자·금액분포) 단위 신호이며 HIGH/MEDIUM 조합 근거가 없다(`batch_combo` 근거없음→LOW). 아래 "PHASE1 점수 흐름"·"코드 반영"·"fraud-combo floor"의 PHASE1-1 scoring-role 서술(`combo_only`·`batch_combo_bonus`·L4 family weight 등)은 **코드 반영 batch에서 macro 단위로 재정립 예정**이며, 현재는 이관 전 원문을 보존한다.

- **심각도**: 2
- **운영 성격**: 단독 고위험 적발 룰이 아니라 Phase 1 보조 검토 신호다. 과거 Phase 2 WU-09로 설계되었으나, 최신 PHASE1 관계도에서는 `statistical_outlier` evidence와 `batch_combo_bonus` 입력으로 운영한다.
- **근거**: 배치·인터페이스·시스템 전표는 정상 대량 처리도 많으므로, 단독 hit만으로 부정 가능성을 강하게 주장하지 않는다. 다만 개별 승인/검토가 약할 수 있어 기말·대량·금액 특이 패턴은 검토 후보로 남긴다.
- **배치성 source 기본값**: `batch`, `interface`, `system`, `auto`, `automated`, `if`, `sys` 계열. 비교는 대소문자 무시.
- **탐지 로직**: 4가지 하위 패턴 OR 결합
  1. 기말 집중: 배치성 전표 중 기말 비율 > `batch_period_end_ratio` (기본 0.5)
  2. 대량 동시 생성: 동일 `posting_date` 배치성 전표의 `document_id` distinct count ≥ `batch_simultaneous_threshold` (기본 50). `document_id`가 없을 때만 row count로 fallback한다.
  3. 금액 이상: 배치성 전표 내 `abs(Z-score) > batch_amount_zscore` (기본 3.0), std=0 방어 포함. 배치 평균보다 큰 금액뿐 아니라 비정상적으로 작은 금액도 검토 후보에 포함한다.
  4. 단독 배치 정체성 결손 (`lone_batch_identity`, 2026-06-12 신설): 배치성 source를 주장하는데 `batch_id`·`job_id`가 모두 결측이고 같은 날 동류(배치성+정체성 결손) 전표 수 ≤ 10건. **source 위조(자동 위장) 의심** — 정상 자동 전표는 무리지어 다닌다(v41 정상 실측: 자동 202,102 문서 중 82건만 해당). 두 정체성 컬럼이 모두 없으면 검증 불가로 미발동. 구현: `source_trust.lone_automated_mask()`. score 0.45 (단독), 타 패턴 결합 시 0.65.
- **위험도가 높아지는 결합 신호**

  | 결합                        | 의미                                              | 운영 우선순위 |     |                       |                                      |           |
  | --------------------------- | ------------------------------------------------- | ------------- | --- | --------------------- | ------------------------------------ | --------- |
  | `L4-06 + L3-04/L3-07/L1-08` | 자동 배치성 전표가 결산·cutoff·전기일 괴리와 결합 | Medium 이상   |     |                       |                                      |           |
  | `L4-06 + L1-05/L1-06/L1-07` | 자동 처리와 승인/권한 통제 실패가 결합            | Medium 이상   |     |                       |                                      |           |
  | `L4-06 + L4-03/L4-04/L3-10` | 배치성 전표가 고액·희소 계정쌍·민감 계정과 결합   | Medium 이상   |     | `L4-06 + L2-05/L2-02` | 배치성 처리 후 역분개·중복 징후 동반 | High 후보 |

- **PHASE1 점수 흐름**: L4-06 detector raw score는 `0.25/0.45/0.65` band로 남기되, 공통 정규화에서는 `evidence_strength=weak`, `scoring_role=combo_only`, L4 family weight `0.15`가 적용된다. 따라서 L4-06 단독 hit는 row-level `anomaly_score`와 `risk_level`을 의미 있게 끌어올리지 않는다.
- **코드 반영**: `score_aggregator.py`는 L4-06 결합 신호를 `batch_combo_score`로 계산하며, L4-06 단독은 승격하지 않는다. `phase1_case_builder.py`는 같은 원칙으로 `batch_combo_bonus`와 behavior floor를 case priority에만 반영한다.
- **fraud-combo floor 신뢰 게이트 (2026-06-12)**: 사람 행위를 전제하는 fraud-combo floor(가공전표·결산조정·횡령은닉 등 0.75 승격)는 **신뢰 가능한 자동 전표**(자동 계열 source ∧ `lone_batch_identity` 아님, recurring 포함 — `source_trust.trusted_automated_mask()`)에서만 발화한 룰을 콤보 트리거로 인정하지 않는다. 근거: 자동 결산 배치의 승인 부재·결산기 집중은 정상이며, 이를 콤보로 승격하면 정상 medium 노이즈가 생긴다(v41 실측 3,516건 — OPEN_ISSUES #14). 위장 의심(단독 자동) 행의 발화는 신뢰하지 않으므로 콤보 트리거로 유지된다. 구현: `phase1_case_builder._fraud_combo_rule_scope()` → `compute_topic_scores(fraud_combo_rule_scope=...)`.
- **구현**: `anomaly_rules_batch.py` → `c13_batch_anomaly()`
- **필요 피처**: `source`, `is_period_end`, `posting_date`, `debit_amount`, `credit_amount`
- **동일 일자 처리**: 대량 동시 생성 조건은 `posting_date`를 달력일 단위로 정규화한 뒤 집계한다. 시간이 포함된 timestamp라도 같은 날짜면 같은 배치 모집단으로 묶고, 날짜 파싱이 불가능한 값은 앞 10자 문자열로 graceful fallback한다.
- **DataSynth 상태**: DataSynth v114 후보에서 `rule_truth_L4_06.csv`와 `batch_review_population.csv`를 현재 detector raw batch review universe로 맞췄고, v116에서 활성 truth metadata를 현재 후보 기준으로 정리했다. 현재 detector docs `686`, truth docs `686`, detector/truth diff `0`이다. confirmed `BatchAnomaly` 라벨은 이 안에서 뽑은 subset이며, `batch_normal_controls.csv`와 `batch_boundary_controls.csv`는 strict rule truth에 섞지 않는다. `recurring`은 L4-06 batch source가 아니며, 실제 배치성 이상이면 원장 `source`가 `batch`/`interface`/`automated` 계열로 분류되어야 한다.
  - `v120_candidate`부터 `labels/batch_detector_universe*`는 `labels/batch_review_population*`의 명시적 alias다. 둘 다 detector-contract universe이며 독립 현실성 sidecar로 쓰지 않는다.
  - `labels/batch_normal_controls*`와 `labels/batch_legitimate_contexts*`는 정상 batch context다.
  - `labels/batch_boundary_controls*`와 `labels/batch_boundary_contexts*`는 경계 batch context다. v120 기준 `batch_boundary_contexts`는 128문서 중 30문서가 L4-06 detector universe와 겹치므로 strict negative control로 해석하지 않는다.
- **평가 계약**:
  - L4-06은 strict pass/fail 룰이 아니라 `coverage_anchor` 보조 증거다. DataSynth strict Phase 1 truth는 confirmed label만이 아니라 raw batch review universe다.
  - breakdown은 `batch_review_docs`, `period_end_concentration_docs`, `simultaneous_creation_docs`, `amount_outlier_docs`와 row-level `lone_batch_identity_rows`/`lone_identity_only_rows`를 남기고, `score_bands`는 `amount_outlier_only`, `period_end_concentration`, `simultaneous_creation`, `lone_batch_identity`, `multi_signal_batch`로 나눈다.
  - `review_queue_docs`는 확정 라벨 기준 FP가 아니라 `batch_review_docs`를 우선 사용한다.
  - `BatchAnomaly` 라벨은 감사 이슈 subset이다. `rule_truth_L4_06`과 1:1로 같다고 가정하면 안 된다.
  - detector는 row annotation에 `reason_codes`와 `primary_reason`을 남긴다. 동일 행이 기말 집중, 동시 생성, 금액 이상에 동시에 걸릴 수 있으므로 하위 band 합계는 전체 batch review 문서 수와 일치하지 않을 수 있다.
  - L4-06 단독 hit는 정상 자동/배치 처리일 수 있으므로 case priority는 `batch_combo_score`와 독립 보강 룰 그룹 수로 판단한다.
  - PHASE1 사용자 큐는 row-level `anomaly_score`만으로 정렬하면 안 된다. L4-06처럼 단독 점수는 낮지만 결합 근거가 중요한 신호가 묻히지 않도록 `priority_score`, `priority_band`, `batch_combo_bonus`, `priority_adjustment_reasons`를 함께 사용한다.

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

> ⛔ **완전 삭제 (단일 법인 확정, 2026-06-30)**: 관계사 대사는 **두 법인 장부가 다 있어야** 거울 대조가 된다. 단일 법인 확정으로 **영구 불가** → IC01/02/03 검사기·registry·phase2 배선을 **코드에서 삭제**한다(죽은 코드 보존 안 함). 위험 근거(IFRS 10 연결 제거)는 유효하나 데이터·분석 표면이 단일 법인 밖이다. 그룹감사 재도입은 발전방향(doc only): [CONSTRAINTS.md §단일 법인 분석으로 한정](CONSTRAINTS.md). **L3-03 `is_intercompany` 관계사 꼬리표는 PHASE1-1 조합용이라 잔존.** 아래 카드는 **삭제 대상 코드의 과거 명세**다.

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

> ⛔ **완전 삭제 (단일 법인 확정, 2026-06-30)**: 순환거래(A→B→C→A)는 **회사가 여럿 있어야** 경로가 닫힌다. 단일 법인 확정으로 영구 불가 + 이미 호출되지 않는 dead path → GR01·GR03 검사기·registry·dead 함수를 **코드에서 삭제**한다(주석 보존 안 함). 순환거래 근거(round-tripping = SEC AAER 외부 + FSS 페이퍼컴퍼니 순환 사례)는 유효하나 데이터·분석 표면이 단일 법인 밖이다. 그룹감사 재도입은 발전방향(doc only): [CONSTRAINTS.md §단일 법인 분석으로 한정](CONSTRAINTS.md). GR03(이전가격 비대칭)은 정상 가격차와 구별이 약해 폐기. 아래 카드는 **삭제 대상 코드의 과거 명세**다.

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

#### L3-12 — 업무범위 집중 검토 (WorkScopeExcessReview) ✅

- **심각도**: 3
- **근거**: K-SOX 접근권한 검토, 직무분리 설계 검토, 사용자 권한의 최소권한 원칙. 한 사용자가 여러 업무영역에 넓게 관여하면 부정 확정은 아니지만 권한 과다, 직무집중, 보완통제 필요성을 검토할 근거가 된다.
- **성격**: Phase 1 review-only score rule. 과거 이력 또는 동료 baseline을 학습하지 않고, 현재 감사기간 데이터 안에서 사용자별 업무영역 폭을 숫자로 산정한다.
- **판정 단위**: 기본 판정 단위는 전표가 아니라 `created_by` 사용자다. 행별 `review_score_series`는 사용자 점수를 현재 기간 활동 행에 투영한 review/evidence 표현이며, 확정 위반 Boolean이 아니다.
- **탐지와 점수 분리**: 사용자 유형별 process/company 기준 (단일 출처: `config/audit_rules.yaml` → `patterns.work_scope_excess_review.persona_thresholds`) 을 넘으면 자동/시스템 계정까지 raw candidate로 보존한다. 점수는 별도 위험도이며, 정상 가능성이 높은 시스템/관리자 breadth는 `0.00` 또는 낮은 review score로 둔다.
- **L1-06과의 경계**
  - L1-06은 금지된 업무분장 조합, 명시적 SoD conflict, 승인/작성 역할 충돌처럼 **확정 가능한 통제 위반**을 잡는다.
  - L3-12는 금지 여부를 판단하지 않는다. 한 사용자가 여러 프로세스, 회사, 전표유형, 계정군, 입력방식에 과도하게 관여하는 정도를 사용자 점수로 산정하고, 수기·민감계정·고액·결산 같은 문맥은 우선순위 보강 근거로만 쓴다.
  - L3-12 hit는 L1-06의 FP/FN/precision/recall에 포함하지 않는다.
- **탐지 로직**
  - `fiscal_year`가 있으면 `fiscal_year + created_by`별로 현재 데이터의 `business_process`, `company_code`, `document_type`, `gl_account` 계정군, `source` distinct count를 집계한다. `fiscal_year`가 없을 때만 기존처럼 `created_by`별로 집계한다.
  - `user_persona`가 있으면 사용자 유형별 기준을 적용한다. 없으면 default 기준을 쓴다.
  - 자동/배치 계정도 업무범위가 넓으면 raw candidate로 남긴다. 다만 기본 score는 `0.00`이며, 수기/조정 source와 민감계정·고액·결산 맥락이 함께 있을 때만 낮은 system review score를 부여한다.
  - L3-12는 사용자-year 단위 review score다. 한 사용자가 특정 연도 안에서 업무범위 집중 기준을 충족하면 사용자-year summary에 점수와 근거를 저장하고, 해당 사용자-year의 현재 기간 활동 행에는 같은 점수를 evidence projection으로 부여한다. 자동/system-only와 admin/superuser 단순 breadth는 raw candidate로 보존하되 score `0.00`으로 둘 수 있다. 단독 L3-12는 High가 아니며 다른 룰과의 결합 여부로 우선순위를 조정한다.
  - admin/superuser는 단순 다중범위만으로 플래그하지 않고, 수기·민감·고액·결산 등 보강 신호가 2개 이상일 때만 올린다.
- **사용자 유형별 시작 기준 (단일 출처: `config/audit_rules.yaml` → `patterns.work_scope_excess_review.persona_thresholds`)**

| 사용자 유형 (`user_persona`)                     |                                                                                                     process 기준 | company 기준 |
| ------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------: | -----------: |
| `junior`, `staff`, `clerk`                       |                                                                                                           `>= 3` |       `>= 2` |
| `senior`, `accountant`, `default` (미지정/그 외) |                                                                                                           `>= 4` |       `>= 3` |
| `manager`, `controller`                          |                                                                                                           `>= 5` |       `>= 4` |
| `admin`, `superuser`                             |         raw candidate로 보존하되 단순 다중업무는 score `0.00`, 수기/민감/고액/결산 중 2개 이상 결합 시 점수 부여 |         좌동 |
| `automated_system`, `batch_user`                 | raw candidate로 보존하되 기본 score `0.00`, 수기/조정 source와 보강 신호가 함께 있을 때 낮은 system review score |         좌동 |

위 표의 process/company 정수 임계값은 yaml에서 사용자 정의로 변경 가능하며, 카드는 yaml의 현재 값을 단일 출처로 본다. 아래 score bucket 표의 "process 기준 충족", "company 기준 충족" 표현은 위 persona 임계값을 가리킨다.

- **점수 bucket**

| 조건                                                    |                              점수 |
| ------------------------------------------------------- | --------------------------------: |
| 사용자 유형별 process 기준 충족                         |                            `0.20` |
| process 기준 + company 기준 동시 충족                   |                            `0.30` |
| process 또는 company 기준을 한 단계 (해당 유형 +1) 상회 |                            `0.35` |
| 위 조건 + `manual/adjustment` source 포함               |                            `0.45` |
| 위 조건 + 민감 계정군 포함                              |                            `0.50` |
| process/company 기준을 모두 한 단계 상회 + 수기 포함    |                            `0.55` |
| 위 조건 + 결산일/고액/민감계정 중 2개 이상 결합         |                            `0.65` |
| L1-05/L1-06/L1-07 동반                                  | L3-12는 `0.65` 이하, L1이 주 신호 |

- **결과 표현**
  - `score_series`: 항상 `0.00`을 유지한다. L3-12는 확정 위반이 아니므로 `flagged_rules`와 DB `anomaly_flags` 집계에 들어가지 않는다.
  - `review_score_series`: `0.00~0.65` 사용자 업무범위 집중 review score를 제공한다. 이 값은 row `anomaly_score`와 PHASE1 case priority에 weak/booster 신호로만 반영된다.
  - `row_annotations`: `user`, `persona`, `bucket`, `score=0.00`, `review_score`, `process_count`, `company_count`, `document_type_count`, `account_group_count`, `source_count`, `reasons`, `rule_boundary`를 저장한다.
  - `breakdown`: `scoring_unit=user`, `row_projection_policy`, `candidate_rows`, `candidate_users`, `scored_rows`, `review_scored_rows`, `scored_users`, `bucket_counts`, `user_summaries`, `zero_score_system_rows`, `zero_score_admin_rows`를 기록한다.
- **평가/리포트 표시 방식**
  - L3-12는 row-level 라벨-only precision/recall로 해석하지 않는다. v109 DataSynth부터 `work_scope_raw_candidate_population`은 raw candidate truth이고, `work_scope_excess_review_population` 및 `rule_truth_L3_12`는 사용자 단위 scored review truth다.
  - 후보 모집단 평가는 `raw_candidate`와 `work_scope_raw_candidate_population`을 비교한다. 위험 점수 평가는 `review_score_series > 0`과 `rule_truth_L3_12`를 비교한다. 두 지표를 섞어 score `0.00` 시스템/관리자 관찰 후보를 scored truth의 과탐으로 계산하면 안 된다.
  - 리포트의 1차 표시는 사용자 단위 `user_summaries`이며, 전표 행은 해당 사용자 점수의 근거 샘플 또는 결합 evidence로 drill-down한다.
  - Transaction Queue에서는 `review_rules=L3-12`로 노출하고, 확정 위반 목록인 `flagged_rules`에는 넣지 않는다.
  - v95 DataSynth 기준 L3-12 scored truth는 `labels/rule_truth_L3_12.csv`와 `labels/work_scope_excess_review_population.csv`에 `fiscal_year + created_by` 단위로 저장한다. v109부터 raw candidate truth는 `labels/work_scope_raw_candidate_population.csv`에 별도로 저장한다.
  - 전표 단위 결과는 `labels/work_scope_excess_document_projection.csv`에 drill-down projection으로만 저장한다. 이 파일은 strict precision/recall 정답으로 사용하지 않는다.
  - 리포트는 단독 L3-12 hit와 `L3-12 + L3-02/L3-10/L3-04/L4-03/L1-*` 결합 후보를 분리한다.
  - 단순 프로세스 폭은 낮은 우선순위, 수기·민감계정·고액·결산 맥락 결합은 높은 우선순위로 본다.
- **운영 예외와 보완 통제**
  - shared service, 결산 집중 기간, 소규모 조직, 백업 담당, migration/test user는 정상 사유가 가능하다.
  - 단순히 여러 업무를 했다는 이유만으로 부정 또는 통제 위반으로 결론내리지 않는다.
  - 권한 부여 사유, 승인 로그, 대체 승인자, 조직도, 사용자 직무기술서, 보완 검토 통제를 함께 확인한다.
- **구현**: `fraud_rules_access.py` → `b14_work_scope_excess_review()`, `fraud_layer.py` → registry rule id `L3-12`
- **필요 피처**: 필수 `created_by`, `business_process`; 권장 `user_persona`, `company_code`, `document_type`, `gl_account`, `source`, `is_period_end`, `exceeds_threshold`, `amount_zscore`
