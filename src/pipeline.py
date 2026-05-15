# ruff: noqa: E501
"""감사 파이프라인 오케스트레이터 — Ingest → Validate → Feature → Detection → DB."""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from src.context import CompanyContext, ContextFactory
from src.detection.base import BaseDetector, DetectionResult
from src.detection.constants import DETECTOR_DISPLAY_ORDER, get_detector_profile
from src.export.audit_trail import AuditEvent, AuditTrailProtocol
from src.ingest.datasynth_labels import (
    apply_datasynth_label_mode,
    get_source_path,
    load_document_labels,
    set_source_path,
)
from src.ingest.datasynth_metadata import (
    apply_validated_metadata_attrs,
    build_validated_metadata_messages,
    load_validated_metadata_json,
)
from src.llm.models import CaseNarrative
from src.metrics.models import PerformanceReport
from src.models.phase1_case import Phase1CaseResult
from src.services.phase2_case_contract import build_phase2_case_overlays

logger = logging.getLogger(__name__)


class _NullAuditTrail:
    """audit_trail 미주입 시 사용하는 no-op 구현체.

    Why: 기존 테스트·CLI 경로에서 AuditTrail 주입 없이 AuditPipeline을 쓰는
         호출부를 수정하지 않고도 단계별 로깅 지점을 일관되게 유지하기 위함.
         AuditTrailProtocol을 암묵적으로 만족 — duck typing 대신 Protocol로
         타입 체커가 시그니처 변경을 잡을 수 있다.
    """

    def log(self, event: AuditEvent) -> None:  # noqa: ARG002 — 인터페이스 호환
        return None
_TEXT_EXT = frozenset({".csv", ".tsv", ".txt", ".dat"})
_EXCEL_EXT = frozenset({".xlsx", ".xls", ".xlsb"})
_INGEST_CACHE_SCHEMA_VERSION = "ingest-cache-v1"


