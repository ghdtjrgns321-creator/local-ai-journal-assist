# FT-Transformer Ablation Study

- 8-model OOF F1-macro: **0.8120**
- 7-model OOF F1-macro (FT-T 제거): **0.8080**
- Δ F1 (절대): +0.0040
- Δ F1 (상대, %): +0.49%
- 샘플 수: 50,000
- 양성 수: 1,200

## 결론

**판정 보류** — F1 변화가 노이즈 범위 내 (|Δ| < 0.5%). 추가 seed 반복 실험이 필요하다.