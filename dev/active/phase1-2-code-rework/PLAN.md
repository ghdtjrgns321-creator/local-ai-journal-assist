# PHASE1-2 코드 재작업 — 구현 계획

작성: 2026-06-30. 설계 SoT: [DETECTION_RULES_PHASE1-2.MD](../../../docs/spec/DETECTION_RULES_PHASE1-2.MD), [CONSTRAINTS.md §단일 법인](../../../docs/spec/CONSTRAINTS.md), [HIGH_COMBO_GROUNDING.md](../../../docs/spec/HIGH_COMBO_GROUNDING.md).

> **⚠️ 2026-07-15 갱신 — 구현 후 실측으로 §3 Phase 1·§6 시계열 결론이 바뀌었다.** 실측 근거 전량: [backend_verify.md](backend_verify.md).
>
> | 항목                       | 계획(2026-06-30)             | 현행(2026-07-15)                                                    |
> | -------------------------- | ---------------------------- | ------------------------------------------------------------------- |
> | Phase 1 단일 회사 스코프   | 회사별 실행 후 병합          | **폐기 → 입구 가드**(데이터 15개 중 14개가 이미 단일 회사)          |
> | 시계열 당기내 집중         | 자기 큐 신규 채택            | **폐기 → D02 드릴다운**(당기 내 baseline 이 결산 캘린더를 재발견)   |
> | 자기 큐                    | 6종                          | **5종**(시계열 제외)                                                |
> | macro 큐 top_n(100) 절단   | 유지 전제                    | **제거**(PHASE1-2 는 검토 목록을 소유하지 않음)                     |
> | 라운드넘버 `round_amount_score` 재활용 | 재활용            | 신규 `round_density_rules.py`(이항검정) + `is_round_number` 정의 교체 |
> | PHASE2_TIMESERIES_ROLE_LOCK | 본 결정으로 supersede 예정  | **supersede 취소** — 결산 lane lock 존속                            |
>
> 완료: Phase 0(baseline) · Phase 2(레거시 정리) · Phase 3(첫등장/희소) · Phase 4(배지 통합). 미착수: Phase 5·6(UI — 사용자 지시로 범위 외), D02 드릴다운.

## 0. 한 줄 목표

문서로만 확정된 PHASE1-2 재설계(자기 큐 / 배지 / 범위 외 / 드롭)를 코드에 반영하고, 옛 PHASE2 rule-style 잔재를 정리하며, 전표 테스트를 단일 법인 단위로 스코프한다.

## 1. 핵심 발견 (실측, 3 Explore 에이전트)

재설계의 상당부분이 **이미 코드 골격에 존재**한다. 새로 만드는 것보다 **연결·재분류·정리**가 주다.

| 사실                                                                                                            | 근거 (파일:줄)                                                                                |
| --------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| GR01/GR03(graph)는 dead — 정의만 있고 호출 0                                                                    | `pipeline.py:1717` 정의, 호출 site 0건                                                        |
| IC·relational·duplicate·TS는 phase2_only 블록에서만 실행                                                        | `pipeline.py:1460-1491` (force_enable)                                                        |
| rule-style 4종은 row anomaly_score 미기여(overlay 전용)                                                         | `score_aggregator.py:337-344` track 미주입                                                    |
| 자기 큐 백엔드(계정 finding + queue 빌더) 존재, 화면 없음                                                       | `phase1_case_builder.py:832-1098`, `phase1_case_view.py:2348-2366`; `tab_phase1.py` 미import  |
| 배지 토대(time_severity + weak_evidence_tags) 존재, 통합 컬럼 없음                                              | `phase1_case_builder.py:88-95`, `:4843-4878`; unit 그리드 컬럼 고정 `tab_phase1.py:3418-3427` |
| macro 0기여 강제 이미 작동                                                                                      | `rule_scoring.py:38-43`, `score_aggregator.py:251-254`                                        |
| base 경로(default) 실행 = Integrity(L1-01~03)+FraudLayer+Anomaly(11룰)+Benford+Evidence(L3-11)+variance(조건부) | `pipeline.py:1397-1454`                                                                       |

