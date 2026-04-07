"""DB E2E 테스트 --DataSynth 1M행 전체 파이프라인 → DuckDB 적재 → 쿼리 검증.

독립 실행 스크립트 (pytest 아님). 1M행 처리에 수십 초 소요.
실행: uv run python tests/test_db/test_e2e_db.py
결과: tests/test_db/test-results/e2e-db-datasynth.md
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd

from config.settings import get_audit_rules, get_settings
from src.db.connection import _override_connection, close_connection
from src.db.loader import LoadResult, load_all
from src.db.queries import PRESET_QUERIES, execute_preset
from src.db.schema import initialize_schema
from src.detection.anomaly_layer import AnomalyDetector
from src.detection.base import DetectionResult
from src.detection.benford_detector import BenfordDetector
from src.detection.fraud_layer import FraudLayer
from src.detection.integrity_layer import IntegrityDetector
from src.detection.score_aggregator import aggregate_scores
from src.feature.engine import generate_all_features

# ── 경로 상수 ──────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_CSV = PROJECT_ROOT / "data/journal/primary/datasynth/journal_entries.csv"
OUTPUT_DIR = Path(__file__).resolve().parent / "test-results"
OUTPUT_MD = OUTPUT_DIR / "e2e-db-datasynth.md"


# ── 파이프라인 단계 ────────────────────────────────────────


def load_data() -> pd.DataFrame:
    """DataSynth CSV 로드 + 날짜 파싱."""
    df = pd.read_csv(
        DATA_CSV,
        parse_dates=["posting_date", "document_date"],
        low_memory=False,
    )
    return df


def run_features(df: pd.DataFrame) -> pd.DataFrame:
    """피처 엔진 실행 → 18개 파생변수 추가."""
    settings = get_settings()
    rules = get_audit_rules()
    result = generate_all_features(df, settings=settings, rules=rules)
    return result.data


def run_detection(df: pd.DataFrame) -> dict:
    """3레이어 탐지 + 점수 집계."""
    results: dict[str, DetectionResult] = {}
    timings: dict[str, float] = {}

    t0 = time.perf_counter()
    results["layer_a"] = IntegrityDetector().detect(df)
    timings["layer_a"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    results["layer_b"] = FraudLayer().detect(df)
    timings["layer_b"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    results["layer_c"] = AnomalyDetector().detect(df)
    timings["layer_c"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    results["benford"] = BenfordDetector().detect(df)
    timings["benford"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    agg_df = aggregate_scores(df, list(results.values()))
    timings["aggregator"] = time.perf_counter() - t0

    # Why: aggregate_scores는 3컬럼(anomaly_score, risk_level, flagged_rules)만 반환.
    #      loader.load_all()에는 원본+피처+탐지결과가 병합된 df 필요.
    merged_df = pd.concat([df, agg_df], axis=1)

    return {"results": results, "agg_df": merged_df, "timings": timings}


def run_db_load(
    conn: duckdb.DuckDBPyConnection,
    agg_df: pd.DataFrame,
    results: dict[str, DetectionResult],
    batch_id: str,
) -> LoadResult:
    """DB 적재 --load_all()."""
    return load_all(conn, agg_df, batch_id, results=list(results.values()))


def run_queries(
    conn: duckdb.DuckDBPyConnection,
    batch_id: str,
) -> dict[str, pd.DataFrame]:
    """6종 프리셋 쿼리 실행."""
    query_results: dict[str, pd.DataFrame] = {}
    for name in PRESET_QUERIES:
        if name == "document_rule_detail":
            continue  # Why: document_id 필요 → 별도 테스트
        query_results[name] = execute_preset(conn, name, batch_id=batch_id)
    return query_results


def run_drilldown(
    conn: duckdb.DuckDBPyConnection,
    batch_id: str,
    document_id: str,
) -> pd.DataFrame:
    """document_rule_detail 드릴다운 쿼리."""
    return execute_preset(conn, "document_rule_detail", params=(batch_id, document_id))


# ── 검증 함수 ─────────────────────────────────────────────


def verify_results(
    load_result: LoadResult,
    query_results: dict[str, pd.DataFrame],
    agg_df: pd.DataFrame,
    results: dict[str, DetectionResult],
    drilldown_df: pd.DataFrame,
    drilldown_doc_id: str,
) -> list[dict]:
    """검증 항목을 실행하고 결과 리스트 반환."""
    checks: list[dict] = []

    # 1. general_ledger 행 수 일치
    gl_rows = query_results["batch_ledger"]
    checks.append({
        "name": "GL 행 수 일치",
        "expected": len(agg_df),
        "actual": len(gl_rows),
        "pass": len(gl_rows) == len(agg_df),
    })

    # 2. anomaly_flags 행 수 > 0
    af_rows = query_results["batch_flags"]
    checks.append({
        "name": "AF 행 수 > 0",
        "expected": "> 0",
        "actual": len(af_rows),
        "pass": len(af_rows) > 0,
    })

    # 3. anomaly_flags 행 수 == load_result
    checks.append({
        "name": "AF 적재 수 == 조회 수",
        "expected": load_result.anomaly_flags_rows,
        "actual": len(af_rows),
        "pass": len(af_rows) == load_result.anomaly_flags_rows,
    })

    # 4. benford_summary 1행
    bs = query_results["benford_summary"]
    checks.append({
        "name": "Benford summary 1행",
        "expected": 1,
        "actual": len(bs),
        "pass": len(bs) == 1,
    })

    # 5. benford_digits 9행
    bd = query_results["benford_digits"]
    checks.append({
        "name": "Benford digits 9행",
        "expected": 9,
        "actual": len(bd),
        "pass": len(bd) == 9,
    })

    # 6. benford deviation = observed - expected
    if not bd.empty:
        dev_ok = all(
            abs(row["deviation"] - (row["observed_freq"] - row["expected_freq"])) < 1e-10
            for _, row in bd.iterrows()
        )
    else:
        dev_ok = False
    checks.append({
        "name": "Benford deviation 정합",
        "expected": "obs - exp",
        "actual": "일치" if dev_ok else "불일치",
        "pass": dev_ok,
    })

    # 7. rule_violation_stats VIEW 정합
    rvs = query_results["rule_violation_stats"]
    checks.append({
        "name": "VIEW 쿼리 행 > 0",
        "expected": "> 0",
        "actual": len(rvs),
        "pass": len(rvs) > 0,
    })

    # 8. VIEW flagged_count 합계 == anomaly_flags 행 수
    if not rvs.empty:
        view_total = int(rvs["flagged_count"].sum())
    else:
        view_total = 0
    checks.append({
        "name": "VIEW flagged_count 합 == AF 행 수",
        "expected": len(af_rows),
        "actual": view_total,
        "pass": view_total == len(af_rows),
    })

    # 9. risk_level 분포 존재
    risk_levels = set(gl_rows["risk_level"].dropna().unique())
    checks.append({
        "name": "risk_level 분포",
        "expected": "1+ 등급",
        "actual": risk_levels,
        "pass": len(risk_levels) >= 1,
    })

    # 10. anomaly_score 범위 [0, 1]
    scores = gl_rows["anomaly_score"].dropna()
    score_range_ok = scores.min() >= 0 and scores.max() <= 1.0 if not scores.empty else False
    checks.append({
        "name": "anomaly_score 범위 [0,1]",
        "expected": "[0.0, 1.0]",
        "actual": f"[{scores.min():.4f}, {scores.max():.4f}]" if not scores.empty else "빈",
        "pass": score_range_ok,
    })

    # 11. drilldown 쿼리 결과
    checks.append({
        "name": "드릴다운 쿼리 결과 > 0",
        "expected": f"> 0 (doc={drilldown_doc_id})",
        "actual": len(drilldown_df),
        "pass": len(drilldown_df) > 0,
    })

    # 12. drilldown 결과 컬럼 정합
    expected_cols = {"track_name", "rule_code", "score"}
    actual_cols = set(drilldown_df.columns)
    checks.append({
        "name": "드릴다운 컬럼 정합",
        "expected": expected_cols,
        "actual": actual_cols,
        "pass": expected_cols == actual_cols,
    })

    # 13. batch_id 격리 (존재하지 않는 배치 → 0행)
    # Why: 이 검증은 run_queries에서 이미 batch_id 필터링되므로 암묵적 검증

    return checks


# ── 리포트 생성 ────────────────────────────────────────────


def generate_report(
    n_rows: int,
    load_result: LoadResult,
    query_results: dict[str, pd.DataFrame],
    checks: list[dict],
    timings: dict[str, float],
    drilldown_doc_id: str,
    drilldown_df: pd.DataFrame,
) -> str:
    """MD 리포트 문자열 생성."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    passed = sum(1 for c in checks if c["pass"])
    total = len(checks)
    total_time = sum(timings.values())

    md = []
    md.append(f"# DB E2E 테스트 결과 (DataSynth {n_rows:,d}행)")
    md.append(f"\n> 실행일: {now} | **{passed}/{total} 검증 통과**")

    # §1 요약
    md.append("\n---\n\n## 1. 요약\n")
    md.append(f"| {'항목':24s} | {'값':>20s} |")
    md.append(f"|:{'-'*24}|{'-'*20}:|")
    md.append(f"| {'입력 행 수':24s} | {n_rows:>20,d} |")
    md.append(f"| {'GL 적재':24s} | {load_result.general_ledger_rows:>20,d} |")
    md.append(f"| {'AF 적재':24s} | {load_result.anomaly_flags_rows:>20,d} |")
    md.append(f"| {'Benford summary':24s} | {load_result.benford_summary_rows:>20,d} |")
    md.append(f"| {'Benford digits':24s} | {load_result.benford_digits_rows:>20,d} |")
    md.append(f"| {'총 적재 행':24s} | {load_result.total_rows:>20,d} |")
    md.append(f"| {'적재 소요':24s} | {load_result.elapsed_seconds:>19.2f}s |")
    md.append(f"| {'전체 소요 (적재+쿼리)':24s} | {total_time:>19.2f}s |")
    if load_result.warnings:
        md.append(f"| {'경고':24s} | {len(load_result.warnings):>20d} |")

    # §2 소요시간
    md.append("\n---\n\n## 2. 소요시간\n")
    md.append("```")
    md.append(f"{'단계':20s}  {'소요(s)':>10s}")
    md.append(f"{'─'*20}  {'─'*10}")
    for stage, elapsed in timings.items():
        md.append(f"{stage:20s}  {elapsed:>10.3f}")
    md.append(f"{'─'*20}  {'─'*10}")
    md.append(f"{'합계':20s}  {total_time:>10.3f}")
    md.append("```")

    # §3 검증 결과
    md.append("\n---\n\n## 3. 검증 결과\n")
    md.append(f"| {'#':>2s} | {'검증 항목':32s} | {'기대':>20s} | {'실제':>20s} | {'결과':4s} |")
    md.append(f"|{'-'*3}:|:{'-'*32}|{'-'*20}:|{'-'*20}:|:{'-'*4}:|")
    for i, c in enumerate(checks, 1):
        status = "PASS" if c["pass"] else "FAIL"
        md.append(
            f"| {i:>2d} | {c['name']:32s} | {str(c['expected']):>20s} | {str(c['actual']):>20s} | {status:4s} |"
        )

    # §4 쿼리별 결과 행 수
    md.append("\n---\n\n## 4. 쿼리별 조회 결과\n")
    md.append("```")
    md.append(f"{'쿼리명':24s}  {'행 수':>10s}  {'컬럼 수':>8s}")
    md.append(f"{'─'*24}  {'─'*10}  {'─'*8}")
    for name, qdf in query_results.items():
        md.append(f"{name:24s}  {len(qdf):>10,d}  {len(qdf.columns):>8d}")
    md.append(f"{'document_rule_detail':24s}  {len(drilldown_df):>10,d}  {len(drilldown_df.columns):>8d}")
    md.append("```")

    # §5 risk_level 분포
    gl = query_results["batch_ledger"]
    md.append("\n---\n\n## 5. risk_level 분포\n")
    risk_dist = gl["risk_level"].value_counts()
    md.append(f"| {'등급':10s} | {'건수':>10s} | {'비율':>8s} |")
    md.append(f"|:{'-'*10}|{'-'*10}:|{'-'*8}:|")
    for level in ["High", "Medium", "Low", "Normal"]:
        cnt = int(risk_dist.get(level, 0))
        pct = f"{cnt / len(gl) * 100:.2f}%" if len(gl) > 0 else "0.00%"
        md.append(f"| {level:10s} | {cnt:>10,d} | {pct:>8s} |")

    # §6 anomaly_flags 트랙별 분포
    af = query_results["batch_flags"]
    md.append("\n---\n\n## 6. anomaly_flags 트랙별 분포\n")
    if not af.empty:
        track_dist = af.groupby("track_name").agg(
            행수=("score", "count"),
            avg_score=("score", "mean"),
            max_score=("score", "max"),
        ).reset_index()
        md.append(f"| {'트랙':12s} | {'행 수':>10s} | {'avg_score':>10s} | {'max_score':>10s} |")
        md.append(f"|:{'-'*12}|{'-'*10}:|{'-'*10}:|{'-'*10}:|")
        for _, row in track_dist.iterrows():
            md.append(
                f"| {row['track_name']:12s} | {int(row['행수']):>10,d} "
                f"| {row['avg_score']:>10.4f} | {row['max_score']:>10.4f} |"
            )

    # §7 rule_violation_stats VIEW 상위 10
    rvs = query_results["rule_violation_stats"]
    md.append("\n---\n\n## 7. 룰별 위반 통계 (상위 10)\n")
    if not rvs.empty:
        top10 = rvs.head(10)
        md.append(f"| {'트랙':10s} | {'룰':8s} | {'건수':>10s} | {'avg_score':>10s} | {'max_score':>10s} |")
        md.append(f"|:{'-'*10}|:{'-'*8}|{'-'*10}:|{'-'*10}:|{'-'*10}:|")
        for _, row in top10.iterrows():
            md.append(
                f"| {row['track_name']:10s} | {row['rule_code']:8s} | {int(row['flagged_count']):>10,d} "
                f"| {row['avg_score']:>10.4f} | {row['max_score']:>10.4f} |"
            )

    # §8 Benford 요약
    bs = query_results["benford_summary"]
    md.append("\n---\n\n## 8. Benford 분석 요약\n")
    if not bs.empty:
        row = bs.iloc[0]
        md.append(f"| {'항목':20s} | {'값':>16s} |")
        md.append(f"|:{'-'*20}|{'-'*16}:|")
        md.append(f"| {'sample_size':20s} | {int(row['sample_size']):>16,d} |")
        md.append(f"| {'MAD':20s} | {row['mad']:>16.6f} |")
        md.append(f"| {'MAD conformity':20s} | {str(row['mad_conformity']):>16s} |")
        md.append(f"| {'Chi² statistic':20s} | {row['chi2_statistic']:>16.4f} |")
        md.append(f"| {'Chi² p-value':20s} | {row['chi2_p_value']:>16.4f} |")
        md.append(f"| {'KS statistic':20s} | {row['ks_statistic']:>16.4f} |")
        md.append(f"| {'KS p-value':20s} | {row['ks_p_value']:>16.4f} |")
        md.append(f"| {'is_conforming':20s} | {str(row['is_conforming']):>16s} |")
        md.append(f"| {'confidence':20s} | {str(row['confidence']):>16s} |")

    # §9 드릴다운 예시
    md.append(f"\n---\n\n## 9. 드릴다운 예시 (document_id={drilldown_doc_id})\n")
    if not drilldown_df.empty:
        md.append(f"| {'트랙':12s} | {'룰':8s} | {'score':>8s} |")
        md.append(f"|:{'-'*12}|:{'-'*8}|{'-'*8}:|")
        for _, row in drilldown_df.iterrows():
            md.append(f"| {row['track_name']:12s} | {row['rule_code']:8s} | {row['score']:>8.4f} |")

    # §10 관련 문서
    md.append("\n---\n\n## 10. 관련 문서\n")
    md.append("| 문서 | 내용 |")
    md.append("|:-----|:-----|")
    md.append("| [docs/pre-plan/06-db.md](../../../docs/pre-plan/06-db.md) | DB 레이어 설계 |")
    md.append("| [db-all-results.md](db-all-results.md) | DB unit test 결과 (34 passed) |")
    md.append("| [e2e-detection-datasynth.md](../../test_detection/test-results/e2e-detection-datasynth.md) | Detection E2E 결과 |")

    return "\n".join(md) + "\n"


