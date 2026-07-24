"""Tab 2: Benford 분석 — 첫째 자릿수 분포 검정 + 분리 분석.

Why: 07-dashboard.md §270-302 스펙 구현.
     사이드바 필터에 반응하도록 analyze_benford()를 실시간 재계산.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd
import streamlit as st

from config.settings import get_settings
from dashboard._state import KEY_FILTERS, FilterState
from dashboard.components.charts import benford_overlay
from dashboard.components.charts.benford_charts import (
    benford_facet,
    benford_group_summary,
)
from dashboard.components.filters import apply_filters
from src.validation.benford import BENFORD_EXPECTED, analyze_benford

if TYPE_CHECKING:
    from src.pipeline import PipelineResult

# ── 분리 기준 옵션 ──────────────────────────────────────────
# Why: 단일 법인 확정 프로젝트라 company_code 분리는 그룹이 1개뿐 → 무의미하여 제거.
#      대신 국소 조작을 좁힐 수 있는 감사 강력 축(계정과목·기표자·회계기간)을 추가.
#      계정·기표자는 카디널리티가 높지만 benford_facet이 Top6 + 기타 병합으로 처리.
_SPLIT_OPTIONS: dict[str, str] = {
    "계정과목": "gl_account",
    "기표자": "created_by",
    "회계기간(월)": "fiscal_period",
    "업무 프로세스": "business_process",
    "소스": "source",
}

# Why: 벤포드는 표본이 적으면 분포가 우연히 크게 튀어 신호로 오인된다. Nigrini 권장선인
#      300건 이상 그룹만 이탈도 순위 대상으로 삼고, 미만은 참고용 목록으로만 노출.
_BENFORD_MIN_SAMPLE = 300

# Why: 슬라이더 없이 기본으로 개별 차트에 보여줄 최대 그룹 수 (3×3 그리드).
_MAX_FACETS = 9


@st.cache_data(show_spinner=False)
def _account_name_map() -> dict[str, str]:
    """gl_account 코드 → 한글 계정명. chart_of_accounts.csv 로드 (없으면 빈 dict)."""
    path = Path(get_settings().chart_of_accounts_path)
    if not path.exists():
        return {}
    try:
        coa = pd.read_csv(path, dtype=str)
    except Exception:
        return {}
    if "gl_account" not in coa.columns or "account_name_kr" not in coa.columns:
        return {}
    return dict(
        zip(
            coa["gl_account"].astype(str).str.strip(),
            coa["account_name_kr"].astype(str).str.strip(),
            strict=False,
        )
    )


def _group_label(group_value, name_map: dict[str, str]) -> str:
    """그룹 원본값을 표시 라벨로 — 계정코드면 '2200 매출채권' 형태."""
    code = str(group_value).strip()
    name = name_map.get(code)
    return f"{code} {name}" if name else code


def render(result: PipelineResult) -> None:
    """Benford 분석 탭 렌더링 — 필터 연동 실시간 재계산."""
    if "first_digit" not in result.data.columns:
        st.info("first_digit 피처가 없어 Benford 분석을 수행할 수 없습니다.")
        return

    # Why: 메타데이터는 Batch 전체 정적 결과 → 필터 적용 후 재계산해야 UX 일관성 유지
    filters: FilterState = st.session_state.get(KEY_FILTERS, {})
    filtered_df = apply_filters(result.data, filters)
    digits = filtered_df["first_digit"].dropna()

    if len(digits) < 30:
        st.info(f"유효 표본 {len(digits)}건 — Benford 분석에 충분하지 않습니다.")
        return

    settings = get_settings()
    br, _warnings = analyze_benford(digits, settings=settings)

    # Why: "무엇을 분석했나"를 제목 아래 대상 줄로 명시 — 필터 유무로 대상 범위 표시.
    scope = "전체 원장" if len(filtered_df) == len(result.data) else "필터 적용 구간"
    st.subheader("Benford 첫째 자릿수 분석")
    st.caption(f"대상 : {scope} {len(digits):,}건")

    # ── Row 1: 전체 Benford 결과 ──────────────────────────────
    _render_overview(br, settings.benford_mad_threshold)

    # ── Row 2: 분리 분석 ──────────────────────────────────────
    _render_split_analysis(filtered_df, settings.benford_mad_threshold)


def _render_overview(br, mad_threshold: float) -> None:
    """Row 1: 오버레이 차트 + 통계 메트릭 카드."""
    # Why: BenfordResult.observed/expected dict → benford_overlay 입력용 DataFrame 변환
    digits_df = pd.DataFrame(
        {
            "digit": range(1, 10),
            "observed_freq": [br.observed.get(d, 0.0) for d in range(1, 10)],
            "expected_freq": [BENFORD_EXPECTED[d] for d in range(1, 10)],
        }
    )
    digits_df["deviation"] = (digits_df["observed_freq"] - digits_df["expected_freq"]).abs()

    col_chart, col_metrics = st.columns([2, 1])

    with col_chart:
        fig = benford_overlay(digits_df, mad_threshold=mad_threshold)
        # Why: 우측 통계 패널(.bf-panel 고정 320px)과 상·하단을 맞추고, 제목은
        #      상단 subheader와 중복되므로 차트 내부 제목을 빈 문자열로 제거한다.
        #      (title=None 은 'undefined' 로 렌더되므로 text=""로 지정.)
        #      y축 라벨이 잘리지 않도록 좌측 여백을 넉넉히 둔다.
        fig.update_layout(
            title={"text": ""},
            height=320,
            margin={"l": 55, "r": 20, "t": 15, "b": 40},
        )
        st.plotly_chart(fig, width="stretch")

    with col_metrics:
        st.markdown(_build_stat_panel(br), unsafe_allow_html=True)


# Why: MAD 판정(mad_conformity)을 감사 비전문가도 읽히는 한국어 + 색상 등급으로 변환.
#      전문 용어(MAD·카이제곱·KS)는 라벨에서 빼고 hover 툴팁으로 이관.
_CONFORMITY_DISPLAY: dict[str, tuple[str, str, str]] = {
    # key: (한국어 판정, CSS 등급, 한 줄 풀이)
    "close": ("적합", "good", "실제 금액 분포가 벤포드 이론과 잘 맞습니다."),
    "acceptable": ("수용 가능", "good", "이론과 대체로 일치합니다."),
    "marginally": ("경계", "warn", "일부 구간이 이론에서 벗어납니다 — 관찰 대상."),
    "nonconforming": ("부적합", "bad", "이론과 크게 달라 추가 검토가 필요합니다."),
}


def _build_stat_panel(br) -> str:
    """오버레이 차트 우측 통계 패널 HTML 생성.

    Why: st.metric은 'Close (적합)' 같은 긴 텍스트를 수치용 대형 폰트로 렌더해
         크기·정렬이 어색하다. 전용 패널로 판정을 헤드라인화하고 세부 지표는
         작은 행으로 정리 + 전문 용어는 hover 풀이로 이관한다.
    """
    verdict_ko, grade, note = _CONFORMITY_DISPLAY.get(
        br.mad_conformity,
        (br.mad_conformity, "warn", ""),
    )

    mad = f"{br.mad:.4f}" if br.mad is not None else "N/A"
    chi2 = f"{br.chi2_p_value:.4f}" if br.chi2_p_value is not None else "N/A"
    ks = f"{br.ks_p_value:.4f}" if br.ks_p_value is not None else "N/A"

    rows = [
        _stat_row(
            "분석 건수",
            f"{br.sample_size:,}",
            unit="건",
            hint=f"Benford 분석에 사용된 금액 개수입니다. 신뢰도: {br.confidence}",
        ),
        _stat_row(
            "이론과의 평균 차이",
            mad,
            hint="MAD(평균절대편차): 실제 첫자리 분포와 벤포드 이론 분포의 "
            "평균 차이. 0에 가까울수록 정상이며, 이 값이 판정의 기준입니다.",
        ),
        _stat_row(
            "일치도 검정",
            chi2,
            hint="카이제곱 검정 p값. 0.05보다 크면 이론과 통계적으로 일치. "
            "표본이 매우 크면 작은 차이도 불일치로 잡혀 0에 가까워지는 "
            "한계가 있어, 위의 '평균 차이'를 우선 봅니다.",
        ),
        _stat_row(
            "보조 검정",
            ks,
            hint="콜모고로프-스미르노프(KS) 검정 p값. 첫자리처럼 값이 몇 개로 "
            "떨어지는 분포에서는 정확도가 낮아 보조 지표로만 씁니다.",
        ),
    ]

    return (
        f'<div class="bf-panel">'
        f'<div class="bf-verdict bf-verdict--{grade}">'
        f'<div class="bf-verdict__label">분포 적합도</div>'
        f'<div class="bf-verdict__value">{verdict_ko}</div>'
        f'<div class="bf-verdict__note">{note}</div>'
        f"</div>"
        f'<div class="bf-stat-grid">{"".join(rows)}</div>'
        f"</div>"
    )


def _stat_row(label: str, value: str, *, unit: str = "", hint: str = "") -> str:
    """통계 패널 1행 HTML — label(+hover 풀이) / value(+단위)."""
    hint_html = (
        f'<span class="bf-stat__hint">?<span class="bf-tip">{hint}</span></span>' if hint else ""
    )
    unit_html = f'<span class="bf-unit">{unit}</span>' if unit else ""
    return (
        f'<div class="bf-stat">'
        f'<span class="bf-stat__label">{label}{hint_html}</span>'
        f'<span class="bf-stat__value">{value}{unit_html}</span>'
        f"</div>"
    )


def _render_split_analysis(filtered_df: pd.DataFrame, mad_threshold: float) -> None:
    """Row 2: 분리 분석 facet 차트 (expander 없이 바로 표시)."""
    st.divider()
    st.subheader("분리 분석")
    split_label = st.selectbox("분리 기준", list(_SPLIT_OPTIONS.keys()))
    group_col = _SPLIT_OPTIONS[split_label]

    if group_col in filtered_df.columns:
        _render_split_facets(filtered_df, group_col, split_label, mad_threshold)
    else:
        st.info(f"'{group_col}' 컬럼이 데이터에 없습니다.")


def _render_split_facets(
    filtered_df: pd.DataFrame,
    group_col: str,
    split_label: str,
    mad_threshold: float,
) -> None:
    """벤포드 이탈도(MAD) 순 facet 렌더링.

    '상위' = 건수가 아니라 벤포드에서 가장 벗어난(=우선 검토) 그룹. 표본 300건 이상만
    순위 대상이며 기본 최대 9개까지 차트로 보여준다. 나머지(미표시 순위 그룹 + 소표본
    그룹)는 기타로 뭉치지 않고 표로 노출하되, 소표본은 '표본부족'으로 따로 표시한다.
    """
    summary = benford_group_summary(
        filtered_df,
        group_col,
        min_sample=_BENFORD_MIN_SAMPLE,
    )
    if summary.empty:
        st.info("유효한 first_digit 데이터가 없습니다.")
        return

    name_map = _account_name_map() if group_col == "gl_account" else {}
    eligible = summary[summary["eligible"]]
    n_elig = len(eligible)
    charted = eligible.head(_MAX_FACETS)

    if len(charted) == 0:
        st.info(
            f"표본 {_BENFORD_MIN_SAMPLE}건 이상인 그룹이 없어 이탈도 순위를 만들 수 "
            "없습니다. 아래 목록에서 그룹별 건수를 확인하세요."
        )
    else:
        st.markdown(
            f"**{split_label}별 Benford 분포** — 표본 {_BENFORD_MIN_SAMPLE:,}건 이상 "
            f"{n_elig:,}개 그룹 중 이탈도(MAD) 상위 {len(charted)}개"
        )
        labels = {g: _group_label(g, name_map) for g in charted.index}
        fig = benford_facet(
            filtered_df,
            group_col,
            groups=charted.index.tolist(),
            mad_threshold=mad_threshold,
            group_labels=labels,
        )
        st.plotly_chart(fig, width="stretch")

    # 나머지 = 차트에 없는 모든 그룹 (미표시 순위 그룹 + 소표본 그룹). 기타 병합 없이 표로.
    rest = summary.loc[~summary.index.isin(charted.index)]
    if len(rest) > 0:
        with st.expander(f"차트에 없는 나머지 그룹 {len(rest):,}개 보기"):
            st.caption(f"표본 {_BENFORD_MIN_SAMPLE}건 미만 그룹은 '표본부족'으로 표시")
            st.dataframe(
                _build_rest_table(rest, split_label, name_map),
                width="stretch",
                height=280,
                hide_index=True,
            )


def _build_rest_table(
    rest: pd.DataFrame, split_label: str, name_map: dict[str, str]
) -> pd.DataFrame:
    """나머지 그룹 표 — 코드/한글명/건수/이탈도/표본충분 여부."""
    codes = [str(c).strip() for c in rest.index]
    data: dict[str, list] = {split_label: codes}
    if name_map:
        data["계정명"] = [name_map.get(c, "") for c in codes]
    data["건수"] = [int(n) for n in rest["count"]]
    data["이탈도(MAD)"] = [round(float(m), 4) for m in rest["mad"]]
    data["표본"] = ["충분" if n >= _BENFORD_MIN_SAMPLE else "표본부족(<300)" for n in rest["count"]]
    return pd.DataFrame(data)
