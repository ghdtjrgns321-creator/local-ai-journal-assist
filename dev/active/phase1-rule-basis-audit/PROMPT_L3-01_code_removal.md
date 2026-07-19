# 코드 작업 프롬프트 — L3-01 (MisclassifiedAccount) 완전 제거

## 0. 응답 규약
- **모든 보고·설명은 한국어로.**
- 보고는 "STATUS: DONE/BLOCKED" + 단계별 증거(rg 출력·테스트 수치·toy 결과)를 그대로 붙여라. "완료했습니다"만 쓰지 말 것.
- 각 단계의 검증 명령과 **실제 출력**을 함께 제출하라. 출력 없는 PASS는 무효(hollow-PASS).

## 1. 배경 / 결정
- 문서 SoT(`docs/spec/DETECTION_RULES.md`)에서 **L3-01은 폐기 확정**(2026-06-20). 근거: 계정-업무 프로세스 부조화는 사람이 유지하는 정답 조합표(denylist/category)에 의존해 기준이 애매하고, 통합점수체계 조합에서도 참조되지 않았다. 도메인상 이상한 계정 조합 중 실제로 드문 것은 **L4-04(희소 차대 계정쌍, `c09_rare_account_pair`)** 가 데이터 기반으로 포착한다.
- canonical L1~L4 transaction rule count: **31 → 30** (문서 `RULE_DETAIL_METADATA_V1_LOCK.md` 이미 갱신됨).
- 이 작업은 **코드에서 L3-01을 완전히 들어내는 것**이다. 동작을 다른 룰로 옮기지 않는다(역할은 L4-04가 이미 수행).

## 2. 제거 대상 앵커 (확인된 시작점 — 전수는 rg로 직접 찾을 것)
- `src/detection/integrity_layer.py`
  - `_l301_misclassified_account()` 메서드 정의 (대략 :425~) — **삭제**
  - dispatch 등록 `("L3-01", self._l301_misclassified_account)` (:191) — **삭제**
  - `RuleExplanation` `"L3-01": ...` 항목 (:62) — **삭제**
  - config 로드 `rules.get("l3_01_misclassified_account")` (:570, :572) 및 관련 헬퍼 — **삭제**
  - 모듈 docstring `"""L1/L3 data-quality rule track (L1-01~L1-03, L3-01).` (:1) — L3-01 표기 제거
  - L3-01 관련 로그·주석(:137, :428, :433, :476 등) — **삭제**
- `config/audit_rules.yaml` — `l3_01_misclassified_account:` 블록 전체 **삭제**
- 등록/매핑/설명/카탈로그/점수 계열 (rg로 전수 확인): `rule_detail_metadata.py`, `rule_mapping.py`(`src/metrics/`), `score_aggregator.py`, `rule_scoring.py`, `explanations.py`, `phase1_rule_catalog.py`, `constants.py`, `phase1_case_builder.py`, `phase1_case_view.py`(`src/export/`), `phase2_case_contract.py`(`src/services/`), `phase1_case.py`(`src/models/`), `text_reader.py`(`src/ingest/`), `ground_truth_evaluator.py`(`src/metrics/`), `access_audit_rules.py`, `batch_reader.py`(`src/db/`), `engine.py`(`src/feature/`)
  - 각 파일에서 L3-01/l301/l3_01 식별자·매핑 엔트리·전용 정규화(signal_strength)·priority floor(`l301_priority_bonus`, `l301_context`) 제거.
- `config/phase1_case.yaml` — `priority_adjustments`에 L3-01 관련 항목 있으면 제거.

## 3. 단조심 — 건드리지 말 것 (오작동 방지)
- **DataSynth 라벨 `MisclassifiedAccount`** 는 합성 데이터에 실존하는 라벨명이다. 데이터/라벨 생성 코드·테스트 픽스처의 `MisclassifiedAccount` 문자열은 **데이터이지 룰이 아니다 — 제거하지 말 것.** (룰 식별자 `L3-01`/`l301`/`l3_01`/`_l301_`/`misclassified_account` 설정키만 제거 대상)
- `rule_mapping.py`에 하위호환 alias 레이어가 있으면, L3-01을 canonical에서 빼되 과거 raw hit 호환이 깨지지 않게 처리(폐기 표기). 단 **canonical count·display·selector에서는 완전 제외**.
- L4-04(`c09_rare_account_pair`)는 손대지 말 것.

## 4. 실행 순서
1. `rg -n "l301|_l301|l3_01|L3-01|misclassified" src/ config/` 전수 출력 → 제거 목록 확정(MisclassifiedAccount 데이터 라벨은 분류해 제외).
2. §2 앵커부터 제거. import·dispatch·매핑·설정·정규화·floor 순.
3. canonical count 검증 코드/테스트를 **30**으로 갱신(`assert ... == 31` → `30`).
4. L3-01 전용 테스트 삭제(폐기 동작 테스트는 정당 obsolete). 단 **살아있는 다른 룰 테스트를 함께 지우지 말 것**(테스트 가위질 금지).

## 5. 검증 게이트 (전부 출력 첨부, 하나라도 실패면 BLOCKED 보고)
- **G1 (잔존 0)**: `rg -n "l301|_l301|l3_01|L3-01" src/ config/` = **0건**. `rg -n "misclassified" src/ config/` 잔존은 전부 DataSynth 라벨임을 증명(라벨 아닌 룰 참조 0). 실패조건: 룰 식별자 1건이라도 잔존.
- **G2 (count=30)**: canonical count 검증 테스트가 30으로 통과. 실패조건: 31 잔존 또는 count assert 실패.
- **G3 (전체 스위트)**: `uv run pytest tests/modules/test_detection/ -q -k "not composite_sort_score_v126_truth_capture_thresholds"` → **신규 실패 0** (제외한 1건은 기존 환경 MemoryError, baseline). 직전 baseline은 "1371 passed, 8 skipped". L3-01 테스트 삭제분만큼 passed 수 감소는 허용, **신규 fail/error 0**.
- **G4 (독립 toy, ripple — 2+ 케이스)**: 직접 파이프라인/IntegrityDetector를 돌려 ① business_process+gl_account가 있는 정상 DF에서 과거 L3-01이 잡던 행이 더 이상 L3-01로 플래그되지 않음(L3-01 키 부재), ② L4-04 희소쌍 탐지는 그대로 동작(회귀 없음) — 두 케이스 출력 첨부. 실패조건: L3-01 키가 결과 어딘가에 남음 / L4-04 회귀.

## 6. 보고 형식
```
STATUS: DONE
G1: rg 출력 …(붙여넣기)… → 룰 식별자 0, misclassified 잔존 N건 전부 DataSynth 라벨(증명)
G2: count 테스트 … == 30 PASS
G3: pytest … 1357 passed(예시), 신규 fail 0
G4: toy ①… ②… 출력
삭제 파일/라인 요약: …
```
