"""Measure current PHASE1 catch/miss against P3-2 semantic_v1 truth."""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import tools.scripts.profile_phase1_v126 as phase1_profile
from config.settings import get_audit_rules, get_phase1_case, get_risk_keywords, get_settings
from src.detection.phase1_case_builder import build_phase1_case_result, save_phase1_case_result
from src.ingest.datasynth_labels import apply_datasynth_label_mode
from src.services.analysis_service import make_phase_settings

RULE_IDS = (
    "L1-01",
    "L1-02",
    "L1-03",
    "L1-04",
    "L1-05",
    "L1-06",
    "L1-07",
    "L1-08",
    "L1-09",
    "L2-01",
    "L2-02",
    "L2-03",
    "L2-04",
    "L2-05",
    "L3-01",
    "L3-02",
    "L3-03",
    "L3-04",
    "L3-05",
    "L3-06",
    "L3-07",
    "L3-08",
    "L3-09",
    "L3-10",
    "L3-11",
    "L3-12",
    "L4-01",
    "L4-02",
    "L4-03",
    "L4-04",
    "L4-05",
    "L4-06",
    "IC01",
    "IC02",
    "IC03",
    "GR01",
    "GR03",
    "D01",
    "D02",
)


@dataclass(frozen=True)
class MeasurementPaths:
    dataset_dir: Path
    journal_path: Path
    truth_path: Path | None
    output_dir: Path


def _emit_text(path: Path, text: str) -> None:
    with path.open(chr(119), encoding="utf-8") as handle:
        print(text, end="", file=handle)


def _json_list(value: Any) -> list[str]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    text = str(value).strip()
    if not text:
        return []
    parsed = json.loads(text) if text.startswith("[") else text.split("|")
    return [str(item) for item in parsed if str(item)]


def _resolve_paths(dataset_dir: Path, output_dir: Path | None) -> MeasurementPaths:
    dataset_dir = dataset_dir.resolve()
    journal_path = dataset_dir / "journal_entries.csv"
    if not journal_path.exists():
        raise FileNotFoundError(f"journal_entries.csv not found: {journal_path}")
    truth_path = dataset_dir / "labels" / "p3_2_rule_truth.csv"
    if not truth_path.exists():
        truth_path = None
    out = (
        output_dir.resolve()
        if output_dir
        else dataset_dir / "reports" / "phase1_current_measurement"
    )
    return MeasurementPaths(dataset_dir, journal_path, truth_path, out)