## 2. Gap 인벤토리 — 룰별 현 상태 → 운명

| 룰                      | 현 위치 (파일:줄)                                       | 현 실행             | 새 운명            | 작업                                                                                                                        |
| ----------------------- | ------------------------------------------------------- | ------------------- | ------------------ | --------------------------------------------------------------------------------------------------------------------------- |
| L4-02 Benford           | `benford_detector.py`; macro_only `rule_scoring.py:352` | base 활성           | **자기 큐**        | 화면 연결만                                                                                                                 |
| D01                     | `variance_layer.py:130`; macro_only `:413`              | optional(전기 필요) | **자기 큐**        | 화면 연결만                                                                                                                 |
| D02                     | `variance_layer.py:109`; macro_only `:423`              | optional            | **자기 큐**        | 화면 연결만                                                                                                                 |
| L4-05 OFF-TIME          | `anomaly_layer.py:252`; OFF_TIME_SET                    | base 활성, 점수 0   | **배지**           | 통합 배지 필드에 포함                                                                                                       |
| L4-06 batch             | `anomaly_layer.py:265`; macro_only `:399`               | base 활성, 점수 0   | **배지**           | role 재분류(표시) + 배지 필드                                                                                               |
| L3-12 work scope        | `fraud_layer.py:295`; macro_only `:330`                 | base 활성, 점수 0   | **배지**           | role 재분류(표시) + 배지 필드                                                                                               |
| 라운드넘버              | `_case_weak_evidence_tags:4860` `is_round_number`       | base(단건 boolean)  | **배지 + 자기 큐** | 단건=배지 / 밀집도 macro 신설=자기 큐(Benford식)                                                                            |
| 첫등장/희소 R01·R05·R07 | `relational_rules.py:43,269,383`                        | **phase2_only**     | **배지 + 자기 큐** | base 신규 구현(거래처 단위). 전수 목록·거래내용 묶음·고액/대량 정렬 (§6)                                                    |
| R02·R04·R06             | `relational_rules.py:89,229,328`                        | phase2_only         | **드롭**           | 비활성 + registry 정리                                                                                                      |
| IC01·02·03              | `intercompany_matcher.py:615+`                          | phase2_only         | **완전 삭제**      | matcher·registry·phase2 배선 제거. L3-03 관계사 꼬리표는 PHASE1-1 조합용 잔존                                               |
| GR01·GR03               | `graph_detector.py:90,101`                              | **dead**            | **완전 삭제**      | dead 함수·registry·constants 제거(주석 보존 안 함)                                                                          |
| duplicate b05b/c/d      | `duplicate_detector.py:95-117`                          | phase2_only         | **드롭**           | fuzzy·split 드롭. 시차중복은 L2-03 매칭 확장(거래처+금액+근접기간)으로 흡수. b05a exact=L2-03 base 유지. PHASE1-2 신설 없음 |
| TS01·TS02               | `timeseries_detector.py`                                | phase2_only         | **자기 큐 신규**   | 당기 내 거래 집중으로 재설계(통계 재활용). 결산 lock supersede (§6)                                                         |

## 3. 단계별 계획 (순서 = 위험 낮은 것부터, 각 단계 독립 검증)

### Phase 0 — 회귀 baseline 고정 (착수 전 필수)
- `uv run pytest tests/phase1_rulebase/ -q` 통과 수 기록.
- 한 데이터셋(정상 v44f)으로 현재 PHASE1 case/queue/band 분포 수치 캡처 → `dev/active/phase1-2-code-rework/baseline.md`.
- 검증 기준: 이후 모든 단계에서 "알려진 실패 N, 신규 0" 가드. band 분포 의도적 변경 외 회귀 0.

