"""GraphDetector 룰 함수 — WU-22 (GR01 순환거래 / GR03 이전가격).

Why: L3-03 MVP는 `is_intercompany` 플래그만 반환(recall 7%). 실제 A→B→C→A
     N-hop 순환, 양방향 IC 엣지 가격 asymmetry는 그래프 토폴로지 없이 탐지 불가.

OOM 방어 원칙:
    - 100만+ 행 회계 장부를 naive MultiDiGraph에 적재하면 수십 분 지연 + OOM
    - Step 1: pandas 벡터화 사전 필터 (is_intercompany + min_amount)
    - Step 2: np.where로 src/dst 컬럼 생성 (iterrows/apply 금지)
    - Step 3: `nx.from_pandas_edgelist`로 C-레벨 변환 (`add_edge` 루프 금지)
    - Step 4: weakly_connected_components 분리 + max_edges 안전장치
"""

from __future__ import annotations

import logging

import networkx as nx
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_REQUIRED_COLS = ("company_code", "debit_amount", "credit_amount", "is_intercompany")


# ── 헬퍼: 사전 필터 + implicit 엣지 복구 + 벡터화 그래프 구축 ──


def _filter_edges(
    df: pd.DataFrame,
    *,
    min_amount: float,
    max_edges: int,
) -> tuple[pd.DataFrame, float, int]:
    """IC + min_amount 사전 필터. max_edges 초과 시 분위수 기반 자동 상향.

    Returns:
        (filtered_df, effective_min_amount, raised_flag)
    """
    ic_mask = df["is_intercompany"].fillna(False).astype(bool)
    amount = df[["debit_amount", "credit_amount"]].fillna(0).max(axis=1)
    mask = ic_mask & (amount >= min_amount)
    edges_df = df.loc[mask].copy()
    edges_df["_amount"] = amount.loc[mask]

    raised = 0
    effective_min = float(min_amount)
    if len(edges_df) > max_edges:
        # Why: 엣지 수를 max_edges로 압축하기 위해 상위 분위수 기반으로 min_amount 상향
        quantile = 1 - (max_edges / len(edges_df))
        new_min = float(edges_df["_amount"].quantile(quantile))
        if new_min > effective_min:
            effective_min = new_min
            edges_df = edges_df[edges_df["_amount"] >= new_min].copy()
            raised = 1
        # Why: 동일 금액 집중 시 quantile이 기존 min 이하를 반환 → 분위수 상향 효과 없음.
        #      OOM 방어를 위해 상위 max_edges행으로 강제 절단 (nlargest는 안정 정렬 보장)
        if len(edges_df) > max_edges:
            logger.warning(
                "GR01 동일 금액 집중 — 상위 %d행 강제 절단 (원본 %d행)",
                max_edges, len(edges_df),
            )
            edges_df = edges_df.nlargest(max_edges, "_amount", keep="first").copy()
            raised = 1
    return edges_df, effective_min, raised