def _run_current_phase1_direct(dataset_dir, output_dir=None):
    paths = _resolve_paths(dataset_dir, output_dir)
    batch_id = paths.dataset_dir.name + "_current_phase1"
    checkpoint = paths.output_dir / "direct_phase1_checkpoint.json"
    stage_summary = dict(
        data_dir=str(paths.dataset_dir), started_at=datetime.now(UTC).isoformat(), stages=dict()
    )
    phase1_profile._write_checkpoint(checkpoint, stage_summary)  # noqa: SLF001
    settings = make_phase_settings(get_settings(), phase="phase1")
    audit_rules = get_audit_rules()
    risk_keywords = get_risk_keywords()
    df = phase1_profile._read_data(paths.dataset_dir, checkpoint, stage_summary)  # noqa: SLF001
    df = apply_datasynth_label_mode(
        df, source_path=paths.journal_path, mode=getattr(settings, "datasynth_label_mode", "hidden")
    )
    df = phase1_profile._run_features(
        df,
        settings=settings,
        audit_rules=audit_rules,
        risk_keywords=risk_keywords,
        checkpoint=checkpoint,
        summary=stage_summary,
    )  # noqa: SLF001
    detector_results = phase1_profile._run_detectors(
        df, settings=settings, audit_rules=audit_rules, checkpoint=checkpoint, summary=stage_summary
    )  # noqa: SLF001
    # Why: prof._run_detectors는 layer_a/b/c + benford 4트랙만 돈다. 제품 파이프라인
    #      (src/pipeline.py)이 함께 돌리는 evidence(L3-11)·intercompany(IC01-03)·
    #      graph(GR01/03)·variance(D01/02) 트랙이 빠지면 해당 8룰이 case priority
    #      측정에서 통째로 누락된다(도구 사각 ≠ 실제 미탐). detector_catch와 동일하게
    #      보완 트랙을 추가해 전 39룰이 case build에 반영되게 한다.
    from tools.scripts.measure_phase1_detector_catch import _run_extra_detectors

    detector_results = detector_results + _run_extra_detectors(
        df, settings=settings, audit_rules=audit_rules, checkpoint=checkpoint, summary=stage_summary
    )
    df = phase1_profile._aggregate_and_case(
        df,
        detector_results,
        settings=settings,
        data_dir=paths.dataset_dir,
        checkpoint=checkpoint,
        summary=stage_summary,
        cache_path=None,
        stop_after_cache=True,
        batch_id=batch_id,
    )  # noqa: SLF001
    case_start = time.perf_counter()
    # Why(임시 진단): PHASE1_CASE_CPROFILE 환경변수 설정 시 case build만 cProfile로 감싼다.
    #      detector 추적 없이 거대 case 병목 함수를 격리한다. 변수 미설정 시 동작 불변.
    import os as _os

    _case_prof = _os.environ.get("PHASE1_CASE_CPROFILE")
    _pr = None
    if _case_prof:
        import cProfile as _cp

        _pr = _cp.Profile()
        _pr.enable()
    phase1_case_result = build_phase1_case_result(
        df,
        detector_results,
        company_id="_anonymous",
        batch_id=batch_id,
        dataset_id=str(paths.dataset_dir),
        # Why: 빈 설정이면 use_topic_scoring=False로 떨어져 topic floor/머지가 priority에
        #      반영되지 않는 legacy 경로를 측정하게 된다(제품은 yaml 로드). 제품과 동일하게
        #      config/phase1_case.yaml을 로드해 topic scoring 경로를 측정한다.
        phase1_case_config=get_phase1_case(),
    )
    if _pr is not None:
        _pr.disable()
        _pr.dump_stats(_case_prof)
    artifact_path = save_phase1_case_result(phase1_case_result)
    stage_summary["stages"]["phase1_case_builder"] = dict(
        elapsed_sec=round(time.perf_counter() - case_start, 3),
        case_count=len(phase1_case_result.cases),
        unit_count=len(phase1_case_result.units),
        macro_finding_count=int(phase1_case_result.metadata.get("macro_finding_count", 0) or 0),
        artifact_path=str(artifact_path),
    )
    stage_summary["finished_at"] = datetime.now(UTC).isoformat()
    phase1_profile._write_checkpoint(checkpoint, stage_summary)  # noqa: SLF001
    result = SimpleNamespace(
        batch_id=batch_id,
        data=df,
        results=detector_results,
        phase1_case_result=phase1_case_result,
        direct_phase1_checkpoint=str(checkpoint),
        phase1_case_artifact_path=str(artifact_path),
        direct_phase1_stage_summary=stage_summary,
    )
    return result, df


def _read_truth(truth_path: Path | None) -> pd.DataFrame:
    if truth_path is None:
        return pd.DataFrame()
    truth = pd.read_csv(truth_path)
    for column in ("member_document_ids", "base_document_ids"):
        if column in truth.columns:
            truth[column] = truth[column].map(_json_list)
    if "member_document_ids" not in truth.columns:
        truth["member_document_ids"] = [[] for _ in range(len(truth))]
    if "natural_unit_id" not in truth.columns:
        truth["natural_unit_id"] = ""
    return truth


def run_current_phase1(
    dataset_dir: Path, *, output_dir: Path | None = None
) -> tuple[Any, pd.DataFrame]:
    return _run_current_phase1_direct(dataset_dir, output_dir=output_dir)


