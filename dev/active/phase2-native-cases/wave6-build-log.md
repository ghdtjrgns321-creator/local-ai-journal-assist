# PHASE2 Native Cases — Wave 6 Build Log

S6 단계 산출물 — Relational + Timeseries detector artifact + builders. 두 family
detector 가 독립이므로 Agent J (Relational) / Agent K (Timeseries) 병렬 진행.

## Agent K — Timeseries (Phase B + Phase D) (2026-05-28)

- 확장 / 신규 파일:
  - src/detection/timeseries_detector.py (+약 250 LoC, Phase B)
    - TimeseriesWindowArtifact dataclass + build_timeseries_window_artifact +
      _append_windows helper 신규
    - _ts_json_safe (duplicate / IC `_json_safe` 패턴 정합), _resolve_subject_column,
      _assign_evidence_tier, _empty_timeseries_window_artifact 추가
    - _build_result 에 metadata key ``timeseries_window_artifact`` 부착
    - _skipped_result 에도 빈 artifact dict 부착 (builder graceful fallback 호환)
  - src/services/phase2_timeseries_case_builder.py (약 200 LoC, 신규, Phase D)
    - build_timeseries_cases + _build_window_case + _make_ref_from_position +
      _column_value + _build_case
  - tests/modules/test_detection/test_timeseries_window_artifact.py (+9 테스트, 약 230 LoC)
    - Phase B 사양 8건 + build_timeseries_window_artifact direct 호출 보조 1건
  - tests/modules/test_services/test_phase2_timeseries_case_builder.py (+12 테스트, 약 215 LoC)
    - Phase D 사양 10건 + moderate tier with sub_signal_high + track_name mismatch 2건
- 기존 timeseries 출력 회귀: 0건 — `test_timeseries_rule.py` 80개 PASS
  (`tests/modules/test_services/` + `tests/modules/test_detection/` +
  `tests/modules/test_models/test_phase2_row_ref.py` 통합 1937 PASS / 3 SKIPPED,
  약 2분 26초)
- pytest Phase B: 9/9 통과 (TS02 fixture skip 조건 통과 — vendor baseline + spike 보강)
- pytest Phase D: 12/12 통과
- Gate: evidence_tier ∈ {strong, moderate} AND sub_signal_high (Δ13 final)
- 도메인 정당화: 모듈 docstring 인용
  - TS01 daily burst → PCAOB AS 2401 §B7 (unusual posting timing / period-end clustering)
  - TS02 unusual frequency → ISA 240 §32 (Management override via timing manipulation)
