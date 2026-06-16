# Local Evidence Brief Spec

> 작성일: 2026-05-26  
> 상태: Implemented, hidden from active result UI

## 목적

Local Evidence Brief는 PHASE1 case drilldown에서 이미 산출된 룰/문서/family 신호를 짧게 정리하는 deterministic 표시 컴포넌트다. 외부 API를 호출하지 않으며, 감사인의 검토 편의를 위한 요약만 제공한다. 2026-05-26 현재 active dashboard 결과 화면에서는 표시하지 않는다.

## 입력

- `drilldown["case"]`
- `drilldown["raw_rule_hits"]`
- `drilldown["documents"]`
- 선택: `drilldown["family_contributions"]`

## 출력

- 핵심 근거 3~5개
- 확인 절차 3~5개
- 한계 1~2개

## 원칙

- 새 판단을 생성하지 않는다.
- priority score, rank, PHASE2 family score를 재계산하지 않는다.
- 확정적 fraud/violation 표현을 쓰지 않는다.
- raw line text 전문을 별도로 요약하지 않는다.
- PHASE1/PHASE2 detection과 scoring은 변경하지 않는다.

## UI 문구

현재 active dashboard 결과 화면에서는 아래 문구를 렌더링하지 않는다.

- 제목: “로컬 근거 요약”
- 설명: “이미 산출된 룰/패밀리 신호를 요약합니다. 외부 API 호출 없음.”
- 제한: “확정 판단이 아니라 검토 편의를 위한 요약입니다.”
