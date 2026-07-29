"""Preprocessing constants shared across training paths."""

from __future__ import annotations

LABEL_COLUMNS = frozenset(
    {
        "is_fraud",
        "fraud_type",
        "is_anomaly",
        "anomaly_type",
        "sod_violation",
        "sod_conflict_type",
        "label",
        "target",
    }
)

# DataSynth-only columns. Real customer CSVs never contain these, so they must
# not appear in raw-data previews, mapping selectboxes, or recommended-mapping
# warnings. Composed of (a) truth labels and (b) manipulation sidecar metadata.
SYNTHETIC_ONLY_COLUMNS = LABEL_COLUMNS | frozenset(
    {
        "mutation_base_event_type",
        "mutation_type",
        "mutation_mutated_field",
        "mutation_original_value",
        "mutation_mutated_value",
        "mutation_reason",
        "detection_surface_hints",
        "is_mutated",
        "is_synthetic",
        "semantic_scenario_id",
    }
)

# ── PHASE2 입력 차단 목록 ─────────────────────────────────────────────
#
# 2026-07-29 이후 이 목록은 **2차 방어**다. 1차는 허용 목록
# (`preprocessing.phase2_features.PHASE2_SOURCE_COLUMNS`)이고, 거기 없으면 애초에
# 들어오지 않는다. 실측상 허용 ∩ 차단 = 0 이라 아래 22칸은 **한 칸도 발동하지 않는다.**
#
# 그래도 남기는 이유는 죽은 코드로 두려는 게 아니라 **허용 목록의 가드레일**이기
# 때문이다. 누군가 허용 목록에 위험한 칸을 추가하면
# `test_allow_list_and_deny_list_never_overlap` 이 즉시 실패한다.
# 차단 사유(왜 위험한가)는 여기에, 미채택 사유(왜 안 넣었나)는 허용 목록 쪽에 적는다.
#
# 구조적 차단 — 재측정으로 풀 수 없다. 데이터가 바뀌어도 유지된다.
#
#   정답지·조작 메모  실 ERP 에 존재하지 않는 칸. AUROC 가 낮아도 쓸 수 없다.
#   식별자            값이 거의 다 달라 모델엔 난수다(document_id 113,465종).
#   비식별화          ip_address 는 정책상 ML 입력 금지.
#   기술 필드         line_number 는 전표 안에서의 줄 위치일 뿐 감사 신호가 아니다.
#
# 날짜 원본(posting_date 등)과 라벨(LABEL_COLUMNS)은 각각 phase2_plan 의
# datetime_raw · leakage_label 갈래가 막으므로 여기 중복 기재하지 않는다.
LEAKAGE_DENY_COLUMNS_STRUCTURAL = frozenset(
    {
        "detection_surface_hints",
        "document_id",
        "document_number",
        "ip_address",
        "is_mutated",
        "is_synthetic",
        "line_number",
        "mutation_base_event_type",
        "mutation_mutated_field",
        "mutation_mutated_value",
        "mutation_original_value",
        "mutation_reason",
        "mutation_type",
        "reference",
        "semantic_scenario_id",
    }
)

