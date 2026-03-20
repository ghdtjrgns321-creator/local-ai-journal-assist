"""EDA 프로파일링 모듈 — DataFrame 데이터 품질·분포·이상치 프로파일링.

사용법:
    from src.eda import profile_dataframe, profile_to_dict, summarize_for_dashboard

    profile = profile_dataframe(df)
    json_data = profile_to_dict(profile)
    dashboard_data = summarize_for_dashboard(profile)
"""

from src.eda.models import ColumnProfile, EDAProfile
from src.eda.profiler import profile_dataframe, profile_to_dict
from src.eda.report import summarize_for_dashboard

__all__ = [
    "ColumnProfile",
    "EDAProfile",
    "profile_dataframe",
    "profile_to_dict",
    "summarize_for_dashboard",
]
