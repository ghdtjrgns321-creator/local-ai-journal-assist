# 성능 평가 지표

## 구분

- `ground_truth`: DataSynth 라벨처럼 정답이 있는 경우의 precision / recall / F1
- `operational_proxy`: 정답이 없을 때 보는 운영 지표. whitelist, high-risk 비율, flagged 문서 수 같은 근사 지표

## 핵심 지표

- `precision`: 탐지한 문서 중 실제 이상으로 확인된 비율
- `recall`: 실제 이상 문서 중 탐지한 비율
- `f1`: precision과 recall의 조화 평균
- `high_risk_ratio`: 전체 문서 대비 `risk_level=High` 문서 비율
- `whitelist_removed_docs`: whitelist로 예외 처리된 문서 수

## 해석 주의사항

- whitelist는 사람이 `false positive`라고 본 사례의 근사치이지, precision의 정답 대체물이 아니다.
- DataSynth 라벨 기반 평가는 synthetic 규칙과 가까워 실무보다 높게 나올 수 있다.
- historical batch는 런타임 스냅샷이 불완전할 수 있어 `metric_confidence=partial`로 표시될 수 있다.
