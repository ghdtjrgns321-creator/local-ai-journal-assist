# pattern_specs — 6 부정 family 생성 기전 spec

모집단 동결본([INJECTION_POPULATION.md](../INJECTION_POPULATION.md), in 227)을 6 family로 묶고, 각 family를 **어떤 기전으로 전표를 생성할지** 정의한다. rule-blind: 기전은 자금흐름·계정·증빙·시점·주체로만 기술하고 탐지 룰 발화조건을 근거로 쓰지 않는다(DESIGN ③·⑥).

각 spec 4절(DESIGN §1⑥·⑦):
- **A 기전 고정값** — 부정 정체성이 강제하는 컬럼값(5벌 동일).
- **C 현실 범위** — 자유롭되 현실 범위 내 추출(5벌 재추출).
- **D 상태 대상** — 실재 장부 객체 참조(지어내기 금지). Phase1=약함/없음, Phase2=강함.
- **spec 선언위반(=truth)** — 이 전표가 일부러 깨는 정합규칙. spec 밖 정합은 전부 지킨다.

| #   | family                | Phase           | 상태  | in행수(multi-label) | 파일                                                               |
| --- | --------------------- | --------------- | ----- | ------------------- | ------------------------------------------------------------------ |
| 1   | 가공전표/수익통계     | 1               | 경    | 181                 | [01-fabricated-revenue.md](01-fabricated-revenue.md)               |
| 2   | 비용자산화            | 1               | 경    | 18                  | [02-expense-capitalization.md](02-expense-capitalization.md)       |
| 3   | 계정분류 misbooking   | 1               | 경~중 | 23                  | [03-account-misclassification.md](03-account-misclassification.md) |
| 4   | 횡령은폐/중복자금유출 | 2               | 중    | 88                  | [04-embezzlement-concealment.md](04-embezzlement-concealment.md)   |
| 5   | 승인SoD               | 2               | 중    | 24                  | [05-approval-sod.md](05-approval-sod.md)                           |
| 6   | 순환거래              | PHASE1-2 family | 중    | 13                  | [06-circular-transaction.md](06-circular-transaction.md)           |

> multi-label: 한 case가 여러 family에 속함(예 2018-2019-16 = 횡령+순환). 합 ≠ 227. family 미배정 in행 0(대조표 패턴족열 검증).

사람용 평이체 해설은 [docs/phase1-2realism/02-six-mechanisms.md](../../../docs/phase1-2realism/02-six-mechanisms.md).