### Phase 1 — 단일 회사 스코프 → **입구 가드로 대체 (2026-07-15 완료)**
- ~~base+variance 탐지를 `company_code`별로 돌려 합치도록.~~ **폐기.** DataSynth 데이터셋 15개 중 **14개가 이미 단일 회사(C001)**이고 다회사는 본 PLAN 작성일과 같은 날 생성된 `contract_v3_rebuild_20260630_r1` 1개뿐이다. 운영 DB 도 회사·연도별 격리. 단일 법인 확정 하에서 병합 기계(`flagged_indices` 위치 재매핑 + 탐지기별 metadata 병합)는 투기성 복잡도(§YAGNI).
- **현행**: `pipeline.py::single_company_scope_warnings` — 다회사면 `[분석범위제한]` 경고 1건, 단일회사·컬럼부재면 no-op. 결측 `company_code` 는 회사로 세지 않는다.
- **검증 완료(2케이스)**: 다회사 contract_v3_rebuild(3사·결측 6행) → 경고 1건 / 단일회사 v53_r6 → 경고 0건. 단위테스트 6/6. 산출물 [backend_verify.md](backend_verify.md) §2.
- **회사 오염 룰 7/17 전수 조사** 완료 — L4-01·L1-06·L2-03·L2-05·L4-05·L4-06·L3-09(경고 문구에 명시). 안전: L4-02·L4-03·L4-04·L2-02·D01·D02.

### Phase 2 — 레거시 정리 (low risk, 대부분 dead/phase2-only)
- (2a) `pipeline.py:1460-1491` phase2_only family 블록에서 **relational·duplicate·intercompany 제거**, timeseries만 잔류(PHASE2 lane). VAE 경로(`_try_ml_detection`) 무변경.
- (2b) dead graph 정리: `_try_graph_detection`(`pipeline.py:1717`) + GR01/GR03 registry(`constants.py:148-149`, `rule_scoring.py`/`rule_detail_metadata.py`) 정리 또는 deprecated 표기.
- (2c) R02/R04/R06, duplicate b05b/c/d 비활성(코드 보존, 호출 차단).
- 검증: 정리 후 `uv run pytest` 회귀 0 (소비처 silent-skip 확인 — 에이전트 B). PHASE2 추론이 VAE만으로 graceful 동작.
- 실패조건: 테스트 신규 실패 OR VAE 경로 깨짐.

### Phase 3 — 첫등장/희소(R01/R05/R07) → PHASE1 배지
- R01/R05/R07를 phase2 relational family에서 분리해 PHASE1 base 경로에서 거래처 단위로 계산, 배지 신호로 산출.
- 주의: first-seen은 전기(2022·2023) 미등장 + 당기(2024) 등장 교차로만 판정(단일 연도 무의미 — 설계 SoT 명시).
- 검증: 통합 연도 실행 시 first-seen 거래처 수가 0도 전부도 아님(중간값). 단일 연도 실행 시 경고/스킵.
- 실패조건: 단일 연도에서 거의 모든 거래처가 first-seen으로 잡힘.

### Phase 4 — 배지 통합 필드
- case/unit 모델에 `badge_tags` 추가: time_severity(OFF-TIME L4-05) + weak_evidence_tags(라운드넘버·희소) + L4-06·L3-12 발화여부 + 첫등장/희소. 점수 비병합(기존 0강제 지점 재사용).
- L3-12·L4-06 role을 표시상 배지로 재분류(`rule_scoring.py:330,399`) — 단 row 점수 0 유지(score_aggregator 제외 목록에 잔류).
- 검증: 배지 부착된 전표가 HIGH/MEDIUM/LOW 등급은 안 바뀜(점수 비병합 회귀 테스트). 배지 boolean 정확.

### Phase 5 — 자기 큐 UI (백엔드 재사용)
- `build_phase1_macro_finding_queue`(`phase1_case_view.py:2348`)를 `tab_phase1.py`에 import + "분석적 검토(계정)" 섹션 렌더(Benford·D01·D02 계정 목록).
- 검증: 계정 목록이 macro_findings 수와 일치, drill-down 동작.