def _positive_rule_hits(result: Any) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    data = getattr(result, "data", pd.DataFrame())
    doc_series = data.get("document_id") if isinstance(data, pd.DataFrame) else None
    for detector in getattr(result, "results", []) or []:
        details = getattr(detector, "details", None)
        if not isinstance(details, pd.DataFrame) or details.empty:
            continue
        for rule_id in details.columns:
            scores = pd.to_numeric(details[rule_id], errors="coerce").fillna(0.0)
            mask = scores.gt(0)
            if not bool(mask.any()):
                continue
            docs = (
                doc_series.reindex(details.index)
                if doc_series is not None
                else pd.Series("", index=details.index)
            )
            frames.append(
                pd.DataFrame(
                    {
                        "rule_id": str(rule_id),
                        "row_index": details.index[mask].astype(int),
                        "document_id": docs[mask].astype(str).values,
                        "score": scores[mask].astype(float).values,
                        "track_name": getattr(detector, "track_name", ""),
                    }
                )
            )
    if not frames:
        return pd.DataFrame(columns=["rule_id", "row_index", "document_id", "score", "track_name"])
    return pd.concat(frames, ignore_index=True)


def _phase1_units(result: Any) -> list[Any]:
    case_result = getattr(result, "phase1_case_result", None)
    return list(getattr(case_result, "units", []) or [])


def _phase1_cases(result: Any) -> list[Any]:
    case_result = getattr(result, "phase1_case_result", None)
    return list(getattr(case_result, "cases", []) or [])


def _rule_positive_row_count(result, rule_id):
    stage = getattr(result, "direct_phase1_stage_summary", {}) or {}
    stages = stage.get("stages", {}) if isinstance(stage, dict) else {}
    for layer in ("layer_a", "layer_b", "layer_c"):
        payload = stages.get("detector_rules", {}).get(layer, {}).get(rule_id)
        if isinstance(payload, dict) and "flagged_rows" in payload:
            return int(payload.get("flagged_rows") or 0)
    for detector in getattr(result, "results", []) or []:
        details = getattr(detector, "details", None)
        if not isinstance(details, pd.DataFrame) or rule_id not in details.columns:
            continue
        scores = pd.to_numeric(details[rule_id], errors="coerce").fillna(0.0)
        return int(scores.gt(0).sum())
    return 0


def _unit_documents(unit: Any) -> set[str]:
    docs = set(str(doc) for doc in getattr(unit, "member_document_ids", []) or [] if str(doc))
    for hit in getattr(unit, "evidence_rows", []) or []:
        doc = str(getattr(hit, "document_id", "") or "")
        if doc:
            docs.add(doc)
    if getattr(unit, "unit_type", "") == "document" and getattr(unit, "unit_id", ""):
        docs.add(str(getattr(unit, "unit_id")))
    return docs


def _unit_rules(unit: Any) -> set[str]:
    return {
        str(getattr(hit, "rule_id", ""))
        for hit in getattr(unit, "evidence_rows", []) or []
        if getattr(hit, "rule_id", "")
    }


def _case_documents(case: Any) -> set[str]:
    docs = {
        str(getattr(doc, "document_id", ""))
        for doc in getattr(case, "documents", []) or []
        if getattr(doc, "document_id", "")
    }
    for hit in getattr(case, "raw_rule_hits", []) or []:
        doc = str(getattr(hit, "document_id", "") or "")
        if doc:
            docs.add(doc)
    return docs


def _case_rules(case: Any) -> set[str]:
    rules = {
        str(getattr(hit, "rule_id", ""))
        for hit in getattr(case, "raw_rule_hits", []) or []
        if getattr(hit, "rule_id", "")
    }
    for doc in getattr(case, "documents", []) or []:
        rules.update(str(rule) for rule in getattr(doc, "matched_rules", []) or [] if str(rule))
    return rules


def _ranked_units(result: Any) -> list[Any]:
    return sorted(
        _phase1_units(result),
        key=lambda unit: (
            -float(
                getattr(unit, "triage_rank_score", 0.0)
                or getattr(unit, "priority_score", 0.0)
                or 0.0
            ),
            str(getattr(unit, "unit_id", "")),
        ),
    )


def _ranked_cases(result: Any) -> list[Any]:
    return sorted(
        _phase1_cases(result),
        key=lambda case: (
            -float(
                getattr(case, "triage_rank_score", 0.0)
                or getattr(case, "priority_score", 0.0)
                or 0.0
            ),
            str(getattr(case, "case_id", "")),
        ),
    )


