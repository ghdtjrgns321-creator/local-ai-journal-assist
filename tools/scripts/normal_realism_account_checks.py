"""NORMAL realism gate — 계정 체계 검사 ACC01~ACC07.

왜 이 검사가 생겼나
    기존 게이트의 `C06_ACCOUNT_PAIR_REUSE`는 "계정쌍을 재사용하라"는 **결과**만 봤고
    **방법**을 보지 않았다. 그래서 생성기가 계정을 무작위로 흩뿌린 뒤
    `normalize_v53_account_pair_determination`이 최빈 계정으로 강제 치환하는 방식으로
    통과했다. 치환은 gl_account만 갈아끼우고 line_text는 두었기 때문에 임차료 계정에
    급여 적요가 5,145건 남았다. 게이트가 fitting을 유발한 것이다.

    ACC02는 그 우회를 막는다. 원장의 (scenario, side, subtype) -> gl_account 가
    생성기의 계정결정 표와 일치해야 하므로, 사후에 gl_account만 재작성하면 반드시 깨진다.
    ACC01/ACC05/ACC07은 표와 무관한 도메인 근거로 독립 검증한다 — 표 자체가 틀려도 잡히게.

임계 근거
    전부 "위반 0"이다. 회계 도메인상 예외가 성립하지 않는 항목만 골랐다.
    ACC03만 비율 임계이며, 근거는 순수 je_generator 스파이크에서 0% 달성이 확인된 것이다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

# 생성기가 실제로 쓰는 표. 게이트가 별도 사본을 들면 둘이 어긋나므로 원본을 읽는다.
ACCOUNT_DETERMINATION_YAML = (
    Path(__file__).resolve().parents[2]
    / "tools"
    / "datasynth"
    / "crates"
    / "datasynth-generators"
    / "config"
    / "account_determination.yaml"
)

# `Cash 4`, `Deferred Revenue 6` 처럼 끝에 일련번호가 붙은 자동생성 계정명.
AUTO_NAME = re.compile(r"\s\d+$")

# 계정명이 스스로 세금계정임을 밝히는 토큰. sub_type이 놓치는 계정(1160 Input VAT는
# sub_type=other_receivables)을 이름으로 건진다.
TAX_NAME = re.compile(r"\b(vat|tax)\b|부가세|세액|예수금|대급금", re.IGNORECASE)


def _canon(series: pd.Series) -> pd.Series:
    """CSV 라운드트립으로 `1190.0`이 된 계정코드를 되돌린다."""
    return series.astype(str).str.replace(r"\.0$", "", regex=True).str.strip()


def load_coa(dataset: Path) -> dict[str, dict[str, Any]]:
    path = dataset / "chart_of_accounts.json"
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    accounts = raw["accounts"] if isinstance(raw, dict) and "accounts" in raw else raw
    return {str(a.get("account_number")).strip(): a for a in accounts}


def load_determination_table() -> dict[str, Any]:
    if not ACCOUNT_DETERMINATION_YAML.exists():
        return {}
    return yaml.safe_load(ACCOUNT_DETERMINATION_YAML.read_text(encoding="utf-8")) or {}


def _resolve(table: dict[str, Any], scenario: str, is_debit: bool, subtype: str) -> str | None:
    side = "debit" if is_debit else "credit"
    for ov in table.get("overrides") or []:
        if (
            ov.get("scenario") == scenario
            and ov.get("side") == side
            and ov.get("subtype") == subtype
        ):
            return str(ov.get("account"))
    hit = (table.get("default") or {}).get(subtype)
    return str(hit) if hit is not None else None


def acc01_tax_lines_use_tax_accounts(
    df: pd.DataFrame,
    coa: dict[str, dict[str, Any]],
    vat_rate: float = 0.10,
    rate_band: float = 0.01,
    noise_budget: float = 0.005,
) -> tuple[str, dict[str, Any]]:
    """전표 단위 부가세 검증 (2026-07-17 재설계 — reports/unit2_rescope/acc01_design_review.md).

    구 검사(행 단위: 세액 붙은 행은 무조건 세금계정)는 실무 ERP 관행 — 세액은 그 세액을
    발생시킨 거래 줄의 속성이고 부가세 계정 줄은 파생 줄 — 을 위반으로 잡았다.
    r6 64,714건 오탐 + 세금 모듈이 꺼진 데이터만 통과하는 역전(설계 검토 반증 4건).

    재설계 두 축:
      (a) 전표 단위 부가세 미계상 — 세액이 붙은 전표에는 부가세 계정 줄이 최소 1개.
      (b) 세율 정합 — **문서 단위**: 부가세 계정 줄의 세액 합 / 공급가액(헤더)이 법정 세율
          대역 [vat_rate−rate_band, vat_rate+rate_band] 안. 면세·영세율(tax 0/NaN) 비대상.
          r6의 4.12% 같은 세액 계산 붕괴를 잡는 축 — 구 검사는 위치만 보고 금액을 안 봤다.
          라인 단위 비교는 오설계: 세액은 거래 줄과 부가세 줄 양쪽에 붙고(문서 합계 = 2×세율),
          과세 줄이 여러 개인 문서는 줄별 세액이 그 줄의 베이스 기준이라 헤더 공급가액과
          단위가 어긋난다 (s10 실측: 라인식은 정상 데이터의 26%를 오탐).
    합격: (a) 위반 전표 0 그리고 (b) 대역 밖 문서 비율 <= noise_budget(자연 노이즈 예산).
    """
    if "tax_amount" not in df.columns:
        return "BLOCKED", {"reason": "tax_amount column absent"}
    tax_amt = pd.to_numeric(df["tax_amount"], errors="coerce").fillna(0)
    has_tax = tax_amt > 0
    if not has_tax.any():
        return "BLOCKED", {"reason": "no rows carry a positive tax_amount"}
    # 세금계정 판별은 표와 무관하게 CoA 자체 증거로만 한다 — 표가 틀려도 이 검사는 잡아야 한다.
    # sub_type만 보면 안 된다: 1160 Input VAT는 sub_type이 other_receivables라 놓친다.
    tax_accounts = {
        c
        for c, a in coa.items()
        if "tax" in str(a.get("sub_type", "")).lower()
        or TAX_NAME.search(f"{a.get('short_description', '')} {a.get('long_description', '')}")
    }
    gl = _canon(df["gl_account"])
    doc = df["document_id"].astype(str)

    # (a) 세액 있는 전표에 부가세 계정 줄 존재 여부 — 전표 단위.
    docs_with_tax = set(doc[has_tax])
    docs_with_tax_account = set(doc[gl.isin(tax_accounts)])
    missing_docs = docs_with_tax - docs_with_tax_account

    # (b) 문서 단위 세율 정합 — 부가세 계정 줄 세액 합 / 공급가액(헤더 값, 문서 내 동일).
    #     부가세 줄이 없는 문서는 (a)에서 이미 위반이므로 (b) 분모에서 제외(이중 계상 방지).
    if "supply_amount" in df.columns:
        supply = pd.to_numeric(df["supply_amount"], errors="coerce").fillna(0)
        vat_line = gl.isin(tax_accounts) & has_tax
        vat_sum = tax_amt[vat_line].groupby(doc[vat_line]).sum()
        doc_supply = supply[has_tax & (supply > 0)].groupby(doc[has_tax & (supply > 0)]).first()
        both = vat_sum.index.intersection(doc_supply.index)
        ratio = vat_sum.loc[both] / doc_supply.loc[both]
        off_band = (ratio < vat_rate - rate_band) | (ratio > vat_rate + rate_band)
        off_count = int(off_band.sum())
        checked_docs = int(len(both))
        off_share = off_count / checked_docs if checked_docs else 0.0
        ratio_median = float(ratio.median()) if checked_docs else None
    else:
        off_count, checked_docs, off_share, ratio_median = 0, 0, 0.0, None

    metric = {
        "docs_with_tax": len(docs_with_tax),
        "docs_missing_tax_account_line": len(missing_docs),
        "rate_checked_docs": checked_docs,
        "rate_off_band_docs": off_count,
        "rate_off_band_share": round(off_share, 6),
        "rate_median": ratio_median,
        "vat_rate_band": [vat_rate - rate_band, vat_rate + rate_band],
        "noise_budget": noise_budget,
        "tax_accounts_in_coa": len(tax_accounts),
    }
    ok = len(missing_docs) == 0 and off_share <= noise_budget
    return ("PASS" if ok else "FAIL"), metric


def acc02_account_determination_compliance(
    df: pd.DataFrame, table: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    """원장 계정이 생성기의 계정결정 표와 일치해야 한다.

    사후에 gl_account만 재작성하면 반드시 깨진다 — fitting 우회 차단용.
    """
    need = {"semantic_scenario_id", "semantic_account_subtype", "gl_account", "debit_amount"}
    missing = need - set(df.columns)
    if missing:
        return "BLOCKED", {"reason": f"columns absent: {sorted(missing)}"}
    if not table:
        return "BLOCKED", {"reason": f"table not found at {ACCOUNT_DETERMINATION_YAML}"}

    debit = pd.to_numeric(df["debit_amount"], errors="coerce").fillna(0) > 0
    gl = _canon(df["gl_account"])
    scenario = df["semantic_scenario_id"].astype(str)
    subtype = df["semantic_account_subtype"].astype(str)

    expected = [
        _resolve(table, s, d, st) for s, d, st in zip(scenario, debit, subtype, strict=True)
    ]
    expected_ser = pd.Series(expected, index=df.index, dtype="object")
    covered = expected_ser.notna()
    mismatched = covered & (expected_ser != gl)

    violations = int(mismatched.sum())
    sample = (
        df.loc[mismatched, ["semantic_scenario_id", "semantic_account_subtype"]]
        .assign(actual=gl[mismatched], expected=expected_ser[mismatched])
        .value_counts()
        .head(5)
    )
    metric = {
        "violations": violations,
        "denominator": int(covered.sum()),
        "uncovered_rows": int((~covered).sum()),
        "top_mismatches": {" | ".join(map(str, k)): int(v) for k, v in sample.items()},
    }
    return ("PASS" if violations == 0 else "FAIL"), metric


def acc03_semantic_subtype_assigned(df: pd.DataFrame) -> tuple[str, dict[str, Any]]:
    """subtype이 `standard_account`(의미 미부여)로 남은 비율.

    임계 1% 근거: 순수 je_generator 스파이크에서 0% 달성 확인 (2026-07-15, 44,050행).
    """
    if "semantic_account_subtype" not in df.columns:
        return "BLOCKED", {"reason": "semantic_account_subtype column absent"}
    st = df["semantic_account_subtype"].astype(str)
    n = int((st == "standard_account").sum())
    ratio = n / len(df) if len(df) else 0.0
    metric = {
        "standard_account_rows": n,
        "denominator": len(df),
        "ratio": round(ratio, 6),
        "threshold": 0.01,
    }
    return ("PASS" if ratio <= 0.01 else "FAIL"), metric


def acc04_suspense_flag_agrees_with_coa(
    df: pd.DataFrame, coa: dict[str, dict[str, Any]]
) -> tuple[str, dict[str, Any]]:
    """원장의 is_suspense_account 컬럼이 CoA 플래그와 일치해야 한다."""
    if "is_suspense_account" not in df.columns:
        return "BLOCKED", {"reason": "is_suspense_account column absent"}
    gl = _canon(df["gl_account"])
    coa_flag = gl.map(lambda c: bool(coa.get(c, {}).get("is_suspense_account", False)))
    ledger_flag = df["is_suspense_account"].astype(str).str.lower().isin(["true", "1"])
    violations = int((coa_flag != ledger_flag).sum())
    metric = {
        "violations": violations,
        "denominator": len(df),
        "disagreeing_accounts": gl[coa_flag != ledger_flag].value_counts().head(5).to_dict(),
    }
    return ("PASS" if violations == 0 else "FAIL"), metric


def acc05_no_autogenerated_account_names(
    df: pd.DataFrame, coa: dict[str, dict[str, Any]]
) -> tuple[str, dict[str, Any]]:
    """원장이 `Cash 4` 같은 자동생성 이름 계정에 기표하면 안 된다.

    실제 ERP 계정과목표에 일련번호 이름은 존재하지 않는다. CoA 패딩 계정에 기표됐다는 뜻.
    """
    gl = _canon(df["gl_account"])
    auto = {c for c, a in coa.items() if AUTO_NAME.search(str(a.get("short_description", "")))}
    hit = gl.isin(auto)
    violations = int(hit.sum())
    metric = {
        "violations": violations,
        "denominator": len(df),
        "distinct_auto_accounts_posted": int(gl[hit].nunique()),
        "sample": {c: str(coa[c].get("short_description")) for c in list(gl[hit].unique())[:5]},
    }
    return ("PASS" if violations == 0 else "FAIL"), metric


def acc06_ledger_accounts_defined_in_coa(
    df: pd.DataFrame, coa: dict[str, dict[str, Any]]
) -> tuple[str, dict[str, Any]]:
    """원장이 쓰는 계정은 전부 CoA에 정의돼 있어야 한다 (참조 무결성)."""
    if not coa:
        return "BLOCKED", {"reason": "chart_of_accounts.json absent"}
    gl = _canon(df["gl_account"])
    undefined = sorted(set(gl.unique()) - set(coa))
    violations = int(gl.isin(undefined).sum())
    metric = {
        "undefined_accounts": undefined[:10],
        "undefined_account_count": len(undefined),
        "violating_rows": violations,
        "denominator": len(df),
        "accounts_used": int(gl.nunique()),
    }
    return ("PASS" if not undefined else "FAIL"), metric


def acc08_subtype_vocabulary_is_real(
    df: pd.DataFrame, table: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    """semantic_account_subtype은 계정결정 표가 아는 어휘여야 한다.

    ACC02는 표에 없는 subtype을 '미커버'로 건너뛴다. 그래서 생성기가 표에 없는 라벨을
    지어내면 ACC02의 사각지대로 숨는다. 실제로 `semantic_subtype_for_account_code`가
    계정코드 앞 2자리로 `OPERATING_EXPENSE`·`COGS`·`REVENUE` 같은 라벨을 지어냈고,
    그 20행이 ACC02를 그냥 통과했다. 이 검사가 그 구멍을 막는다.
    """
    if "semantic_account_subtype" not in df.columns:
        return "BLOCKED", {"reason": "semantic_account_subtype column absent"}
    if not table:
        return "BLOCKED", {"reason": f"table not found at {ACCOUNT_DETERMINATION_YAML}"}
    known = set(table.get("default") or {})
    st = df["semantic_account_subtype"].astype(str)
    unknown = st[~st.isin(known)]
    metric = {
        "violations": int(len(unknown)),
        "denominator": len(df),
        "known_subtypes": len(known),
        "unknown_labels": unknown.value_counts().head(8).to_dict(),
    }
    return ("PASS" if unknown.empty else "FAIL"), metric


def acc09_payroll_text_sits_on_payroll_accounts(
    df: pd.DataFrame, table: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    """급여 적요는 급여 계정에만 붙어야 한다 (비용 계정 한정).

    이 사건의 발단이 정확히 이것이다 — r6에서 `6300 임차료`에 급여 family 5,145건,
    `500300 매출원가`에 9,588건. 계정만 최빈값으로 갈아끼우고 적요를 두면 이렇게 된다.
    카탈로그 §목적이 요구하는 regression gate로 박는다.

    비용 계정(5·6·7류)에만 적용한다. 급여 지급 전표의 현금·미지급급여 라인이 급여 적요를
    갖는 것은 정상이므로 대차 상대 계정은 대상이 아니다.

    ACC02(계정↔subtype)와 축이 다르다. 반복전표 템플릿 버그처럼 적요가 계정과 따로
    교체되는 경로는 ACC02가 못 잡는다.
    """
    if "line_text_family" not in df.columns:
        return "BLOCKED", {"reason": "line_text_family column absent"}
    if not table:
        return "BLOCKED", {"reason": f"table not found at {ACCOUNT_DETERMINATION_YAML}"}

    default = table.get("default") or {}
    # 급여 성격 family가 앉아도 되는 비용 계정 = 표가 급여 비용으로 지목한 계정.
    payroll_accounts = {
        str(default[k]) for k in ("OPEX_PAYROLL", "COGS_DIRECT_LABOR") if k in default
    }
    if not payroll_accounts:
        return "BLOCKED", {"reason": "table has no payroll expense account"}

    gl = _canon(df["gl_account"])
    fam = df["line_text_family"].astype(str)
    is_expense = gl.str.match(r"^[567]").fillna(False)
    is_payroll_text = fam.str.upper().str.contains("PAYROLL", na=False)
    scope = is_expense & is_payroll_text
    violations = scope & ~gl.isin(payroll_accounts)

    metric = {
        "violations": int(violations.sum()),
        "denominator": int(scope.sum()),
        "payroll_expense_accounts": sorted(payroll_accounts),
        "top_violations": df[violations]
        .assign(gl=gl[violations])
        .groupby(["gl", "line_text_family"])
        .size()
        .sort_values(ascending=False)
        .head(5)
        .to_dict()
        if violations.any()
        else {},
    }
    metric["top_violations"] = {
        f"{k[0]}|{k[1]}": int(v) for k, v in metric["top_violations"].items()
    }
    return ("PASS" if not violations.any() else "FAIL"), metric


def acc07_no_duplicate_account_names(
    df: pd.DataFrame, coa: dict[str, dict[str, Any]]
) -> tuple[str, dict[str, Any]]:
    """원장이 쓰는 계정 중 이름이 겹치는 것이 없어야 한다.

    같은 이름의 계정 둘에 기표되면 감사인이 둘을 구분할 근거가 사라진다.
    """
    gl = set(_canon(df["gl_account"]).unique())
    names: dict[str, list[str]] = {}
    for code in gl:
        name = str(coa.get(code, {}).get("short_description", "")).strip()
        if name:
            names.setdefault(name, []).append(code)
    dupes = {n: sorted(cs) for n, cs in names.items() if len(cs) > 1}
    metric = {
        "duplicate_name_groups": len(dupes),
        "denominator_accounts_used": len(gl),
        "duplicates": dict(list(dupes.items())[:5]),
    }
    return ("PASS" if not dupes else "FAIL"), metric


def run_account_checks(
    df: pd.DataFrame, dataset: Path
) -> list[tuple[str, str, dict[str, Any], str]]:
    """(test_id, status, metric, notes) 목록을 돌려준다. verdict() 래핑은 호출부가 한다."""
    coa = load_coa(dataset)
    table = load_determination_table()
    out: list[tuple[str, str, dict[str, Any], str]] = []

    s, m = acc01_tax_lines_use_tax_accounts(df, coa)
    out.append(
        (
            s,
            m,
            "ACC01_TAX_LINE_USES_TAX_ACCOUNT",
            "tax-bearing lines must post to a tax account; VAT receivable/payable have dedicated accounts under Korean VAT law",
        )
    )
    s, m = acc02_account_determination_compliance(df, table)
    out.append(
        (
            s,
            m,
            "ACC02_ACCOUNT_DETERMINATION_COMPLIANCE",
            "ledger gl_account must match the generator's account determination table for its (scenario, side, subtype); post-hoc gl_account rewriting necessarily breaks this",
        )
    )
    s, m = acc03_semantic_subtype_assigned(df)
    out.append(
        (
            s,
            m,
            "ACC03_SEMANTIC_SUBTYPE_ASSIGNED",
            "semantic_account_subtype must carry meaning, not the 'standard_account' placeholder",
        )
    )
    s, m = acc04_suspense_flag_agrees_with_coa(df, coa)
    out.append(
        (
            s,
            m,
            "ACC04_SUSPENSE_FLAG_AGREES_WITH_COA",
            "ledger is_suspense_account must agree with the CoA flag for the same account",
        )
    )
    s, m = acc05_no_autogenerated_account_names(df, coa)
    out.append(
        (
            s,
            m,
            "ACC05_NO_AUTOGENERATED_ACCOUNT_NAMES",
            "no postings to padding accounts named like 'Cash 4'; real charts of accounts have no serial-numbered names",
        )
    )
    s, m = acc06_ledger_accounts_defined_in_coa(df, coa)
    out.append(
        (
            s,
            m,
            "ACC06_LEDGER_ACCOUNTS_DEFINED_IN_COA",
            "every gl_account used by the ledger must exist in chart_of_accounts.json",
        )
    )
    s, m = acc07_no_duplicate_account_names(df, coa)
    out.append(
        (
            s,
            m,
            "ACC07_NO_DUPLICATE_ACCOUNT_NAMES",
            "accounts posted to must have distinct names; duplicates leave an auditor no basis to tell them apart",
        )
    )
    s, m = acc08_subtype_vocabulary_is_real(df, table)
    out.append(
        (
            s,
            m,
            "ACC08_SUBTYPE_VOCABULARY_IS_REAL",
            "semantic_account_subtype must come from the account determination table's vocabulary; invented labels hide from ACC02, which skips subtypes it does not know",
        )
    )
    s, m = acc09_payroll_text_sits_on_payroll_accounts(df, table)
    out.append(
        (
            s,
            m,
            "ACC09_PAYROLL_TEXT_ON_PAYROLL_ACCOUNTS",
            "payroll line text must sit on a payroll expense account; regression gate for the defect that started this work (rent account carried 5,145 payroll lines because a post-hoc step rewrote gl_account and left the text)",
        )
    )

    # (status, metric, test_id, notes) -> (test_id, status, metric, notes)
    return [(tid, st, mt, nt) for st, mt, tid, nt in out]