- ruff format: 4 files left unchanged / ruff check: All checks passed
- 주요 결정 / 이슈:
  - subject 컬럼 우선순위 — `gl_account` 우선, 없으면 `business_process` 로 fallback
    (`_resolve_subject_column`). 둘 다 부재 시 빈 windows 로 graceful fallback.
  - TS01 window = single-day (start == end == posting_date.normalize().date()).
    TS02 window = trailing (start = end - (ts_group_window_days - 1) days,
    end = posting_date). `ts_group_window_days` 는 settings 에서 동적 조회.
  - evidence_tier 분기: 양수 row score 의 q95 strong / q80 moderate / 그 외 weak.
    빈 분포 (q95 == 0) 에서는 양수 score → strong 으로 보수적 처리 (precision/recall
    튜닝 압력 사용 금지, D044).
  - sub_signal_high 단순화 spec (Δ13): `evidence_tier == "strong" AND
    max_score / score_max >= 0.6`. builder 는 detector flag 만 신뢰 — 임계 재정의 안 함.
  - artifact entry 의 row_indices 는 `_ts_json_safe` 평탄화 (MultiIndex tuple → str),
    row_positions 는 int 그대로. builder 는 `_make_ref_from_position` 으로
    `df.index[position]` 을 source of truth 로 사용 (invariant #66, S5 #60 정합).
  - evidence_signature: `f"sub_rule={rule_id}|subject={subject}|window={window_start}"` —
    case identity 만. z_score / daily_count / expected_count 등 raw metric 절대 포함 금지
    (invariant #65, IC builder invariant #55 동일 원칙).
  - `_append_windows` 가 (subject, posting_date_norm) 그룹핑 — 같은 (rule_id, subject,
    day) 가 여러 row 에 등장하면 dedup 후 row_indices / row_positions 가 그 row 들을
    모두 보유. `_WINDOW_ARTIFACT_CAP=500` 으로 운영 가시성 확보.
  - expected_count 는 보수적으로 0.0 유지 — builder 가 case identity 만 사용하므로
    PHASE2 case 의 expected_count 필드도 0.0 으로 전달. baseline 추정치 도입은
    S6.next (family_ecdf 외부 결합 / enrichment) 와 함께 검토.
  - track_name mismatch / metadata 부재 / windows 빈 리스트 → 빈 tuple graceful
    fallback (invariant #68). PHASE1 prior 접근 0건, phase1_case_refs default ()
    (invariant #67).

## Agent J — Relational (Phase A + Phase C) (2026-05-28)

- 확장 / 신규 파일:
  - src/detection/relational_detector.py (219 → 약 360 LoC, Phase A)
    - RelationalEdgeArtifact dataclass + build_relational_edge_artifact +
      _extract_rule_edges helper 신규
    - _rel_json_safe (duplicate / IC `_json_safe` 패턴 정합), _rel_safe_str,
      _column_series_or_blank 보조 헬퍼 추가
    - 룰별 default tier 매핑 (_RULE_DEFAULT_TIER): R03/R05/R06/R07 → strong,
      R01/R02/R04 → moderate. metric_name 매핑 (_RULE_METRIC_NAME) 동시 도입.
    - 룰별 edge 컬럼 매핑 (_RULE_EDGE_COLUMNS): R01/R07 = (trading_partner, ""),
      R02/R04 = ("", gl_account), R03/R05 = (trading_partner, gl_account),
      R06 = (created_by, gl_account).
    - _build_result 에 metadata key ``relational_edge_artifact`` 부착
    - _empty_result 에도 빈 artifact dict 부착 (builder graceful fallback 호환)
  - src/services/phase2_relational_case_builder.py (약 200 LoC, 신규, Phase C)
    - build_relational_cases + _build_case_from_edge + _make_ref_from_position +
      _column_value + _gate_pass
- 기존 relational 출력 회귀: 0건
  - `tests/modules/test_detection/test_relational_*` 77/77 PASS (54s)
  - `tests/modules/test_services/` + `tests/modules/test_detection/` +
    `tests/modules/test_models/test_phase2_row_ref.py` 통합 1937 PASS / 3 SKIPPED
- pytest Phase A: 9/9 통과 (사양 8건 + build_relational_edge_artifact direct 1건)
- pytest Phase C: 11/11 통과 (사양 10건 + multi-row edge → row_refs 다건 1건)
- Gate (Δ5): evidence_tier == "strong" OR (moderate AND family_ecdf >= 0.95).
  builder 단계에서 family_ecdf=0.0 — 실효적으로 strong tier 만 통과. moderate
  통과 검증은 S6.next enrichment (family_ecdf 외부 결합) 활성 후로 유예.
- 도메인 정당화: 모듈 docstring 인용
  - relational_edge_artifact → PCAOB AS 2401 §B7 (relationship-based unusual
    journal entries) + ISA 240 §32 (Management override via unusual relationships)
  - R01~R07 audit standard 인용은 기존 detector docstring / relational_rules
    docstring 의 inline 인용 그대로 유지 (변경 0건).
- ruff format: 4 files left unchanged / ruff check: All checks passed
- 주요 결정 / 이슈:
  - edge_a/edge_b 가 모두 빈 문자열인 row 는 edge 단위 case 의미가 없어 제외
    (`_extract_rule_edges` 내부 가드). R01 (edge_b="") / R02 (edge_a="") /
    R07 (edge_b="") 는 한쪽만 보유해도 edge entry 로 인정.
  - 동일 (rule_id, edge_a, edge_b) 의 여러 row → 하나의 edge entry 로 dedup.
    row_indices / row_positions 가 그 row 들을 모두 보유 → builder 단계의 case
    한 건이 다중 row_refs 를 가질 수 있음 (multi-row edge 테스트 케이스).
  - metric_value 는 raw row score 의 max (group 내). severity 정규화 전 raw
    score 를 사용 — edge 의미상 raw score 가 자연스럽다. detector 의 row 단위
    `details` 는 여전히 severity/5.0 정규화 (회귀 0건 보장).
  - evidence_tier 는 룰별 default 그대로 (D044, precision/recall 튜닝 압력
    사용 금지). settings/audit_rules 파라미터는 schema-stable signature 로
    예약만 — 현재 미사용, 추후 룰별 tier override 확장 여지.
  - evidence_signature: `f"sub_rule={rule_id}|edge_a={edge_a}|edge_b={edge_b}"` —
    case identity 만. metric_value / raw score 절대 포함 금지 (invariant #64,
    IC builder invariant #55 동일 원칙). 검증: metric_value 만 다르면 case_id
    동일, edge_b 한 글자만 바뀌어도 case_id 변경.
  - artifact entry 의 row_indices 는 `_rel_json_safe` 평탄화, row_positions
    는 int 그대로. builder 는 `_make_ref_from_position` 으로 `df.index[position]`
    을 source of truth 로 사용 (invariant #66, S5 #60 정합).
  - track_name mismatch / metadata 부재 / edges 빈 리스트 → 빈 tuple graceful
    fallback (invariant #68). PHASE1 prior 접근 0건, phase1_case_refs default ()
    (invariant #67).
  - Timeseries 측 파일 / IC 측 파일 / S1~S4.next.2 산출물 변경 0건.
