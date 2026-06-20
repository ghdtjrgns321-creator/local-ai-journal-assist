"""프로젝트 전역 설정 모듈.

우선순위: 환경변수 > .env > 코드 기본값
YAML 설정(schema, keywords, risk_keywords)은 별도 로더로 읽는다.
"""

from __future__ import annotations

import functools
from pathlib import Path

import yaml
from pydantic import Field, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 프로젝트 루트 = config/ 의 부모
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"


class AuditSettings(BaseSettings):
    """프로젝트 전역 설정. 환경변수 > .env > 코드 기본값 순 우선."""

    # --- 파일 관련 (deprecated: file_validator는 file_categories.py 사용) ---
    # 카테고리별 크기 제한은 src/ingest/file_categories.py에 정의
    # 아래 필드는 하위 호환용으로 유지. 신규 코드에서 참조하지 말 것
    max_file_size_mb: int = 100
    allowed_extensions: list[str] = [
        ".xlsx",
        ".xls",
        ".xlsb",
        ".csv",
        ".tsv",
        ".txt",
        ".dat",
        ".parquet",
    ]

    # --- 헤더 탐지 관련 ---
    min_expected_headers: int = 4  # 키워드 스코어 정규화 분모
    max_header_scan_rows: int = 20  # 상위 N행만 탐색
    min_header_confidence: float = 0.3  # 이하면 탐지 실패 → UI 개입
    # WU-28: 구조 스코어 미달(< min_header_confidence) 시 LLM(gpt-5.4-mini)에 보조 판단 요청.
    # False면 기존 동작(구조 스코어만) — 오프라인/CI 결정론적 테스트용.
    enable_llm_header_fallback: bool = True
    datasynth_label_mode: str = "hidden"
    datasynth_metadata_enforcement: str = "warn"
    enable_ingest_cache: bool = True
    ingest_cache_dir: str = "artifacts/ingest_cache"
    enable_feature_cache: bool = True
    feature_cache_dir: str = "artifacts/feature_cache"

    @field_validator("min_expected_headers")
    @classmethod
    def _check_min_expected_headers(cls, v: int) -> int:
        """0 이하면 스코어 공식이 무의미 → 조기 차단."""
        if v <= 0:
            raise ValueError("min_expected_headers는 1 이상이어야 합니다.")
        return v

    # --- 매핑 관련 (⚠️ 예시값 — 실제 ERP 헤더 매칭 정확도 보며 튜닝) ---
    fuzzy_threshold: int = 80  # 이상이면 확정 매핑
    fuzzy_low_threshold: int = 40  # 이상이면 추천(suggestions), 미만이면 unmapped

    # --- 타입 캐스팅 관련 ---
    casting_null_warn_threshold: float = 0.1  # 캐스팅 후 결측률 경고 임계 (10%)
    casting_null_demote_threshold: float = 0.9  # 90% 초과 → 오매핑 의심
    casting_date_dayfirst: bool = False  # True면 DD/MM/YYYY 해석

    # --- 감사 룰 관련 (⚠️ 예시값 — 실제 감사 기준에 맞춰 조정) ---
    balance_tolerance: float = 1.0  # A01: 차대변 불일치 허용 오차 (원)
    # --- L2 검증 fatal 정책 ---
    # Why: 대차불일치는 회계 복식부기 근본 위반 → 일정 비율 초과 시 파이프라인 중단.
    #      단순히 1행이라도 불일치하면 중단하는 정책은 노이즈 큰 실제 데이터에서 위험하므로
    #      "전체 차변 대비 차이 비율" + "불일치 전표 비중" 두 축으로 판정한다.
    balance_fatal_ratio: float = 0.01  # 전체 차변 대비 절대 차이 비율 임계 (1%)
    balance_fatal_doc_ratio: float = 0.10  # 불일치 전표 비중 임계 (10%)
    chart_of_accounts_path: str = "config/chart_of_accounts.csv"  # A03: CoA 파일 경로
    # 다단계 승인한도 — 한국 중견 제조업 전결규정 반영 (DataSynth v1.2.0)
    # Level 1~6: 자동승인(10M) → 담당자(100M) → 팀장(1B) → 본부장(5B) → CFO(10B) → 이사회(50B)
    approval_thresholds: list[int] = [
        10_000_000,
        100_000_000,
        1_000_000_000,
        5_000_000_000,
        10_000_000_000,
        50_000_000_000,
    ]

    @computed_field
    @property
    def approval_threshold(self) -> int:
        """레거시 호환용. approval_thresholds의 최고 한도 반환."""
        return max(self.approval_thresholds)

    near_threshold_ratio: float = 0.90  # 한도의 90% 이상이면 플래그
    round_unit: int = 1_000_000  # B04: 정수 단위 판정 기준 (100만원)
    zscore_threshold: float = 3.0  # C08: 이상치 기준 (detection에서 사용)
    l403_min_amount_quantile: float = 0.90  # L4-03: 전역 상위 금액 분위수 가드
    midnight_start: float = 22.0  # C03: 심야 전기
    midnight_end: float = 6.0  # C03: 심야 전기
    period_end_margin_days: int = 5  # C01: 기말 판정 마진 (월말 전후 n일)
    fiscal_year_start: int = 1  # 회계연도 시작월 (1=1월, 4=4월~3월)
    custom_holidays: list[str] = []  # 회사 지정 휴일 ["2025-07-01"]

    # --- Detection Layer B 관련 ---
    duplicate_payment_window_days: int = 90  # B04: 중복 지급 판정 기간 (일)
    sod_process_threshold: int = 3  # L3-12: 업무범위 검토 fallback 프로세스 수 임계
    topside_threshold: int = 2  # B19: Top-side JE 가점 임계 (5점 만점, 수기 전제)
    expense_capitalization_amount_tolerance: float = 0.02  # B11: 자산/비용 금액 허용 오차 (2%)
    expense_capitalization_min_amount: float = 0.0  # B11: 소액 라인 제외 기준 (0=미적용)

    # --- DuplicateDetector (WU-05) ---
    duplicate_fuzzy_threshold: int = 80  # B05b: 적요 유사도 임계 (rapidfuzz 0~100)
    duplicate_amount_tolerance: float = 0.02  # B05b/c: 금액 허용 오차 (2%)
    duplicate_reference_max_frequency_ratio: float = 0.10  # L2-03: 특정 reference 반복률 상한
    duplicate_reference_min_unique_ratio: float = 0.20  # L2-03: reference 전체 고유율 하한
    duplicate_reference_nonunique_min_count: int = 10  # L2-03: 비고유 가드 최소 반복 건수
    duplicate_split_window_days: int = 3  # B05c: 분할 거래 윈도우 (일)
    duplicate_time_window_days: int = 7  # B05d: 시차 중복 윈도우 (일)
    duplicate_max_group_size: int = 1000  # 그룹 크기 제한 (초과 시 스킵)
    # pair similarity artifact (Phase 2 duplicate family 보강)
    # Why: 정상 반복 거래(월세·주차료)에서 pair 폭발 방지 + metadata payload 크기 제한.
    duplicate_max_pairs_per_row: int = 200  # 단일 row가 진입할 수 있는 pair 상한
    duplicate_max_total_pairs: int = 200_000  # 내부 candidate pair 절대 상한
    duplicate_pair_artifact_top_n: int = 500  # metadata 노출용 top-N pair (sanitized)
    # Default remains the fixed5 document-diversity retention path. evidence_diversity
    # is a Phase 4 candidate selector for audit-observable pair ordering comparison.
    duplicate_pair_artifact_selection_strategy: str = "rule_balanced_evidence"
    # top-N diversity pass soft caps. If the diverse pass cannot fill top_n, remaining
    # high-score pairs may fill the artifact and exceed these caps.
    duplicate_pair_artifact_max_pairs_per_document: int = 5
    duplicate_pair_artifact_max_pairs_per_document_pair: int = 1
    # Why: row scoring 은 벡터화돼 있어 100k 행이 1초 내 끝나지만 pair feature 산출은
    #      blocking sweep 비용이 크다. 대용량 입력에서는 artifact 만 graceful skip.
    duplicate_pair_artifact_max_rows: int = 50_000
    # Large-input supplement lane. Keeps the score-ranked row subset, but reserves
    # a small bounded budget for audit-observable duplicate-shaped documents that
    # lower score can otherwise exclude before pair evidence is generated.
    duplicate_pair_artifact_candidate_supplement_strategy: str = "observable_profile"
    duplicate_pair_artifact_candidate_supplement_max_docs: int = 500
    duplicate_recurring_suppress_enabled: bool = True
    duplicate_recurring_min_series_length: int = 3
    duplicate_recurring_min_interval_days: int = 21
    duplicate_recurring_max_interval_days: int = 100
    duplicate_recurring_interval_cv_threshold: float = 0.20
    duplicate_recurring_near_extra_ratio: float = 0.50
    duplicate_recurring_amount_band_ratio: float = 0.01
    duplicate_recurring_amount_band_min: float = 1000.0
    duplicate_recurring_near_extra_allowed_sources: list[str] = ["manual", "adjustment"]
    duplicate_recurring_near_extra_suppressed_sources: list[str] = [
        "automated",
        "auto",
        "recurring",
        "batch",
        "interface",
        "system",
    ]
    duplicate_recurring_near_extra_suppressed_processes: list[str] = [
        "R2R",
        "Intercompany",
    ]
    duplicate_recurring_near_extra_suppressed_process_tokens: list[str] = [
        "closing",
        "close",
        "accrual",
        "period_end",
        "period end",
        "month_end",
        "month end",
        "결산",
        "미지급",
        "발생",
    ]

    # --- Detection Layer C 관련 ---
    backdated_threshold_days: int = 30  # C04: 전기일-문서일 괴리 임계 일수
    suspense_aging_days: int = 30  # C10: 가계정 장기체류 기본 임계 일수
    suspense_min_open_amount: float = 0.0  # C10: 장기체류 판정 최소 미정리 금액
    account_pair_rare_percentile: float = 0.01  # C09: 희소 쌍 하위 백분위

    # --- Detection Layer C: C13 배치 전표 이상 ---
    batch_source_values: list[str] = [
        "batch",
        "interface",
        "system",
        "auto",
        "automated",
        "if",
        "sys",
        "BATCH",
        "INTERFACE",
        "SYSTEM",
        "AUTO",
        "AUTOMATED",
        "IF",
        "SYS",
    ]  # source 컬럼 배치/자동 전표 식별 값
    batch_period_end_ratio: float = 0.5  # 기말 집중 비율 임계
    batch_simultaneous_threshold: int = 50  # 동일일자 동시 생성 건수 임계
    batch_amount_zscore: float = 3.0  # 배치 내 금액 Z-score 임계

    # --- Detection Layer C: C11 역분개 ---
    reversal_mirror_window_days: int = 90  # L2-05: 1:1 거울 쌍 매칭 허용 일수

    # --- RelationalDetector (WU-08) ---
    rel_new_cp_large_quantile: float = 0.90  # R01: 대액 기준 분위수
    rel_new_cp_lookback_days: int = 90  # R01: 신규 거래처 판정 기간 (일)
    rel_dormant_inactive_days: int = 180  # R02: 휴면 계정 판정 기간 (일)
    rel_dormant_reactivation_window_days: int = 7  # R02: 연좌 플래깅 윈도우 (일)
    rel_dormant_reactivation_min_amount: float = 0.0  # R02: 재활성화 최소 금액 (0=제한없음)
    rel_tp_ic_deviation_threshold: float = (
        1.0  # R03: IC 가격 편차 허용 (truth-negative q95 ≈ 0.9995)
    )
    rel_tp_min_ic_pairs: int = 5  # R03: 최소 비교 쌍 수 (그룹 통계 유의미 최소 표본)

    # --- RelationalDetector graph/entity 보강 (R05~R07) ---
    # Why: Phase 2 relational family를 graph/entity anomaly로 격상.
    #      모든 sub-detector는 컬럼 부재 시 0 반환 (graceful), small sample 가드 포함.
    rel_r05_min_pair_population: int = 50  # R05: rare 판정 최소 unique pair 수 (small sample 가드)
    rel_r05_min_freq: int = 2  # R05: rare pair 판정 최대 빈도
    rel_r05_lookback_days: int = 90  # R05: 첫 등장 recency bonus 윈도우 (일)
    rel_r06_period: str = "M"  # R06: degree bucket period ("M" month 또는 "W" week)
    rel_r06_z_threshold: float = 2.0  # R06: robust z-score (MAD 기반) 임계
    rel_r06_min_user_obs: int = 3  # R06: user별 period 관측 수 최소 (통계 유의미)
    rel_r06_min_users: int = 10  # R06: 모집단 user 수 최소 (small sample 가드)
    rel_r07_partner_inactive_days: int = 180  # R07: trading_partner 휴면 판정 일수
    rel_r07_reactivation_window_days: int = 7  # R07: 재활성화 윈도우 (일)
    rel_r07_min_amount: float = 0.0  # R07: 재활성화 최소 금액 (0=제한없음)

    # --- GraphDetector (WU-22) — networkx 기반 순환/이전가격 탐지 ---
    # Why: 회계 장부 100만+ 행을 graph에 올리면 OOM. pandas 사전 필터 + from_pandas_edgelist 강제.
    graph_gr01_max_cycle_length: int = 5  # GR01: simple_cycles length_bound (Johnson 폭주 방지)
    graph_gr01_min_amount: float = (
        10_000_000.0  # GR01: 엣지 최소 금액 (materiality 추정치, 1천만원)
    )
    graph_gr01_max_edges: int = 50_000  # GR01: 엣지 수 상한 (초과 시 min_amount 자동 상향)
    graph_gr01_max_component_size: int = 500  # GR01: component 노드 임계 (엣지도 크면 skip)
    graph_gr01_max_component_edges: int = 5_000  # GR01: component 엣지 임계 (노드도 크면 skip)
    graph_gr03_min_path_length: int = 2  # GR03: 경로 최소 노드 수
    graph_gr03_price_deviation_threshold: float = 0.20  # GR03: 양방향 가격 편차 허용 (20%)

    # --- NLPDetector (WU-21) — 적요 임베딩 기반 의미 탐지 ---
    # Why: ISA 315/240 경제적 실질 검증. OpenAI 임베딩 + kiwipiepy morpheme_tokens.
    #      비식별화 — 원본 적요 전송 금지, 형태소 join만 API 전달.
    nlp_header_account_threshold: float = 0.30  # NLP01: header-account 코사인 유사도 미만 → 불일치
    nlp_process_account_threshold: float = (
        0.30  # NLP02: process-account 코사인 유사도 미만 → 불일치
    )
    nlp_anomaly_percentile: float = 0.95  # NLP03: gl_account 그룹 centroid 거리 상위 분위수
    nlp_ic_similarity_threshold: float = 0.50  # NLP04: IC 클러스터 평균 거리 기준
    nlp_synonym_threshold: float = 0.70  # NLP05: risk keyword 임베딩 유사도 임계
    nlp_embedding_batch_size: int = 100  # 임베딩 API 배치 크기
    nlp_min_group_size: int = 5  # NLP03/NLP04: centroid 산출 최소 표본 (소규모 그룹 스킵)

    # --- IntercompanyMatcher (WU-07) ---
    ic_amount_tolerance: float = 0.05  # IC01/IC02: 금액 허용 오차 (5%)
    ic_max_diff_ratio: float = 0.10  # IC02: 최대 비율 (10% → score 1.0)
    ic_cross_currency_ratio_threshold: float = 20.0  # IC02: 통화 미상 시 FX 의심 금액비 가드
    ic_date_window_days: int = 5  # IC03: 정상 시차 허용 (일)
    ic_max_day_diff: int = 30  # IC03: 최대 시차 (30일 → score 1.0)
    ic_min_ic_rows: int = 2  # 최소 IC 행 수 (미달 시 스킵 + warning)
    ic_use_related_party_master: bool = True  # IC01: YAML related_party_master 사용 여부
    ic_period_boundary_days: int = 5  # IC03: 결산 경계 reason code 부착용 (월말 ±N일)
    # PHASE2 internal probabilistic reconciliation (IC01~03 보강) 폴백 기본값.
    # Why: audit_rules.yaml::patterns.intercompany.matching_weights /
    #      candidate_blocking 미지정 시 사용.
    ic_prob_weight_amount: float = 0.40
    ic_prob_weight_date: float = 0.25
    ic_prob_weight_reference: float = 0.20
    ic_prob_weight_counterparty: float = 0.15
    ic_prob_amount_bucket_factor: float = 2.0
    ic_prob_max_candidates_per_row: int = 50
    ic_prob_reference_min_length: int = 3
    # contract-tier score caps (audit evidence strength 기준, truth recall 튜닝 금지).
    # Why: no_candidate (counterpart 가 후보로 잡히지 않은 row) 는 정상 단방향 거래나
    #      matching evidence 부족과 양립하므로 strong anomaly 처럼 다루면 정상 row 가
    #      Phase2 Noisy-OR TOP 구간을 오염시킨다. candidate mismatch (실제 reconciliation
    #      gap 가 측정된 case) 만 강한 점수를 받을 수 있게 cap 을 분리한다.
    #   - L1 + candidate mismatch: 1.0 — counterparty + reference 식별자 명확한데 gap → 강 증거
    #   - L1 + no_candidate:       0.5 — counterpart 명확한데 후보 없음 → 단방향 양립, mid review
    #   - L2 + candidate mismatch: 0.7 — reference 약함으로 매칭 정밀도 하락, FP 가능
    #   - L2 + no_candidate:       0.3 — matching evidence 약함 + 후보 없음, weak review
    #   - weak cp_block:           0.3 — cc/tp 모두 비어 anchor 부재, matching evidence 자체 부족
    #   - L3 insufficient:         0.0 — matching 불가능 (early return, 폴백용 상수)
    ic_prob_l1_mismatch_cap: float = 1.0
    ic_prob_l2_mismatch_cap: float = 0.7
    ic_prob_no_candidate_cap_l1: float = 0.5
    ic_prob_no_candidate_cap_l2: float = 0.3
    ic_prob_weak_contract_cap: float = 0.3
    ic_prob_l3_cap: float = 0.0

    # --- IC timing_prob 도메인 분리 (정상 결산 close lag vs 의심 timing gap) ---
    # Why: ic_timing_prob 는 단독 row 의 day_diff/max_day_diff 만 보고 1.0 박는다.
    #      정상 IC 는 receivable 측 월말 결산 → payable 측 다음 달 인식 패턴이
    #      흔하다 (K-IFRS / KICPA cutoff). 시차만 큰 정상 close lag 가 의심 timing
    #      gap 과 동일 점수로 합류하면 IC family TOP 구간이 정상으로 채워진다.
    #      audit 의미상 timing 단독은 weak signal, timing + (amount mismatch /
    #      weak counterparty / no reference) 조합만 strong evidence 로 본다.
    ic_timing_grace_window_days: int = 14  # month-end close lag 판정 day_diff 한계
    ic_timing_month_end_window_days: int = 7  # 월말/월초 N일 정의 (raw close pattern)
    ic_timing_amount_strong_min: float = 0.95  # amount_sim ≥ → amount 강한 매칭 판정
    ic_timing_cp_strong_min: float = 0.5  # cp_score ≥ → counterparty 강한 매칭 판정
    ic_timing_ref_strong_min: float = 0.7  # reference_sim ≥ → ref 강한 매칭 판정
    ic_timing_only_weak_cap: float = 0.3  # 모든 evidence 강할 때 timing 단독 cap

    # --- PHASE2 internal: single-document reciprocal IC flow (ic_reciprocal_flow_prob) ---
    # Why: 정상 IC 는 receivable 또는 payable 한 쪽 GL 만 단일 doc 에 기록하고
    #      양측 reconciliation 으로 검증된다 (분석 결과 fixed5: 정상 9,256건 single-doc
    #      reciprocal GL 비율 0%). receivable + payable GL pair 가 같은 doc 안에
    #      self-balanced 로 동시 기표되면 양측 검증 없이 한 회사가 임의로 양변을
    #      동시 처리한 것 (ISA 550 §23 related-party 사업상 합리성 결여,
    #      PCAOB AS 2401 management override). cap/weight 는 audit evidence 강도
    #      기준이며 fixed5 truth recall 기준으로 튜닝 금지.
    ic_reciprocal_amount_similarity_min: float = 0.95  # 1 - |rec-pay|/max ≥ threshold
    ic_reciprocal_min_structural_score: float = 0.5  # structural 미달 시 context boost 차단
    ic_reciprocal_structural_weight: float = 0.7  # bounded combination weight (structural)
    ic_reciprocal_context_weight: float = 0.3  # bounded combination weight (context)
    ic_reciprocal_context_period_end_days: int = 5  # 월말/월초 N일 (posting_date.day 기반)
    ic_reciprocal_context_round_amount_unit: float = 1_000_000.0  # round amount 판정 단위
    ic_reciprocal_context_period_end_weight: float = 0.4  # context sub-weight (sum=1)
    ic_reciprocal_context_after_hours_weight: float = 0.3
    ic_reciprocal_context_round_weight: float = 0.3

    # --- Detection Layer C: C12 비정상 시간대 집중 분석 ---
    normal_hours_start: float = 8.5  # 정상 업무시간 시작 (08:30)
    normal_hours_end: float = 18.5  # 정상 업무시간 종료 (18:30)
    settlement_start_mmdd: str = "1220"  # 결산 집중기간 시작 (12월 20일)
    settlement_end_mmdd: str = "0115"  # 결산 집중기간 종료 (1월 15일)

    @field_validator("settlement_start_mmdd", "settlement_end_mmdd")
    @classmethod
    def _check_mmdd_format(cls, v: str) -> str:
        """MMDD 형식 검증 — 잘못된 값은 silent 오탐 유발."""
        if len(v) != 4 or not v.isdigit():
            raise ValueError(f"MMDD 형식이어야 합니다 (예: '1220'): {v!r}")
        m, d = int(v[:2]), int(v[2:])
        if not (1 <= m <= 12 and 1 <= d <= 31):
            raise ValueError(f"유효하지 않은 월/일: month={m}, day={d}")
        return v

    abnormal_sigma_threshold: float = 2.5  # 사용자별 이상치 판정 σ
    rapid_approval_minutes: int = 5  # 부실 검토 의심 임계 (분)
    min_abnormal_ratio: float = 0.1  # σ 이상치여도 절대 비율 10% 미만이면 미플래그
    min_midnight_entries: int = 3  # 소수 인원 폴백 시 최소 심야 건수
    min_user_entries: int = 10  # C12: 사용자별 최소 전표 건수 (미달 시 분석 제외)
    # C12: 실사용자 심야 다건 보조 조건
    min_high_context_midnight_entries: int = 100
    auto_entry_sources: list[str] = [  # 자동 전기 소스 (급속 승인 검증 제외 대상)
        "batch",
        "interface",
        "system",
        "automated",
        "recurring",
        "auto",
        "BATCH",
        "IF",
        "SYS",
    ]

    # --- Detection Layer D: 전기 대비 변동 ---
    variance_threshold: float = 0.5  # D01: 계정 거래 활동량 변동률 플래그 임계 (50%)
    monthly_pattern_threshold: float = 0.3  # D02: JSD 플래그 임계
    min_monthly_data_months: int = 3  # D02: 비교 수행 최소 월수
    d02_min_account_docs: int = 100  # D02: 계정 단위 최소 당기 문서 수
    d02_min_annual_amount: float = 0.0  # D02: 계정 단위 최소 당기 활동금액
    d02_min_top_month_delta: float = 0.25  # D02: 최대월 비중 변화 최소값
    d02_review_score: float = 0.2  # D02: 단독 review signal 점수 상한
    d02_group_keys: list[str] = ["company_code", "gl_account"]  # D02 평가 단위

    # --- Detection Access Audit (WU-15) ---
    aa01_high_amount_quantile: float = 0.90  # AA01: 고액 판정 분위수
    aa04_max_delay_days: int = 3  # AA04: 승인 지연 임계 (영업일)

    # --- Detection Evidence (WU-14) ---
    ev_tax_threshold: float = 30_000  # EV01: 적격증빙 필요 금액 (원, 한국 세법 기준)
    ev_split_max_amount: float = 29_000  # EV01: 분할 의심 건당 상한
    ev_split_min_count: int = 3  # EV01: 분할 의심 최소 건수
    ev_revenue_cutoff_days: int = 5  # L3-11: 매출 컷오프 허용 일수
    ev_expense_cutoff_days: int = 7  # L3-11: 비용 컷오프 허용 일수
    ev_cutoff_period_end_weight: float = 1.5  # L3-11: 기말 가중 계수
    ev_cutoff_max_day_diff: int = 30  # L3-11: 최대 차이일수 (score=1.0 상한)
    ev_cutoff_use_business_days: bool = True  # L3-11: 영업일 계산 사용 여부
    ev_amount_tolerance: float = 1.0  # EV03: 3-way matching 허용 오차 (원)
    ev_vat_rate: float = 0.10  # EV03: 부가세율 (한국 표준 10%)
    ev_vat_tolerance: float = 1.0  # EV03: 부가세 검증 허용 오차 (원)

    # --- Detection TrendBreak (WU-16) ---
    trendbreak_min_periods: int = 2  # TB01/TB02: 최소 비교 기간 수 (3개년 잔액 = 2개 error)
    trendbreak_bias_ratio: float = 0.8  # TB01: 동일 부호 비율 임계
    trendbreak_extremity_quantile: float = 0.1  # TB02: 극단 영역 분위수 (상/하위 10%)
    trendbreak_max_years: int = 5  # 다기간 로더: 최대 조회 연도 수
    trendbreak_min_years: int = 3  # 다기간 로더: 최소 유효 연도 수

    # --- Detection Timeseries (TS01/TS02) ---
    # Why: legacy boolean rolling mean+sigma 파라미터. ts_* statistical anomaly
    # 경로로 대체 예정이나, 외부 직접 참조가 없어졌음을 별도 PR에서 확인 후 제거.
    burst_window_days: int = 7  # legacy TS01 boolean (deprecated)
    burst_sigma: float = 3.0  # legacy TS01 boolean (deprecated)
    frequency_window_days: int = 7  # legacy TS02 boolean (deprecated)
    frequency_min_count: int = 5  # legacy TS02 boolean (deprecated)

    # --- Detection Timeseries statistical anomaly (TS sub-signal v2) ---
    # Why: rule-style boolean → robust z-score + ECDF 정규화 + period-end
    # concentration 결합. 임계는 ECDF percentile 단일 기준으로 일관화.
    ts_burst_window_days: int = 14  # 일별 burst robust baseline 롤링 윈도우
    ts_group_window_days: int = 7  # 그룹(vendor/account) 단기 빈도 윈도우
    # Why(min_support): baseline 유의성 확보. 5건은 baseline median 이 0~1 에 머물러 spike
    # 변별력이 없다. 10건은 group 시계열이 최소 baseline 형성 가능한 도메인 기준이다.
    # 본 값은 anomaly semantics 기준이며 truth recall 기준이 아니다.
    ts_group_min_support: int = 10  # 그룹 baseline 산출 최소 표본 (5→10, sanity guard)
    # Why(spike 정의 가드): broad activity 를 anomaly 로 보지 않기 위한 sanity guard.
    # 이전 group_frequency 는 단순 활동 빈도를 spike 로 오인하여 분포 62% case 가 nonzero
    # 였다. 아래 3 조건을 모두 충족할 때만 group spike 로 인정한다 (AND 조건).
    #   - 활성일 ≥ 3: 단일 일자 burst 는 daily_burst(TS01) 영역. group spike 는 기간 패턴.
    #   - 절대 excess ≥ 3: PCAOB AS 2401 burst 표준 ("baseline 대비 +3 건 이상").
    #   - 비율 ≥ 2.0: 회계 burst 표준 ("double the normal"). 1.5 는 노이즈.
    # 값은 truth recall 튜닝이 아니라 도메인 anomaly semantics 기준이다.
    ts_group_min_active_days: int = 3  # group spike 인정 최소 활성일
    ts_group_min_excess_count: int = 3  # group spike 인정 최소 절대 초과 건수
    ts_group_spike_ratio_min: float = 2.0  # group spike 인정 최소 비율 (current/baseline)
    # Why(cold_start_score_cap): baseline_median=0 인 cold-start group 의 단순 1~2 건 첫
    # 활동은 strong anomaly 가 아닌 context 신호로만 본다. cap 값은 기존 period_end
    # context_cap=0.30 과 일관. cold-start 은 baseline 정보가 없으므로 boost 입력 자격만.
    ts_group_cold_start_score_cap: float = 0.30
    ts_burst_high_pctile: float = 0.95  # TS01 boolean 임계 (ts01_signal ECDF)
    ts_freq_high_pctile: float = 0.95  # TS02 boolean 임계 (s2 ECDF)
    ts_period_end_window_days: int = 3  # 월말/분기말 근접도 선형 감쇠 윈도우
    ts_period_end_high: float = 0.80  # period_end_concentration high score 기준
    # Why: ISA 240 ¶A41 의 "period-end transactions" 는 routine 결산 거래를 포함한다.
    # unusual 로 격상하려면 amount/frequency/volume baseline 이상 신호가 함께 있어야 한다.
    # cap=0.30 — TS01 boolean 임계 0.95 보다 훨씬 낮아 context 없는 period-end-only 는
    # row score 가 weak band 에 머물러 boolean flag 도, family TOP 점유도 차단된다.
    # threshold=0.50 — ECDF median. anomaly context (s1/s2/amount_tail) 가 분포 상위 절반
    # 이상이어야 "충분한 context" 로 간주. 값은 truth-recall 튜닝이 아니라 도메인 기준.
    ts_period_end_context_cap: float = 0.30
    ts_period_end_context_threshold: float = 0.50
    # Why(strong_present_threshold): row_score 결합식의 evidence role gating 임계.
    # strong_score = max(daily_burst_ecdf, group_spike_ecdf) 가 본 임계 이상이어야 context
    # (period_end / amount_tail) 가 raw 값으로 row_score 에 기여한다. strong 부재 시 context
    # 는 ts_period_end_context_cap 이하로 cap → context 단독 high score 차단. 값은 도메인
    # 기준 (context_cap 과 동일) — broad activity 를 anomaly 로 보지 않기 위한 sanity guard.
    ts_strong_present_threshold: float = 0.30

    # --- TS composite temporal anomaly (3-axis 결합식) ---
    # Why: strong axis (daily_burst/group_spike) 가 단일 사건 fraud 패턴 (fictitious_entry
    # 1~2 건 추가, period_end_adjustment 결산 분개, expense_capitalization 단일 자본화)
    # 를 모두 우회한다. amount_tail / period_end / after_hours / manual / round 같은
    # context+rarity 신호가 *결합* 될 때만 strong band 진입을 허용하는 composite path 를
    # 추가한다. 단독 신호는 cap 이하 — context_count >= 2 + rarity_tail >= q95 OR
    # context_count >= 3 + rarity_tail >= q90 만 cap 초과 허용. 모든 임계는 audit anomaly
    # semantics 기준 (분포 위치, evidence count). truth recall 기준 튜닝 금지.
    # Why: evidence_count = context_count + rarity_high_count. 3 이상 + context >= 1 이면
    # composite path 통과. 단독 신호 (rarity 1 + context 0, context 1 + rarity 0) 모두 차단.
    ts_composite_min_evidence_count: int = 3
    ts_composite_tail_q: float = 0.90  # moderate path rarity 분포 임계 (상위 10%)
    ts_composite_strong_tail_q: float = 0.95  # strong-composite path rarity 분포 임계 (상위 5%)
    ts_composite_context_boost_max: float = 0.80  # composite path row_score 상한
    # Why: context 신호 boolean 판정 임계. period_end_concentration raw score 가 본 값 이상
    # 일 때만 context_count 에 산입. 0.05 는 노이즈 floor (proximity * percentile_tail
    # 곱에서 D-3 ~ 0.5 percentile 인 경우 0.125 이상 산출, 그 이하는 약한 결산기 인접).
    ts_composite_period_end_min: float = 0.05
    # Why: rarity sub-signal 의 batch-local ECDF 산출 시 unique pair 수가 본 값 미만이면
    # 통계적으로 의미 있는 rare 판정 불가 → 전체 0. R05 와 일관 (rel_r05_min_pair_population).
    ts_rarity_min_pair_population: int = 50

    # --- L3 통계 검증 (statistical_validator) ---
    monthly_volatility_zscore: float = 2.0  # 월별 변동률 이상 판정 Z-score
    shapiro_alpha: float = 0.05  # 정규성 검정 유의수준
    benford_mad_threshold: float = 0.012  # MAD 이상 판정 (Nigrini "acceptable")
    benford_min_sample: int = 100  # Benford 최소 표본
    benford_chi2_alpha: float = 0.05  # Chi-square 유의수준
    hhi_concentrated_threshold: float = 0.25  # HHI 집중 판정
    cv_high_threshold: float = 1.0  # 계정 CV 고변동 판정

    # --- 텍스트 피처 관련 ---
    min_description_length: int = 3  # C06: poor/normal 경계 글자수
    ttr_threshold: float = 0.3  # C06: TTR(어휘다양성) < 0.3 → poor
    entropy_threshold: float = 1.0  # C06: Shannon entropy < 1.0 → poor

    # --- 매핑 프로파일 관련 ---
    profile_dir: str = "data/profiles"  # 프로파일 저장 디렉토리

    # --- ML Pipeline (Phase 2) ---
    phase2_training_mode: str = "unsupervised_autoencoder_mvp"
    phase2_train_max_rows: int = 50_000
    phase2_profile_max_rows: int = 100_000
    phase2_random_seed: int = 42
    phase2_review_capacity_ratio: float = 0.10
    phase2_unsup_train_ratio: float = 0.80
    phase2_unsup_calibration_rows: int = 50_000
    phase2_calibration_size: float = 0.20
    phase2_split_strategy: str = "group"
    phase2_split_group_column: str = "document_id"
    phase2_temporal_column: str = "posting_date"
    phase2_low_card_rare_min_count: int = 2
    phase2_reconstruction_group_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "numeric": 1.0,
            "categorical": 1.0,
            "amount": 1.0,
            "boolean": 1.0,
            "date": 1.0,
            "indicator": 1.0,
        }
    )
    vae_latent_dim: int = 32
    vae_hidden_dim: int = 64
    vae_epochs: int = 50
    vae_batch_size: int = 256
    vae_lr: float = 1e-3
    vae_beta: float = 1.0
    vae_posterior_collapse_ratio_threshold: float = 1e-4
    if_contamination: float = 0.01  # IsolationForest
    cv_folds: int = 5
    cv_scoring: str = "f1_macro"
    supervised_min_positive: int = 50
    supervised_min_positive_rate: float = 0.01
    supervised_allowed_label_sources: list[str] = [
        "ground_truth",
        "synthetic",
        "holdout_test",
        "train_oof",
        "oof_fold",
    ]

    # --- FT-Transformer (WU-01b) ---
    ft_d_token: int = 64  # 피처 토큰 임베딩 차원
    ft_n_layers: int = 2  # Transformer 인코더 레이어 수
    ft_n_heads: int = 4  # Multi-head attention 헤드 수
    ft_d_ff: int = 128  # Feed-forward 은닉 차원
    ft_dropout: float = 0.1  # Dropout 비율
    ft_epochs: int = 50  # 학습 에폭 수
    ft_batch_size: int = 256  # 배치 크기 (~300MB VRAM)
    ft_lr: float = 1e-3  # 학습률 (Adam)

    # --- BiLSTM Sequence (WU-01c) ---
    bilstm_hidden_size: int = 64  # BiLSTM 은닉 차원 (bidirectional → 출력 128)
    bilstm_seq_len: int = 16  # 시퀀스 윈도우 길이
    bilstm_stride: int = 16  # 학습 슬라이딩 윈도우 보폭 (detect는 stride=1 고정)
    bilstm_epochs: int = 50  # 학습 에폭 수
    bilstm_batch_size: int = 256  # 배치 크기 (~100MB VRAM)
    bilstm_lr: float = 1e-3  # 학습률 (Adam)
    bilstm_dropout: float = 0.3  # Dropout 비율
    bilstm_num_layers: int = 1  # LSTM 레이어 수

    # --- Stacking Meta-Learner (WU-03) ---
    # Why: MVP는 3-fold + 병렬화로 학습 시간 페널티 상쇄 (BiLSTM/FT-T 5번 재학습 부담).
    #      Phase 3 안정화 후 5로 승격 권장 (통계적 표준).
    stacking_cv_folds: int = 3  # OOF fold 수 (GroupKFold)
    stacking_oof_n_jobs: int = -1  # OOF fold 병렬 학습 (joblib n_jobs)
    stacking_min_positive: int = 50  # fallback 판정: 양성 최소 건수
    stacking_fallback_threshold: float = 0.01  # fallback 판정: 양성 비율 미만
    stacking_alpha: float = 1.0  # Ridge 규제 강도

    # --- Risk Level Classification ---
    # Why: Stacking Ridge 출력은 진짜 확률이 아니므로 "HIGH=0.9 = 90% 확률" 해석은
    #      오해. 분위수 모드는 score 분포 기준 상위 N% 를 HIGH로 분류한다.
    #      "absolute" = 기존 동작 (RISK_THRESHOLDS 절대값), "quantile" = 분위수.
    risk_classification_mode: str = "absolute"
    risk_quantile_high: float = 0.90  # 상위 10% → HIGH
    risk_quantile_medium: float = 0.75  # 상위 25% → MEDIUM 이상
    risk_quantile_low: float = 0.50  # 상위 50% → LOW 이상

    # --- Detection Parallelism (묶음 2) ---
    # Why: pandas/numpy 내부 연산은 GIL 해제 → ThreadPoolExecutor로 독립 탐지기
    #      병렬화. ProcessPool은 DataFrame pickle 비용(1M 행 기준 수 초)이 커서
    #      오히려 느림. None이면 순차 실행(테스트/디버깅용).
    # 2026-05-18 벤치 결과: 1.07M 행 / 4 workers 에서 단축 0.4% (268.67s → 267.63s).
    # 각 detector wall time이 2~24x 길어짐 — Python 코드(.map/.apply/loop/regex)가
    # GIL을 잡고 있어 ThreadPool 이득이 거의 없고 contention만 발생. 순차 유지.
    detection_parallel_workers: int | None = None

    # --- Detection execution scope ---
    # Why: Phase 1 default path is L1-L4 plus L3-11, and D01/D02 when prior data exists.
    #      enable_evidence_detection controls optional EV01/EV03 extensions only;
    #      L3-11 cutoff runs by default through the PHASE1 base detector path.
    enable_timeseries_detection: bool = False
    enable_relational_detection: bool = False
    enable_graph_detection: bool = False
    enable_nlp_detection: bool = False
    enable_access_audit_detection: bool = False
    enable_evidence_detection: bool = False
    enable_trendbreak_detection: bool = False
    enable_variance_detection: bool = True
    enable_ml_detection: bool = False

    # --- SHAP Explainer (WU-17) ---
    # Why: SHAP 연산은 무거움(10만 건 → 수십 분). 이상 전표만 설명하면 충분.
    shap_threshold: float = 0.7  # anomaly_score 하한 — 이 이상인 전표만 SHAP 계산
    shap_max_rows: int = 500  # 안전 상한 — flagged rows가 많아도 상위 N건만

    # --- DB ---
    duckdb_path: str = "data/audit.duckdb"

    # --- LLM API (Phase 3 OpenAI) ---
    # 2티어 분리: light(gpt-5.4-mini)=일상 호출, reasoning(gpt-5.4)=심층 추론·최종 보고서
    openai_api_key: str = ""  # AUDIT_OPENAI_API_KEY 환경변수 주입
    openai_light_model: str = "gpt-5.4-mini"  # 경량 호출용 (전처리 제안, Text-to-SQL, NLP 등)
    openai_reasoning_model: str = "gpt-5.4"  # 심층 추론용 (최종 보고서, XAI 내러티브)
    openai_embedding_model: str = "text-embedding-3-small"  # RAG 임베딩
    openai_temperature: float = 0.1  # 감사 분석은 정확성 우선 → 낮은 temperature
    openai_timeout: float = 60.0  # 초

    # --- WU-25: LLM 인사이트 + XAI Narrative ---
    # Why: 긴 JSON 배열을 한 번에 생성하면 GPT가 Laziness(중간 생략/max_tokens 잘림)로
    #      항목을 누락한다(예: 50건 요청 → 34건 반환). 복잡 스키마에서는 10~20 권장.
    narrative_batch_size: int = 15  # Laziness 방어: 10~20 권장, 50 금지
    narrative_max_retries: int = 2  # 누락 응답 재귀 재시도 횟수
    narrative_risk_levels: list[str] = ["High", "Critical"]  # 사유서 생성 대상 risk_level
    insight_significant_tx_top_n: int = 20  # C08 AND B01 유의적 거래 Top N

    @field_validator("datasynth_label_mode")
    @classmethod
    def _check_datasynth_label_mode(cls, v: str) -> str:
        normalized = v.lower()
        if normalized not in {"hidden", "visible", "auto"}:
            raise ValueError("datasynth_label_mode must be one of: hidden, visible, auto")
        return normalized

    @field_validator("datasynth_metadata_enforcement")
    @classmethod
    def _check_datasynth_metadata_enforcement(cls, v: str) -> str:
        normalized = v.lower()
        if normalized not in {"off", "warn", "strict"}:
            raise ValueError(
                "datasynth_metadata_enforcement must be one of: off, warn, strict",
            )
        return normalized

    @field_validator("openai_api_key")
    @classmethod
    def _warn_empty_openai_api_key(cls, v: str) -> str:
        """키 미설정 시 경고만 — 로컬/CI 환경에서 import가 죽으면 안 되므로 raise 금지."""
        if not v:
            import logging

            logging.getLogger(__name__).warning(
                "openai_api_key 미설정 — LLM 기능 사용 시 get_chat_client()가 RuntimeError 발생"
            )
        return v

    # --- 전처리 판정 기준 (Heuristics) ---
    heuristic_skewness_threshold: float = 2.0  # |skewness| 초과 시 고왜도 판정 (imputer 분기)
    heuristic_log_skewness_threshold: float = 3.0  # |skewness| 초과 시 log 변환 권장 (outlier 분기)
    heuristic_outlier_rate_threshold: float = 0.10  # outlier_rate 초과 시 다수 이상치
    heuristic_high_cardinality_threshold: int = 50  # cardinality 초과 시 고카디널리티
    heuristic_imbalance_threshold: float = 0.05  # 레이블 비율 미만 시 불균형 판정
    heuristic_missing_rate_threshold: float = 0.10  # missing_rate 초과 시 고결측 판정

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="AUDIT_",
        extra="ignore",
    )


