# PHASE1-1 대규모 수정 최신 메모

작성일: 2026-06-17

이 문서는 PHASE1-1의 2026-06 대규모 수정에서 무엇이 최신 상태로 남았고, 무엇이 legacy가 되었는지 정리한다.

## 변경 전 문제

기존 문서와 코드에는 네 가지가 섞여 있었다.

1. 전표 단위 deterministic rule과 계정/월/관계망 단위 macro/family finding이 한 PHASE1 점수 안에 섞임.
2. weighted score 계수와 floor 숫자가 감사 근거 없이 band를 설명하는 것처럼 보임.
3. `intercompany_cycle` 같은 구조 탐지가 PHASE1-1 topic처럼 보임.
4. DataSynth 라벨과 운영 review queue 언어가 섞여 fraud 확정처럼 읽힐 위험이 있음.

## 최신 결정

| 결정                    | 최신 상태                                                                                                                                      |
| ----------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| 3-surface 분리          | PHASE1-1, PHASE1-2, PHASE2를 독립 surface로 유지한다.                                                                                          |
| 6-topic PHASE1-1        | `intercompany_cycle`을 regular PHASE1-1 topic에서 제거하고 6개 topic으로 정리했다.                                                             |
| weighted score 폐기     | band 결정은 weighted sum이 아니라 tier trigger가 한다.                                                                                         |
| priority_score 호환값화 | `priority_score`는 tier 대표값이다. 위험 확률이 아니다.                                                                                        |
| macro 중화              | L4-02/Benford, D01, D02는 `macro_only`로 PHASE1-1 점수/tier 기여 0이다.                                                                        |
| HIGH 근거 재정렬        | "HIGH 조합 5개" 프레이밍을 폐기하고 HIGH 10, MEDIUM 3, LOW scheme 기준으로 재분류한다. 코드 미구현 HIGH 자격 scheme은 LOW가 아니라 탐지갭이다. |

## 최신 구현에 반영된 주요 combo 변경

`src/detection/topic_scoring.py` 기준으로 다음 변경이 반영되어 있다.

| 변경                                  | 상태                                                                                                                                                                                                                                                            |
| ------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 가공전표 2차정황 A안 확장             | 반영. `L4-04`, `L2-03`, `L3-03`, `L3-10`, `L1-05`, `L3-11`을 인정한다.                                                                                                                                                                                          |
| 가공전표 과탐 다리 제거               | 반영. `L3-04`, `L1-09`는 정상 결산 과발화 때문에 2차정황에서 제외됐다.                                                                                                                                                                                          |
| 결산조작 HIGH의 단순 고액 게이트 제거 | 반영. timing seed와 weak description/sensitive account 중심으로 발화한다.                                                                                                                                                                                       |
| 횡령은폐 HIGH의 승인필수 완화         | 반영. outflow + approval bypass뿐 아니라 `L2-05 + L3-02` 역분개/수기 은폐 분기도 허용한다.                                                                                                                                                                      |
| 횡령은폐 HIGH의 단순 고액 게이트 제거 | 반영. 고액은 중요성/정렬 렌즈로 남고 필수 게이트에서 빠졌다.                                                                                                                                                                                                    |
| 관계사 역분개 HIGH                    | 반영. `L2-05 + L3-03 + L3-04`가 `related_party_reversal_high`로 발화한다.                                                                                                                                                                                       |
| 비용자산화 HIGH                       | 반영. `L2-04 + L3-02 + L3-04`가 `expense_capitalization_high`로 발화한다.                                                                                                                                                                                       |
| 승인우회 HIGH의 단순 고액 게이트 제거 | 반영. cutoff, 기말+수기, 심야+수기 같은 행위/시점 맥락을 사용한다.                                                                                                                                                                                              |
| HIGH-6/8/10 복권                      | 가공거래처·재고 과대평가 조작형·topside/연결조정은 HIGH 자격으로 복권(등급 유지). 단 셋 다 **GL-only 범위 외**(거래처 마스터·재고 보조원장·연결 산출물 비보유)로 PHASE1-1 primary 룰 신설 안 함([CONSTRAINTS.md](../spec/CONSTRAINTS.md) §HIGH-6/8/10 범위 외). |
| KPI baseline                          | 고액 제거 후 정상 데이터 기준 HIGH 1.905%로 HARD ≤2%를 통과했지만, period_end가 대부분이라 L3-10 임계 조정 후 재측정 대상이다.                                                                                                                                  |

## 여전히 legacy로 남은 것