def _recover_implicit_partner(edges_df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """trading_partner NULL → 동일 document_id 그룹의 다른 company_code로 복구.

    Why: DataSynth 643건 중 640건이 trading_partner NULL. 동일 전표의 차/대
         양측 company_code를 implicit IC pair로 추론하여 recall 개선.
    """
    if "document_id" not in edges_df.columns or "trading_partner" not in edges_df.columns:
        return edges_df, 0

    null_mask = edges_df["trading_partner"].isna()
    if not null_mask.any():
        return edges_df, 0

    # Why: document_id별 고유 company_code 리스트를 한 번에 집계 (groupby + agg)
    doc_companies = (
        edges_df.groupby("document_id")["company_code"]
        .agg(lambda s: list(pd.Series(s).dropna().astype(str).unique()))
        .rename("_doc_companies")
    )
    edges_df = edges_df.merge(
        doc_companies, left_on="document_id", right_index=True, how="left"
    )

    # Why: NULL partner 행에 한해서만 list comprehension 실행 (전체 루프 아님)
    null_mask = edges_df["trading_partner"].isna()
    targets = edges_df.loc[null_mask, ["_doc_companies", "company_code"]]

    def _pick_other(codes: object, current: object) -> str | None:
        if not isinstance(codes, list):
            return None
        others = [c for c in codes if c != str(current)]
        # Why: 3사 이상(2개 이상 다른 회사) 그룹은 partner 특정 불가 — FP 방지 위해 복구 포기
        if len(others) != 1:
            return None
        return others[0]

    recovered_partners = [
        _pick_other(codes, cur)
        for codes, cur in zip(targets["_doc_companies"], targets["company_code"])
    ]
    edges_df.loc[null_mask, "trading_partner"] = recovered_partners
    edges_df.drop(columns=["_doc_companies"], inplace=True, errors="ignore")
    recovered_count = int(sum(1 for v in recovered_partners if v is not None))
    return edges_df, recovered_count


def _build_graph(
    df: pd.DataFrame,
    *,
    min_amount: float,
    max_edges: int,
    metadata: dict,
) -> nx.MultiDiGraph | None:
    """사전 필터 → implicit 엣지 복구 → nx.from_pandas_edgelist (C-레벨)."""
    if not set(_REQUIRED_COLS).issubset(df.columns):
        metadata["gr01_skip_reason"] = "missing_required_columns"
        return None

    edges_df, eff_min, raised = _filter_edges(
        df, min_amount=min_amount, max_edges=max_edges
    )
    metadata["gr01_edges_prefiltered"] = int(len(edges_df))
    metadata["gr01_min_amount_effective"] = eff_min
    metadata["gr01_max_edges_raised"] = raised

    if edges_df.empty:
        metadata["gr01_edges_built"] = 0
        return None

    edges_df, recovered = _recover_implicit_partner(edges_df)
    metadata["gr01_implicit_edges"] = recovered

    # Why: partner 여전히 NULL인 행은 그래프에서 제외 (고립 노드 방지)
    edges_df = edges_df[edges_df["trading_partner"].notna()].copy()
    if edges_df.empty:
        metadata["gr01_edges_built"] = 0
        return None

    # Why: 방향 결정 — credit > 0은 company→partner, debit > 0은 partner→company
    is_credit = edges_df["credit_amount"].fillna(0) > 0
    company_str = edges_df["company_code"].astype(str)
    partner_str = edges_df["trading_partner"].astype(str)
    edges_df["_src"] = np.where(is_credit, company_str, partner_str)
    edges_df["_dst"] = np.where(is_credit, partner_str, company_str)
    edges_df["_row_idx"] = edges_df.index.astype(int)

    # Why: self-loop 방지 (implicit 복구 오탐 차단)
    edges_df = edges_df.loc[edges_df["_src"] != edges_df["_dst"]]
    if "document_id" not in edges_df.columns:
        edges_df["document_id"] = ""
    edges_df["document_id"] = edges_df["document_id"].fillna("")

    metadata["gr01_edges_built"] = int(len(edges_df))
    if edges_df.empty:
        return None

    # Why: from_pandas_edgelist로 C-레벨 변환 — add_edge 루프 금지 (OOM Trap 방어)
    return nx.from_pandas_edgelist(
        edges_df,
        source="_src",
        target="_dst",
        edge_attr=["_row_idx", "_amount", "document_id"],
        create_using=nx.MultiDiGraph,
    )


# ── GR01: N-hop 순환거래 ──────────────────────────────────────


def gr01_circular_transaction(
    df: pd.DataFrame,
    *,
    max_cycle_length: int = 5,
    min_amount: float = 10_000_000.0,
    max_edges: int = 50_000,
    max_component_size: int = 500,
    metadata: dict | None = None,
) -> pd.Series:
    """GR01: Johnson 알고리즘 기반 N-hop 순환 탐지.

    Why: ISA 550 §23 특수관계자 합리성. 페이퍼컴퍼니 A→B→C→A 가공매출을
         DFS/Johnson `simple_cycles(length_bound=N)`로 탐지.
    """
    scores = pd.Series(0.0, index=df.index)
    if metadata is None:
        metadata = {}

    graph = _build_graph(
        df,
        min_amount=min_amount,
        max_edges=max_edges,
        metadata=metadata,
    )
    if graph is None or graph.number_of_edges() == 0:
        metadata.setdefault("gr01_cycles_found", 0)
        return scores

    cycles_found = 0
    skipped_components = 0

    for component in nx.weakly_connected_components(graph):
        if len(component) > max_component_size:
            skipped_components += 1
            logger.warning(
                "GR01 component skip: size=%d > max=%d",
                len(component),
                max_component_size,
            )
            continue

        subgraph = graph.subgraph(component)
        try:
            for cycle in nx.simple_cycles(subgraph, length_bound=max_cycle_length):
                cycles_found += 1
                cycle_nodes = list(cycle) + [cycle[0]]
                for i in range(len(cycle_nodes) - 1):
                    u, v = cycle_nodes[i], cycle_nodes[i + 1]
                    edge_map = subgraph.get_edge_data(u, v) or {}
                    for _, edge_data in edge_map.items():
                        row_idx = edge_data.get("_row_idx")
                        if row_idx is not None and row_idx in scores.index:
                            scores.at[row_idx] = 1.0
        except Exception as exc:
            logger.warning("GR01 simple_cycles 실행 실패: %s", exc)

    metadata["gr01_cycles_found"] = cycles_found
    metadata["gr01_skipped_components"] = skipped_components
    return scores


# ── GR03: 양방향 IC 엣지 price asymmetry ──────────────────────


def gr03_transfer_pricing_graph(
    df: pd.DataFrame,
    *,
    min_path_length: int = 2,
    deviation_threshold: float = 0.20,
    metadata: dict | None = None,
) -> pd.Series:
    """GR03: IC 네트워크에서 양방향 (A↔B) 엣지의 평균가 비대칭성 탐지.

    Why: R03은 (partner, account) 그룹 |x-μ|/μ 통계 편차. GR03은 **방향성**을
         명시 사용 — A→B 평균 vs B→A 평균 차이가 threshold 초과 시 양측 flag.
         동일 관계자에서 매출/매입 가격이 비대칭이면 이전가격 조작 신호.
    """
    scores = pd.Series(0.0, index=df.index)
    if metadata is None:
        metadata = {}

    required = {"is_intercompany", "company_code", "trading_partner",
                "debit_amount", "credit_amount"}
    if not required.issubset(df.columns):
        metadata["gr03_skip_reason"] = "missing_required_columns"
        return scores

    ic_mask = df["is_intercompany"].fillna(False).astype(bool)
    if not ic_mask.any():
        return scores

    ic_df = df.loc[ic_mask].copy()
    ic_df["_amount"] = ic_df[["debit_amount", "credit_amount"]].fillna(0).max(axis=1)
    ic_df = ic_df[(ic_df["_amount"] > 0) & ic_df["trading_partner"].notna()]
    if ic_df.empty:
        return scores

    # Why: 방향성 — credit이면 (company→partner), debit이면 (partner→company)
    is_credit = ic_df["credit_amount"].fillna(0) > 0
    ic_df["_src"] = np.where(
        is_credit,
        ic_df["company_code"].astype(str),
        ic_df["trading_partner"].astype(str),
    )
    ic_df["_dst"] = np.where(
        is_credit,
        ic_df["trading_partner"].astype(str),
        ic_df["company_code"].astype(str),
    )
    ic_df = ic_df[ic_df["_src"] != ic_df["_dst"]]
    if ic_df.empty:
        return scores

    # Why: gl_account 포함 시 계정별로 세분화, 없으면 src/dst만
    group_cols = ["_src", "_dst"]
    if "gl_account" in ic_df.columns:
        ic_df["_gl"] = ic_df["gl_account"].astype(str)
        group_cols.append("_gl")

    group_mean = (
        ic_df.groupby(group_cols)["_amount"]
        .mean()
        .reset_index()
        .rename(columns={"_amount": "_mean_amount"})
    )

    # Why: 역방향(B→A) 평균을 정방향(A→B)과 동일 key로 노출하기 위해 _src/_dst 교환.
    #      inner join으로 양방향 쌍만 남김 (단방향 IC 거래는 자동 제외 → FP 방지)
    reverse = group_mean.rename(columns={
        "_src": "_dst",
        "_dst": "_src",
        "_mean_amount": "_rev_mean",
    })
    merge_keys = ["_src", "_dst"] + (["_gl"] if "_gl" in group_cols else [])
    bidirectional = group_mean.merge(reverse, on=merge_keys, how="inner")
    if bidirectional.empty:
        metadata["gr03_bidirectional_pairs"] = 0
        return scores

    metadata["gr03_bidirectional_pairs"] = int(len(bidirectional))

    # Why: deviation = |mean - rev_mean| / min(mean, rev_mean) — 대칭 비대칭성
    min_vals = bidirectional[["_mean_amount", "_rev_mean"]].min(axis=1).clip(lower=1e-10)
    bidirectional["_deviation"] = (
        (bidirectional["_mean_amount"] - bidirectional["_rev_mean"]).abs() / min_vals
    )
    flagged = bidirectional[bidirectional["_deviation"] > deviation_threshold].copy()
    metadata["gr03_flagged_pairs"] = int(len(flagged))
    if flagged.empty:
        return scores

    # Why: 원본 행 index 보존을 위해 merge 전 reset_index
    ic_df["_orig_idx"] = ic_df.index
    flagged_subset = flagged[merge_keys + ["_deviation"]]
    joined = ic_df.merge(flagged_subset, on=merge_keys, how="inner")
    if joined.empty:
        return scores

    # Why: score = min(1.0, deviation / (threshold * 3)) — R03 수식 재사용
    score_vec = (joined["_deviation"] / (deviation_threshold * 3)).clip(upper=1.0)
    for orig_idx, score in zip(joined["_orig_idx"].values, score_vec.values):
        scores.at[orig_idx] = max(scores.at[orig_idx], float(score))
    return scores
