"""통합 쓸모 벤치마크 채점 harness (T7) — scheme × surface, 정상 baseline 대비.

spec: dev/active/integrated-usefulness-benchmark/SCORING_HARNESS_SPEC.md
catch 정의(DESIGN §1⑤) + 변별력(§9 hollow 방지):
  PHASE1-1: scheme 문서가 리뷰 큐 priority_band(high/medium) 진입 — **정상 baseline 동시 보고**
            ("아무 룰이나 발화"는 룰이 전 문서에 발화해 hollow → band 사용).
  PHASE1-2: timeseries flagged (graph/relational 삭제 → timeseries만).
  PHASE2  : VAE 이상점수 상위 K%(=1%) 진입(고정 리뷰예산이라 자체 변별).
3-surface 비병합. 미가동 surface는 "측정불가" 정직 표기.

사용: python tools/scripts/score_integrated_benchmark.py <dataset_dir>
"""

from __future__ import annotations

import argparse
import collections
import json
import math
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BAND_RANK = {"context": 0, "low": 1, "medium": 2, "high": 3}


def parse_docs(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return set()
    t = str(v).strip()
    if not t:
        return set()
    try:
        x = json.loads(t) if t.startswith("[") else [t]
    except json.JSONDecodeError:
        x = [t]
    return {str(i) for i in x if str(i)}


def doc_band_map(pcr):
    """document_id → priority_band(high/medium/low/context). 여러 case면 최고 band."""
    dm = {}
    for cs in getattr(pcr, "cases", []) or []:
        band = str(getattr(cs, "priority_band", "") or "").lower()
        for d in getattr(cs, "documents", []) or []:
            did = str(getattr(d, "document_id", "") or "")
            if not did:
                continue
            if did not in dm or BAND_RANK.get(band, 0) > BAND_RANK.get(dm[did], 0):
                dm[did] = band
    return dm


def surface_ts(df, settings, doc_series):
    try:
        from src.detection.timeseries_detector import TimeseriesDetector

        r = TimeseriesDetector(settings).detect(df)
        idx = [i for i in (r.flagged_indices or []) if 0 <= i < len(df)]
        return set(doc_series.iloc[idx]), None
    except Exception as exc:
        return None, str(exc)[:200]


def surface_vae(df, settings, doc_series, k_frac):
    try:
        from src.detection.vae_detector import UnsupervisedDetector
        from src.preprocessing.model_registry import ModelRegistry

        reg = ROOT / "data/companies/test/engagements/fy2022/models"
        det = UnsupervisedDetector(settings, model_registry=ModelRegistry(registry_dir=reg))
        det.load_model("unsupervised")
        r = det.detect(df)
        sc = pd.to_numeric(getattr(r, "scores", None), errors="coerce")
        if sc is None or sc.dropna().empty or sc.nunique() <= 1:
            return None, "scores 비어있음/상수 — 측정불가"
        sc = sc.reindex(df.index).fillna(sc.min())
        k = max(1, math.ceil(len(df) * k_frac))
        return set(doc_series.reindex(sc.nlargest(k).index)), None
    except Exception as exc:
        return None, str(exc)[:200]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset_dir", type=Path)
    ap.add_argument("--k-frac", type=float, default=0.01)
    ap.add_argument(
        "--normal-sample",
        type=int,
        default=None,
        help="정상 문서 랜덤 표본 행수(전량 case 빌드 OOM 회피). fraud는 전량 유지.",
    )
    args = ap.parse_args(argv)
    D = args.dataset_dir
    out = D / "reports" / "integrated_benchmark"
    out.mkdir(parents=True, exist_ok=True)

    tfile = next((f for f in (D / "labels").glob("*_truth.csv")), None)
    if tfile is None:
        raise SystemExit(f"truth 없음: {D / 'labels'}")
    truth = pd.read_csv(tfile)
    truth["docs"] = truth["member_document_ids"].map(parse_docs)
    fraud_docs = set().union(*truth["docs"]) if len(truth) else set()

    from config.settings import get_settings
    from src.pipeline import AuditPipeline
    from src.services.analysis_service import make_phase_settings

    # 전량 378k는 case 빌드 OOM → 대표 표본(fraud 전량 + 정상 랜덤)으로 fraud-vs-정상 변별 측정
    sample_note = "전량"
    csv_path = str(D / "journal_entries.csv")
    if args.normal_sample:
        full = pd.read_csv(csv_path, low_memory=False)
        full["_did"] = full["document_id"].astype(str)
        is_fr = full["_did"].isin(fraud_docs)
        fr = full[is_fr]
        norm = full[~is_fr]
        # 문서 단위 샘플(행 단위면 전표 차대 쪼개져 검증 실패). 목표 행수 ≈ n_docs × 평균라인.
        norm_docs = norm["_did"].drop_duplicates()
        avg = len(norm) / max(len(norm_docs), 1)
        n_docs = max(1, int(args.normal_sample / avg))
        pick = set(norm_docs.sample(n=min(n_docs, len(norm_docs)), random_state=42))
        nm = norm[norm["_did"].isin(pick)]
        samp = pd.concat([fr, nm]).drop(columns=["_did"])
        tmp = out / "_sample_journal.csv"
        samp.to_csv(tmp, index=False)
        csv_path = str(tmp)
        sample_note = f"표본(fraud 전량 {fr['document_id'].nunique()} + 정상 랜덤 {len(nm)}행, seed=42) — 절대율은 전량과 다를 수 있음, fraud-vs-정상 변별이 신호"

    res = AuditPipeline(skip_db=True).run(csv_path)
    df = res.data
    doc_series = df.get("document_id", pd.Series("", index=df.index)).astype(str)
    dm = doc_band_map(res.phase1_case_result)
    all_docs = set(doc_series)
    fraud_docs = set().union(*truth["docs"]) if len(truth) else set()
    normal_docs = all_docs - fraud_docs

    settings = make_phase_settings(get_settings(), phase="phase2")
    ts_docs, ts_err = surface_ts(df, settings, doc_series)
    vae_docs, vae_err = surface_vae(df, settings, doc_series, args.k_frac)

    # 정상 baseline (동일 임계에서 정상 문서 비율)
    def band_rate(docs, min_band):
        r = BAND_RANK[min_band]
        hit = sum(1 for d in docs if BAND_RANK.get(dm.get(d, "context"), 0) >= r)
        return hit, len(docs)

    # scheme catch
    rows = []
    for _, tr in truth.iterrows():
        m = tr["docs"]
        best = max((BAND_RANK.get(dm.get(d, "context"), 0) for d in m), default=0)
        rows.append(
            dict(
                seed_id=tr.get("seed_id", ""),
                pattern=tr.get("generated_pattern_name", ""),
                weak=str(tr.get("weak_signal", "")).lower() == "true",
                band_rank=best,
                p1_high=best >= 3,
                p1_med=best >= 2,
                p1_2=(bool(m & ts_docs) if ts_docs is not None else None),
                p2=(bool(m & vae_docs) if vae_docs is not None else None),
            )
        )
    sc = pd.DataFrame(rows)
    N = len(sc)

    def fc(col):
        return int(sc[col].fillna(False).sum()) if not sc[col].isna().all() else None

    L = []
    L.append("# 통합 쓸모 벤치마크 채점 리포트 (T7) — band 기반 + 정상 baseline")
    L.append("")
    L.append(
        f"dataset: `{D.name}` | scheme N=**{N}** | journal {len(df)}행 | 문서 fraud {len(fraud_docs)}/normal {len(normal_docs)}"
    )
    L.append(f"측정 범위: {sample_note}")
    L.append(
        f"surface: PHASE1-1 band ✅ / PHASE1-2 timeseries {'✅' if ts_docs is not None else '⛔ ' + str(ts_err)} / PHASE2 VAE {'✅' if vae_docs is not None else '⛔ ' + str(vae_err)}"
    )
    L.append("PHASE1-2 graph/relational 삭제 → timeseries만. 순환거래 구조적 blind(도구경계).")
    L.append("")
    L.append("## ⚠ 변별력 — PHASE1-1은 fraud catch와 **정상 baseline**을 반드시 함께 본다")
    L.append(
        "리뷰 큐가 전 문서를 high/medium에 넣으면 fraud '100% catch'는 무의미(§9 hollow). fraud율이 정상율보다 유의하게 높아야 변별."
    )
    L.append("| 임계 | fraud catch | 정상 baseline | 변별(fraud−정상) |")
    L.append("|------|-------------|---------------|------------------|")
    for lbl, mb, col in [("band≥high", "high", "p1_high"), ("band≥medium", "medium", "p1_med")]:
        fh = fc(col)
        nh, nn = band_rate(normal_docs, mb)
        L.append(
            f"| {lbl} | {fh}/{N} ({100 * fh / N:.0f}%) | {nh}/{nn} ({100 * nh / nn:.0f}%) | {100 * fh / N - 100 * nh / nn:+.0f}%p |"
        )
    L.append("")
    L.append("## 다른 surface (scheme catch)")
    L.append("| surface | fraud catch/N | 정상 baseline |")
    L.append("|---------|---------------|---------------|")
    if ts_docs is not None:
        nts = len(ts_docs & normal_docs)
        L.append(
            f"| PHASE1-2 timeseries | {fc('p1_2')}/{N} | {nts}/{len(normal_docs)} ({100 * nts / max(len(normal_docs), 1):.1f}%) |"
        )
    else:
        L.append(f"| PHASE1-2 timeseries | 측정불가 | {ts_err} |")
    if vae_docs is not None:
        nvae = len(vae_docs & normal_docs)
        L.append(
            f"| PHASE2 VAE@{int(args.k_frac * 100)}% | {fc('p2')}/{N} | {nvae}/{len(normal_docs)} (상위{int(args.k_frac * 100)}% 고정예산) |"
        )
    else:
        L.append(f"| PHASE2 VAE | 측정불가 | {vae_err} |")
    L.append("")
    L.append("## 패턴족 × surface (fraud catch)")
    L.append("| 패턴 | N | P1-1≥high | P1-1≥med | P1-2 | P2 |")
    L.append("|------|---|-----------|----------|------|----|")
    for pat, sub in sc.groupby("pattern"):
        n = len(sub)

        def r(c):
            return "n/a" if sub[c].isna().all() else f"{int(sub[c].fillna(False).sum())}/{n}"

        L.append(f"| {pat} | {n} | {r('p1_high')} | {r('p1_med')} | {r('p1_2')} | {r('p2')} |")
    L.append("")

    # 0-surface: band<medium AND ts miss AND vae miss (범위내/weak 분리)
    def caught_any(row):
        return bool(row["p1_med"]) or (row["p1_2"] is True) or (row["p2"] is True)

    sc["any"] = sc.apply(caught_any, axis=1)
    zero = sc[(~sc["any"]) & (~sc["weak"])]
    L.append("## 0-surface scheme (band<medium & timeseries miss & VAE miss)")
    L.append(f"- 범위 내(weak 제외): **{len(zero)}/{N}** (DESIGN ⑨ 바닥선 게이트 후보)")
    L.append(f"- weak-signal: {len(sc[(~sc['any']) & (sc['weak'])])}")
    if len(zero):
        L.append(f"- 패턴 분해: {zero.groupby('pattern').size().to_dict()}")
    L.append("")
    L.append("## seed 안정성 (band≥medium)")
    for sid, sub in sc.groupby("seed_id"):
        L.append(f"- {sid}: {int(sub['p1_med'].sum())}/{len(sub)}")
    (out / "benchmark_report.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    sc.drop(columns=["any"]).to_csv(out / "scheme_catch.csv", index=False, encoding="utf-8")

    nh, nn = band_rate(normal_docs, "high")
    nm, _ = band_rate(normal_docs, "medium")
    print(
        f"[T7] N={N} | P1-1 high fraud={fc('p1_high')}/{N} normal={nh}/{nn} | med fraud={fc('p1_med')} normal={nm} | "
        f"P1-2={fc('p1_2') if ts_docs is not None else 'NA'} P2={fc('p2') if vae_docs is not None else 'NA'} | zero(비weak)={len(zero)}"
    )
    print(f"[T7] band 분포 전체: {dict(collections.Counter(dm.values()))}")
    print(f"[T7] report: {out / 'benchmark_report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