def _truth_docs(row: pd.Series) -> set[str]:
    docs = set(str(doc) for doc in row.get("member_document_ids", []) if str(doc))
    natural = str(row.get("natural_unit_id", "") or "")
    if str(row.get("natural_unit_type", "")) == "document" and natural:
        docs.add(natural)
    return docs


def _unit_matches_truth(unit: Any, row: pd.Series) -> bool:
    natural_id = str(row.get("natural_unit_id", "") or "")
    if natural_id and natural_id in {
        str(getattr(unit, "unit_id", "")),
        str(getattr(unit, "flow_id", "")),
    }:
        return True
    docs = _truth_docs(row)
    return bool(docs and docs.intersection(_unit_documents(unit)))


def _case_matches_truth(case: Any, row: pd.Series) -> bool:
    docs = _truth_docs(row)
    return bool(docs and docs.intersection(_case_documents(case)))


def _truth_measurement_rows(truth: pd.DataFrame, result: Any, hits: pd.DataFrame) -> pd.DataFrame:
    if truth.empty:
        return pd.DataFrame()
    units = _ranked_units(result)
    cases = _ranked_cases(result)
    unit_rank = {id(unit): index + 1 for index, unit in enumerate(units)}
    case_rank = {id(case): index + 1 for index, case in enumerate(cases)}

    # Why(성능): truth 행마다 전체 units(17만)·cases(3.8만)·hits 를 선형 스캔하면 O(truth×N)으로
    #      수십 분 병목. 인덱스를 1회 구축해 truth 행당 '후보'만 검사한다. 출력은 count·min(rank) 뿐이고
    #      후보 집합은 dedup(id 기준)되므로 순서 무관 — 기존 full-scan 과 동일 결과(동작 불변).
    unit_docs_cache: dict[int, set[str]] = {}
    unit_rules_cache: dict[int, set[str]] = {}
    units_by_doc: dict[str, list[Any]] = {}
    units_by_natural: dict[str, list[Any]] = {}
    for unit in units:
        uid = id(unit)
        u_docs = _unit_documents(unit)
        unit_docs_cache[uid] = u_docs
        unit_rules_cache[uid] = _unit_rules(unit)
        for doc in u_docs:
            units_by_doc.setdefault(doc, []).append(unit)
        for natural in (str(getattr(unit, "unit_id", "")), str(getattr(unit, "flow_id", ""))):
            if natural:
                units_by_natural.setdefault(natural, []).append(unit)

    case_rules_cache: dict[int, set[str]] = {}
    cases_by_doc: dict[str, list[Any]] = {}
    for case in cases:
        cid = id(case)
        case_rules_cache[cid] = _case_rules(case)
        for doc in _case_documents(case):
            cases_by_doc.setdefault(doc, []).append(case)

    hit_docs_by_rule: dict[str, set[str]] = {}
    rules_in_hits: set[str] = set()
    if not hits.empty:
        for rule_value, doc_value in zip(
            hits["rule_id"].astype(str), hits["document_id"].astype(str), strict=False
        ):
            rules_in_hits.add(rule_value)
            hit_docs_by_rule.setdefault(rule_value, set()).add(doc_value)

    out: list[dict[str, Any]] = []
    for _, row in truth.iterrows():
        rule_id = str(row.get("rule_id", ""))
        docs = _truth_docs(row)
        natural_id = str(row.get("natural_unit_id", "") or "")
        if docs:
            direct_hit = bool(docs & hit_docs_by_rule.get(rule_id, set()))
        else:
            direct_hit = rule_id in rules_in_hits

        # 후보 units: natural_id 일치 ∪ docs 교집합. 둘 다 _unit_matches_truth 를 만족하므로 rule_id 만 필터.
        unit_candidates: dict[int, Any] = {}
        if natural_id:
            for unit in units_by_natural.get(natural_id, ()):  # noqa: SIM118
                unit_candidates[id(unit)] = unit
        for doc in docs:
            for unit in units_by_doc.get(doc, ()):  # noqa: SIM118
                unit_candidates[id(unit)] = unit
        matched_units = [
            unit for uid, unit in unit_candidates.items() if rule_id in unit_rules_cache[uid]
        ]

        # 후보 cases: docs 교집합(_case_matches_truth 는 docs 기반). docs 없으면 후보 없음(기존과 동일).
        case_candidates: dict[int, Any] = {}
        for doc in docs:
            for case in cases_by_doc.get(doc, ()):  # noqa: SIM118
                case_candidates[id(case)] = case
        matched_cases = [
            case for cid, case in case_candidates.items() if rule_id in case_rules_cache[cid]
        ]
        caught = bool(direct_hit or matched_units or matched_cases)
        out.append(
            {
                "rule_id": rule_id,
                "case_kind": str(row.get("case_kind", "")),
                "case_index": row.get("case_index"),
                "natural_unit_type": str(row.get("natural_unit_type", "")),
                "natural_unit_id": str(row.get("natural_unit_id", "")),
                "member_document_count": len(docs),
                "caught": caught,
                "direct_rule_hit": direct_hit,
                "matched_unit_rank": min(
                    (unit_rank[id(unit)] for unit in matched_units), default=None
                ),
                "matched_case_rank": min(
                    (case_rank[id(case)] for case in matched_cases), default=None
                ),
                "matched_unit_count": len(matched_units),
                "matched_case_count": len(matched_cases),
                "expected_surface": row.get("expected_surface", ""),
                "evasion_vector": row.get("evasion_vector", ""),
            }
        )
    return pd.DataFrame(out)