| legacy 요소                                    | 왜 남아 있나                                                                        | 문서화 기준                                   |
| ---------------------------------------------- | ----------------------------------------------------------------------------------- | --------------------------------------------- |
| `_priority_score()` weighted 함수              | export, PHASE2 linker, macro context, 과거 artifact 호환 경로가 아직 일부 의존한다. | 최종 band 결정 근거로 설명하지 않는다.        |
| `priority_band` threshold config               | 기존 UI/export threshold 호환 때문이다.                                             | tier 대표값을 해석하는 호환 layer로 설명한다. |
| `L4-02`, `Benford`, `D01`, `D02` registry 항목 | 삭제하면 unknown rule fallback으로 primary 점수가 붙을 수 있다.                     | macro_only 중화 항목으로 설명한다.            |
| archive 문서의 weighted score                  | 변경 이력 확인용이다.                                                               | 현재 기준으로 인용하지 않는다.                |

## 최신 탐지갭과 backlog

아래는 최신 `HIGH_COMBO_GROUNDING.md` 기준의 탐지갭이다. 핵심 원칙은 "코드가 못 잡는다는 이유로 LOW로 강등하지 않는다"이다.

| gap                                 | 최신 tier 자격    | 현재 상태                                                      | 다음 방향                                                                                                                     |
| ----------------------------------- | ----------------- | -------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| 가공거래처                          | HIGH              | GL-only — 거래처 마스터 비보유. PHASE1-1 primary 룰 신설 안 함 | **범위 외**([CONSTRAINTS.md](../spec/CONSTRAINTS.md)). PHASE1-2가 원장 첫 등장·희소 약근사로 일부 surface(HIGH-6 커버 비주장) |
| 재고 과대평가 조작형                | HIGH              | GL-only — 재고 보조원장(수량·단가·NRV) 비보유                  | **범위 외**([CONSTRAINTS.md](../spec/CONSTRAINTS.md) §재고). 등급 HIGH 유지                                                   |
| topside/연결조정                    | HIGH 자격         | GL-only — 연결 산출물(eliminations) PHASE1 입력 밖             | **범위 외**([CONSTRAINTS.md](../spec/CONSTRAINTS.md) §연결조정). 등급 HIGH 유지                                               |
| split-invoice                       | MEDIUM            | L2-01 한도직하와 다른 거래레벨 행동탐지. 전용 룰 없음          | 송장 단위 분할청구 룰 필요                                                                                                    |
| 휴면계정 활성화                     | LOW               | 전용 룰 없음                                                   | 계정 activity history 기반 룰은 가능하나 HIGH/MEDIUM으로 과장하지 않는다.                                                     |
| 단순 추정 누락/추정형 재고 평가손실 | LOW               | 전표 직접조작 신호가 약함                                      | 조작형과 구분해 LOW scheme으로 유지                                                                                           |
| L4-05                               | CONTEXT/이관 후보 | tier 기여가 거의 없고 행동 집중성 성격                         | 제거 또는 PHASE1-2 behavioral lane 이관 후보                                                                                  |
| L1-09                               | MEDIUM 일부 재료  | 근거와 과발화 이슈가 있음                                      | combo 역할 축소/재검토 후보                                                                                                   |

## 최신 문서에서 쓰는 상태 구분

| 상태          | 의미                                                         |
| ------------- | ------------------------------------------------------------ |
| 구현됨        | 현재 코드에 반영되어 발화한다.                               |
| 중화됨        | registry에는 있으나 PHASE1-1 점수/tier를 올리지 않는다.      |
| PHASE1-2 이관 | PHASE1-1 전표 룰이 아니라 family/macro surface가 담당한다.   |
| backlog       | 아직 코드에 없거나 데이터 단위 확인이 필요한 향후 작업이다.  |
| legacy        | 과거 방식 설명에는 필요하지만 현재 기준으로 사용하지 않는다. |

## 검증과 테스트 관점

PHASE1-1 tier 변경을 검증할 때는 다음을 확인한다.

- HIGH/MEDIUM trigger가 `compute_topic_tiers()`에서 기대한 `fired_triggers`로 남는가.
- booster, combo_only, macro_only만 있는 case가 standalone HIGH/MEDIUM/LOW가 되지 않는가.
- `priority_score`가 tier 대표값으로 덮이고 UI band가 stale artifact band를 따르지 않는가.
- L4-02/Benford/D01/D02가 PHASE1-1 row/case priority를 올리지 않는가.
- 정상 결산 데이터에서 `L3-04`, `L1-09`가 가공전표 HIGH 2차정황으로 과발화하지 않는가.
- 고액 제거 후 period_end HIGH가 정상 데이터에서 과도하게 남는지, L3-10 임계 조정 후 재측정했는가.
- PHASE1-1이 못 잡는 HIGH 자격 scheme을 LOW로 강등하지 않고 탐지갭으로 보고하는가.
- PHASE1-2/PHASE2 결과가 PHASE1-1 단일 combined score로 병합되지 않는가.

## 현재 문서 묶음의 기준일

이 폴더는 2026-06-17 현재 checkout의 코드와 active 문서를 기준으로 한다. 이후 combo 구현, 신규 룰, PHASE1-2 surface 분리 UI가 바뀌면 이 폴더를 먼저 갱신한다.
