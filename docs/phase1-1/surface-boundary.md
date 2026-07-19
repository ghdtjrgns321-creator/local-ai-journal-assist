# PHASE1-1, PHASE1-2, PHASE2 경계

작성일: 2026-06-17

이 문서는 PHASE1-1이 PHASE1-2, PHASE2와 어떻게 다른지 정리한다. 현재 아키텍처 불변식은 3개 surface를 절대 하나의 점수나 하나의 queue로 병합하지 않는 것이다.

## 3-surface 구조

| surface | 입력/단위 | 출력 | 강점 | 금지 해석 |
|---------|-----------|------|------|-----------|
| PHASE1-1 | 전표/행 단위 GL | 명명된 deterministic rule hit, topic tier, review queue | 왜 걸렸는지 설명 가능. 감사기준/사례 기반 조합. | fraud 확정, ML score, 모집단 구조 탐지 |
| PHASE1-2 | 그래프, 관계, 시계열, 모집단 통계 | 관계/계정/월/그룹 단위 named family finding | 한 전표로 안 보이는 알려진 구조를 잡음. | 전표 단건 룰처럼 설명, PHASE1-1 band와 단순 합산 |
| PHASE2 | ML/VAE/비지도 companion | 정상 분포 밖 anomaly score와 보조 사유 | 룰로 명명하지 못한 비정형을 추가 후보로 surface | 이상치=부정, PHASE1 점수 보정기, 룰 정답 재학습 |

## PHASE1-1의 담당 범위

PHASE1-1은 "이 전표/행에서 이름 붙일 수 있는 위반 또는 이상 신호가 발화했다"를 만든다.

예:

- 승인한도 초과
- 자기승인
- 수기 전표
- 중복 지급
- 역분개
- 결산기 전표
- cutoff 불일치
- 이상 고액
- 희소 차대 계정쌍
- 비용 자산화

PHASE1-1은 이 신호들을 topic과 tier로 묶어 auditor review queue를 만든다.

## PHASE1-2의 담당 범위

PHASE1-2는 deterministic이고 설명 가능하지만 전표 한 건만 봐서는 판단할 수 없는 구조를 맡는다.

예:

- Benford/L4-02 같은 계정 또는 모집단 digit distribution
- D01/D02 같은 전기 대비 계정/월 시계열 variance
- IC01~03 관계사 대사, 금액차이, 시차차이
- GR01 circular transaction
- 직원-거래처 관계, graph/relational novelty
- L4-05처럼 사용자 행동 집중성으로 해석해야 하는 behavioral lane 후보

이들은 PHASE1-1 rule hit를 보강할 수는 있지만, PHASE1-1 전표 tier로 직접 합치지 않는다.

## PHASE2의 담당 범위

PHASE2는 비지도/ML companion surface다. PHASE1 룰이 가진 이름 붙은 기준을 다시 학습하는 것이 아니라, 금액, 사용자, 프로세스, 시점, 밀도, 분포 안에서 정상 밖 패턴을 추가 후보로 올리는 역할이다.

PHASE2가 하면 안 되는 일:

- `L1-05가 있으면 위험` 같은 룰 ID를 feature로 넣어 룰 복제기가 되는 것
- PHASE1 priority를 단일 fraud score로 보정하는 것
- VAE score를 fraud likelihood처럼 말하는 것

## 왜 병합하지 않는가

PHASE1-1, PHASE1-2, PHASE2는 출력 단위와 신뢰도가 다르다.

| 항목 | PHASE1-1 | PHASE1-2 | PHASE2 |
|------|----------|----------|--------|
| 단위 | 전표/행 | 계정, 월, 관계, 그룹 | 전표/문서 feature vector |
| 근거 | 룰명, 조합, 감사기준 | 구조/모집단 family 근거 | 학습된 정상 분포 밖 |
| 설명 | 명명된 위반/후보 | 명명된 구조 finding | 통계적 이상 |
| queue 의미 | auditor가 먼저 볼 전표 | 별도 구조/계정/관계 검토 | companion 후보 |

이 세 가지를 하나의 combined score로 더하면 "전표 단건 위반", "계정 분포 이상", "ML 이상치"가 같은 척 섞인다. 그러면 UI, export, 설명 문구에서 과잉 주장과 false precision이 생긴다.

## PHASE1-1과 PHASE1-2의 애매한 경계

일부 룰은 이름만 보면 PHASE1-1처럼 보이지만 실제 담당은 PHASE1-2다.

| 신호 | PHASE1-1에서 남는 것 | 실제 담당 |
|------|----------------------|-----------|
| 관계사 | `L3-03` 관계사 거래 맥락 booster | 실제 대사/순환/관계망은 PHASE1-2 |
| Benford | `L4-02/Benford` macro_only 중화 | PHASE1-2 모집단 통계 |
| 전기 대비 variance | `D01/D02` macro_only 중화 | PHASE1-2 시계열/macro |
| 비정상 시간 집중 | `L4-05` booster, tier 기여 거의 없음 | PHASE1-2 behavioral lane 후보 |
| 순환거래 | PHASE1-1 regular topic에서 제거 | PHASE1-2 graph |

## PHASE1-1의 출력 언어

PHASE1-1 문서, UI, export는 다음 표현을 사용한다.

| 권장 표현 | 피해야 할 표현 |
|-----------|----------------|
| review item | fraud detected |
| 검토 후보 | 부정 확정 |
| 우선순위 승격 | 위험 확률 |
| named rule hit | ML 예측 |
| tier 대표값 | 통합 부정점수 |

## PHASE3는 현재 active product path가 아니다

과거 LLM Review Narrator 또는 PHASE3 표현은 현재 active product path에서 제거됐다. LLM이 붙더라도 PHASE1-1의 role은 "근거 있는 review queue 생성"이며, LLM은 별도 설명/요약 layer일 뿐 fraud 판정 surface가 아니다.