### Phase 6 — UI 한 화면 소분류 + 배지 컬럼
- 4-tab을 설계대로: 검토 케이스(등급 + **배지 컬럼 신설** `tab_phase1.py:3418-3427`) / 데이터 정합성 / 분석적 검토(자기 큐) — PHASE2는 별도 유지.
- 검증: 한 번 실행 → 한 결과창에 3 소분류 + 배지 노출(developing-with-streamlit 스킬, 스모크).

## 4. 회귀 가드 (전 단계 공통)
- PHASE1 KPI 3-Layer 가드(CONSTRAINTS.md): Layer A/B HARD 통과, Layer C SOFT WARN 절대값 회귀만.
- 3-surface 불변식: 자기큐/배지/PHASE2 점수 비병합 유지.
- 각 단계 종료 시 `uv run pytest tests/phase1_rulebase/` + 관련 모듈 테스트 통과.

## 5. 확정 결정 (2026-06-30 사용자)
- **라운드넘버 = 단건 배지 + 밀집도 자기 큐 둘 다**. 단건 `is_round_number`는 배지로, "계정·월 모집단 둥근 금액 집중" 밀집도 macro를 **신설**해 Benford·D01·D02와 함께 자기 큐(분석적 검토)로 화면 표시. → §2 표 라운드넘버 운명을 "배지 + 자기 큐"로, §3에 라운드넘버 밀집도 신설 단계 추가.
- **dead graph(GR01/GR03) = 완전 삭제** (주석 보존 안 함). registry·constants·dead 함수 제거.

## 6. 보류 — 별도 의논 대상 (PHASE2 실패 코드, 2026-06-30)
IC · duplicate · 관계형(relational) · 시계열(timeseries) 4종은 **옛 PHASE2에서 실패한 구현**이라, 정리/드롭/이관을 코딩하기 전에 "단일 법인에서 무엇을 잡을지·어떻게 새로 만들지"를 먼저 의논한다. 따라서:
- §3 Phase 2a(rule-style 비활성)·Phase 3(첫등장/희소 추출)는 이 의논 종결 전까지 **착수 보류**.
- 의논 종결 후 본 §6을 각 항목 결론으로 갱신하고 Phase 표에 반영.
- 의논 무관하게 진행 가능: Phase 0(baseline)·Phase 1(단일 스코프)·graph 삭제·자기큐(D01/D02/Benford/라운드넘버)·배지(OFF-TIME/라운드넘버 단건)·UI.

### 의논 결론
- **IC (2026-06-30 종결)**: **검사기(IC01/02/03 = 양쪽 거울 대사) 완전 삭제.** 단일 법인은 상대 계열사 장부가 없어 거울 대사 자체가 불가 → 영구 불가, 죽은 코드 보존 안 함. `intercompany_matcher.py`·`intercompany_rules.py`·registry(constants/rule_scoring/rule_detail_metadata)·phase2 배선(pipeline.py:1467, training/inference family) 제거. **단 L3-03 `is_intercompany` 관계사 거래 꼬리표는 PHASE1-1 조합(관계사+역분개 등)용이라 잔존**(IC 검사기와 별개). CONSTRAINTS.md 발전방향(그룹감사 재도입) 노트는 doc로 유지.
- **duplicate (2026-06-30 종결)**: **한계점 아님 — CONSTRAINTS 기록 불요.** 중복지급은 단일 법인에서 충분히 잡히며, 전표 짝 룰이라 **PHASE1-1 `L2-03` 소관**이다(PHASE1-2 분석적 검토 대상 아님). 조치: (1) `L2-03` 매칭을 "완전 동일"→"같은 거래처 + 같은 금액 + 근접 기간"으로 확장해 날짜만 다른 시차 중복지급(구 b05d) 흡수, (2) fuzzy 적요 유사(b05b)·split 쪼개기(b05c)는 **드롭**(근거 약함·합성 fitting 위험, 단일법인 한계가 아니라 미구현 선택), (3) **PHASE1-2엔 duplicate 검사기 신설 없음**. phase2 duplicate family 배선(pipeline.py:1466) 제거.
- **관계형(첫등장/희소) (2026-06-30 종결)**: **(B) 배지 + 자기 큐.** 가공거래처(유령회사) GL-only 약근사 — 적발 아님, HIGH-6 커버 비주장 꼬리표 유지.
  - **자기 큐(거래처 목록)**: 새로 등장한/희소 거래처를 **전수**로 올린다(금액 게이트 없음 — 절대 임계 리터럴로 자르지 않음, §3 준수).
  - **묶음**: 각 거래처의 거래를 **내용(gl_account·document_type 등)별로 묶어** 요약 표시("이 새 거래처가 무슨 거래를 했나").
  - **정렬**: **고액/대량 순**(합계금액·건수). 큰 게 위로, 작은 건 아래로(잘리지 않음).
  - **배지**: 해당 거래처 전표에 "새/희소 거래처" 꼬리표.
  - **first-seen 정의**: 전기(2022·2023) 미등장 + 당기 등장 교차(연도 통합 실행 필수, 단일 연도 무의미). rare = 거래처 거래 건수 극소수.
  - **구현**: 실패한 R01/R05/R07(phase2 relational) 코드는 신뢰·재사용하지 않고 base 경로에서 거래처 단위로 신규 구현. R02/R04/R06은 드롭.