def _rule_summary(
    truth: pd.DataFrame, measurement: pd.DataFrame, hits: pd.DataFrame
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    all_rules = list(RULE_IDS)
    if not truth.empty:
        all_rules = sorted(
            set(all_rules).union(str(rule) for rule in truth["rule_id"].dropna().unique())
        )
    emitted = hits.groupby("rule_id")["document_id"].nunique().to_dict() if not hits.empty else {}
    for rule_id in all_rules:
        if truth.empty:
            input_units = standard_input = evasion_input = caught = standard_caught = (
                evasion_caught
            ) = 0
        else:
            subset = measurement[measurement["rule_id"].astype(str).eq(rule_id)]
            input_units = int(len(subset))
            standard = subset[subset["case_kind"].eq("standard")]
            evasion = subset[subset["case_kind"].eq("evasion")]
            standard_input = int(len(standard))
            evasion_input = int(len(evasion))
            caught = int(subset["caught"].sum())
            standard_caught = int(standard["caught"].sum())
            evasion_caught = int(evasion["caught"].sum())
        rows.append(
            {
                "rule_id": rule_id,
                "input_units": input_units,
                "emitted_units": int(emitted.get(rule_id, 0)),
                "caught_units": caught,
                "standard_input": standard_input,
                "standard_caught": standard_caught,
                "standard_missed": standard_input - standard_caught,
                "evasion_input": evasion_input,
                "evasion_caught": evasion_caught,
                "evasion_missed_phase2": evasion_input - evasion_caught,
            }
        )
    return pd.DataFrame(rows)


def _priority_band_summary(result: Any) -> dict:
    """PHASE1 priority_band(high/medium/low) 분포 + 광역발화 룰별 high/medium 기여.

    Why: PHASE1 결과를 detector 발화율(row)만으로 판단하면 검토모집단 룰(L3-12·L1-07 등 광역 발화)을
         과탐으로 오인한다. 실제 감사인 부담은 case/unit의 high/medium 우선순위 비율이므로, PHASE1
         결과를 낼 때 항상 함께 산출한다. 정상 데이터는 high/medium 0이 기대값(광역 row 발화는 low로
         차등). high_medium_rules가 비어있지 않으면 어떤 룰이 우선순위를 올렸는지 룰별로 드러난다.
    """

    def _dist(items: list[Any]) -> dict:
        counts = {"high": 0, "medium": 0, "low": 0}
        for item in items:
            band = str(getattr(item, "priority_band", "low") or "low")
            counts[band] = counts.get(band, 0) + 1
        return counts

    cases = _phase1_cases(result)
    rule_band: dict[str, dict[str, int]] = {}
    for case in cases:
        band = str(getattr(case, "priority_band", "low") or "low")
        for rule in _case_rules(case):
            entry = rule_band.setdefault(rule, {"cases": 0, "high": 0, "medium": 0})
            entry["cases"] += 1
            if band in ("high", "medium"):
                entry[band] += 1
    high_medium_rules = {
        rule: entry for rule, entry in rule_band.items() if entry["high"] > 0 or entry["medium"] > 0
    }
    return dict(
        priority_band_units=_dist(_phase1_units(result)),
        priority_band_cases=_dist(cases),
        priority_band_high_medium_rule_count=len(high_medium_rules),
        priority_band_high_medium_rules=high_medium_rules,
    )


def _summary(result, truth, measurement, hits, elapsed):
    units = _phase1_units(result)
    l304_units = [unit for unit in units if "L3-04" in _unit_rules(unit)]
    row_count = int(len(getattr(result, "data", [])))
    l304_rows = _rule_positive_row_count(result, "L3-04")
    return dict(
        generated_at=datetime.now(UTC).isoformat(),
        elapsed_sec=round(elapsed, 3),
        batch_id=getattr(result, "batch_id", ""),
        rows=row_count,
        phase1_case_count=int(len(_phase1_cases(result))),
        phase1_unit_count=int(len(units)),
        phase1_raw_hit_count=int(len(hits)),
        truth_units=int(len(truth)),
        caught_truth_units=int(measurement["caught"].sum()) if not measurement.empty else 0,
        missed_truth_units=int((~measurement["caught"]).sum()) if not measurement.empty else 0,
        l3_04_row_count=l304_rows,
        l3_04_row_rate=round(l304_rows / row_count, 6) if row_count else 0.0,
        l3_04_unit_count=int(len(l304_units)),
        phase1_case_artifact_path=getattr(result, "phase1_case_artifact_path", ""),
        direct_phase1_checkpoint=getattr(result, "direct_phase1_checkpoint", ""),
        baseline_case_count=int(len(_phase1_cases(result))) if truth.empty else None,
        baseline_new_truth_units=0 if truth.empty else None,
        **_priority_band_summary(result),
    )


def _save_outputs(paths, summary, rule_summary, measurement, hits):
    paths.output_dir.mkdir(parents=True, exist_ok=True)
    enc = "utf-8"
    _emit_text(
        paths.output_dir / "summary.json",
        json.dumps(summary, ensure_ascii=False, indent=2) + chr(10),
    )
    rule_summary.to_csv(paths.output_dir / "rule_summary.csv", index=False, encoding=enc)
    measurement.to_csv(paths.output_dir / "truth_unit_measurement.csv", index=False, encoding=enc)
    hits.to_csv(paths.output_dir / "rule_hits.csv", index=False, encoding=enc)
    _emit_text(paths.output_dir / "measurement.md", rule_summary.to_markdown(index=False) + chr(10))


def measure_dataset(dataset_dir: Path, *, output_dir: Path | None = None):
    paths = _resolve_paths(dataset_dir, output_dir)
    truth = _read_truth(paths.truth_path)
    start = time.perf_counter()
    result, _prep_df = run_current_phase1(paths.dataset_dir, output_dir=paths.output_dir)
    elapsed = time.perf_counter() - start
    hits = _positive_rule_hits(result)
    measurement = _truth_measurement_rows(truth, result, hits)
    rules = _rule_summary(truth, measurement, hits)
    summary = _summary(result, truth, measurement, hits, elapsed)
    _save_outputs(paths, summary, rules, measurement, hits)
    return {
        "summary": summary,
        "output_dir": str(paths.output_dir),
        "rule_summary": rules,
        "measurement": measurement,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset_dir", type=Path)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--expect-truth-units", type=int, default=None)
    args = parser.parse_args(argv)
    paths = _resolve_paths(args.dataset_dir, args.output_dir)
    truth = _read_truth(paths.truth_path)
    if args.expect_truth_units is not None and len(truth) != args.expect_truth_units:
        raise SystemExit(
            f"truth unit count mismatch: expected {args.expect_truth_units}, got {len(truth)}"
        )
    print(
        "[measure] current PHASE1 run may take 10+ minutes on full semantic_v1 P3-2 datasets",
        flush=True,
    )
    result = measure_dataset(args.dataset_dir, output_dir=args.output_dir)
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2), flush=True)
    print("[measure] outputs: " + result["output_dir"], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
