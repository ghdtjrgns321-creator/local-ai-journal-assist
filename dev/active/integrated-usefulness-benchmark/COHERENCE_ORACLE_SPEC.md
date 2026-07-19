# 정합 오라클 spec — 2·3층 (T4)

목적: 주입한 부정 전표가 **자기 spec이 선언한 위반(semantic truth)만 깨고, 구조 정합은 전부 지키는지** 검사한다. 구조 정합이 깨지면 그것은 의도된 부정이 아니라 **생성 사고(accident)** — 재생성 대상.

핵심 원칙(DESIGN ⑦): 부정은 *substance(실질)*만 조작한다(물건 없이 매출, 비용을 자산으로). *structure(구조)*는 정상 전표와 똑같이 지킨다(차대균형·시점순서·참조 실존). 따라서 오라클 = **HARD 구조 불변식** 검사기. declared_violations(=의미 truth)는 채점(T7)이 쓰고, 오라클은 구조만 본다.

- 대상: fraud 문서(truth member_document_ids)만. base 문서 break는 base 품질 이슈로 별도 보고.
- 통과 기준: fraud 문서의 HARD 불변식 break == 0 (spec_outside_allowed=false).
- rule-blind: 불변식은 회계 구조(차대·참조·시점·잔액)로 정의. 탐지 룰ID를 근거로 쓰지 않음.

## 불변식 목록

| ID            | 층  | 검사                     | 대상 컬럼/파일                                                  | 사고 정의(break)                                                                      |
| ------------- | --- | ------------------------ | --------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| INV-BAL       | 1   | 문서 단위 차대균형       | debit_amount·credit_amount (document_id 그룹)                   | round(Σdebit−Σcredit,2) ≠ 0                                                           |
| INV-POS       | 1   | 라인 금액 유효           | debit_amount·credit_amount                                      | 음수, 또는 한 라인에서 debit·credit 동시 >0                                           |
| INV-REV       | 2   | 역분개 원전표 실존       | reversal_document_id                                            | 비어있지 않은데 journal document_id 집합에 없음                                       |
| INV-ORIG      | 2   | 원전표 참조 실존         | original_document_id                                            | 비어있지 않은데 집합에 없음                                                           |
| INV-TEMPORAL  | 3   | 시점 순서                | approval_date·document_date·settlement_date·posting_date        | approval < document, 또는 settlement < posting                                        |
| INV-CLEAR     | 3   | clearing 자기정합        | is_cleared·amount_open·settlement_status                        | is_cleared=true인데 amount_open>0, 또는 settlement_status='cleared'인데 amount_open>0 |
| INV-AR-EXISTS | 3   | 없는 AR/포지션 갚기 금지 | (clearing 전표의) 참조 invoice/aux ↔ document_flows amount_open | clearing이 참조하는 대상이 flows에 없거나 당시 amount_open≤0                          |

- **HARD(전부)**: 위 7종은 어떤 부정도 깨서는 안 된다. 부정은 substance를 조작할 뿐 구조를 지킨다.
- **INV-AR-EXISTS**가 "없는 매출채권 갚기"(DESIGN ⑦ 예시)를 막는 3층 핵심. Phase2 돌려막기·역분개 위장에서 발화 대상. Phase1(새 분개, clearing 없음)에서는 미발화 → baseline 0.

## Phase별 발화 예상
- **Phase1**(가공전표·비용자산화·계정분류): 새 분개·self-contained. INV-BAL/POS만 관여, 나머지 미발화. → 사고 0 기대(baseline).
- **Phase2**(횡령·승인·순환): reversal_document_id·is_cleared·amount_open·trading_partner 참조. INV-REV/CLEAR/AR-EXISTS/TEMPORAL 실질 발화. 상태 인지 생성(존재하는 것만 참조)이 1차 방어, 오라클이 그물.

## 비-hollow 보증
Phase1이 대부분 불변식을 미발화하므로 "baseline 0"만으로는 오라클이 작동하는지 증명 못 함(hollow 위험). 따라서 `--self-test`: 각 불변식을 깨는 인위 문서를 만들어 오라클이 FLAG하는지 + 정상 문서가 통과하는지 확인한다. self-test 실패 시 오라클 자체 결함.

## 산출물
- 구현: `tools/scripts/verify_injection_coherence.py`
- baseline 리포트: 실행 시 stdout(층별 사고 수) + exit code(0=통과).
