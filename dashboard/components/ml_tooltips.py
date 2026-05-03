"""ML 지표 한글 툴팁 사전 — 감사인 친화적 설명.

Why: 감사인은 AUPRC, F2-score 등 ML 지표에 익숙하지 않다.
     각 지표 옆에 한글 설명을 표시하여 비전문가가 해석 가능하게 한다.

Usage:
    from dashboard.components.ml_tooltips import ML_TOOLTIPS
    st.metric(label="AUPRC", value="0.85", help=ML_TOOLTIPS["AUPRC"])

참고: docs/pre-plan/07-dashboard.md §604~614
"""

from __future__ import annotations

# Why: Streamlit의 st.metric/st.dataframe은 help= 파라미터로 네이티브 툴팁 제공.
#      별도 헬퍼 함수 없이 dict만 노출하여 호출부에서 직접 사용.
ML_TOOLTIPS: dict[str, str] = {
    # --- ML 성능 지표 ---
    "AUPRC": (
        "모델이 부정 전표를 얼마나 정확하게 골라내는지를 나타내는 종합 점수 "
        "(0~1, 높을수록 좋음)"
    ),
    "F2-score": (
        "부정을 놓치지 않는 능력에 가중치를 둔 정확도 "
        "(0~1, Recall을 Precision보다 2배 중시)"
    ),
    "DR@FAR=5%": "오탐 5%를 허용할 때 실제 부정을 몇 퍼센트 잡아내는지 (Detection Rate)",
    "Precision": "모델이 '이상'으로 판정한 것 중 실제 이상인 비율 (오탐 제어)",
    "Recall": "실제 이상 중 모델이 잡아낸 비율 (미탐 제어)",

    # --- 이상 점수 컬럼 ---
    "anomaly_score": "모든 탐지 레이어의 종합 이상 점수 (0~1). 룰 기반 + ML 기반 합산 결과.",
    "supervised_score": "지도학습 모델이 판정한 부정 확률 (0~1). 과거 라벨 기반 학습.",
    "unsupervised_score": "비지도학습 모델이 판정한 이상 정도 (0~1). VAE/IF 재구성 오차 기반.",
    "stacking_score": "여러 ML 모델 출력을 메타 러너가 재결합한 최종 점수 (0~1).",

    # --- 위험 등급 ---
    "risk_level": "위험 등급 기준: High(>0.7), Medium(>0.4), Low(>0.2), Normal(≤0.2)",

    # --- SHAP ---
    "shap_value": (
        "SHAP 기여도 — 해당 피처가 최종 예측 점수에 얼마나 영향을 줬는지 "
        "(+는 부정 방향, -는 정상 방향)"
    ),
    "base_value": "모델의 기본 예측값(전체 데이터 평균). SHAP Waterfall 차트의 시작점.",
}
