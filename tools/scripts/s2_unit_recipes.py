"""S2 룰별 표적 주입 레시피 — 활성 표면 29룰.

각 레시피: (ctx) -> (rows_df, expected_document_ids). 근거는
reports/s2_unit_firing/firing_specs_{a,b,c}.json (룰 코드 파일:라인 추출본).
정본 base 무변경 — 배경 사본에 얹을 행만 만든다. 정답지는 별도 파일(빌더가 기록).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

# 주입 행 공통 상수 — 배경(FY2024, C001)과 정합
COMPANY = "C001"
FY = "2024"
STAFF = "staff"
MANUAL = "manual"


@dataclass
class RecipeContext:
    base_dir: Path
    background: pd.DataFrame
    seed: int = 20260717
    _template: dict | None = field(default=None, repr=False)
    _employees: list[dict] | None = field(default=None, repr=False)

    def template(self) -> dict:
        """배경의 수기 행 하나를 원형으로 복제 — 컬럼 전수 보존."""
        if self._template is None:
            bg = self.background
            manual = bg[bg["source"].fillna("").str.strip().str.lower().eq("manual")]
            row = (manual.iloc[0] if len(manual) else bg.iloc[0]).to_dict()
            # 주입 행에서 오해를 부를 수 있는 흔적 제거 (라벨·시맨틱·증빙·배치)
            for col in row:
                if col.startswith(("semantic_", "mutation_", "debit_account", "credit_account")):
                    row[col] = ""
            for col in (
                "scenario_id",
                "event_type",
                "detection_surface_hints",
                "batch_id",
                "job_id",
                "batch_type",
                "reference",
                "trading_partner",
                "auxiliary_account_number",
                "delivery_date",
                "supply_amount",
                "tax_amount",
                "invoice_amount",
                "tax_code",
                "tax_treatment",
                "ip_address",
                "reversal_document_id",
                "original_document_id",
                "reversal_reason",
                "reversal_reason_code",
                "approval_date",
                "line_text_family",
                "counterparty_type",
                "sod_conflict_type",
                "header_text",
            ):
                if col in row:
                    row[col] = ""
            for col in (
                "is_fraud",
                "is_anomaly",
                "sod_violation",
                "is_intercompany",
                "is_suspense_account",
                "has_attachment",
                "is_synthetic",
                "is_mutated",
            ):
                if col in row:
                    row[col] = "false"
            if "is_cleared" in row:
                row["is_cleared"] = ""
            return dict(row)
        return dict(self._template)

    def employees(self) -> list[dict]:
        if self._employees is None:
            raw = json.loads(
                (self.base_dir / "master_data" / "employees.json").read_text(encoding="utf-8")
            )
            self._employees = raw if isinstance(raw, list) else raw.get("employees", [])
        return self._employees

    def approver_with_min_limit(self) -> tuple[str, float]:
        """can_approve_je 승인자 중 최소 양수 한도 (L1-04·L2-01용)."""
        cands = [
            (e["user_id"], float(e["approval_limit"]))
            for e in self.employees()
            if e.get("can_approve_je") and float(e.get("approval_limit") or 0) > 0
        ]
        if not cands:
            raise RuntimeError("employees.json에 승인권자 없음")
        return min(cands, key=lambda t: t[1])

    def any_user(self, exclude: str = "") -> str:
        for e in self.employees():
            if e["user_id"] != exclude:
                return e["user_id"]
        raise RuntimeError("employees.json 비어 있음")


def _row(
    ctx: RecipeContext,
    doc_id: str,
    line_no: int,
    gl: str,
    debit: float,
    credit: float,
    posting: str,
    **over,
) -> dict:
    r = ctx.template()
    doc_date = over.pop("document_date", posting.split(" ")[0])
    month = int(posting[5:7])
    r.update(
        document_id=doc_id,
        document_number=f"S2-{doc_id[-8:]}",
        company_code=COMPANY,
        fiscal_year=FY,
        fiscal_period=str(month),
        posting_date=posting,
        document_date=doc_date,
        document_type=over.pop("document_type", "SA"),
        source=over.pop("source", MANUAL),
        business_process=over.pop("business_process", "R2R"),
        created_by=over.pop("created_by", "S2MAKER001"),
        user_persona=over.pop("user_persona", STAFF),
        approved_by=over.pop("approved_by", ""),
        line_number=str(line_no),
        gl_account=gl,
        debit_amount=f"{debit:.0f}" if debit else "0",
        credit_amount=f"{credit:.0f}" if credit else "0",
        line_text=over.pop("line_text", "S2 단위시험"),
    )
    r.update(over)
    return r


def _doc(ctx, doc_id, posting, lines, **over) -> list[dict]:
    """복식 문서: lines = [(gl, debit, credit), ...]."""
    return [
        _row(ctx, doc_id, i + 1, gl, d, c, posting, **dict(over))
        for i, (gl, d, c) in enumerate(lines)
    ]


# ── 레시피들 (rule_id → rows, expected doc ids) ─────────────────────────


def r_l1_01(ctx):
    rows = _doc(
        ctx, "S2-L101-1", "2024-06-12 10:00:00", [("1000", 1_000_000, 0), ("2000", 0, 999_000)]
    )  # diff 1,000원 > 1
    return pd.DataFrame(rows), ["S2-L101-1"]


def r_l1_02(ctx):
    rows = _doc(
        ctx,
        "S2-L102-1",
        "2024-06-13 10:00:00",
        [("1000", 200_000, 0), ("2000", 0, 200_000)],
        document_type="",
    )
    return pd.DataFrame(rows), ["S2-L102-1"]


def r_l1_03(ctx):
    # CoA 미등재 코드를 런타임에 고른다 — 1차 시도 '999999'는 실제 CoA 등재 계정이라 오탐 레시피였음
    coa_csv = Path(__file__).resolve().parents[2] / "config" / "chart_of_accounts.csv"
    coa = set(pd.read_csv(coa_csv, dtype=str)["gl_account"].astype(str).str.strip())
    absent = next(c for c in ("424242", "313131", "878787", "565656") if c not in coa)
    rows = _doc(
        ctx, "S2-L103-1", "2024-06-14 10:00:00", [(absent, 300_000, 0), ("1000", 0, 300_000)]
    )
    return pd.DataFrame(rows), ["S2-L103-1"]


def r_l1_04(ctx):
    uid, limit = ctx.approver_with_min_limit()
    amt = math.ceil(limit * 1.5)
    rows = _doc(
        ctx,
        "S2-L104-1",
        "2024-06-17 10:00:00",
        [("6700", amt, 0), ("2000", 0, amt)],
        approved_by=uid,
        created_by=ctx.any_user(exclude=uid),
    )
    return pd.DataFrame(rows), ["S2-L104-1"]


def r_l1_05(ctx):
    uid = ctx.any_user()
    rows = _doc(
        ctx,
        "S2-L105-1",
        "2024-06-18 10:00:00",
        [("6400", 500_000, 0), ("1000", 0, 500_000)],
        created_by=uid,
        approved_by=uid,
    )
    return pd.DataFrame(rows), ["S2-L105-1"]


def r_l1_06(ctx):
    # red pair TRE+P2P — 같은 사람이 자금·구매 양쪽 전표 생성
    a = _doc(
        ctx,
        "S2-L106-1",
        "2024-06-19 10:00:00",
        [("1000", 400_000, 0), ("1030", 0, 400_000)],
        created_by="S2TOXIC001",
        business_process="TRE",
    )
    b = _doc(
        ctx,
        "S2-L106-2",
        "2024-06-20 10:00:00",
        [("6700", 400_000, 0), ("2000", 0, 400_000)],
        created_by="S2TOXIC001",
        business_process="P2P",
    )
    return pd.DataFrame(a + b), ["S2-L106-1", "S2-L106-2"]


def r_l1_07(ctx):
    rows = _doc(
        ctx,
        "S2-L107-1",
        "2024-06-21 10:00:00",
        [("6400", 700_000, 0), ("1000", 0, 700_000)],
        approved_by="",
    )
    return pd.DataFrame(rows), ["S2-L107-1"]


def r_l1_07_02(ctx):
    rows = _doc(
        ctx,
        "S2-L10702-1",
        "2024-06-24 10:00:00",
        [("6400", 800_000, 0), ("1000", 0, 800_000)],
        approved_by="GHOST999",
    )
    return pd.DataFrame(rows), ["S2-L10702-1"]


def r_l1_08(ctx):
    rows = _doc(
        ctx, "S2-L108-1", "2024-03-11 10:00:00", [("6400", 250_000, 0), ("1000", 0, 250_000)]
    )
    for r in rows:
        r["fiscal_period"] = "4"  # 3월 전기인데 4월 귀속
    return pd.DataFrame(rows), ["S2-L108-1"]


def r_l2_01(ctx):
    uid, limit = ctx.approver_with_min_limit()
    amt = math.floor(limit * 0.95)
    rows = _doc(
        ctx,
        "S2-L201-1",
        "2024-06-25 10:00:00",
        [("6700", amt, 0), ("2000", 0, amt)],
        approved_by=uid,
        created_by=ctx.any_user(exclude=uid),
    )
    return pd.DataFrame(rows), ["S2-L201-1"]


def r_l2_02(ctx):
    common = dict(
        business_process="P2P",
        document_type="KZ",
        trading_partner="S2-VENDOR-X",
        auxiliary_account_number="S2-VENDOR-X",
        reference="S2-INV-100",
    )
    a = _doc(
        ctx,
        "S2-L202-1",
        "2024-05-10 10:00:00",
        [("2000", 1_000_000, 0), ("1000", 0, 1_000_000)],
        **common,
    )
    b = _doc(
        ctx,
        "S2-L202-2",
        "2024-05-20 10:00:00",
        [("2000", 1_000_000, 0), ("1000", 0, 1_000_000)],
        **common,
    )
    return pd.DataFrame(a + b), ["S2-L202-2"]  # 후행 문서 발화


def r_l2_03(ctx):
    # exact 키 = gl+금액+posting **타임스탬프**+side(+partner+line_text) — 시각까지 동일해야 하고
    # partner_key 빈 행은 모집단 제외(fraud_rules_groupby.py:275-281). 1차 시도는 둘 다 위반.
    kw = dict(
        line_text="S2 중복 시험",
        trading_partner="S2-DUP-VENDOR",
        auxiliary_account_number="S2-DUP-VENDOR",
    )
    a = _doc(
        ctx, "S2-L203-1", "2024-05-14 10:00:00", [("6700", 505_000, 0), ("1000", 0, 505_000)], **kw
    )
    b = _doc(
        ctx, "S2-L203-2", "2024-05-14 10:00:00", [("6700", 505_000, 0), ("1000", 0, 505_000)], **kw
    )
    return pd.DataFrame(a + b), ["S2-L203-1", "S2-L203-2"]


def r_l2_04(ctx):
    rows = _doc(
        ctx, "S2-L204-1", "2024-06-26 10:00:00", [("1550", 3_000_000, 0), ("6700", 0, 3_000_000)]
    )
    return pd.DataFrame(rows), ["S2-L204-1"]


def r_l2_05(ctx):
    a = _doc(ctx, "S2-L205-1", "2024-07-05 10:00:00", [("6400", 777_777, 0), ("2000", 0, 777_777)])
    b = _doc(ctx, "S2-L205-2", "2024-07-15 10:00:00", [("6400", 0, 777_777), ("2000", 777_777, 0)])
    return pd.DataFrame(a + b), ["S2-L205-1", "S2-L205-2"]


def r_l3_02(ctx):
    rows = _doc(
        ctx,
        "S2-L302-1",
        "2024-07-16 10:00:00",
        [("6400", 350_000, 0), ("1000", 0, 350_000)],
        source="Manual",
    )
    return pd.DataFrame(rows), ["S2-L302-1"]


def r_l3_03(ctx):
    rows = _doc(
        ctx, "S2-L303-1", "2024-07-17 10:00:00", [("1100", 900_000, 0), ("4500", 0, 900_000)]
    )  # 4500 = IC 매출 prefix
    return pd.DataFrame(rows), ["S2-L303-1"]


def r_l3_04(ctx):
    rows = _doc(
        ctx,
        "S2-L304-1",
        "2024-08-30 10:00:00",  # 월말 마진 5일 내 평일
        [("6400", 450_000, 0), ("1000", 0, 450_000)],
    )
    return pd.DataFrame(rows), ["S2-L304-1"]


def r_l3_05(ctx):
    rows = _doc(
        ctx,
        "S2-L305-1",
        "2024-08-17 10:00:00",  # 토요일, 월중
        [("6400", 320_000, 0), ("1000", 0, 320_000)],
    )
    return pd.DataFrame(rows), ["S2-L305-1"]


def r_l3_06(ctx):
    rows = _doc(
        ctx, "S2-L306-1", "2024-08-13 23:30:00", [("6400", 280_000, 0), ("1000", 0, 280_000)]
    )
    return pd.DataFrame(rows), ["S2-L306-1"]


def r_l3_07(ctx):
    rows = _doc(
        ctx,
        "S2-L307-1",
        "2024-07-19 10:00:00",
        [("6400", 260_000, 0), ("1000", 0, 260_000)],
        document_date="2024-06-04",
    )  # 45일 괴리 > 30
    return pd.DataFrame(rows), ["S2-L307-1"]


def r_l3_09(ctx):
    rows = _doc(
        ctx,
        "S2-L309-1",
        "2024-06-03 10:00:00",  # dataset_end(12/31)보다 30일+ 이전
        [("1190", 1_200_000, 0), ("1000", 0, 1_200_000)],
    )
    for r in rows:
        if r["gl_account"] == "1190":
            r["is_suspense_account"] = "true"
            r["is_cleared"] = "false"
    return pd.DataFrame(rows), ["S2-L309-1"]


def r_l3_10(ctx):
    rows = _doc(
        ctx, "S2-L310-1", "2024-07-22 10:00:00", [("6200", 600_000, 0), ("2220", 0, 600_000)]
    )  # 2220 확정코드 축
    return pd.DataFrame(rows), ["S2-L310-1"]


def r_l3_11(ctx):
    rows = _doc(
        ctx,
        "S2-L311-1",
        "2024-01-08 10:00:00",
        [("1100", 1_100_000, 0), ("4000", 0, 1_100_000)],
        delivery_date="2023-12-28",
    )  # 전년 납품 → 연도 경계
    return pd.DataFrame(rows), ["S2-L311-1"]


def r_l3_12(ctx):
    docs, rows = [], []
    for i, bp in enumerate(["P2P", "O2C", "H2R"], 1):
        did = f"S2-L312-{i}"
        docs.append(did)
        rows += _doc(
            ctx,
            did,
            f"2024-09-0{i + 1} 10:00:00",
            [("6400", 150_000, 0), ("1000", 0, 150_000)],
            created_by="S2SCOPE001",
            business_process=bp,
        )
    return pd.DataFrame(rows), docs


def r_l4_01(ctx):
    # 매출계정 로그 z>3 보장: 배경 4000 그룹 로그분포에서 exp(μ+4σ) 산출
    bg = ctx.background
    gl = bg["gl_account"].astype(str).str.strip()
    m = gl.eq("4000")
    base = pd.concat(
        [
            pd.to_numeric(bg.loc[m, "debit_amount"], errors="coerce"),
            pd.to_numeric(bg.loc[m, "credit_amount"], errors="coerce"),
        ],
        axis=1,
    ).max(axis=1)
    logv = np.log(base[base > 0])
    amt = float(np.exp(logv.mean() + 4.0 * max(logv.std(), 1.0)))
    amt = max(amt, 1e10)
    rows = _doc(ctx, "S2-L401-1", "2024-07-23 10:00:00", [("1100", amt, 0), ("4000", 0, amt)])
    return pd.DataFrame(rows), ["S2-L401-1"]


def r_l4_03(ctx):
    rows = _doc(
        ctx,
        "S2-L403-1",
        "2024-07-24 10:00:00",
        [("1540", 1_000_000_000, 0), ("2000", 0, 1_000_000_000)],
    )  # 10억
    return pd.DataFrame(rows), ["S2-L403-1"]


def r_l4_04(ctx):
    # 배경에 없는 차변→대변 쌍 탐색 (둘 다 배경 실존 계정 — L1-03 오염 방지)
    bg = ctx.background
    gl = bg["gl_account"].astype(str).str.strip()
    debit = pd.to_numeric(bg["debit_amount"], errors="coerce").fillna(0) > 0
    pairs = set()
    for _, g in bg.assign(_gl=gl, _d=debit).groupby("document_id"):
        ds, cs = g.loc[g["_d"], "_gl"], g.loc[~g["_d"], "_gl"]
        pairs.update((d, c) for d in ds for c in cs)
    accounts = sorted(gl.unique())
    chosen = None
    for d in accounts:
        for c in accounts:
            if d != c and (d, c) not in pairs:
                chosen = (d, c)
                break
        if chosen:
            break
    if not chosen:
        raise RuntimeError("미사용 계정쌍 탐색 실패")
    rows = _doc(
        ctx, "S2-L404-1", "2024-07-25 10:00:00", [(chosen[0], 850_000, 0), (chosen[1], 0, 850_000)]
    )
    return pd.DataFrame(rows), ["S2-L404-1"]


def r_l4_05(ctx):
    docs, rows = [], []
    for i in range(1, 4):  # 정확 3건 (<10 총건수 & midnight>=3)
        did = f"S2-L405-{i}"
        docs.append(did)
        rows += _doc(
            ctx,
            did,
            f"2024-09-1{i} 02:1{i}:00",
            [("6400", 90_000 + i, 0), ("1000", 0, 90_000 + i)],
            created_by="S2NIGHT001",
        )
    return pd.DataFrame(rows), docs


def r_l4_06(ctx):
    rows = _doc(
        ctx,
        "S2-L406-1",
        "2024-07-26 03:00:00",
        [("6400", 120_000, 0), ("1000", 0, 120_000)],
        source="batch",
        created_by="S2BATCH001",
    )
    for r in rows:
        r["batch_id"] = ""
        r["job_id"] = ""  # lone identity — 배치 소스인데 정체성 없음
    return pd.DataFrame(rows), ["S2-L406-1"]


RECIPES = {
    "L1-01": r_l1_01,
    "L1-02": r_l1_02,
    "L1-03": r_l1_03,
    "L1-04": r_l1_04,
    "L1-05": r_l1_05,
    "L1-06": r_l1_06,
    "L1-07": r_l1_07,
    "L1-07-02": r_l1_07_02,
    "L1-08": r_l1_08,
    "L2-01": r_l2_01,
    "L2-02": r_l2_02,
    "L2-03": r_l2_03,
    "L2-04": r_l2_04,
    "L2-05": r_l2_05,
    "L3-02": r_l3_02,
    "L3-03": r_l3_03,
    "L3-04": r_l3_04,
    "L3-05": r_l3_05,
    "L3-06": r_l3_06,
    "L3-07": r_l3_07,
    "L3-09": r_l3_09,
    "L3-10": r_l3_10,
    "L3-11": r_l3_11,
    "L3-12": r_l3_12,
    "L4-01": r_l4_01,
    "L4-03": r_l4_03,
    "L4-04": r_l4_04,
    "L4-05": r_l4_05,
    "L4-06": r_l4_06,
}
