"""부정 overlay 의 컬럼 계약 검증 — 정상 정본이 정답지다.

사용: uv run python tools/scripts/verify_overlay_column_contract.py <fraud_dir> [<fraud_dir2> ...]

배경(2026-07-27): phase2 overlay 가 정상 행이 채우는 부속 컬럼 8개를 안 채워서
"결측 자체"가 부정 정답지로 작동했고, 적요를 donor 행에서 복사해 계정과 어긋난
(적요, 계정) 조합이 부정에만 생겼다. 전자는 L3-09·L1-07 을 구조적으로 미발화시키고
L1-04 를 날조 발화시켰으며, 둘 다 부정을 정밀도 1.0 으로 지목하는 누출이었다.

검사 축 (전부 전수 — 표본 판정 금지):
  C1 채움률 대비 (WARN) — 정상은 채우는데 부정은 비는 컬럼. 단독으로는 결함 판정 근거가
                          못 된다(정상도 대부분 비는 컬럼이면 결측이 정보가 없다).
                          실제 판정은 C2 가 한다.
  C2 단일 컬럼 오라클 (HARD) — 행 단위로, 결측 여부와 각 값이 부정을 지목하는가.
  C5 조합 축 오라클 (HARD) — 컬럼 쌍의 값 조합 중 정상에 한 번도 없는 것이 부정에 있는가.
                             단일 컬럼만 보면 못 잡는다 — 이 축을 빠뜨려 적요×계정 누출을
                             한 라운드 놓쳤다.
  C3 조건부 계약 (HARD) — source→배치식별자, 가계정→is_cleared, 차대→subtype,
                          승인자↔승인일자 1:1 이 정상과 같은 규칙인가.
  C4 L3-09 도달성 (HARD) — 가계정 파킹 라인이 미정리로 남아 룰이 도달 가능한가.

exit 0 = 모든 HARD 검사 통과.
"""

from __future__ import annotations

import sys
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

# 부정 라벨 컬럼 — 정답지가 맞으므로 오라클 스캔 대상에서 뺀다.
LABEL_COLUMNS = {
    "is_fraud",
    "fraud_type",
    "is_anomaly",
    "anomaly_type",
    "detection_surface_hints",
}
# 전표 식별자 — 부정 전표는 정의상 새 번호를 받으므로 이 컬럼이 낀 조합은 자동으로
# "정상 미출현"이 된다. 필드 배선 문제가 아니라 신원이라 조합 누출 판정에서 뺀다.
# (예: credit_account_subtype × original_document_id 135행은 원전표 ID가
#  부정 UUID 라서 나온 것이고, 계정·subtype 배선과 무관하다.)
IDENTIFIER_COLUMNS = {
    "document_id",
    "document_number",
    "accounting_document_number",
    "reference",
    "original_document_id",
    "reversal_document_id",
    "batch_id",
}
EXCLUDED_COLUMNS = LABEL_COLUMNS | IDENTIFIER_COLUMNS
PRECISION_HARD = 0.99  # 이 이상이면 사실상 단독 분리자
RECALL_MIN = 0.05  # 부정의 5% 이상을 지목해야 유의미한 누출로 본다
PAIR_MAX_CARDINALITY = 400  # 조합 스캔 대상 컬럼의 고유값 상한


def _present(series: pd.Series) -> pd.Series:
    return series.notna() & series.astype(str).str.strip().ne("")


