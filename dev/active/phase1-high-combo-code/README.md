# PHASE1 HIGH_COMBO 코드반영 — 단계별 작업 지시서

SoT: `docs/spec/HIGH_COMBO_GROUNDING.md` (§3.0 발화표 · §6 종합표 · §8 변경이력).
문서 정리는 완료, **코드는 0건 반영** 상태. 이 디렉터리의 지시서는 그 문서 결정을
기존 코드(`src/detection/topic_scoring.py` 외)에 반영하기 위한 것이다. **0부터가 아니라
기존 코드 수정.** 각 지시서는 한 태스크만 담고, 단계마다 테스트 게이트가 있다.

## 실행 순서 (의존성 — 순서 고정)

1. **stage1_combos.md** — `_fraud_combo_floor_results` 조합 재정의 + DEFAULT_COMBO_FLOORS + 룰셋 상수.
   (가장 큰 단계. tier 발화 로직의 핵심.)
2. **stage2_sortkey.md** — `time_severity_score`(OFF-TIME 보조축) 신설 + sort_key 삽입.
   (stage1과 독립이나 stage1 머지 후 진행 권장 — 같은 파일군 충돌 방지.)
3. **stage3 (단위 통일 — 3분할)** — `stage3_low_coverage.md`는 전제 오류로 폐기(아래 사유).
   UNIT_MEASUREMENT_POLICY 정합으로 재설계: tier는 document/flow(`phase1.units`)에만,
   case는 집계뷰(자기 band 정렬축 아님). 순서 고정:
   - **stage3a_unit_queue.md** — `phase1.units` 기반 검토 큐(tier∈{HIGH,MEDIUM}·1전표 1줄)
     + 커버리지 표(룰별 전수) + unit 모델에 total_amount·time_severity_score 이동. (핵심)
   - **stage3b_case_aggregate.md** — 기존 case 큐 빌더를 unit 소비로 전환/집계뷰 강등
     (case.priority_band를 truth 정렬축에서 제거). 3a 머지 후.
   - **stage3c_dashboard_rewire.md** — dashboard(tab_phase1.py)가 3a 큐·커버리지 소비. 3b 머지 후.
4. **stage4_integration_test.md** — 1~3 통합 후 전체 회귀 + ripple grep 게이트.

### stage3 폐기 사유 (전제 오류)
`stage3_low_coverage.md`는 "전표 단위 tier 줄에서 LOW를 빼는 최소 수정"을 전제했으나,
검증 결과 **검토 큐가 전부 case(집계뷰) 단위**이고 전표 단위 큐는 코드에 없었다(`phase1.units`
계산만 되고 소비처 0건). UNIT_MEASUREMENT_POLICY는 tier가 document/flow에만 붙고 case는
자기 점수가 없는 집계뷰라고 못박으므로, "통일" = 큐를 전표/흐름 단위로 전환하는 것. 3a/b/c가 그 작업.

## 리뷰 게이트 (설계자=메인 컨텍스트가 각 단계 보고 수신 후 수행)

- 증거 대조: §7 보고의 각 체크 항목에 명령 출력 원문이 있는가. 없으면 미수행 처리.
- 핵심 재현: §6 검증 명령 1개 이상을 직접 재실행해 대조.
- hollow-PASS 점검: 기대값을 출력에 맞춰 고치거나 skip/xfail로 통과시킨 흔적 diff 확인.
- 하드코딩 스캔: §5 금지 리터럴(연도·금액 임계·룰ID 분기 신설)이 diff에 들어왔는지 grep.

## 절대 불변식 (전 단계 공통)

- **3-surface 비병합**: PHASE1-1 룰 / PHASE1-2 family / PHASE2 VAE 점수 미병합.
- **tier 단위 = 전표(document)**, case = 집계뷰(자체 tier 없음). UNIT_MEASUREMENT_POLICY.md.
- **보조축(OFF-TIME·적요부실·라운드넘버)은 게이트 미참여** — tier 승격 불가, 정렬·UI만.
- tier 순서형: HIGH>MEDIUM>LOW>CONTEXT. 가중합·band컷 폐기(현행 유지).