# --- YAML 로더 ---


def _load_yaml(filename: str) -> dict:
    """config/ 디렉토리의 YAML 파일을 읽어 dict로 반환."""
    path = CONFIG_DIR / filename
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


@functools.lru_cache
def get_settings() -> AuditSettings:
    """싱글톤 — 앱 전체에서 하나의 설정 인스턴스만 사용."""
    return AuditSettings()


@functools.lru_cache
def get_schema() -> dict:
    """표준 컬럼 스키마 로드."""
    return _load_yaml("schema.yaml")


@functools.lru_cache
def get_keywords() -> dict:
    """ERP별 헤더 키워드 사전 로드."""
    return _load_yaml("keywords.yaml")


@functools.lru_cache
def get_risk_keywords() -> dict:
    """위험 적요 키워드 사전 로드."""
    return _load_yaml("risk_keywords.yaml")


@functools.lru_cache
def get_cleaning_config() -> dict:
    """타입 캐스팅 전처리 규칙 로드. config/cleaning.yaml."""
    return _load_yaml("cleaning.yaml")


@functools.lru_cache
def get_audit_rules() -> dict:
    """감사 업무 룰(패턴/키워드) 로드. config/audit_rules.yaml."""
    return _load_yaml("audit_rules.yaml")


@functools.lru_cache
def get_phase1_case() -> dict:
    """PHASE1 케이스 그룹화/우선순위 설정 로드. config/phase1_case.yaml."""
    return _load_yaml("phase1_case.yaml")