- **시계열 (2026-06-30 채택 → 2026-07-15 폐기)**: ~~살린다 — 당기 내 거래 집중 신호로 신규 설계, 자기 큐.~~ **구현 후 실측으로 전제가 깨져 자기 큐에서 폐기. D02 드릴다운으로 재정의.**
  - 구 근거(빈 구멍): D01/D02는 *전기 대비*만 보므로 "당기 안에서 특정 시점에 몰림"은 별개 차원(ACFE 결산 직전 집중).
  - **폐기 사유(실측 3라운드, 정상 v53_r6 376,727행·계정 57개)**:
    1. 당기 내 자기 리듬 median 대비 → finding **864건**, 버킷의 **70%가 분기말**(3월 95·6월 112·9월 88·12월 307). "이 계정은 분기말에 바쁘다"를 계정마다 재발견 — L3-04(기말 전표)가 이미 행 단위로 커버.
    2. 분기말/평월 레인 분리 후에도 **595건·52.4%**, 12월 185건 잔존. 연말 결산은 감가상각·충당금·법인세가 얹혀 분기 결산보다 무거워 같은 레인으로 묶어도 12월이 매번 튄다.
    3. **원리적 한계** — 한 해에 연말은 한 번뿐이라 "연말치고도 이상한가"의 baseline 이 당기 안에 없다. 전기 연말과 비교해야 하는데 그건 본 §6 의 "전기비교 아님" 전제와 충돌.
    4. **D02 중복** — "작년 같은 달 비교"는 D02(전기/당기 월별 분포 JSD, 계정 단위)가 이미 수행. 3개년 데이터라 기준점이 1~2개뿐이라 median/MAD 도 성립 안 함.
  - **DataSynth 게이트 판정 — 아티팩트 아님**: 분기·연말 결산 집중은 실무상 정상이며 Rust 를 고쳐 없애면 데이터가 비현실적이 된다. 따라서 실패조건("정상 데이터 집중 과탐이 Rust 미수정 상태로 잔존")에 **비해당**.
  - **코드**: `timeseries_concentration_rules.py`(계정별 × 일/주/월 축별 robust-z + 기말/평월 레인) + 테스트 9건 **보존**, `phase1_case_builder` 배선 **제거**. 당기내 robust-z 자산은 D02 드릴다운에서 재사용 가능.
  - **PHASE2_TIMESERIES_ROLE_LOCK supersede 취소** — 시계열이 PHASE2 lane 에 잔류하므로 결산 lane lock 은 존속한다.