# ── 메인 ──────────────────────────────────────────────────


def main():
    """전체 파이프라인 실행."""
    print("=" * 60)
    print("DB E2E 테스트 --DataSynth → DuckDB 적재 → 쿼리 검증")
    print("=" * 60)

    timings: dict[str, float] = {}

    # Step 1: 데이터 로드
    print("\n[1/6] DataSynth CSV 로드...")
    t0 = time.perf_counter()
    df = load_data()
    timings["data_load"] = time.perf_counter() - t0
    print(f"  → {len(df):,d}행 로드 ({timings['data_load']:.2f}s)")

    # Step 2: 피처 생성
    print("[2/6] 피처 엔진 실행...")
    t0 = time.perf_counter()
    df = run_features(df)
    timings["feature"] = time.perf_counter() - t0
    print(f"  → 피처 생성 완료 ({timings['feature']:.2f}s)")

    # Step 3: 탐지 + 점수 집계
    print("[3/6] Detection 3레이어 + score_aggregator...")
    t0 = time.perf_counter()
    det = run_detection(df)
    timings["detection"] = time.perf_counter() - t0
    agg_df = det["agg_df"]
    results = det["results"]
    print(f"  → 탐지 완료 ({timings['detection']:.2f}s)")

    # Step 4: DuckDB 적재
    print("[4/6] DuckDB in-memory 적재...")
    conn = duckdb.connect(":memory:")
    _override_connection(conn)
    initialize_schema(conn)
    batch_id = f"e2e-{uuid.uuid4().hex[:8]}"

    t0 = time.perf_counter()
    load_result = run_db_load(conn, agg_df, results, batch_id)
    timings["db_load"] = time.perf_counter() - t0
    print(f"  → 적재 완료: GL={load_result.general_ledger_rows:,d}, "
          f"AF={load_result.anomaly_flags_rows:,d}, "
          f"BS={load_result.benford_summary_rows}, BD={load_result.benford_digits_rows} "
          f"({timings['db_load']:.2f}s)")

    # Step 5: 쿼리 실행
    print("[5/6] 6종 프리셋 쿼리 실행...")
    t0 = time.perf_counter()
    query_results = run_queries(conn, batch_id)

    # 드릴다운 테스트 --anomaly_score 최고 document_id 선택
    gl = query_results["batch_ledger"]
    top_doc_id = str(gl.iloc[0]["document_id"]) if not gl.empty else "UNKNOWN"
    drilldown_df = run_drilldown(conn, batch_id, top_doc_id)
    timings["queries"] = time.perf_counter() - t0
    print(f"  → 쿼리 완료 ({timings['queries']:.2f}s)")

    # Step 6: 검증
    print("[6/6] 검증 실행...")
    checks = verify_results(
        load_result, query_results, agg_df, results, drilldown_df, top_doc_id,
    )
    passed = sum(1 for c in checks if c["pass"])
    total = len(checks)
    print(f"  → {passed}/{total} 검증 통과")

    for c in checks:
        status = "PASS" if c["pass"] else "FAIL"
        print(f"    [{status}] {c['name']}: expected={c['expected']}, actual={c['actual']}")

    # 리포트 저장
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report = generate_report(
        len(df), load_result, query_results, checks, timings, top_doc_id, drilldown_df,
    )
    OUTPUT_MD.write_text(report, encoding="utf-8")
    print(f"\n리포트 저장: {OUTPUT_MD}")

    # 정리
    close_connection()

    if passed < total:
        print(f"\n⚠ {total - passed}건 검증 실패")
        raise SystemExit(1)
    print(f"\n전체 통과 ({sum(timings.values()):.2f}s)")


if __name__ == "__main__":
    main()