# 실측 차단 — 합성 데이터가 실제로 지름길을 흘리는 칸만 남긴다.
#
# 재측정 (2026-07-29, `tools/scripts/diag_deny_basis_recheck.py`, 데이터셋 r9):
#   기준선은 v6 치트루트 감사가 쓴 것 그대로 — HARD AUROC ≥ 0.95 / SOFT 0.80~0.95.
#   차단 중이던 27칸 전수 재측정 결과 **HARD 0건**, SOFT 1건, 나머지 26칸 근거소멸.
#
#   | 칸                        | v6 감사 | r9 재측정 |
#   | debit_amount / credit_amount | 0.917 | 0.71 |
#   | local_amount              | 0.918 | 0.78 |
#   | invoice_amount            | 0.853 | 0.56 |
#   | tax_amount                | 0.848 | 0.57 |
#   | days_backdated            |     — | 0.50 |
#   | exceeds_threshold         |     — | 0.51 |
#
#   v6 근거는 결측 누출·조합 누출이 살아 있던 생성기에서 나온 값이다. r9 에서
#   도너 복제 구조로 재설계하며 그 누출들을 제거했고, 지름길도 같이 사라졌다.
#   근거가 사라진 차단을 남겨두면 원장의 핵심인 차대변 금액을 영구히 못 본다.
#
# **이 목록은 누출 차단 전용이다.** 파생 피처끼리의 중복(금액 계열 다수 등)은
# 여기서 다루지 않는다 — 섞으면 "왜 막혔는지"를 다시 잃는다.
#
# 생성기를 바꾸면 위 스크립트를 다시 돌려 이 목록을 갱신한다.
LEAKAGE_DENY_COLUMNS_MEASURED = frozenset(
    {
        # 문서 단위 AUROC 0.8622 — 유일하게 SOFT 대역에 남았다.
        #
        # 2026-07-29 같은 날 오후, PHASE2 입력이 허용 목록으로 바뀌면서 이 칸을 만드는
        # PHASE1 파생 자체가 입력에서 빠졌다. 따라서 이 조항은 **현재 도달하지 않는다.**
        # 지우지 않는 이유는 측정값이 살아 있기 때문이다 — 누군가 이 파생을 PHASE2
        # 입력에 다시 넣으려 할 때 "쟀더니 SOFT 였다"는 근거가 여기 남아 있어야 한다.
        "near_threshold_gap_ratio",
    }
)

# PHASE1 집계 산출물. 2026-07-28 발견 — `AuditPipeline` 이 aggregate 결과를 원본 DF 에
# 되쓰기(src/pipeline.py:879) 때문에, 그 DF 를 그대로 PHASE2 입력으로 넘기는 경로에서는
# PHASE1 룰 발화·점수가 VAE 입력 피처로 들어간다. 3-surface 비병합(PHASE1/PHASE2 독립,
# FINAL-REPORT 9장 §9.4)의 위반이므로 입력 경계에서 차단한다.
#
# 경로별 실태:
#   신규 실행  — `PipelineResult.featured_data` 는 탐지 전 스냅샷(pipeline.py:850)이라 깨끗.
#   DB 재적재  — `load_batch` 가 featured_data=None 을 주고 journal_entries 테이블에
#                anomaly_score/risk_level 이 저장돼 있어(db/schema.py:115) `.data` 폴백이 오염.
#   측정 스크립트 — `res.data` 를 쓰므로 오염.
# 어느 스냅샷이 넘어왔는지에 의존하지 않도록 deny 목록에서 막는다.
LEAKAGE_DENY_COLUMNS_PHASE1_OUTPUT = frozenset(
    {
        "anomaly_score",
        "risk_level",
        "flagged_rules",
        "review_rules",
        "risk_floor_reasons",
        "topside_score",
    }
)

LEAKAGE_DENY_COLUMNS = (
    LEAKAGE_DENY_COLUMNS_STRUCTURAL
    | LEAKAGE_DENY_COLUMNS_MEASURED
    | LEAKAGE_DENY_COLUMNS_PHASE1_OUTPUT
)

# Stage 5 concentration risk — deterministic Top-5 rule columns are removed
# from ML training inputs to block circular shortcut learning. Rules remain
# available to PHASE1 score_aggregator / PHASE3 narrator.
#
# Stage 5 v4 rerun (artifacts/manipulation_v4_audit_rerun_summary_20260516.md):
# 24-dim AUPRC 0.397, Top-5 deny 후 0.056 (잔존 14.0%, drop ratio 0.86).
# v3 에서 강했던 L1-07-02, L2-02 는 v4 shortcut noise 로 약화되어 deny 에서 제외.
LEAKAGE_DENY_RULES = frozenset(
    {
        "rule_L3-02",  # 수기 전표 (v4 univariate AUPRC 0.1472)
        "rule_L3-09",  # (v4 신규 진입, AUPRC 0.1282)
        "rule_L1-03",  # (v4 신규 진입, AUPRC 0.0827)
        "rule_L2-03",  # 중복 지급 (v4 AUPRC 0.0532)
        "rule_L1-05",  # 자기 승인 (v4 AUPRC 0.0422)
    }
)

DEFAULT_GROUND_TRUTH_LABEL_COLUMNS = (
    "is_fraud",
    "is_anomaly",
)
