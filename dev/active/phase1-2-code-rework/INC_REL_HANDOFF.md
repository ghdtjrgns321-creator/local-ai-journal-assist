# Inc-REL (relational family 완전 삭제) — ✅ 완료 (2026-06-30)

> **종결**: 전용 파일 4 + 전용 테스트 8 삭제, phase2 배선·pipeline·registry·config·대시보드 6·공용 테스트 swap/재-swap 완료.
> 전체 스위트 NEW 실패 **0**(final 34 == baseline 34 동일집합), collection 4050 정상, 음의공간 6/6 prose(live 0),
> phase1_rulebase 25 passed, 한글 U+FFFD 0. 증거·상세는 contract `.claude/state/contracts/ad43d23a-…md`
> "Inc-REL … 파괴적 본삭제 실행 (이번 턴)" 섹션 참조. 아래 계획 본문은 착수 당시 기록으로 보존.
> relational 재구현(첫등장/희소 거래처 단위)은 PLAN Phase 3 별도 과제로 잔존.

> 시작 한 줄: "INC_REL_HANDOFF.md 보고 relational 본삭제 진행해".
> IC/dup/graph 와 동일 플레이북. 상세 결정 근거는 PLAN.md §2·§6(관계형 결론).

## 전제
- relational family = **옛 PHASE2 실패 코드 전체 삭제**. R02/R04/R06=드롭, R01/R05/R07=옛 코드 삭제
  (재구현은 base 경로 거래처 단위로 **Phase 3 별도** — 이번엔 삭제만).
- **all-or-nothing**: product+dashboard+config+test 한 번에. 절반 삭제=빌드 깨짐.
- baseline: 다음 컨텍스트 착수 시점 working tree로 **새로 캡처**(`pytest tests/ -q | grep FAILED|ERROR | sort`).
  현재(IC 직후) 기준값은 scratchpad/ic_final.txt = 34건(전부 기존, 데이터/툴 부재).
  ⚠️ IC 변경은 아직 **미커밋 working tree** — Inc-REL 착수 전 IC가 커밋됐는지 git log 확인.

## 보존 (절대 건드리지 말 것)
- **timeseries / unsupervised(VAE) family 잔존** — 삭제 후 phase2 case = timeseries+unsupervised 만.
- relational_graph_features 는 relational_rules 만 import → 공유 함정 없음(함께 삭제 OK).
  access_audit·evidence·nlp 는 relational 무의존(grep 오탐이었음).
- lane_sort 의 `relational_continuity_depth` 보조축은 relational 전용 → 제거 대상(보존 아님).

## 삭제 대상
1. **전용 파일 4**: `src/detection/relational_detector.py`·`relational_rules.py`·`relational_graph_features.py`,
   `src/services/phase2_relational_case_builder.py`.
2. **전용 테스트 5**: test_relational_detector / _edge_artifact / _graph_features / _rules,
   test_phase2_relational_case_builder. (+ relational_v31/v33* 류 있으면 동반)
3. **phase2 배선**: `RelationalCase` 모델(phase2_case.py) + orchestrator·store·linker·aggregator
   ·contract(relational_continuity_depth)·inference·lane_sort(relational branch+continuity)
   ·family_policy(`RELATIONAL_*` 상수 다수+__all__)·training_service(relational family).
4. **pipeline**: `_try_relational_detection`(~1611-1652) + `from ...relational_rules import build_doc_flow_df`
   + `relational_continuity` overlay 입력(연쇄).
5. **registry**: constants(R01~R07 라벨/severity)·rule_mapping·rule_scoring·rule_detail_metadata
   ·score_aggregator·phase1_case_builder 의 R01~R07.
6. **config**: phase2_subdetector_tiers.yaml R01~R07(7엔트리, 삭제 후 1 VAE+2 TS+4 dup=**7개**),
   settings.py `rel_*` 튜닝값(사용처 grep 먼저 — IC처럼 dead면 제거).
7. **대시보드**: tab_phase2·tab_phase1·native_case_metrics·native_case_panel·subdetector_grid 의 relational 레인.
8. **공용 테스트 swap + 재-swap**: test_phase2_row_ref·case_hash·case_phase1_linker·case_set_orchestrator
   ·case_store·inference_service_case_set_attach·native_case_panel·tab_phase2.
   ⚠️ **IC 삭제 때 IC테스트를 relational 로 swap 한 것들을 이번엔 timeseries/unsupervised 로 재-swap** 필수.

## 작업 순서 (IC 플레이북)
1. baseline 캡처(working tree) → 파일 9개 삭제(git rm) → registry → phase2 배선 → pipeline → config → 대시보드
   → 테스트(collection 막는 import 먼저) → 검증.

## 검증 (IC에서 검증된 방법)
- **음의공간**: `grep -rnE "RelationalCase|relational_cases|build_relational_cases|RelationalDetector|relational_continuity|from src.detection.relational|from src.services.phase2_relational" src dashboard --include=*.py` = 0(prose 주석 제외).
- **collection**: `pytest tests/ --co -q` → "Interrupted: errors during collection" 0건, 수집 수 정상.
- **HEAD/working-tree baseline diff**: `comm -23 현재 baseline` NEW=0 + `comm -13`(GONE) 확인.
- 카운트 갱신 예상: subdetector_tiers 14→7, family 7→6, active 3→2, grid 9→2(TS만).
- phase1_rulebase 25 passed. 28모듈 import OK. 한글 U+FFFD=0.

## 함정 (IC에서 겪음)
- pytest는 **collection error 1건이라도 있으면 세션 전체 Interrupted**(테스트 0개 실행). → 삭제 심볼 import를
  먼저 전부 제거해 collection 통과시킨 뒤, runtime 실패를 baseline diff로 전수 도출.
- status doc/refmap의 "테스트 N파일" 목록은 불완전 — baseline diff(comm -23)가 forcing function.
- "import만 0 = 완료"는 hollow. 살아있는 배선(lane/contract/aggregator/inference/대시보드 런타임) 직접 grep.
- IC 때 relational 로 swap 한 테스트를 빠뜨리면 이번 삭제로 다시 깨짐 — 재-swap 목록(§8) 필수.
