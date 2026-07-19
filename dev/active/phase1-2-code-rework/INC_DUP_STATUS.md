# Inc-DUP (duplicate 완전 삭제) — ✅ 완결 (2026-06-30)

> **종결**: 제품+대시보드+테스트 전부 완료. 아래 "미완" 기록은 역사(당시 상태)로만 보존.
> 최종 상태·증거는 contract `.claude/state/contracts/…md` "Inc-DUP 완전 종결" 섹션 참조.
> 핵심: (1) 이전 "제품 import-clean=완료"는 hollow였음 — family 배선(lane_sort·contract·aggregator·inference·family_policy)·대시보드 런타임버그(`case_set.duplicate_cases` AttributeError) 잔존. (2) 테스트 모집단은 7파일이 아니라 16파일 — 누락 8파일을 HEAD baseline diff로 적발. (3) 광역 스위트 신규 실패 0(잔존 32건 전부 기존, 데이터/툴 부재). live 코드 duplicate-family 토큰 grep=0.

작성 2026-06-30. PLAN/HANDOFF/phase2_reference_map 보조.

## 완료: 제품 코드 (import-clean, 전수 검증)

`uv run python -c "import ..."` 로 src + dashboard 전 모듈 import OK 확인.

- 삭제 파일: `src/detection/duplicate_detector.py`, `duplicate_rules.py`, `duplicate_pair_features.py`, `src/services/phase2_duplicate_case_builder.py`, `src/services/duplicate_pair_tier.py`
- `src/models/phase2_case.py`: `DuplicateCase` 클래스 + `Phase2CaseSet.duplicate_cases` 필드 + `_FAMILY_FIELD_NAMES` "duplicate_cases" + `__all__` 제거
- `src/pipeline.py`: `_try_duplicate_detection` 제거 (block entry는 Inc-A에서 이미 제거)
- `src/services/phase2_training_service.py`: import + 13개 family dict/tuple에서 "duplicate" 제거
- `src/services/phase2_case_set_orchestrator.py`: import + track map + routing 제거
- `src/services/phase2_case_store.py`: import + `_FAMILY_TO_ATTR`/`_FAMILY_TO_DATACLASS` + dedup 분기 + 생성자 제거
- `src/services/phase2_case_family_aggregator.py`: duplicate_pair_tier import + `_duplicate_pair_tier_by_label` + `_case_best_pair_tier` + 호출/분기 제거
- `src/services/phase2_case_contract.py`: `_attach_duplicate_pair_evidence` 함수 + 호출 제거
- `src/services/phase2_case_phase1_linker.py`: DuplicateCase import + `_FAMILY_FIELD_NAMES` + **7개 isinstance(DuplicateCase) 분기** 제거
- `src/services/phase2_inference_service.py`: build_duplicate_policy_summary import + duplicate 요약 제거
- `src/db/batch_reader.py`: `_RESTORED_CORE_TRACKS`에서 "duplicate" 제거
- `src/detection/constants.py`: `Layer.DUPLICATE` membership + profile 제거 (enum 멤버 `DUPLICATE = "duplicate"`는 무해 잔존)
- `dashboard/components/phase2_native_case_panel.py`: DuplicateCase import + `_build_duplicate_row` + dispatch + narrative label + isinstance 제거

### 범위 결정 (의도적 잔존)
- **L2-03a~d alias/reason-code 메타** 잔존: `rule_detail_metadata` canonical 매핑·entry, `constants` 라벨/severity, `rule_mapping`, `phase1_case_builder` L2-03 detail. 사유: L2-03 base(`fraud_layer.py:268 b05_duplicate_entry`) reason-code V1 LOCK 계약, 탐지기 삭제 후 `details.columns` 미존재로 자동 무시(무해).
- `src/services/phase2_family_policy.py` `build_duplicate_policy_summary` 함수 + `DUPLICATE_*` 상수: dead(미참조)이나 미삭제. grep-clean 위해 제거 권장(저위험).

## 미완: 테스트 fixture (다음 세션) ★

DuplicateCase가 phase2 케이스 인프라 테스트의 **generic fixture**로 쓰여 7파일에서 swap/delete 필요.
실제 `DuplicateCase(` 생성자 호출 10곳, `duplicate_cases=`/`stubs["duplicate"]` 다수.

| 파일                                                                           | 처리 방침                                                                                                |
| ------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------- |
| `tests/modules/test_services/test_phase2_case_hash.py`                         | ✅ 완료 — DuplicateCase→RelationalCase swap                                                              |
| `tests/modules/test_services/test_phase2_case_phase1_linker.py`                | generic fixture → RelationalCase swap (171 hits 대부분 단어; ctor 3)                                     |
| `tests/modules/test_services/test_phase2_case_store.py`                        | generic fixture → RelationalCase swap                                                                    |
| `tests/modules/test_models/test_phase2_row_ref.py`                             | generic fixture → RelationalCase swap                                                                    |
| `tests/modules/test_services/test_phase2_case_set_orchestrator.py`             | **duplicate 라우팅 전용** — duplicate 테스트 삭제 + `stubs["duplicate"]`/`case_set.duplicate_cases` 정리 |
| `tests/modules/test_services/test_phase2_inference_service_case_set_attach.py` | duplicate 요약 테스트 삭제 + fixture swap                                                                |
| `tests/modules/test_services/test_phase2_lane_sort.py`                         | duplicate tier 테스트 삭제 또는 swap (duplicate_pair_tier import 있음)                                   |
| `tests/modules/test_dashboard/test_phase2_native_case_panel.py`                | duplicate row 테스트 삭제 + fixture swap                                                                 |
| `tests/modules/test_detection/test_audit_coverage_contract.py`                 | DuplicateDetector import + duplicate 2개 테스트 삭제 (Inc-B에서 남겨둠)                                  |

## 검증 (테스트 swap 완료 후)
- `uv run pytest tests/modules/test_services tests/modules/test_detection tests/modules/test_pipeline tests/phase1_rulebase tests/phase2_rulebase -q` 신규 실패 0
- `grep -rn "DuplicateCase\|build_duplicate_cases\|duplicate_pair_tier" src/ dashboard/ tests/ --include=*.py` (주석 제외) = 0
