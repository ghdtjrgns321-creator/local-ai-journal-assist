"""PHASE1-1 조합 빌더 엔진 — tier 폐지 후 주 검토 표면.

SoT: docs/spec/PHASE1_COMBO_BUILDER_SPEC.md. 어휘(몸통/특징)·프리셋은 config/combo_builder.yaml.
엔진은 phase1.units(전표/흐름) 위 순수 조회다 — 등급을 만들지 않는다(판단 주체 = 감사인).
결합 의미론(§3): 기본 = 그룹 내 OR / 그룹 간 AND, 엄격 모드 = 선택 룰 전부 발화.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "combo_builder.yaml"


@dataclass(frozen=True)
class ComboVocabulary:
    """빌더에 노출되는 어휘 전체. bodies/features 항목은 YAML dict 그대로(라벨·근거 포함)."""

    bodies: tuple[dict[str, Any], ...]
    features: tuple[dict[str, Any], ...]
    presets: tuple[dict[str, Any], ...]

    @property
    def body_ids(self) -> frozenset[str]:
        return frozenset(item["rule_id"] for item in self.bodies)

    @property
    def feature_ids(self) -> frozenset[str]:
        return frozenset(item["rule_id"] for item in self.features)


def load_combo_vocabulary(path: Path | None = None) -> ComboVocabulary:
    """YAML 어휘 로드 + 무결성 검증. 프리셋 features: all 은 특징 전체로 해소."""
    raw = yaml.safe_load((path or _CONFIG_PATH).read_text(encoding="utf-8"))
    bodies = tuple(raw["bodies"])
    features = tuple(raw["features"])
    body_ids = [b["rule_id"] for b in bodies]
    feature_ids = [f["rule_id"] for f in features]
    if len(set(body_ids)) != len(body_ids) or len(set(feature_ids)) != len(feature_ids):
        raise ValueError("combo_builder.yaml: 몸통/특징 rule_id 중복")
    overlap = set(body_ids) & set(feature_ids)
    if overlap:
        raise ValueError(f"combo_builder.yaml: 몸통·특징 겹침 금지 위반 {sorted(overlap)}")

    presets: list[dict[str, Any]] = []
    for preset in raw.get("presets", []):
        resolved = dict(preset)
        if resolved.get("features") == "all":
            resolved["features"] = list(feature_ids)
        unknown = (set(resolved.get("bodies", [])) - set(body_ids)) | (
            set(resolved.get("features", [])) - set(feature_ids)
        )
        if unknown:
            raise ValueError(f"프리셋 {preset.get('preset_id')}: 어휘 밖 rule_id {sorted(unknown)}")
        presets.append(resolved)
    return ComboVocabulary(bodies=bodies, features=features, presets=tuple(presets))


def _fired_rule_ids(unit: Any) -> set[str]:
    return {ref.rule_id for ref in unit.evidence_rows}


def _builder_sort_key(unit: Any) -> tuple[float, int, float, int]:
    """tier(band) 없는 정렬 — 기존 sort 축 재사용: triage_rank → time_severity → 금액 → 근거 수."""
    return (
        unit.triage_rank_score,
        unit.time_severity_score,
        unit.total_amount,
        len(unit.evidence_rows),
    )


def match_units(
    units: list[Any],
    *,
    bodies: set[str] | frozenset[str],
    features: set[str] | frozenset[str],
    strict: bool = False,
) -> list[Any]:
    """선택 조합에 걸리는 unit 목록(정렬 완료).

    기본 모드: (몸통 미선택 or 선택 몸통 중 1+ 발화) AND (특징 미선택 or 선택 특징 중 1+ 발화).
    엄격 모드: 선택한 룰 전부 발화. 양쪽 다 빈 선택 = 빈 결과(안내는 UI 몫).
    """
    selected_bodies = set(bodies)
    selected_features = set(features)
    if not selected_bodies and not selected_features:
        return []
    matched = []
    for unit in units:
        fired = _fired_rule_ids(unit)
        if strict:
            if (selected_bodies | selected_features) <= fired:
                matched.append(unit)
            continue
        body_ok = not selected_bodies or bool(selected_bodies & fired)
        feature_ok = not selected_features or bool(selected_features & fired)
        if body_ok and feature_ok:
            matched.append(unit)
    matched.sort(key=_builder_sort_key, reverse=True)
    return matched


def build_combo_builder_result(
    pr: Any,
    *,
    bodies: list[str] | set[str],
    features: list[str] | set[str],
    strict: bool = False,
    top_n: int | None = None,
    vocabulary: ComboVocabulary | None = None,
) -> dict[str, Any]:
    """대시보드용 결과 뷰. 선택은 어휘 안에서만 허용(밖이면 ValueError — UI 버그 조기 검출)."""
    from src.export.phase1_case_view import _feature_frame, _unit_row, resolve_phase1_case_result

    vocab = vocabulary or load_combo_vocabulary()
    unknown = (set(bodies) - vocab.body_ids) | (set(features) - vocab.feature_ids)
    if unknown:
        raise ValueError(f"어휘 밖 선택: {sorted(unknown)}")

    phase1 = resolve_phase1_case_result(pr)
    if phase1 is None:
        return {"available": False, "matched": 0, "rows": []}
    units = match_units(phase1.units, bodies=set(bodies), features=set(features), strict=strict)
    matched = len(units)
    if top_n is not None:
        units = units[:top_n]
    rows = [_unit_row(unit, phase1) for unit in units]
    _attach_document_meta(rows, phase1, _feature_frame(pr))
    return {
        "available": True,
        "matched": matched,
        "rows": rows,
        "selection": {"bodies": sorted(bodies), "features": sorted(features), "strict": strict},
    }


def build_rule_unit_result(
    pr: Any,
    *,
    rule_id: str,
    top_n: int | None = None,
) -> dict[str, Any]:
    """단일 룰이 발화한 전표/흐름 결과 뷰(어휘 무관 — 커버리지 큐 소비용).

    조합 빌더와 동일한 row 스키마·정렬·메타를 써서 UI 그리드를 그대로 재사용한다.
    """
    from src.export.phase1_case_view import _feature_frame, _unit_row, resolve_phase1_case_result

    target = str(rule_id or "").strip()
    phase1 = resolve_phase1_case_result(pr)
    if phase1 is None or not target:
        return {"available": False, "matched": 0, "rows": []}
    units = [
        unit for unit in phase1.units if any(ref.rule_id == target for ref in unit.evidence_rows)
    ]
    units.sort(key=_builder_sort_key, reverse=True)
    matched = len(units)
    if top_n is not None:
        units = units[:top_n]
    rows = [_unit_row(unit, phase1) for unit in units]
    _attach_document_meta(rows, phase1, _feature_frame(pr))
    return {"available": True, "matched": matched, "rows": rows}


_META_COLUMNS = ("created_by", "posting_date", "counterparty", "gl_account")


def _attach_document_meta(rows: list[dict[str, Any]], phase1: Any, data: Any) -> None:
    """작성자·전기일·거래처·계정을 문서별로 붙인다(문서ID 매칭).

    소스 2개를 병합해 두 세션 상태를 모두 커버:
      1) phase1.cases[].documents(CaseDocumentRef) — 결과에 persist 되어 재시작·DuckDB 폴백
         로드 후에도 살아있음. 단, 상위 case 소속 문서만 커버.
      2) featured frame — 있으면 전 모집단을 덮어써 tail 문서까지 채움(파이프라인 실행 세션).
    둘 다 없으면 빈 문자열. posting_date 는 날짜부(10자)만.
    """
    index = _case_document_index(phase1)
    _overlay_frame_meta(index, data)
    for row in rows:
        doc_ids = row.get("document_ids") or []
        meta = index.get(str(doc_ids[0])) if doc_ids else None
        for col in _META_COLUMNS:
            row[col] = str((meta or {}).get(col) or "")


def _case_document_index(phase1: Any) -> dict[str, dict[str, str]]:
    """document_id → 메타. 재시작 후에도 살아있는 persist 소스."""
    index: dict[str, dict[str, str]] = {}
    for case in getattr(phase1, "cases", None) or []:
        for doc in getattr(case, "documents", None) or []:
            document_id = str(getattr(doc, "document_id", "") or "").strip()
            if not document_id:
                continue
            posting = getattr(doc, "posting_date", None)
            index.setdefault(
                document_id,
                {
                    "created_by": str(getattr(doc, "created_by", "") or ""),
                    "posting_date": str(posting)[:10] if posting else "",
                    "counterparty": str(getattr(doc, "counterparty", "") or ""),
                    "gl_account": str(getattr(doc, "gl_account", "") or ""),
                },
            )
    return index


def _overlay_frame_meta(index: dict[str, dict[str, str]], data: Any) -> None:
    """featured frame 이 있으면 문서별 첫 행 값으로 덮어써 커버리지를 전 모집단으로 넓힌다."""
    if data is None or getattr(data, "empty", True):
        return
    columns = getattr(data, "columns", [])
    present = [c for c in _META_COLUMNS if c in columns]
    if "document_id" not in columns or not present:
        return
    sub = data[["document_id", *present]].drop_duplicates(subset="document_id", keep="first")
    for rec in sub.to_dict("records"):
        document_id = str(rec.get("document_id") or "").strip()
        if not document_id:
            continue
        entry = index.setdefault(document_id, {})
        for col in present:
            value = rec.get(col)
            if col == "posting_date" and value is not None:
                value = str(value)[:10]
            entry[col] = "" if value is None else str(value)