def _run_detectors_parallel(
    detectors: list[BaseDetector],
    df: pd.DataFrame,
    max_workers: int | None = None,
    progress_callback=None,
) -> tuple[list[DetectionResult], list[str]]:
    """독립 탐지기 집합을 병렬 실행 + 탐지기별 elapsed 수집 + 진행 콜백 호출.

    Why:
    - pandas/numpy 내부 연산은 C 레벨에서 GIL 해제 → ThreadPoolExecutor로 충분.
      ProcessPool은 DataFrame pickle 비용(100만 행 기준 수 초)으로 오히려 느림.
    - max_workers=None 또는 1이면 순차 실행 (테스트/디버깅 모드).
    - 각 탐지기의 metadata["elapsed"]는 탐지기 스스로 기록 중이므로 별도 수집 불필요.
    - progress_callback(completed, total, track_name)로 Streamlit st.progress 연동 가능.
    - 한 탐지기 실패가 전체를 막지 않도록 per-detector try/except로 격리.
    - 결과 순서는 입력 `detectors` 순서로 정렬 (병렬 완료 순 아님) — downstream
      로직이 detector 순서에 의존하는 경우 안전성 확보.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    results: list[DetectionResult | None] = [None] * len(detectors)
    warns: list[str] = []
    total = len(detectors)

    def _run_one(idx: int, det: BaseDetector) -> tuple[int, DetectionResult | None, str | None]:
        t0 = time.perf_counter()
        try:
            result = det.detect(df)
            # Why: 탐지기가 metadata에 elapsed를 안 넣은 경우만 보강
            if result.metadata is None:
                result.metadata = {}
            profile = get_detector_profile(det.track_name)
            result.metadata.setdefault("display_name", profile.display_name)
            result.metadata.setdefault("maturity", str(profile.maturity))
            result.metadata.setdefault("default_enabled", profile.default_enabled)
            result.metadata.setdefault("activation_requirements", list(profile.activation_requirements))
            result.metadata.setdefault("run_status", "executed")
            result.metadata.setdefault("elapsed", time.perf_counter() - t0)
            return idx, result, None
        except Exception as exc:
            logger.warning("detector failed: %s (%s)", det.track_name, exc, exc_info=True)
            return idx, None, f"detector_failed:{det.track_name}"

    # Why: max_workers가 None/1이거나 탐지기 1개 이하면 순차 — 오버헤드 회피
    if not max_workers or max_workers <= 1 or total <= 1:
        for idx, det in enumerate(detectors):
            _, res, warn = _run_one(idx, det)
            if res is not None:
                results[idx] = res
            if warn is not None:
                warns.append(warn)
            if progress_callback is not None:
                try:
                    progress_callback(idx + 1, total, det.track_name)
                except Exception:
                    logger.debug("progress_callback 호출 실패", exc_info=True)
    else:
        # 병렬 실행
        completed = 0
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = {
                ex.submit(_run_one, idx, det): (idx, det)
                for idx, det in enumerate(detectors)
            }
            for fut in as_completed(futures):
                idx, res, warn = fut.result()
                if res is not None:
                    results[idx] = res
                if warn is not None:
                    warns.append(warn)
                completed += 1
                if progress_callback is not None:
                    try:
                        progress_callback(
                            completed, total, detectors[idx].track_name,
                        )
                    except Exception:
                        logger.debug("progress_callback 호출 실패", exc_info=True)

    # Why: None(실패) 제거하고 원본 순서 유지
    return [r for r in results if r is not None], warns


def collect_detection_profile(
    results: list[DetectionResult],
) -> dict[str, float]:
    """탐지기별 elapsed 수집 — 병렬화 이득 프로파일링용.

    Why: DetectionResult.metadata["elapsed"]를 track_name으로 집계하여
         "어느 탐지기가 병목인지" 정량 파악. ThreadPoolExecutor 병렬화 이득은
         Amdahl's law에 따라 가장 느린 탐지기에 수렴하므로 프로파일링이 필수.

    Returns:
        {track_name: elapsed_seconds}. elapsed 누락 시 0.0.
    """
    profile: dict[str, float] = {}
    for r in results:
        meta = r.metadata or {}
        profile[r.track_name] = float(meta.get("elapsed", 0.0))
    return profile


def format_detection_profile(profile: dict[str, float]) -> str:
    """프로파일 딕셔너리 → 사람이 읽을 수 있는 표 문자열.

    예시:
        | track_name        | elapsed(s) | share |
        | ----------------- | ---------- | ----- |
        | ml_sequence       |     12.45  |  48%  |
        | layer_b           |      5.30  |  21%  |
        ...
    """
    if not profile:
        return "(탐지기 프로파일 없음)"
    total = sum(profile.values()) or 1.0
    rows = sorted(profile.items(), key=lambda kv: kv[1], reverse=True)
    lines = [
        "| track_name          | elapsed(s) | share |",
        "| ------------------- | ---------- | ----- |",
    ]
    for name, elapsed in rows:
        share = elapsed / total * 100
        lines.append(
            f"| {name:<19} | {elapsed:>10.3f} | {share:>4.1f}% |",
        )
    lines.append(f"**Total**: {total:.3f}s")
    return "\n".join(lines)


def format_phase1_rule_coverage(results: list[DetectionResult]) -> str:
    """Render detector metadata about skipped or partially covered PHASE1 checks."""

    lines: list[str] = []
    for result in results:
        metadata = result.metadata or {}
        skipped_rules = [str(rule_id) for rule_id in metadata.get("skipped_rules", [])]
        coverage_issues = metadata.get("coverage_issues", [])
        if skipped_rules:
            lines.append(f"{result.track_name}: skipped {', '.join(skipped_rules)}")
        if not isinstance(coverage_issues, list):
            continue
        for issue in coverage_issues:
            if not isinstance(issue, dict):
                continue
            rule_id = str(issue.get("rule_id", "unknown_rule"))
            kind = str(issue.get("kind", "coverage_issue"))
            inputs = issue.get("missing_inputs") or issue.get("low_coverage_inputs") or []
            input_text = ", ".join(str(value) for value in inputs) if inputs else "unknown_input"
            if kind == "missing_prerequisites":
                lines.append(f"{result.track_name}: {rule_id} skipped - missing {input_text}")
                continue
            if kind == "partial_input_coverage":
                ratio = issue.get("coverage_ratio")
                ratio_text = ""
                if ratio is not None:
                    ratio_text = f" ({float(ratio) * 100:.1f}%)"
                subcheck = str(issue.get("subcheck", "")).strip()
                subcheck_text = f" {subcheck}" if subcheck else ""
                lines.append(
                    f"{result.track_name}: {rule_id} partial{subcheck_text} - {input_text}{ratio_text}"
                )
                continue
            lines.append(f"{result.track_name}: {rule_id} {kind} - {input_text}")
    return "\n".join(lines)


def _detector_result_warnings(results: list[DetectionResult]) -> list[str]:
    warnings: list[str] = []
    for result in results:
        warnings.extend(str(warning) for warning in (result.warnings or []))
    coverage = format_phase1_rule_coverage(results)
    if coverage:
        warnings.append(f"[분석범위제한]\n{coverage}")
    return warnings


@dataclass
class PipelineResult:
    """전체 파이프라인 실행 결과."""
    data: pd.DataFrame
    results: list[DetectionResult]
    risk_summary: dict[str, int]
    batch_id: str
    load_result: object | None
    elapsed: float
    warnings: list[str] = field(default_factory=list)
    # Why: 재탐지 시 피처 생성 단계를 건너뛰기 위해 피처 완료 시점 DF 캐싱
    featured_data: pd.DataFrame | None = field(default=None, repr=False)
    # Why: DB upload_batches 메타 적재 시 파일명 전달 (리뷰 피드백 #3 — 시그니처 오염 방지)
    file_name: str = ""
    # Why: SHAP 기여도 — flagged rows(anomaly_score ≥ threshold)만 계산.
    #      key: document_id, value: {feature_name: shap_value} top-5.
    #      ML 모델 없음/Cold Start 시 None.
    shap_contributions: dict[str, dict[str, float]] | None = field(default=None, repr=False)
    # Why: Waterfall 차트 시작점 — 모델의 expected_value. None이면 SHAP 미산출.
    shap_base_value: float | None = None
    detector_statuses: list[dict] = field(default_factory=list, repr=False)
    performance_report: PerformanceReport | None = field(default=None, repr=False)
    phase1_case_result: Phase1CaseResult | None = field(default=None, repr=False)
    phase1_case_path: str | None = None
    phase1_case_run_id: str | None = None
    phase1_case_count: int = 0
    phase1_macro_finding_count: int = 0
    phase1_top_theme_ids: list[str] = field(default_factory=list)
    phase2_case_overlays: list[dict] = field(default_factory=list, repr=False)
    phase3_case_narratives: list[CaseNarrative] = field(default_factory=list, repr=False)


class AuditPipeline:
    """감사 파이프라인 오케스트레이터."""

    def __init__(
        self,
        context: CompanyContext | None = None,
        settings=None,
        *,
        skip_db: bool = False,
        conn=None,
        progress_callback=None,
        repo=None,
        audit_trail: AuditTrailProtocol | None = None,
    ) -> None:
        # Why: context 우선 → settings 폴백 → anonymous 폴백 (하위 호환)
        if context is not None:
            self._ctx = context
        elif settings is not None:
            self._ctx = ContextFactory.from_settings(settings)
        else:
            self._ctx = ContextFactory.create_anonymous()
        self._settings = self._ctx.settings
        self._skip_db = skip_db
        self._conn = conn
        # Why: 대시보드에서 st.progress 연동용. (pct: float, msg: str) → None
        self._progress = progress_callback or (lambda pct, msg: None)
        # Why: Layer D(전기 대비 변동 탐지)에서 전기 engagement 탐색용.
        #      None이면 Layer D 자동 스킵 (하위 호환).
        self._repo = repo
        # Why: WU-13 TB 교차검증 — _validate()에서 생성, _load_db()에서 적재
        self._tb_df: pd.DataFrame | None = None
        # Why: audit_trail 미주입 시 no-op. 호출 지점에 분기 없이 동일 log() 호출 가능.
        self._audit = audit_trail or _NullAuditTrail()
        self._detector_statuses: dict[str, dict] = {}

    def _make_batch_id(self) -> str:
        """engagement 접두사 포함 batch_id 생성."""
        eid = self._ctx.engagement_id
        if self._ctx.is_anonymous:
            return uuid.uuid4().hex[:8]
        # Why: engagement_id에 "-", "/" 등 특수문자 → 파일 경로/SQL 에러 방지
        safe_eid = re.sub(r"[^a-zA-Z0-9]", "_", eid)
        return f"{safe_eid}_{uuid.uuid4().hex[:8]}"

    def _log_event(
        self,
        *,
        event_type: str,
        user_action: str,
        batch_id: str,
        details: dict | None = None,
    ) -> None:
        """AuditTrail.log graceful 래퍼 — 로깅 실패가 파이프라인을 막지 않는다.

        Why: 감사 증적은 보조 산출물이므로 기록 실패가 분석 차단 사유가 되면 안 됨.
             _NullAuditTrail은 예외를 던지지 않으나, 실제 AuditTrail이 DB 에러를 낼
             수 있으므로 방어적으로 감싼다.
        """
        try:
            ctx = self._ctx
            event = AuditEvent(
                event_type=event_type,  # type: ignore[arg-type]
                user_action=user_action,
                details=details or {},
                batch_id=batch_id,
                company_id=ctx.company_id if not ctx.is_anonymous else None,
                engagement_id=ctx.engagement_id if not ctx.is_anonymous else None,
            )
            self._audit.log(event)
        except Exception:  # pragma: no cover — 방어적
            logger.warning("AuditTrail.log 실패 (무시)", exc_info=True)

    def _reset_detector_statuses(self) -> None:
        """탐지기별 운영 상태 스냅샷 초기화."""
        self._detector_statuses = {}
        for track_name in DETECTOR_DISPLAY_ORDER:
            profile = get_detector_profile(str(track_name))
            self._detector_statuses[str(track_name)] = {
                "track_name": str(track_name),
                "display_name": profile.display_name,
                "maturity": str(profile.maturity),
                "default_enabled": profile.default_enabled,
                "activation_requirements": list(profile.activation_requirements),
                "run_status": "not_in_path",
                "reason": "not part of current inference path",
                "flagged_docs": 0,
                "rules_run": 0,
                "elapsed_sec": 0.0,
            }

    def _record_detector_status(
        self,
        track_name: str,
        *,
        run_status: str,
        reason: str | None = None,
        result: DetectionResult | None = None,
    ) -> None:
        """탐지기 실행 상태를 공통 구조로 수집."""
        if not hasattr(self, "_detector_statuses"):
            self._reset_detector_statuses()
        profile = get_detector_profile(track_name)
        status = self._detector_statuses.get(track_name, {
            "track_name": track_name,
            "display_name": profile.display_name,
            "maturity": str(profile.maturity),
            "default_enabled": profile.default_enabled,
            "activation_requirements": list(profile.activation_requirements),
            "flagged_docs": 0,
            "rules_run": 0,
            "elapsed_sec": 0.0,
        })
        status["run_status"] = run_status
        status["reason"] = reason
        if result is not None:
            status["flagged_docs"] = result.flagged_count
            status["rules_run"] = result.total_rules_run
            status["elapsed_sec"] = round(result.elapsed_seconds, 3)
            for key in (
                "registry_version",
                "saved_model_name",
                "model_name",
                "sub_detector_keys",
                "contract_version",
                "loaded_version",
                "matrix_schema_hash",
            ):
                if key in result.metadata:
                    status[key] = result.metadata.get(key)
            result.metadata["run_status"] = run_status
            if reason is not None:
                result.metadata["skip_reason"] = reason
        self._detector_statuses[track_name] = status
        logger.info(
            "detector_status track=%s maturity=%s default_enabled=%s status=%s reason=%s",
            track_name,
            status["maturity"],
            status["default_enabled"],
            run_status,
            reason or "-",
        )

    def _get_detector_statuses(self) -> list[dict]:
        """현재 배치의 탐지기 상태 스냅샷 반환."""
        statuses = list(self._detector_statuses.values())
        order = {str(name): idx for idx, name in enumerate(DETECTOR_DISPLAY_ORDER)}
        return sorted(statuses, key=lambda item: order.get(item["track_name"], 999))

    def _build_performance_report(
        self,
        *,
        df: pd.DataFrame,
        agg_df: pd.DataFrame,
        results: list[DetectionResult],
        batch_id: str,
    ) -> PerformanceReport:
        """Ground-truth가 있으면 GT 리포트, 없으면 운영 프록시 리포트 생성."""
        labels = None
        source_path = get_source_path(df)
        if source_path is not None:
            labels = load_document_labels(source_path)

        if labels is not None and not labels.empty and "anomaly_type" in labels.columns:
            from src.metrics.ground_truth_evaluator import build_ground_truth_report

            return build_ground_truth_report(
                df,
                agg_df,
                results,
                labels,
                upload_batch_id=batch_id,
            )

        from src.metrics.operational_evaluator import evaluate_operational_report

        return evaluate_operational_report(
            df,
            upload_batch_id=batch_id,
        )

    def run(self, path: str | Path) -> PipelineResult:
        """파일 경로 → 전체 파이프라인 실행."""
        start = time.monotonic()
        warns: list[str] = []
        df, w = self._ingest(path)
        warns.extend(w)
        fname = Path(path).name
        result = self._execute(
            df, self._make_batch_id(), start, warns, file_name=fname,
        )
        result.file_name = fname
        return result

    def run_from_dataframe(
        self, df: pd.DataFrame, *, file_name: str = "",
    ) -> PipelineResult:
        """DataFrame 직접 입력 (ingest 생략).

        Why: 외부 df 원본 보호를 위해 copy() 후 파이프라인 진입.
        """
        work_df = df.copy()
        if file_name:
            work_df = set_source_path(work_df, file_name)
            work_df = apply_datasynth_label_mode(
                work_df,
                source_path=file_name,
                mode=getattr(self._ctx.settings, "datasynth_label_mode", "hidden"),
            )
            metadata_warnings = self._apply_datasynth_metadata_policy(work_df, file_name)
        else:
            metadata_warnings = []
        result = self._execute(
            work_df, self._make_batch_id(), time.monotonic(), metadata_warnings,
            file_name=file_name,
        )
        result.file_name = file_name
        return result

    def prepare_from_dataframe(
        self, df: pd.DataFrame, *, file_name: str = "",
    ) -> PipelineResult:
        """탐지 전 단계까지만 수행하여 준비 결과를 반환."""
        start = time.monotonic()
        warns: list[str] = []
        load_result = None
        work_df = df.copy()
        if file_name:
            work_df = set_source_path(work_df, file_name)
            work_df = apply_datasynth_label_mode(
                work_df,
                source_path=file_name,
                mode=getattr(self._ctx.settings, "datasynth_label_mode", "hidden"),
            )
            warns.extend(self._apply_datasynth_metadata_policy(work_df, file_name))

        batch_id = self._make_batch_id()
        self._reset_detector_statuses()
        self._log_event(
            event_type="upload",
            user_action="파일 적재 완료",
            batch_id=batch_id,
            details={"file_name": file_name, "records": int(len(work_df))},
        )

        self._progress(0.30, "데이터 검증 중...")
        work_df, w = self._validate(work_df)
        warns.extend(w)
        self._log_event(
            event_type="validate",
            user_action="스키마/회계 검증 완료",
            batch_id=batch_id,
            details={"records": int(len(work_df)), "warnings": len(w)},
        )

        self._progress(0.55, "사전 피처 생성 중...")
        work_df, w = self._generate_features(work_df)
        warns.extend(w)
        featured_snapshot = work_df.copy()
        if not self._skip_db:
            load_result, w = self._load_db(
                work_df,
                batch_id,
                [],
                file_name=file_name,
            )
            warns.extend(w)

        self._progress(1.0, "준비 완료")
        elapsed = time.monotonic() - start
        result = PipelineResult(
            data=work_df,
            results=[],
            risk_summary={},
            batch_id=batch_id,
            load_result=load_result,
            elapsed=elapsed,
            warnings=warns,
            featured_data=featured_snapshot,
            file_name=file_name,
            detector_statuses=self._get_detector_statuses(),
        )
        return result

    def redetect(
        self,
        df: pd.DataFrame,
        batch_id: str = "",
        weights: dict[str, float] | None = None,
        thresholds: dict[str, float] | None = None,
        *,
        file_name: str = "",
        detection_scope: str = "default",
        phase2_inference_contract: dict | None = None,
    ) -> PipelineResult:
        """피처 생성 완료 DF에서 detection + aggregate만 재실행.

        Why: 설정 변경 후 재탐지 시 _generate_features 중복 실행을 방지하여
             컬럼 충돌(_x, _y) 및 데이터 오염 차단.
        """
        start = time.monotonic()
        df = df.copy()
        previous_phase2_contract = getattr(self, "_phase2_inference_contract", None)
        self._phase2_inference_contract = phase2_inference_contract
        try:
            results, warns = self._run_detection(df, detection_scope=detection_scope)
        finally:
            self._phase2_inference_contract = previous_phase2_contract
        warns.extend(_detector_result_warnings(results))

        # Why: weights 미지정 시 ML/Layer D 유무에 따라 가중치 자동 선택
        if weights is None:
            weights = self._select_weights(results)

        from src.detection.score_aggregator import aggregate_scores
        stacking_scores = None
        if detection_scope != "phase2_only":
            stacking_scores = self._try_stacking_ensemble(results, df)
        agg_df = aggregate_scores(
            df, results, weights=weights, thresholds=thresholds,
            settings=self._settings, stacking_scores=stacking_scores,
        )
        for col in agg_df.columns:
            df[col] = agg_df[col].values

        # Why: 재탐지에서도 SHAP 재산출 — 설정 변경 시 flagged rows가 달라질 수 있음
        bid = batch_id or self._make_batch_id()
        shap_contributions, shap_base_value = self._try_shap_explanation(df)
        performance_report = self._build_performance_report(
            df=df,
            agg_df=agg_df,
            results=results,
            batch_id=bid,
        )
        phase1_case_result, phase1_case_ref = self._build_phase1_case_artifact(
            df,
            results,
            batch_id=bid,
        )
        if phase1_case_ref.get("phase1_case_warning"):
            warns.append(str(phase1_case_ref["phase1_case_warning"]))
        detector_statuses = self._get_detector_statuses()
        phase2_case_overlays = self._build_phase2_case_overlays(
            phase1_case_result,
            detector_statuses=detector_statuses,
        )

        load_result = None
        if not self._skip_db:
            self._progress(0.90, "DB 적재 중...")
            load_result, w = self._load_db(
                df,
                bid,
                results,
                file_name=file_name,
                performance_report=performance_report,
                phase1_case_ref=phase1_case_ref,
            )
            warns.extend(w)

        risk_summary = df["risk_level"].value_counts().to_dict() if "risk_level" in df.columns else {}
        elapsed = time.monotonic() - start
        # Why: 재탐지 연속성 — 설정 변경으로 risk_level 분포가 달라졌음을 증적에 남김
        self._log_event(
            event_type="analysis",
            user_action="재탐지 실행",
            batch_id=bid,
            details={"tracks": len(results), "warnings": len(warns)},
        )
        logger.info("재탐지 완료: %.2fs, batch=%s", elapsed, bid)
        return PipelineResult(
            data=df, results=results, risk_summary=risk_summary,
            batch_id=bid, load_result=load_result, elapsed=elapsed, warnings=warns,
            featured_data=df.copy(), file_name=file_name,
            shap_contributions=shap_contributions, shap_base_value=shap_base_value,
            detector_statuses=detector_statuses,
            performance_report=performance_report,
            phase1_case_result=phase1_case_result,
            phase1_case_path=phase1_case_ref.get("phase1_case_path"),
            phase1_case_run_id=phase1_case_ref.get("phase1_case_run_id"),
            phase1_case_count=int(phase1_case_ref.get("phase1_case_count", 0)),
            phase1_macro_finding_count=int(
                phase1_case_ref.get("phase1_macro_finding_count", 0)
            ),
            phase1_top_theme_ids=list(phase1_case_ref.get("top_theme_ids", [])),
            phase2_case_overlays=phase2_case_overlays,
        )

    def _execute(
        self, df: pd.DataFrame, batch_id: str, start: float, warns: list[str],
        *, file_name: str = "",
    ) -> PipelineResult:
        """validate → feature → detection → aggregate → db."""
        # Why: ingest 완료 직후 사후 로깅 — batch_id가 _make_batch_id()로 확정된 시점.
        self._log_event(
            event_type="upload",
            user_action="파일 적재 완료",
            batch_id=batch_id,
            details={"file_name": file_name, "records": int(len(df))},
        )

        _t = time.monotonic()
        self._progress(0.30, "데이터 검증 중...")
        df, w = self._validate(df)
        warns.extend(w)
        logger.warning("[TIMING] validate: %.1fs", time.monotonic() - _t)
        self._log_event(
            event_type="validate",
            user_action="스키마·회계 검증 완료",
            batch_id=batch_id,
            details={"records": int(len(df)), "warnings": len(w)},
        )

        _t = time.monotonic()
        self._progress(0.45, "피처 생성 중...")
        df, w = self._generate_features(df)
        warns.extend(w)
        logger.warning("[TIMING] features: %.1fs", time.monotonic() - _t)

        # Why: 재탐지(redetect)용 클린 DF 스냅샷 — detection 결과 컬럼 미포함 상태
        _t = time.monotonic()
        featured_snapshot = df.copy()
        logger.warning("[TIMING] df.copy snapshot: %.1fs", time.monotonic() - _t)

        _t = time.monotonic()
        self._progress(0.65, "탐지 룰 실행 중...")
        results, w = self._run_detection(df)
        warns.extend(w)
        warns.extend(_detector_result_warnings(results))
        logger.warning("[TIMING] detection: %.1fs", time.monotonic() - _t)
        self._log_event(
            event_type="analysis",
            user_action="탐지 룰 실행 완료",
            batch_id=batch_id,
            details={"tracks": len(results), "warnings": len(w)},
        )

        _t = time.monotonic()
        self._progress(0.80, "점수 집계 중...")
        # Why: aggregate_scores는 별도 DF 반환. .values로 인덱스 불일치 방어.
        from src.detection.score_aggregator import aggregate_scores
        stacking_scores = self._try_stacking_ensemble(results, df)
        weights = self._select_weights(results)
        agg_df = aggregate_scores(
            df, results, weights=weights, stacking_scores=stacking_scores,
        )
        for col in agg_df.columns:
            df[col] = agg_df[col].values
        logger.warning("[TIMING] aggregate: %.1fs", time.monotonic() - _t)

        # Why: anomaly_score 산출 이후 SHAP 계산 — flagged rows만 대상으로 하기 위함
        _t = time.monotonic()
        shap_contributions, shap_base_value = self._try_shap_explanation(df)
        logger.warning("[TIMING] shap: %.1fs", time.monotonic() - _t)
        performance_report = self._build_performance_report(
            df=df,
            agg_df=agg_df,
            results=results,
            batch_id=batch_id,
        )
        phase1_case_result, phase1_case_ref = self._build_phase1_case_artifact(
            df,
            results,
            batch_id=batch_id,
        )
        if phase1_case_ref.get("phase1_case_warning"):
            warns.append(str(phase1_case_ref["phase1_case_warning"]))
        detector_statuses = self._get_detector_statuses()
        phase2_case_overlays = self._build_phase2_case_overlays(
            phase1_case_result,
            detector_statuses=detector_statuses,
        )

        load_result = None
        if not self._skip_db:
            _t = time.monotonic()
            self._progress(0.90, "DB 적재 중...")
            load_result, w = self._load_db(
                df, batch_id, results,
                file_name=file_name,
                performance_report=performance_report,
                phase1_case_ref=phase1_case_ref,
            )
            warns.extend(w)
            logger.warning("[TIMING] db_load: %.1fs", time.monotonic() - _t)
            # Why: event_type Literal 6종 제약상 "analysis" 재사용. user_action으로 구분.
            self._log_event(
                event_type="analysis",
                user_action="DB 적재 완료",
                batch_id=batch_id,
                details={
                    "rows_inserted": (
                        getattr(load_result, "rows_inserted", None)
                        if load_result is not None else None
                    ),
                },
            )

        risk_summary = df["risk_level"].value_counts().to_dict() if "risk_level" in df.columns else {}
        elapsed = time.monotonic() - start
        self._progress(1.0, "완료!")
        logger.info("파이프라인 완료: %.2fs, batch=%s", elapsed, batch_id)
        return PipelineResult(
            data=df, results=results, risk_summary=risk_summary,
            batch_id=batch_id, load_result=load_result, elapsed=elapsed, warnings=warns,
            featured_data=featured_snapshot,
            shap_contributions=shap_contributions, shap_base_value=shap_base_value,
            detector_statuses=detector_statuses,
            performance_report=performance_report,
            phase1_case_result=phase1_case_result,
            phase1_case_path=phase1_case_ref.get("phase1_case_path"),
            phase1_case_run_id=phase1_case_ref.get("phase1_case_run_id"),
            phase1_case_count=int(phase1_case_ref.get("phase1_case_count", 0)),
            phase1_macro_finding_count=int(
                phase1_case_ref.get("phase1_macro_finding_count", 0)
            ),
            phase1_top_theme_ids=list(phase1_case_ref.get("top_theme_ids", [])),
            phase2_case_overlays=phase2_case_overlays,
        )

    def _build_phase1_case_artifact(
        self,
        df: pd.DataFrame,
        results: list[DetectionResult],
        *,
        batch_id: str,
    ) -> tuple[Phase1CaseResult | None, dict[str, object]]:
        try:
            from src.detection.phase1_case_builder import (
                annotate_detection_results_with_phase1_refs,
                build_phase1_case_reference,
                build_phase1_case_result,
                save_phase1_case_result,
            )

            phase1_case_config = copy.deepcopy(self._ctx.phase1_case)
            phase1_case_config.setdefault("phase1_case", {}).setdefault(
                "materiality_amount",
                float(getattr(self._ctx, "materiality_amount", 0.0) or 0.0),
            )
            phase1_result = build_phase1_case_result(
                df,
                results,
                company_id=self._ctx.company_id,
                batch_id=batch_id,
                dataset_id=batch_id,
                phase1_case_config=phase1_case_config,
            )
            artifact_path = save_phase1_case_result(phase1_result)
            annotate_detection_results_with_phase1_refs(results, phase1_result, artifact_path)
            return phase1_result, build_phase1_case_reference(phase1_result, artifact_path)
        except Exception as exc:
            logger.warning("PHASE1 case artifact build failed — skip", exc_info=True)
            return None, {"phase1_case_warning": f"PHASE1 case artifact build failed: {exc}"}

    def _build_phase2_case_overlays(
        self,
        phase1_case_result: Phase1CaseResult | None,
        *,
        detector_statuses: list[dict],
    ) -> list[dict]:
        return build_phase2_case_overlays(
            phase1_case_result,
            detector_statuses=detector_statuses,
        )

    def _ingest(self, path: str | Path) -> tuple[pd.DataFrame, list[str]]:
        """Full ingest pipeline: read → header detect → map → cast.

        Why: 기존 pd.read_csv 직접 호출 방식에서 전체 ingest 파이프라인으로 교체.
             외부 데이터(BPI, SAP 등)의 컬럼 매핑과 인코딩 감지를 자동 처리.
        """
        from src.ingest.column_mapper import auto_map_columns, prepare_dataframe
        from src.ingest.file_validator import validate_file
        from src.ingest.header_detector import detect_headers
        from src.ingest.reader_api import read_file
        from src.ingest.sheet_scorer import score_sheets
        from src.ingest.type_caster import cast_dataframe

        path = Path(path)
        warns: list[str] = []

        # Why: 파이프라인 진입 전 5단계 파일 검증 (확장자→빈파일→크기→무결성)
        validation = validate_file(path)
        if not validation.is_valid:
            raise ValueError("; ".join(validation.errors))
        warns.extend(validation.warnings)

        self._progress(0.05, "파일 읽는 중...")
        cached_df = self._try_load_ingest_cache(path)
        if cached_df is not None:
            cached_df = set_source_path(cached_df, path)
            cached_df = apply_datasynth_label_mode(
                cached_df,
                source_path=path,
                mode=getattr(self._ctx.settings, "datasynth_label_mode", "hidden"),
            )
            warns.extend(self._apply_datasynth_metadata_policy(cached_df, path))
            return cached_df, warns

        read_result = read_file(
            path,
            progress_cb=lambda pct, msg: self._progress(0.05 + pct * 0.05, msg),
        )

        # Why: Parquet은 타입이 이미 확정된 포맷이므로 헤더 탐지 불필요
        if read_result.source_format == "parquet":
            sheet_name = read_result.active_sheet
            data_df = read_result.raw_data[sheet_name]
            source_columns = list(data_df.columns)
            matched_keywords: list[str] = []
        else:
            self._progress(0.08, "헤더 탐지 중...")
            header_results = detect_headers(read_result)
            sheet_scores = score_sheets(read_result, header_results)

            recommended = next((s for s in sheet_scores if s.recommended), None)
            sheet_name = recommended.sheet_name if recommended else read_result.active_sheet

            header_result = header_results[sheet_name]
            raw_df = read_result.raw_data[sheet_name]

            if header_result.header_row is not None:
                source_columns, data_df = prepare_dataframe(raw_df, header_result.header_row)
                matched_keywords = header_result.matched_keywords
            else:
                warns.append("헤더 탐지 실패 — 첫 행을 헤더로 사용")
                source_columns = [str(c) for c in raw_df.columns]
                data_df = raw_df
                matched_keywords = []

        self._progress(0.12, "컬럼 매핑 중...")
        mapping_result = auto_map_columns(
            source_columns, matched_keywords, data_df=data_df,
            schema=self._ctx.schema,
            keywords=self._ctx.keywords,
        )

        if mapping_result.missing_required:
            warns.append(f"필수 컬럼 미매핑: {mapping_result.missing_required}")

        # Why: CLI/test 모드에서는 사용자 확인 없이 best-effort 매핑 적용
        all_mapping = {**mapping_result.mapping, **mapping_result.suggestions}
        df = data_df.rename(columns=all_mapping)

        self._progress(0.15, "타입 캐스팅 중...")
        cast_result = cast_dataframe(
            df,
            schema=self._ctx.schema,
            settings=self._ctx.settings,
            cleaning_config=self._ctx.cleaning_config,
        )
        df = cast_result.data
        warns.extend(cast_result.warnings)
        if cast_result.errors:
            warns.extend(cast_result.errors)

        df = set_source_path(df, path)
        df = apply_datasynth_label_mode(
            df,
            source_path=path,
            mode=getattr(self._ctx.settings, "datasynth_label_mode", "hidden"),
        )
        warns.extend(self._apply_datasynth_metadata_policy(df, path))
        self._write_ingest_cache(path, df)

        return df, warns

    def _ingest_cache_paths(self, path: Path) -> tuple[Path, Path]:
        settings = self._ctx.settings
        cache_dir = Path(getattr(settings, "ingest_cache_dir", "artifacts/ingest_cache"))
        if not cache_dir.is_absolute():
            from config.settings import PROJECT_ROOT

            cache_dir = PROJECT_ROOT / cache_dir
        stat = path.stat()
        payload = {
            "cache_schema": _INGEST_CACHE_SCHEMA_VERSION,
            "path": str(path.resolve()),
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "input_schema": self._ctx.schema,
            "keywords": self._ctx.keywords,
            "cleaning_config": self._ctx.cleaning_config,
            "casting_date_dayfirst": getattr(
                self._ctx.settings,
                "casting_date_dayfirst",
                False,
            ),
        }
        key = hashlib.sha256(
            json.dumps(
                payload,
                sort_keys=True,
                default=str,
                separators=(",", ":"),
            ).encode("utf-8"),
        ).hexdigest()
        return cache_dir / f"{key}.parquet", cache_dir / f"{key}.json"

    def _try_load_ingest_cache(self, path: Path) -> pd.DataFrame | None:
        if not getattr(self._ctx.settings, "enable_ingest_cache", True):
            return None
        if path.suffix.lower() not in _TEXT_EXT:
            return None
        parquet_path, meta_path = self._ingest_cache_paths(path)
        if not parquet_path.exists() or not meta_path.exists():
            return None
        try:
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)
            stat = path.stat()
            if (
                meta.get("schema") != _INGEST_CACHE_SCHEMA_VERSION
                or meta.get("source_size") != stat.st_size
                or meta.get("source_mtime_ns") != stat.st_mtime_ns
            ):
                return None
            df = pd.read_parquet(parquet_path)
        except Exception:
            logger.debug("ingest cache read failed: %s", parquet_path, exc_info=True)
            return None
        logger.info("ingest cache hit: %s", parquet_path)
        return df

    def _write_ingest_cache(self, path: Path, df: pd.DataFrame) -> None:
        if not getattr(self._ctx.settings, "enable_ingest_cache", True):
            return
        if path.suffix.lower() not in _TEXT_EXT:
            return
        parquet_path, meta_path = self._ingest_cache_paths(path)
        try:
            parquet_path.parent.mkdir(parents=True, exist_ok=True)
            cache_df = df.copy()
            cache_df.attrs.clear()
            cache_df.to_parquet(parquet_path, index=False)
            stat = path.stat()
            metadata = {
                "schema": _INGEST_CACHE_SCHEMA_VERSION,
                "source_path": str(path.resolve()),
                "source_size": stat.st_size,
                "source_mtime_ns": stat.st_mtime_ns,
                "rows": int(len(df)),
                "columns": list(df.columns),
            }
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, ensure_ascii=False, sort_keys=True, indent=2)
            logger.info("ingest cache saved: %s", parquet_path)
        except Exception:
            logger.debug("ingest cache write failed: %s", parquet_path, exc_info=True)

    def _apply_datasynth_metadata_policy(
        self,
        df: pd.DataFrame,
        source_path: str | Path,
    ) -> list[str]:
        """Refresh/load validated DataSynth metadata and enforce configured policy."""
        source = Path(source_path)
        if "journal_entries" not in source.name.lower():
            return []

        reconciliation = load_validated_metadata_json(source)
        if reconciliation is None:
            return []

        enforcement = getattr(self._ctx.settings, "datasynth_metadata_enforcement", "warn")
        df.attrs.update(
            apply_validated_metadata_attrs(
                df,
                reconciliation,
                source_csv=source,
            ).attrs
        )
        messages = build_validated_metadata_messages(reconciliation)
        if (
            enforcement == "strict"
            and reconciliation.status == "fail"
        ):
            detail = "; ".join(reconciliation.critical_mismatches[:5]) or "critical metadata mismatch"
            raise ValueError(f"DataSynth metadata validation failed: {detail}")
        if enforcement == "off":
            return []
        return messages

    def _validate(self, df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
        from src.validation import validate_accounting, validate_schema
        warns: list[str] = []
        sr = validate_schema(df, schema=self._ctx.schema, settings=self._ctx.settings)
        if not sr.is_valid:
            # Why: 열 수 불일치 등으로 필수 컬럼에 NaN이 생긴 행을 드롭하고
            #      경고로 표시. 정상 행은 파이프라인을 계속 진행한다.
            not_null_errors = [e for e in sr.errors if e.get("check") == "not_nullable"]
            other_errors = [e for e in sr.errors if e.get("check") != "not_nullable"]

            if not_null_errors and not other_errors:
                # NaN 행만 드롭하여 복구 시도
                required_cols = [col for col in df.columns
                                 if col in {"document_id", "posting_date", "debit_amount",
                                            "credit_amount", "gl_account", "document_type",
                                            "fiscal_year", "fiscal_period", "document_date",
                                            "company_code"}]
                before = len(df)
                df = df.dropna(subset=required_cols, how="any").reset_index(drop=True)
                dropped = before - len(df)
                if dropped > 0:
                    warns.append(f"필수 컬럼 결측 {dropped}행 제거 (원본 {before}행 → {len(df)}행)")
                if len(df) == 0:
                    raise ValueError("L1 구조 검증 실패: 모든 행이 필수 컬럼 결측")
            else:
                raise ValueError(
                    f"L1 구조 검증 실패: {[e.get('check', str(e)) for e in sr.errors]}",
                )
        if sr.warnings:
            warns.extend(w.get("issue", str(w)) for w in sr.warnings)
        acct = validate_accounting(df)
        if not acct.balance_check:
            # Why: 회계 복식부기 근본 위반 — 비율 기반 임계로 fatal/warning 분기.
            #      단일 행 불일치만으로 중단하지 않되, materiality 수준을 넘으면 차단.
            total_debit = float(
                df["debit_amount"].fillna(0).sum()
                if "debit_amount" in df.columns else 0.0
            )
            diff_ratio = (
                acct.balance_diff / total_debit
                if total_debit > 0 else float("inf")
            )
            unique_docs = (
                df["document_id"].nunique()
                if "document_id" in df.columns else 0
            )
            doc_ratio = (
                len(acct.unbalanced_docs) / unique_docs
                if unique_docs > 0 else 0.0
            )

            msg = (
                f"대차불일치 {len(acct.unbalanced_docs)}건, "
                f"차이 {acct.balance_diff:.2f} ({diff_ratio:.2%}), "
                f"불일치 전표 비중 {doc_ratio:.1%}"
            )

            s = self._ctx.settings
            is_fatal = (
                diff_ratio > s.balance_fatal_ratio
                or doc_ratio > s.balance_fatal_doc_ratio
            )
            if is_fatal:
                # Why: detection 진입 차단. audit_log에 사유 기록 후 예외 발생.
                self._record_validate_failure(msg)
                raise ValueError(f"L2 대차불일치 치명: {msg}")
            warns.append(msg)
        if acct.duplicate_entries > 0:
            warns.append(f"중복 행 {acct.duplicate_entries}건")

        # Why: WU-13 TB 교차검증 — GL 계정별 집계 무결성 + 유형별 잔액 대사
        from src.validation.tb_reconciliation import validate_tb_reconciliation
        recon = validate_tb_reconciliation(
            df,
            materiality=self._ctx.materiality_amount,
            account_prefixes=self._ctx.audit_rules.get("reconciliation_account_prefixes"),
        )
        # Why: 오케스트레이터 내부에서 생성한 TB를 재사용 — 이중 생성 방지
        self._tb_df = recon.trial_balance_df
        if not recon.all_reconciled:
            warns.extend(recon.warnings)

        # Why: L3 통계 검증 — 분포/Benford/월별 변동성/계정 집중도 사전 경고.
        #      detection 진입 전에 데이터 건전성 신호를 warns에 누적하여 대시보드에 노출.
        #      validate_statistics()는 170줄 완전 구현되어 있었으나 호출이 누락된 Dead Code였음.
        try:
            from src.validation import validate_statistics
            stat = validate_statistics(df, settings=self._ctx.settings)
            warns.extend(stat.warnings)
            # flags는 dict[str, str] → "L3 type: detail" 포맷으로 평탄화
            warns.extend(f"L3 {f['type']}: {f['detail']}" for f in stat.flags)
            # Why: 후속 단계(_load_db, 대시보드 EDA 탭)에서 재사용 가능
            self._stat_result = stat
        except Exception:
            logger.warning("L3 통계 검증 실패 — graceful 스킵", exc_info=True)
            warns.append("L3 통계 검증 스킵 (예외)")
            self._stat_result = None

        return df, warns

    def _generate_features(self, df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
        settings = self._ctx.settings
        rules = self._ctx.audit_rules
        risk_keywords = self._ctx.risk_keywords
        cache_key = None
        if getattr(settings, "enable_feature_cache", True):
            from src.feature.cache import load_feature_cache

            cached, cache_key = load_feature_cache(
                df,
                settings=settings,
                rules=rules,
                risk_keywords=risk_keywords,
            )
            if cached is not None:
                logger.info(
                    "feature cache hit: key=%s source=%s rows=%d",
                    cache_key.key[:12],
                    cache_key.source_kind,
                    len(cached),
                )
                return cached, []

        from src.feature.engine import generate_all_features
        feat = generate_all_features(
            df,
            settings=settings,
            rules=rules,
            risk_keywords=risk_keywords,
            include_morpheme_tokens=getattr(settings, "enable_nlp_detection", False),
        )
        warns = [f"피처 미생성: {feat.missing_columns}"] if feat.missing_columns else []
        if getattr(settings, "enable_feature_cache", True) and cache_key is not None:
            from src.feature.cache import save_feature_cache

            saved = save_feature_cache(feat.data, settings=settings, cache_key=cache_key)
            if saved is not None:
                logger.info("feature cache saved: %s", saved)
        return feat.data, warns

    def _run_detection(
        self,
        df: pd.DataFrame,
        *,
        detection_scope: str = "default",
    ) -> tuple[list[DetectionResult], list[str]]:
        from src.detection.anomaly_layer import AnomalyDetector
        from src.detection.benford_detector import BenfordDetector
        from src.detection.fraud_layer import FraudLayer
        from src.detection.integrity_layer import IntegrityDetector
        warns: list[str] = []
        self._reset_detector_statuses()

        results: list[DetectionResult] = []

        if detection_scope != "phase2_only":
            # Phase 1 core scope: L1-L4 rules plus D01/D02 when prior data exists.
            base_detectors = [
                IntegrityDetector(
                    self._ctx.settings,
                    chart_of_accounts=self._ctx.chart_of_accounts,
                    schema=self._ctx.schema,
                    audit_rules=self._ctx.audit_rules,
                ),
                FraudLayer(self._ctx.settings, audit_rules=self._ctx.audit_rules),
                AnomalyDetector(self._ctx.settings, audit_rules=self._ctx.audit_rules),
                BenfordDetector(self._ctx.settings),
            ]
            _t = time.monotonic()
            results, base_warns = _run_detectors_parallel(
                base_detectors,
                df,
                max_workers=getattr(self._ctx.settings, "detection_parallel_workers", None),
                progress_callback=getattr(self, "_detection_progress_callback", None),
            )
            warns.extend(base_warns)
            for result in results:
                self._record_detector_status(result.track_name, run_status="executed", result=result)
            for warn in base_warns:
                if warn.startswith("detector_failed:"):
                    failed_track = warn.removeprefix("detector_failed:").strip()
                    self._record_detector_status(
                        failed_track,
                        run_status="failed",
                        reason="detector_exception",
                    )
            logger.warning("[TIMING] base_detectors_parallel: %.1fs", time.monotonic() - _t)
        else:
            for track_name in ("layer_a", "layer_b", "layer_c", "benford"):
                self._record_detector_status(
                    track_name,
                    run_status="skipped",
                    reason="phase2_inference_uses_phase1_baseline",
                )

        optional_detectors = []
        if detection_scope != "phase2_only":
            optional_detectors.append(("variance", self._try_variance_detection))
        if detection_scope != "phase1_core":
            optional_detectors.append(
                ("ml", lambda d: self._try_ml_detection(d, detection_scope=detection_scope))
            )

        for _name, _func in optional_detectors:
            _t = time.monotonic()
            _r = _func(df)
            _elapsed = time.monotonic() - _t
            logger.warning("[TIMING] detect_%s: %.1fs", _name, _elapsed)
            if isinstance(_r, list):
                results.extend(_r)
            elif _r is not None:
                results.append(_r)

        return results, warns

    def _try_timeseries_detection(self, df: pd.DataFrame) -> DetectionResult | None:
        """Timeseries detector execution for TS01/TS02."""
        if not getattr(self._ctx.settings, "enable_timeseries_detection", True):
            logger.debug("timeseries detection disabled by settings")
            self._record_detector_status("timeseries", run_status="skipped", reason="disabled_by_settings")
            return None
        try:
            from src.detection.timeseries_detector import TimeseriesDetector

            det = TimeseriesDetector(self._ctx.settings)
            result = det.detect(df)
            self._record_detector_status("timeseries", run_status="executed", result=result)
            return result
        except Exception:
            logger.warning("Timeseries detection failed and will be skipped", exc_info=True)
            self._record_detector_status("timeseries", run_status="failed", reason="detector_exception")
            return None

    def _try_variance_detection(self, df: pd.DataFrame) -> DetectionResult | None:
        """Layer D(전기 대비 변동) 실행 시도. 조건 불충족 시 None."""
        if not getattr(self._ctx.settings, "enable_variance_detection", True):
            logger.debug("variance detection disabled by settings")
            self._record_detector_status("layer_d", run_status="skipped", reason="disabled_by_settings")
            return None
        if self._ctx.is_anonymous:
            self._record_detector_status("layer_d", run_status="skipped", reason="anonymous_context")
            return None
        if self._ctx.fiscal_year is None:
            self._record_detector_status("layer_d", run_status="skipped", reason="missing_fiscal_year")
            return None
        if self._repo is None:
            logger.debug("repo 미주입 — Layer D 스킵")
            self._record_detector_status("layer_d", run_status="skipped", reason="missing_repository")
            return None

        try:
            from src.detection.prior_data_loader import find_prior_engagement, load_prior_summary
            from src.detection.variance_layer import VarianceDetector

            prior = find_prior_engagement(
                self._repo, self._ctx.company_id, self._ctx.fiscal_year,
            )
            if prior is None:
                logger.info("전기 engagement 없음 — Layer D 스킵")
                self._record_detector_status("layer_d", run_status="skipped", reason="missing_historical_data")
                return None

            prior_db_path = self._repo.db_path(self._ctx.company_id, prior.engagement_id)

            # Why: _run_detection은 _load_db 이전에 호출되므로 self._conn이 None일 수 있음.
            #      ConnectionManager 캐시를 통해 당기 DB 커넥션을 확보하여 ATTACH 기반으로 사용.
            conn = self._conn
            if conn is None:
                from src.db.connection import get_connection
                conn = get_connection(path=str(self._ctx.db_path))

            prior_summary = load_prior_summary(conn, prior_db_path, prior.fiscal_year)
            if prior_summary is None:
                self._record_detector_status("layer_d", run_status="skipped", reason="missing_prior_summary")
                return None

            det = VarianceDetector(self._ctx.settings, prior_summary=prior_summary)
            result = det.detect(df)
            self._record_detector_status("layer_d", run_status="executed", result=result)
            return result

        except Exception:
            logger.warning("Layer D 실행 실패 — 스킵", exc_info=True)
            self._record_detector_status("layer_d", run_status="failed", reason="detector_exception")
            return None

    def _try_relational_detection(self, df: pd.DataFrame) -> DetectionResult | None:
        """Relational 탐지기 실행. R01~R03 항상, R04는 document_flows 존재 시만.

        Why: R04(문서 흐름 누락)는 DuckDB에 적재된 document_references 테이블 필요.
             conn이 없거나 테이블 미적재 시 R04만 graceful 스킵 (R01~R03는 정상 실행).
        """
        if not getattr(self._ctx.settings, "enable_relational_detection", False):
            logger.debug("relational detection disabled by settings")
            self._record_detector_status("relational", run_status="skipped", reason="disabled_by_settings")
            return None
        try:
            from src.detection.relational_detector import RelationalDetector
            from src.detection.relational_rules import build_doc_flow_df

            doc_flow_df = None
            if self._conn is not None:
                try:
                    doc_flow_df = build_doc_flow_df(self._conn)
                except Exception:
                    logger.debug("document_flows 쿼리 실패 — R04 스킵")

            det = RelationalDetector(
                self._ctx.settings,
                audit_rules=self._ctx.audit_rules,
                doc_flow_df=doc_flow_df,
            )
            result = det.detect(df)
            self._record_detector_status("relational", run_status="executed", result=result)
            return result
        except Exception:
            logger.warning("Relational 탐지 실패 — 스킵", exc_info=True)
            self._record_detector_status("relational", run_status="failed", reason="detector_exception")
            return None

    def _try_graph_detection(self, df: pd.DataFrame) -> DetectionResult | None:
        """Graph 탐지기 실행(WU-22). networkx 미설치 또는 예외 시 graceful 스킵.

        Why: GR01(N-hop 순환) + GR03(양방향 IC 가격 asymmetry). 사전 필터 +
             from_pandas_edgelist로 OOM 방어.
        """
        if not getattr(self._ctx.settings, "enable_graph_detection", False):
            logger.debug("graph detection disabled by settings")
            self._record_detector_status("graph", run_status="skipped", reason="disabled_by_settings")
            return None
        try:
            from src.detection.graph_detector import GraphDetector

            det = GraphDetector(self._ctx.settings)
            result = det.detect(df)
            reason = None
            run_status = "executed"
            if result.total_rules_run == 0 and any("networkx" in w for w in result.warnings):
                run_status = "skipped"
                reason = "missing_optional_dependency"
            self._record_detector_status("graph", run_status=run_status, reason=reason, result=result)
            return result
        except Exception:
            logger.warning("Graph 탐지 실패 — 스킵", exc_info=True)
            self._record_detector_status("graph", run_status="failed", reason="detector_exception")
            return None

    def _try_nlp_detection(self, df: pd.DataFrame) -> DetectionResult | None:
        """NLP 탐지기 실행(WU-21). OpenAI API 키 미설정/연결 실패 시 graceful 스킵.

        Why: NLP01~NLP05는 OpenAI 임베딩 API 의존. EmbeddingService 초기화 실패 시
             NLPDetector 내부에서 empty result 반환. 외부 예외만 추가 방어.
        """
        if not getattr(self._ctx.settings, "enable_nlp_detection", False):
            logger.debug("nlp detection disabled by settings")
            self._record_detector_status("nlp", run_status="skipped", reason="disabled_by_settings")
            return None
        try:
            from src.detection.nlp_analyzer import NLPDetector

            det = NLPDetector(self._ctx.settings)
            result = det.detect(df)
            reason = None
            run_status = "executed"
            if result.total_rules_run == 0:
                run_status = "skipped"
                reason = "missing_external_api_or_embedding_service"
            self._record_detector_status("nlp", run_status=run_status, reason=reason, result=result)
            return result
        except Exception:
            logger.warning("NLP 탐지 실패 — 스킵", exc_info=True)
            self._record_detector_status("nlp", run_status="failed", reason="detector_exception")
            return None

    def _try_access_audit_detection(self, df: pd.DataFrame) -> DetectionResult | None:
        """Access Audit 탐지기 실행. change_log 없으면 AL1-01만 graceful 스킵.

        Why: AL1-01(전표 수정이력)은 change_log 테이블 JOIN 필요.
             _try_relational_detection의 doc_flow_df 패턴과 동일한 외부 DF 주입.
        """
        if not getattr(self._ctx.settings, "enable_access_audit_detection", False):
            logger.debug("access audit detection disabled by settings")
            self._record_detector_status("access_audit", run_status="skipped", reason="disabled_by_settings")
            return None
        try:
            from src.detection.access_audit_layer import AccessAuditDetector

            change_log_df = None
            if self._conn is not None:
                try:
                    change_log_df = self._conn.execute(
                        "SELECT document_id, changed_by, changed_field, change_date "
                        "FROM change_log"
                    ).fetchdf()
                except Exception:
                    logger.debug("change_log 미존재 — AL1-01 스킵")

            det = AccessAuditDetector(
                self._ctx.settings,
                change_log_df=change_log_df,
                audit_rules=self._ctx.audit_rules,
            )
            result = det.detect(df)
            self._record_detector_status("access_audit", run_status="executed", result=result)
            return result
        except Exception:
            logger.warning("Access Audit 탐지 실패 — 스킵", exc_info=True)
            self._record_detector_status("access_audit", run_status="failed", reason="detector_exception")
            return None

    def _try_evidence_detection(self, df: pd.DataFrame) -> DetectionResult | None:
        """Evidence 탐지기 실행 (EV01~EV03).

        Why: 증빙 컬럼(has_attachment 등)이 없어도 EV03(금액 불일치)은 실행 가능.
             개별 룰이 컬럼 부재 시 graceful 스킵하므로 무조건 시도.
        """
        if not getattr(self._ctx.settings, "enable_evidence_detection", False):
            logger.debug("evidence detection disabled by settings")
            self._record_detector_status("evidence", run_status="skipped", reason="disabled_by_settings")
            return None
        try:
            from src.detection.evidence_detector import EvidenceDetector

            det = EvidenceDetector(
                self._ctx.settings,
                audit_rules=self._ctx.audit_rules,
            )
            result = det.detect(df)
            self._record_detector_status("evidence", run_status="executed", result=result)
            return result
        except Exception:
            logger.warning("Evidence 탐지 실패 — 스킵", exc_info=True)
            self._record_detector_status("evidence", run_status="failed", reason="detector_exception")
            return None

    def _try_trendbreak_detection(self, df: pd.DataFrame) -> DetectionResult | None:
        """TrendBreak(회계추정치 편의) 실행 시도. 조건 불충족 시 None.

        Why: ISA 540 소급 검토. 3개년 이상 engagement + estimation_accounts 설정 필요.
             _try_variance_detection() 패턴과 동일한 조건부 실행.
        """
        if not getattr(self._ctx.settings, "enable_trendbreak_detection", False):
            logger.debug("trendbreak detection disabled by settings")
            self._record_detector_status("trendbreak", run_status="skipped", reason="disabled_by_settings")
            return None
        if self._ctx.is_anonymous:
            self._record_detector_status("trendbreak", run_status="skipped", reason="anonymous_context")
            return None
        if self._ctx.fiscal_year is None:
            self._record_detector_status("trendbreak", run_status="skipped", reason="missing_fiscal_year")
            return None
        if self._repo is None:
            logger.debug("repo 미주입 — TrendBreak 스킵")
            self._record_detector_status("trendbreak", run_status="skipped", reason="missing_repository")
            return None

        # Why: audit_rules.yaml에서 estimation_accounts 설정 확인
        estimation_config = self._ctx.audit_rules.get("estimation_accounts")
        if not estimation_config:
            logger.debug("estimation_accounts 미설정 — TrendBreak 스킵")
            self._record_detector_status("trendbreak", run_status="skipped", reason="missing_estimation_config")
            return None

        try:
            from src.detection.multi_year_loader import (
                find_multi_year_engagements,
                load_multi_year_estimates,
            )
            from src.detection.trendbreak_detector import TrendBreakDetector

            # Why: YAML에서 계정별 부호 규칙 추출
            account_sign_convention = {
                item["account"]: item.get("sign", "credit_normal")
                for item in estimation_config
            }

            engagements = find_multi_year_engagements(
                self._repo,
                self._ctx.company_id,
                self._ctx.fiscal_year,
                max_years=self._ctx.settings.trendbreak_max_years,
                min_years=self._ctx.settings.trendbreak_min_years,
            )
            if engagements is None:
                logger.info("다기간 engagement 부족 — TrendBreak 스킵")
                self._record_detector_status("trendbreak", run_status="skipped", reason="missing_historical_data")
                return None

            # Why: _try_variance_detection과 동일한 커넥션 확보 패턴
            conn = self._conn
            if conn is None:
                from src.db.connection import get_connection
                conn = get_connection(path=str(self._ctx.db_path))

            estimates = load_multi_year_estimates(
                conn=conn,
                repo=self._repo,
                company_id=self._ctx.company_id,
                engagements=engagements,
                current_df=df,
                current_fiscal_year=self._ctx.fiscal_year,
                estimation_config=estimation_config,
                account_sign_convention=account_sign_convention,
            )
            if estimates is None:
                self._record_detector_status("trendbreak", run_status="skipped", reason="missing_multi_year_estimates")
                return None

            det = TrendBreakDetector(
                self._ctx.settings,
                multi_year_estimates=estimates,
            )
            result = det.detect(df)
            self._record_detector_status("trendbreak", run_status="executed", result=result)
            return result

        except Exception:
            logger.warning("TrendBreak 실행 실패 — 스킵", exc_info=True)
            self._record_detector_status("trendbreak", run_status="failed", reason="detector_exception")
            return None

    @staticmethod
    def _select_weights(results: list[DetectionResult]) -> dict[str, float] | None:
        """탐지 결과에 따라 적절한 가중치 딕셔너리 선택.

        Why: ML 트랙/Layer D/TrendBreak 유무에 따라 가중치 재배분이 필요.
             ML > TrendBreak > default. Layer D does not alter row-level weights.
        """
        has_ml = any(r.track_name.startswith("ml_") for r in results)
        has_trendbreak = any(r.track_name == "trendbreak" for r in results)

        if has_ml:
            from src.detection.constants import LAYER_WEIGHTS_WITH_ML
            return LAYER_WEIGHTS_WITH_ML
        if has_trendbreak:
            from src.detection.constants import RULE_LEVEL_WEIGHTS_WITH_TRENDBREAK
            return RULE_LEVEL_WEIGHTS_WITH_TRENDBREAK
        return None  # 기본 RULE_LEVEL_WEIGHTS (L1-L4)

    def _try_ml_detection(
        self,
        df: pd.DataFrame,
        *,
        detection_scope: str = "default",
    ) -> list[DetectionResult]:
        """학습된 ML 모델 로드 → 탐지 실행. 모델 없으면 빈 리스트 (Cold Start 방어).

        Why: ML 모델은 train() 후에만 사용 가능. 최초 배포/새 회사에서는
             학습 이력이 없으므로 ModelRegistry 로드 실패 시 graceful 스킵.
        """
        results: list[DetectionResult] = []
        if not getattr(self._ctx.settings, "enable_ml_detection", False):
            logger.debug("ml detection disabled by settings")
            self._record_detector_status("ml_supervised", run_status="skipped", reason="disabled_by_settings")
            self._record_detector_status("ml_unsupervised", run_status="skipped", reason="disabled_by_settings")
            return results
        # Why: SHAP 단계에서 재사용하기 위해 Supervised detector 인스턴스 캐싱
        self._ml_supervised_detector = None
        if self._ctx.is_anonymous:
            self._record_detector_status("ml_supervised", run_status="skipped", reason="anonymous_context")
            self._record_detector_status("ml_unsupervised", run_status="skipped", reason="anonymous_context")
            return results

        try:
            from src.preprocessing.model_registry import ModelRegistry
            try:
                registry = ModelRegistry(registry_dir=self._phase2_model_registry_dir())
            except TypeError:
                registry = ModelRegistry()
        except Exception:
            self._record_detector_status("ml_supervised", run_status="skipped", reason="missing_model_registry")
            self._record_detector_status("ml_unsupervised", run_status="skipped", reason="missing_model_registry")
            return results

        class _SkipSupervisedForPhase2Only(Exception):
            pass

        # Supervised (ML01)
        try:
            if detection_scope == "phase2_only":
                self._record_detector_status(
                    "ml_supervised",
                    run_status="skipped",
                    reason="phase2_unsupervised_only",
                )
                raise _SkipSupervisedForPhase2Only
            from src.detection.supervised_detector import SupervisedDetector
            det = SupervisedDetector(self._settings, model_registry=registry)
            det.load_model("supervised")
            gate_snapshot = det.get_training_gate_snapshot()
            gate_status = gate_snapshot.get("gate_status", "unknown")
            gate_reason = gate_snapshot.get("gate_reason")
            if gate_status in {"blocked", "fallback_to_unsupervised"}:
                self._record_detector_status(
                    "ml_supervised",
                    run_status="skipped",
                    reason=gate_reason or "blocked_training_gate",
                )
            else:
                result = det.detect(df)
                if result.metadata is None:
                    result.metadata = {}
                result.metadata["training_gate"] = gate_snapshot
                results.append(result)
                self._record_detector_status(
                    "ml_supervised",
                    run_status="executed",
                    reason=(gate_reason or "unknown_training_gate") if gate_status == "unknown" else None,
                    result=result,
                )
                # Why: SHAP은 sklearn pipeline이 필요 → 로드된 detector 참조 보관
                self._ml_supervised_detector = det
        except _SkipSupervisedForPhase2Only:
            pass
        except FileNotFoundError:
            logger.debug("SupervisedDetector 모델 없음 — 스킵")
            self._record_detector_status("ml_supervised", run_status="skipped", reason="missing_trained_model")
        except Exception:
            logger.warning("SupervisedDetector 탐지 실패", exc_info=True)
            self._record_detector_status("ml_supervised", run_status="failed", reason="detector_exception")

        # Unsupervised (ML02)
        try:
            from src.detection.vae_detector import UnsupervisedDetector
            det = UnsupervisedDetector(self._settings, model_registry=registry)
            phase2_contract = getattr(self, "_phase2_inference_contract", None)
            promoted_versions = (
                phase2_contract.get("promoted_versions", {})
                if isinstance(phase2_contract, dict)
                else {}
            )
            loaded_version = promoted_versions.get("unsupervised")
            det.load_model("unsupervised", version=loaded_version)
            result = det.detect(df)
            if result.metadata is None:
                result.metadata = {}
            if isinstance(phase2_contract, dict):
                result.metadata["contract_version"] = phase2_contract.get("contract_version")
            result.metadata["loaded_version"] = loaded_version
            results.append(result)
            self._record_detector_status("ml_unsupervised", run_status="executed", result=result)
        except FileNotFoundError:
            logger.debug("UnsupervisedDetector 모델 없음 — 스킵")
            self._record_detector_status("ml_unsupervised", run_status="skipped", reason="missing_trained_model")
        except Exception:
            logger.warning("UnsupervisedDetector 탐지 실패", exc_info=True)
            self._record_detector_status("ml_unsupervised", run_status="failed", reason="detector_exception")

        return results

    def _phase2_model_registry_dir(self) -> Path:
        """Return the registry directory that matches the current engagement context."""
        if getattr(self._ctx, "is_anonymous", True):
            from src.preprocessing.model_registry import _DEFAULT_MODELS_DIR

            return _DEFAULT_MODELS_DIR
        return Path(getattr(self._ctx, "model_dir"))

    def _try_stacking_ensemble(
        self,
        results: list[DetectionResult],
        df: pd.DataFrame,
    ) -> pd.Series | None:
        """학습된 Stacking meta-learner 로드 → 추론. 없으면 None.

        Why: meta-learner 미학습 시 None을 반환하여 기존 가중합 경로를 타게 한다.
             Cold Start 시나리오에서 graceful degradation.
        """
        if self._ctx.is_anonymous:
            self._record_detector_status("ensemble", run_status="skipped", reason="anonymous_context")
            return None

        try:
            from src.preprocessing.model_registry import ModelRegistry
            try:
                registry = ModelRegistry(registry_dir=self._phase2_model_registry_dir())
            except TypeError:
                registry = ModelRegistry()
        except Exception:
            self._record_detector_status("ensemble", run_status="skipped", reason="missing_model_registry")
            return None

        try:
            from src.detection.ensemble_detector import EnsembleDetector
            det = EnsembleDetector(self._settings, model_registry=registry)
            det.load_model("stacking_meta")
            result = det.detect_from_results(results, df.index)
            logger.info("Stacking meta-learner 추론 완료 (mode=%s)", result.metadata.get("mode"))
            self._record_detector_status("ensemble", run_status="executed", result=result)
            return result.scores
        except FileNotFoundError:
            logger.debug("Stacking meta-learner 모델 없음 — 기존 가중합 사용")
            self._record_detector_status("ensemble", run_status="skipped", reason="missing_trained_model")
            return None
        except Exception:
            logger.warning("Stacking meta-learner 추론 실패", exc_info=True)
            self._record_detector_status("ensemble", run_status="failed", reason="detector_exception")
            return None

    def _try_shap_explanation(
        self,
        df: pd.DataFrame,
    ) -> tuple[dict[str, dict[str, float]] | None, float | None]:
        """flagged rows(anomaly_score ≥ threshold)만 SHAP 기여도 산출.

        Why: SHAP은 연산량이 무거움(TreeSHAP/KernelSHAP 모두) — 10만 행 전체에
             돌리면 수십 분 소요. 감사인이 설명을 필요로 하는 건 '이상 전표'뿐이므로
             정상 전표는 스킵. 안전 상한(shap_max_rows)으로 OOM 방어.

        Returns:
            (contributions, base_value) 튜플.
            contributions: {document_id: {feature: shap_value}} 또는 None (Cold Start).
            base_value: 모델의 expected_value 또는 None.
        """
        # Why: _try_ml_detection 호출 후 detector가 캐싱됨 — 없으면 ML 모델 자체가 없는 상태
        det = getattr(self, "_ml_supervised_detector", None)
        if det is None or not hasattr(det, "pipeline_"):
            return None, None

        # Why: anomaly_score 컬럼이 없으면 파이프라인 순서 오류 — 방어
        if "anomaly_score" not in df.columns:
            logger.warning("SHAP 산출 스킵 — anomaly_score 컬럼 부재")
            return None, None

        threshold = getattr(self._settings, "shap_threshold", 0.7)
        max_rows = getattr(self._settings, "shap_max_rows", 500)

        # Why: flagged rows만 필터 → 상위 max_rows건으로 안전 상한
        flagged_mask = df["anomaly_score"] >= threshold
        flagged_df = df[flagged_mask]
        if flagged_df.empty:
            logger.debug("SHAP 산출 스킵 — flagged rows 없음 (threshold=%.2f)", threshold)
            return None, None

        if len(flagged_df) > max_rows:
            flagged_df = flagged_df.nlargest(max_rows, "anomaly_score")
            logger.info(
                "SHAP 대상 축소: %d → %d건 (shap_max_rows 적용)",
                int(flagged_mask.sum()), max_rows,
            )

        try:
            from src.preprocessing.explainer import PipelineExplainer
            explainer = PipelineExplainer(
                pipeline=det.pipeline_,
                feature_names=list(flagged_df.columns),
            )
            contributions_list, base_value = explainer.explain_batch(flagged_df, top_k=5)
        except Exception:
            logger.warning("SHAP 산출 실패 — graceful 스킵", exc_info=True)
            return None, None

        # Why: document_id 기준으로 딕셔너리 매핑 — UI에서 doc_id로 빠른 조회
        if "document_id" not in flagged_df.columns:
            logger.warning("SHAP 산출 스킵 — document_id 컬럼 부재")
            return None, None

        doc_ids = flagged_df["document_id"].tolist()
        shap_map = {
            str(doc_id): contrib
            for doc_id, contrib in zip(doc_ids, contributions_list)
        }
        logger.info("SHAP 산출 완료: %d건 (base_value=%.4f)", len(shap_map), base_value)
        return shap_map, base_value

    @staticmethod
    def _detect_datasynth_dir(file_name: str) -> Path | None:
        """journal_entries 파일 경로에서 DataSynth 보조 데이터 디렉토리 감지.

        Why: DataSynth 출력 디렉토리에 document_flows/, master_data/ 등이
             함께 존재하면 보조 데이터를 자동 적재한다.
        """
        if not file_name:
            return None
        p = Path(file_name).resolve()
        parent = p.parent
        if not parent.exists():
            return None
        # Why: document_flows 디렉토리 존재 여부로 DataSynth 출력인지 판별
        if (parent / "document_flows").is_dir():
            return parent
        return None

    def _load_db(
        self, df, batch_id, results, *, file_name: str = "", performance_report=None,
        phase1_case_ref: dict | None = None,
    ) -> tuple[object | None, list[str]]:
        conn, own_conn = self._conn, self._conn is None
        try:
            if own_conn:
                from src.db.connection import get_connection
                # Why: 회사 프로파일 없는 폴백(anonymous/legacy) → :memory: 사용
                #      동일 파일에 동시 쓰기 시 DuckDB File Lock 방지
                if self._ctx.is_anonymous:
                    conn = get_connection(path=":memory:")
                else:
                    conn = get_connection(path=str(self._ctx.db_path))
            from src.db.loader import load_all
            from src.db.performance_store import save_report
            # Why: WU-13 — _validate()에서 캐싱한 TB DataFrame을 DB에 적재
            tb_df = getattr(self, "_tb_df", None)
            datasynth_dir = self._detect_datasynth_dir(file_name)
            lr = load_all(
                conn, df, batch_id, results,
                file_name=file_name, tb_df=tb_df, datasynth_dir=datasynth_dir,
                phase1_case_ref=phase1_case_ref,
            )
            if performance_report is not None:
                save_report(conn, performance_report)

            # Why: engagement_meta에 현재 engagement 기록 (named만)
            if not self._ctx.is_anonymous:
                self._upsert_engagement_meta(conn)

            # Why: ISO 27001 / SOC 2 감사증적 — 파이프라인 실행 이벤트 기록.
            #      락 충돌 시 execute_write 내부 재시도, 영구 실패 시 graceful.
            self._record_detection_run(
                conn, batch_id=batch_id, results=results, df=df, file_name=file_name,
            )

            return lr, []
        except Exception:
            logger.warning("DB 적재 실패", exc_info=True)
            return None, ["DB 적재 실패"]
        finally:
            # Why: anonymous :memory: 커넥션만 직접 close.
            #      named DB 커넥션은 ConnectionManager 캐시가 관리.
            if own_conn and conn is not None and self._ctx.is_anonymous:
                conn.close()

    def _record_detection_run(
        self,
        conn,
        *,
        batch_id: str,
        results: list[DetectionResult],
        df: pd.DataFrame,
        file_name: str,
    ) -> None:
        """audit_log에 detection_run 이벤트 기록 — settings 스냅샷 + 통계 포함."""
        from src.db.audit_log import record_event

        # Why: settings 전체 dump는 노이즈가 크므로 핵심 임계값만 추출
        s = self._ctx.settings
        settings_snapshot = {
            "balance_tolerance": getattr(s, "balance_tolerance", None),
            "balance_fatal_ratio": getattr(s, "balance_fatal_ratio", None),
            "balance_fatal_doc_ratio": getattr(s, "balance_fatal_doc_ratio", None),
            "zscore_threshold": getattr(s, "zscore_threshold", None),
            "approval_thresholds": getattr(s, "approval_thresholds", None),
        }
        anomaly_count = 0
        if "risk_level" in df.columns:
            anomaly_count = int((df["risk_level"] != "Normal").sum())

        record_event(
            conn,
            action="detection_run",
            company_id=None if self._ctx.is_anonymous else self._ctx.company_id,
            engagement_id=None if self._ctx.is_anonymous else self._ctx.engagement_id,
            batch_id=batch_id,
            target_id=file_name or None,
            details={
                "row_count": int(len(df)),
                "rule_track_count": len(results),
                "rule_tracks": [r.track_name for r in results],
                "anomaly_count": anomaly_count,
                "settings_snapshot": settings_snapshot,
            },
        )

    def _record_validate_failure(self, msg: str) -> None:
        """audit_log에 pipeline_validate_fail 이벤트 기록.

        Why: L2 대차불일치 fatal 등 검증 단계 차단 사유를 감사증적에 남긴다.
             _validate() 단계에서는 _conn이 없을 수 있으므로 ConnectionManager로 확보.
             anonymous 컨텍스트는 영속 DB가 없으므로 skip.
        """
        if self._ctx.is_anonymous:
            return
        try:
            from src.db.audit_log import record_event
            from src.db.connection import get_connection
            conn = self._conn or get_connection(path=str(self._ctx.db_path))
            record_event(
                conn,
                action="pipeline_validate_fail",
                company_id=self._ctx.company_id,
                engagement_id=self._ctx.engagement_id,
                details={"reason": "balance_check_fatal", "message": msg},
            )
        except Exception:
            # Why: 검증 실패 차단 흐름은 audit_log 실패와 무관하게 진행
            logger.warning("validate_failure 기록 실패", exc_info=True)

    def _upsert_engagement_meta(self, conn) -> None:
        """engagement_meta 테이블에 현재 engagement 기록 (중복 방지)."""
        # Why: UNIQUE(company_id, engagement_id) 제약으로 DB 레벨 중복 방어
        conn.execute(
            """
            INSERT INTO engagement_meta (company_id, engagement_id, schema_version)
            VALUES (?, ?, 1)
            ON CONFLICT DO NOTHING
            """,
            [self._ctx.company_id, self._ctx.engagement_id],
        )
