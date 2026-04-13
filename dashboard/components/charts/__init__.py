"""Plotly 차트 래퍼 17종 — DataFrame → go.Figure 변환.

호출: from dashboard.components.charts import risk_heatmap
"""

from dashboard.components.charts.benford_charts import benford_facet, benford_overlay
from dashboard.components.charts.eda_charts import (
    amount_box_plot,
    missing_rate_bar,
    numeric_box_plots,
    outlier_ratio_bar,
    quality_gauge,
)
from dashboard.components.charts.distribution_charts import (
    company_comparison,
    persona_risk_matrix,
    process_distribution_bar,
)
from dashboard.components.charts.risk_charts import (
    anomaly_scatter,
    risk_donut,
    risk_heatmap,
)
from dashboard.components.charts.rule_charts import rule_violation_bar
from dashboard.components.charts.special_charts import (
    fraud_type_treemap,
    layer_score_radar,
)
from dashboard.components.charts.comparison_charts import (
    new_accounts_table,
    risk_distribution_comparison,
    rule_violation_delta,
    yoy_amount_bar,
    yoy_count_bar,
)
from dashboard.components.charts.trend_charts import hourly_heatmap, monthly_trend

__all__ = [
    "amount_box_plot",
    "anomaly_scatter",
    "benford_facet",
    "benford_overlay",
    "company_comparison",
    "fraud_type_treemap",
    "hourly_heatmap",
    "layer_score_radar",
    "missing_rate_bar",
    "monthly_trend",
    "numeric_box_plots",
    "outlier_ratio_bar",
    "persona_risk_matrix",
    "process_distribution_bar",
    "quality_gauge",
    "risk_donut",
    "risk_heatmap",
    "rule_violation_bar",
    # comparison (RC-4-7)
    "new_accounts_table",
    "risk_distribution_comparison",
    "rule_violation_delta",
    "yoy_amount_bar",
    "yoy_count_bar",
]
