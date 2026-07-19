# Inc-IC (IC family 완전 삭제) — ✅ 완료 (2026-06-30)

> **종결**: product+dashboard+config+test 전부 삭제 완료. 전체 스위트 NEW 실패 0
> (final 34 == baseline 34 동일집합), collection 4169 정상, phase1_rulebase 25,
> is_intercompany(L3-03) 14파일 보존·재현, 한글 U+FFFD 0. 증거·상세는
> contract `.claude/state/contracts/ad43d23a-…md` "파괴적 본삭제 — 실행" 섹션 참조.
> 아래 계획 본문은 착수 당시 기록으로 보존.

## 전제
- IC는 **살아있는 기능**(케이스·레인·대시보드 탭). 절반 삭제 = 빌드 깨짐 →
  **product + dashboard + test 를 한 번에** 끝내고 마지막에 검증(중간 커밋 금지).
- 선행 완료(이번 세션): `extract_ic_prefixes`+`load_ic_pairs`를 `pattern_features.py`로
  이전 끝남. 그래서 `is_intercompany`(L3-03)는 IC 규칙 파일과 디커플됨 → IC 파일 통삭제 가능.

## 절대 보존 (건드리지 말 것)
- `is_intercompany` 컬럼/로직 16파일: pattern_features(add_is_intercompany + 이전된 헬퍼)·
  engine·db schema/queries·preprocessing/constants·nlp_rules·fraud_layer·fraud_rules_access·
  prompt_presets·ground_truth_evaluator·relational_rules(:191-194 mask) 등.
- 즉 "intercompany" 문자열이 전부 삭제 대상 아님 — IC **family(검사기·케이스·레인)** 만.

## 삭제 대상
1. 파일 삭제: `src/detection/intercompany_matcher.py`, `intercompany_rules.py`(헬퍼 이전됐으니 통삭제),
   `src/services/phase2_intercompany_case_builder.py` + IC 전용 테스트 7개
   (test_intercompany_matcher / _matcher_pair_artifact / _reciprocal_flow / _timing_domain /
   _v7_fixed3_smoke / _incremental_value_diagnostic, test_phase2_intercompany_case_builder).
2. phase2 family 배선: `IntercompanyCase` 모델(phase2_case.py) + orchestrator·aggregator·
   lane_sort(`_IC_ROLE_PRIORITY`·`_ic_role_priority`)·contract(IC internal prob band)·
   inference·store·native_panel 의 IC 분기 + training_service IC family + subdetector_tiers.yaml IC 엔트리.
3. pipeline: `_try_intercompany_detection`(~1684-1715) + `enable_intercompany_detection` getattr.
4. registry: constants·rule_detail_metadata·rule_mapping·score_aggregator IC 항목.
5. 대시보드: tab_phase2·phase2_family_matrix·phase2_subdetector_grid·phase2_native_case_metrics·
   tab_comparison 의 intercompany 레인/라벨/색/집계.
6. **공용 테스트의 IntercompanyCase fixture 12파일**: 다른 active family(relational/timeseries)로
   swap 또는 삭제. 특히 test_phase2_lane_sort 의 `TestIntercompanyRolePriority`(전체 클래스)·
   case_contract IC internal prob band·linker/store/row_ref/orchestrator/inference_attach/native_panel.

## 작업 순서 (duplicate 플레이북 그대로)
1. (이미 됨) extract_ic_prefixes 이전.
2. detector/builder 파일 삭제 → registry → phase2 family 배선 → pipeline → 대시보드.
3. 테스트: 전용 7파일 삭제 + 공용 12파일 swap/삭제.
4. 검증.

## 검증 (반드시 — duplicate에서 검증된 방법)
- **음의공간**: `grep -rlE "IntercompanyCase|intercompany_cases|build_intercompany|intercompany_matcher|intercompany_rules|_ic_role_priority|_IC_ROLE_PRIORITY" src dashboard tests --include=*.py` = 0.
- **is_intercompany 보존**: 위 16파일 `is_intercompany` grep 잔존 + L3-03 동작 재현([True,False]).
- **HEAD baseline diff (핵심)**: `git stash`로 HEAD 광역스위트 실패집합 캡처 → 변경본 동일명령 →
  `comm -23` NEW=0. (duplicate 때 누락 테스트 8파일을 이 방법이 적발함 — status doc/refmap 목록 믿지 말고 직접.)
- phase1_rulebase 25 passed. src+dashboard import smoke OK. 한글 U+FFFD=0.

## 함정 (duplicate에서 겪음)
- status doc/refmap의 "테스트 N파일" 목록은 **불완전**. tests/ 직접 grep + baseline diff로 전수 도출.
- "import만 0 = 완료"는 hollow. 살아있는 배선(lane/contract/aggregator/inference/대시보드 런타임) 직접 확인.