def check_dataset(fraud_dir: Path) -> list[str]:
    failures: list[str] = []
    df = pd.read_csv(fraud_dir / "journal_entries.csv", dtype=str, low_memory=False)
    prov = pd.read_csv(fraud_dir / "labels/phase2_scheme_provenance.csv", dtype=str)
    fraud_docs = sorted(set(prov["document_id"]))
    is_fraud = df["document_id"].isin(fraud_docs).to_numpy()
    fraud, normal = df[is_fraud], df[~is_fraud]
    n_fraud = int(is_fraud.sum())
    print(f"\n=== {fraud_dir.name} ===")
    print(
        f"행 {len(df):,} (부정 {n_fraud:,}) · 문서 {df['document_id'].nunique():,}"
        f" (부정 {len(fraud_docs):,})"
    )

    scan_columns = [c for c in df.columns if c not in EXCLUDED_COLUMNS]

    # ── C1 채움률 대비 (WARN) ───────────────────────────────────
    gaps = []
    for column in scan_columns:
        n_rate = float(_present(normal[column]).mean())
        f_rate = float(_present(fraud[column]).mean())
        if n_rate > 0.02 and f_rate < 0.02:
            gaps.append((column, n_rate, f_rate))
    if gaps:
        for column, n_rate, f_rate in gaps:
            print(f"  [C1 WARN] {column:<28} 정상 {n_rate:.3f} → 부정 {f_rate:.3f}")
    else:
        print("  [C1 OK  ] 부정에서만 비는 컬럼 없음")

    # ── C2 단일 컬럼 오라클 (행 단위) ──────────────────────────
    leaks = []
    for column in scan_columns:
        present = _present(df[column]).to_numpy()
        for label, mask in (("결측", ~present), ("보유", present)):
            hit_f = int((mask & is_fraud).sum())
            hit_n = int((mask & ~is_fraud).sum())
            if hit_f == 0:
                continue
            precision = hit_f / (hit_f + hit_n)
            recall = hit_f / n_fraud
            if precision >= PRECISION_HARD and recall >= RECALL_MIN:
                leaks.append((f"{column} {label}", precision, recall, hit_f, hit_n))
        counts_f = df.loc[is_fraud, column].fillna("<NA>").value_counts()
        counts_n = df.loc[~is_fraud, column].fillna("<NA>").value_counts()
        for value, cnt_f in counts_f.items():
            cnt_n = int(counts_n.get(value, 0))
            precision = int(cnt_f) / (int(cnt_f) + cnt_n)
            recall = int(cnt_f) / n_fraud
            if precision >= PRECISION_HARD and recall >= RECALL_MIN:
                leaks.append((f"{column}={value!r}", precision, recall, int(cnt_f), cnt_n))
    if leaks:
        failures.append(f"C2: 단독 분리자 {len(leaks)}건")
        for name, precision, recall, hit_f, hit_n in sorted(leaks, key=lambda r: -r[2])[:15]:
            print(
                f"  [C2 FAIL] {name:<46} 정밀도 {precision:.4f} 재현율 {recall:.4f}"
                f" (부정 {hit_f} / 정상 {hit_n})"
            )
    else:
        print(
            f"  [C2 PASS] 행 단위 단독 분리자 없음 (정밀도 {PRECISION_HARD}+ · 재현율 {RECALL_MIN}+)"
        )

    # ── C5 조합 축 오라클 — 정상에 한 번도 없는 값 조합 ─────────
    codes: dict[str, np.ndarray] = {}
    for column in scan_columns:
        series = df[column].fillna("<NA>")
        if series.nunique() > PAIR_MAX_CARDINALITY:
            continue
        codes[column], _ = pd.factorize(series)
    pair_leaks = []
    for left, right in combinations(sorted(codes), 2):
        base = int(codes[right].max()) + 1
        combined = codes[left].astype(np.int64) * base + codes[right].astype(np.int64)
        normal_seen = np.unique(combined[~is_fraud])
        fraud_codes = combined[is_fraud]
        unseen = ~np.isin(fraud_codes, normal_seen)
        recall = float(unseen.mean())
        if recall >= RECALL_MIN:
            pair_leaks.append((f"{left} × {right}", recall, int(unseen.sum())))
    if pair_leaks:
        failures.append(f"C5: 정상 미출현 조합 {len(pair_leaks)}쌍")
        for name, recall, hit in sorted(pair_leaks, key=lambda r: -r[1])[:15]:
            print(f"  [C5 FAIL] {name:<50} 부정 전용 조합 {hit}행 (재현율 {recall:.4f})")
    else:
        print(f"  [C5 PASS] 정상에 없는 컬럼쌍 조합이 부정의 {RECALL_MIN:.0%} 이상인 쌍 없음")

    # ── C3 조건부 계약 ─────────────────────────────────────────
    ok = True
    auto = fraud["source"].isin(["automated", "recurring"])
    for column in ("batch_id", "job_id"):
        got_auto = float(_present(fraud.loc[auto, column]).mean()) if int(auto.sum()) else 1.0
        got_manual = float(_present(fraud.loc[~auto, column]).mean()) if int((~auto).sum()) else 0.0
        if got_auto < 0.999 or got_manual > 0.001:
            failures.append(f"C3: {column} source 조건부 계약 위반")
            print(
                f"  [C3 FAIL] {column} 자동계열 {got_auto:.3f}(기대 1.0)"
                f" / 수기계열 {got_manual:.3f}(기대 0.0)"
            )
            ok = False

    approver = _present(fraud["approved_by"]).to_numpy()
    approval_date = _present(fraud["approval_date"]).to_numpy()
    if not np.array_equal(approver, approval_date):
        failures.append("C3: approved_by ↔ approval_date 1:1 위반")
        print(
            f"  [C3 FAIL] 승인자 보유 {int(approver.sum())} vs 승인일자 보유"
            f" {int(approval_date.sum())} — 정상은 전건 일치"
        )
        ok = False

    susp = fraud["is_suspense_account"].astype(str).str.lower().eq("true")
    stray = int(_present(fraud.loc[~susp, "is_cleared"]).sum())
    if stray > 0:
        failures.append("C3: 비가계정 라인에 is_cleared 존재")
        print(f"  [C3 FAIL] 비가계정 {stray}행이 is_cleared 보유 — 정상은 0건")
        ok = False
    if int(susp.sum()) and float(_present(fraud.loc[susp, "is_cleared"]).mean()) < 0.999:
        failures.append("C3: 가계정 라인 is_cleared 결측")
        print("  [C3 FAIL] 가계정 라인에 is_cleared 결측 존재")
        ok = False

    debit = pd.to_numeric(fraud["debit_amount"], errors="coerce").fillna(0) != 0
    for side, column in (("차변", "debit_account_subtype"), ("대변", "credit_account_subtype")):
        mask = debit if side == "차변" else ~debit
        own = float(_present(fraud.loc[mask, column]).mean()) if int(mask.sum()) else 1.0
        other = float(_present(fraud.loc[~mask, column]).mean()) if int((~mask).sum()) else 0.0
        if own < 0.999 or other > 0.001:
            failures.append(f"C3: {column} 차대 방향 계약 위반")
            print(f"  [C3 FAIL] {column} {side}행 {own:.3f}(기대 1.0) / 반대 {other:.3f}(기대 0.0)")
            ok = False
    if ok:
        print("  [C3 PASS] source→배치식별자 · 승인 1:1 · 가계정→is_cleared · 차대→subtype")

    # ── C6 의도 신호 보존 — 수법이 요구하는 성질이 실제로 남았는가 ──
    #    도너 통째 복제로 조합 정합성을 얻는 대가로 신호가 도너 값에 덮일 위험이 있다.
    #    비율이 아니라 "수법의 정의상 필연"인 것만 걸려 있으므로 전건이어야 한다.
    scheme_of = dict(zip(prov["document_id"], prov["scheme_id"], strict=False))
    fdoc = fraud.drop_duplicates("document_id").copy()
    fdoc["_scheme"] = fdoc["document_id"].map(scheme_of)
    intent = {
        "수기 입력 (결산 조작)": (
            ["FS02", "FS06", "FS07", "FS09"],
            fdoc["source"].eq("manual"),
        ),
        # 정상 데이터에는 서식 변동 노이즈(앞뒤 공백)가 균일하게 섞여 있으므로 비교 전 정규화한다.
        "자기승인 (횡령)": (
            ["FS03", "FS04"],
            _present(fdoc["created_by"])
            & fdoc["created_by"]
            .astype(str)
            .str.strip()
            .eq(fdoc["approved_by"].astype(str).str.strip()),
        ),
        "증빙 부재 (가공매출)": (
            ["FS01", "FS05"],
            ~_present(fdoc["supporting_doc_type"]),
        ),
    }
    intent_ok = True
    for label, (schemes_wanted, mask) in intent.items():
        target = fdoc["_scheme"].isin(schemes_wanted)
        if not int(target.sum()):
            continue
        rate = float(mask[target].mean())
        if rate < 0.999:
            failures.append(f"C6: {label} 신호 유실 ({rate:.1%})")
            print(f"  [C6 FAIL] {label} — 대상 {int(target.sum())}문서 중 {rate:.1%}만 보유")
            intent_ok = False
    if intent_ok:
        print("  [C6 PASS] 수법이 요구하는 성질(수기·자기승인·증빙부재) 전건 보존")

    # ── C4 L3-09 도달성 ────────────────────────────────────────
    uncleared = fraud["is_cleared"].astype(str).str.lower().eq("false")
    reachable = fraud.loc[susp & uncleared, "document_id"].nunique()
    if reachable == 0:
        failures.append("C4: 미정리 가계정 부정 문서 0건 — L3-09 도달 불가")
        print("  [C4 FAIL] 미정리 가계정 부정 문서 0건")
    else:
        print(f"  [C4 PASS] 미정리 가계정 부정 문서 {reachable}건 — L3-09 도달 가능")

    return failures


def main() -> int:
    dirs = [Path(a) for a in sys.argv[1:]]
    if not dirs:
        print("usage: verify_overlay_column_contract.py <fraud_dir> [...]")
        return 2
    all_failures = {d.name: check_dataset(d) for d in dirs}
    print("\n=== 종합 ===")
    for name, failures in all_failures.items():
        print(f"  {name}: {'FAIL — ' + '; '.join(failures) if failures else 'PASS'}")
    return 1 if any(all_failures.values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
