"""차트 공통 테마 — 색상·레이아웃·빈 데이터 Figure.

Why: 17종 차트의 시각적 일관성을 한 곳에서 관리.

Design System (shadcn/Tailwind 기반):
  Background  #FFFFFF   Surface    #F8F9FA
  Border      #E2E5E9   Primary    #2563EB
  Text        #111827   Text Muted #6B7280 / #9CA3AF
"""

from __future__ import annotations

import plotly.graph_objects as go

# ── 앱 팔레트 (styles.py CSS variables와 동일) ────────────────

COLOR_PRIMARY = "#2563EB"  # blue-600 — CTA, 강조
COLOR_TEXT = "#111827"  # gray-900 — 핵심 텍스트
COLOR_TEXT_MUTED = "#6B7280"  # gray-500 — 부가 설명
COLOR_BORDER = "#E2E5E9"  # gray-200 — 테두리, 그리드
COLOR_SURFACE = "#F8F9FA"  # gray-50 — 카드 배경
COLOR_BG = "#FFFFFF"  # 순백

# ── 위험등급 색상 (도넛 차트 전용 — semantic) ────────────────
# Why: 따뜻한 톤(red→amber) = 위험, 차가운 톤(blue→gray) = 안전.
#      채도를 낮추어 대시보드 전체 톤과 조화.
#      row 단위 risk_level 만 사용. case priority_band 와 색상이 겹치지 않도록 분리.

RISK_COLORS: dict[str, str] = {
    "High": "#E54D4D",  # Radix red-9 desaturated
    "Medium": "#E09B3D",  # Radix amber-9 desaturated
    "Low": "#68A8D6",  # Radix sky-9 desaturated
    "Normal": "#CDD5DF",  # Radix slate-6
}

# ── Case priority_band 색상·라벨 (RISK_COLORS 와 다른 축) ────────────────
# Why: row risk_level (anomaly_score 기반) 과 case priority_band (topic_score 기반)
#      은 서로 다른 축이다. 동일 색상/이모지 사용 시 운영자가 "high case = 모든 row
#      high" 로 오해한다 (artifacts/phase1_score_band_audit.md §5-4). RISK_COLORS 가
#      warm(red/amber) 톤이므로 case 축은 cool/neutral 톤(indigo/violet/slate)으로
#      분리하고, 라벨 접두사도 row(●) vs case(◆) 로 시각적으로 구분한다.

CASE_BAND_COLORS: dict[str, str] = {
    "high": "#4338CA",  # indigo-700 — 우선 검토 case
    "medium": "#7C3AED",  # violet-600 — 보조 검토 case
    "low": "#94A3B8",  # slate-400 — 모집단 case
    "none": "#E2E8F0",  # slate-200 — 신호 없는 전표
}

CASE_BAND_LABELS: dict[str, str] = {
    "high": "◆ 즉시검토",
    "medium": "◆ 검토대상",
    "low": "◆ 참고후보",
    "none": "◆ 신호 없음",
}

ROW_RISK_LABELS: dict[str, str] = {
    "High": "● 행 High",
    "Medium": "● 행 Medium",
    "Low": "● 행 Low",
    "Normal": "● 행 Normal",
}

# ── Layer 색상 (바 차트 전용 — 3색 분리) ──────────────────────
# Why: 도넛(red/amber/blue/gray)과 hue가 겹치지 않는 3색.
#      각 레이어가 한눈에 구분되도록 hue 자체를 다르게 배정.

LAYER_COLORS: dict[str, str] = {
    "layer_a": "#8B5CF6",  # violet-500 — 무결성
    "layer_b": "#0D9488",  # teal-600 — 부정
    "layer_c": "#F97316",  # orange-500 — 징후
    "benford": "#6366F1",  # indigo-500 — Benford
}

LAYER_LABELS: dict[str, str] = {
    "layer_a": "L1/L3 Data Quality",
    "layer_b": "L1-L4 Fraud Rules",
    "layer_c": "L1-L4 Anomaly Rules",
    "benford": "L4-02 Benford",
}

# ── 범용 차트 시퀀스 색상 (8색) ────────────────────────────────
# Why: 색상환 균등 배치, 인접색 명도차 확보, 색각 이상자 구분 가능.
LAYER_COLORS.update(
    {
        "layer_b": "#0D9488",
        "layer_c": "#F97316",
        "L1": "#8B5CF6",
        "L2": "#0D9488",
        "L3": "#F97316",
        "L4": "#6366F1",
        "Analytical": "#64748B",
        "Phase 2/3": "#2563EB",
    }
)

LAYER_LABELS.update(
    {
        "layer_a": "L1/L3 Data Quality",
        "layer_b": "L1-L4 Fraud Rules",
        "layer_c": "L1-L4 Anomaly Rules",
        "benford": "L4-02 Benford",
        "L1": "L1",
        "L2": "L2",
        "L3": "L3",
        "L4": "L4",
        "Analytical": "Analytical",
        "Phase 2/3": "Phase 2/3",
    }
)

SEQUENCE_COLORS: list[str] = [
    "#2563EB",
    "#7C3AED",
    "#0891B2",
    "#059669",
    "#D97706",
    "#DC2626",
    "#DB2777",
    "#4B5563",
]

# ── 기본 레이아웃 ─────────────────────────────────────────────

# Why: xaxis/yaxis/title/margin 등을 DEFAULT_LAYOUT에 넣으면
#      개별 차트의 동일 키워드와 **중복 키워드 에러** 발생.
#      이들은 _apply_theme() 헬퍼로 분리하여 fig 생성 후 적용.
DEFAULT_LAYOUT: dict = {
    "template": "plotly_white",
    "font": {
        "family": "Pretendard, Inter, -apple-system, sans-serif",
        "color": COLOR_TEXT,
        "size": 12,
    },
    "margin": {"l": 40, "r": 20, "t": 40, "b": 40},
    "hovermode": "closest",
    "paper_bgcolor": "rgba(0,0,0,0)",
    "plot_bgcolor": "rgba(0,0,0,0)",
}

# Why: 그리드선 스타일을 별도 dict로 분리 — update_layout 후 update_xaxes/yaxes로 적용.
AXIS_STYLE: dict = {
    "gridcolor": "rgba(226,229,233,0.5)",
    "zerolinecolor": COLOR_BORDER,
}


def empty_figure(message: str = "데이터가 없습니다") -> go.Figure:
    """빈 DataFrame일 때 표시할 안내 Figure."""
    fig = go.Figure()
    fig.update_layout(
        **DEFAULT_LAYOUT,
        xaxis={"visible": False},
        yaxis={"visible": False},
        annotations=[
            {
                "text": message,
                "xref": "paper",
                "yref": "paper",
                "x": 0.5,
                "y": 0.5,
                "showarrow": False,
                "font": {"size": 14, "color": COLOR_TEXT_MUTED},
            }
        ],
    )
    return fig
