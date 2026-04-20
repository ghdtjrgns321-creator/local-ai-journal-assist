"""?꾨줈?앺듃 ?꾩뿭 ?ㅼ젙 紐⑤뱢.

?곗꽑?쒖쐞: ?섍꼍蹂??> .env > 肄붾뱶 湲곕낯媛?
YAML ?ㅼ젙(schema, keywords, risk_keywords)? 蹂꾨룄 濡쒕뜑濡??쎈뒗??
"""

from __future__ import annotations

import functools
from pathlib import Path

import yaml
from pydantic import computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# ?꾨줈?앺듃 猷⑦듃 = config/ ??遺紐?
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"


class AuditSettings(BaseSettings):
    """?꾨줈?앺듃 ?꾩뿭 ?ㅼ젙. ?섍꼍蹂??> .env > 肄붾뱶 湲곕낯媛????곗꽑."""

    # --- ?뚯씪 愿??(deprecated: file_validator??file_categories.py ?ъ슜) ---
    # 移댄뀒怨좊━蹂??ш린 ?쒗븳? src/ingest/file_categories.py???뺤쓽
    # ?꾨옒 ?꾨뱶???섏쐞 ?명솚?⑹쑝濡??좎?. ?좉퇋 肄붾뱶?먯꽌 李몄“?섏? 留?寃?
    max_file_size_mb: int = 100
    allowed_extensions: list[str] = [
        ".xlsx", ".xls", ".xlsb",
        ".csv", ".tsv", ".txt", ".dat",
        ".parquet",
    ]

    # --- ?ㅻ뜑 ?먯? 愿??---
    min_expected_headers: int = 4            # ?ㅼ썙???ㅼ퐫???뺢퇋??遺꾨え
    max_header_scan_rows: int = 20           # ?곸쐞 N?됰쭔 ?먯깋
    min_header_confidence: float = 0.3       # ?댄븯硫??먯? ?ㅽ뙣 ??UI 媛쒖엯
    # WU-28: 援ъ“ ?ㅼ퐫??誘몃떖(< min_header_confidence) ??LLM(gpt-5.4-mini)??蹂댁“ ?먮떒 ?붿껌.
    # False硫?湲곗〈 ?숈옉(援ъ“ ?ㅼ퐫?대쭔) ???ㅽ봽?쇱씤/CI 寃곗젙濡좎쟻 ?뚯뒪?몄슜.
    enable_llm_header_fallback: bool = True
    datasynth_label_mode: str = "hidden"
    datasynth_metadata_enforcement: str = "warn"

    @field_validator("min_expected_headers")
    @classmethod
    def _check_min_expected_headers(cls, v: int) -> int:
        """0 ?댄븯硫??ㅼ퐫??怨듭떇??臾댁쓽誘???議곌린 李⑤떒."""
        if v <= 0:
            raise ValueError("min_expected_headers??1 ?댁긽?댁뼱???⑸땲??")
        return v

    # --- 留ㅽ븨 愿??(?좑툘 ?덉떆媛????ㅼ젣 ERP ?ㅻ뜑 留ㅼ묶 ?뺥솗??蹂대ŉ ?쒕떇) ---
    fuzzy_threshold: int = 80            # ?댁긽?대㈃ ?뺤젙 留ㅽ븨
    fuzzy_low_threshold: int = 40        # ?댁긽?대㈃ 異붿쿇(suggestions), 誘몃쭔?대㈃ unmapped

    # --- ???罹먯뒪??愿??---
    casting_null_warn_threshold: float = 0.1   # 罹먯뒪????寃곗륫瑜?寃쎄퀬 ?꾧퀎 (10%)
    casting_null_demote_threshold: float = 0.9  # 90% 珥덇낵 ???ㅻℓ???섏떖
    casting_date_dayfirst: bool = False         # True硫?DD/MM/YYYY ?댁꽍

    # --- 媛먯궗 猷?愿??(?좑툘 ?덉떆媛????ㅼ젣 媛먯궗 湲곗???留욎떠 議곗젙) ---
    balance_tolerance: float = 1.0         # L1-01: 李⑤?蹂 遺덉씪移??덉슜 ?ㅼ감 (??
    # --- L2 寃利?fatal ?뺤콉 ---
    # Why: ?李⑤텋?쇱튂???뚭퀎 蹂듭떇遺湲?洹쇰낯 ?꾨컲 ???쇱젙 鍮꾩쑉 珥덇낵 ???뚯씠?꾨씪??以묐떒.
    #      ?⑥닚??1?됱씠?쇰룄 遺덉씪移섑븯硫?以묐떒?섎뒗 ?뺤콉? ?몄씠利????ㅼ젣 ?곗씠?곗뿉???꾪뿕?섎?濡?
    #      "?꾩껜 李⑤? ?鍮?李⑥씠 鍮꾩쑉" + "遺덉씪移??꾪몴 鍮꾩쨷" ??異뺤쑝濡??먯젙?쒕떎.
    balance_fatal_ratio: float = 0.01      # ?꾩껜 李⑤? ?鍮??덈? 李⑥씠 鍮꾩쑉 ?꾧퀎 (1%)
    balance_fatal_doc_ratio: float = 0.10  # 遺덉씪移??꾪몴 鍮꾩쨷 ?꾧퀎 (10%)
    chart_of_accounts_path: str = "config/chart_of_accounts.csv"  # L1-03: CoA ?뚯씪 寃쎈줈
    # ?ㅻ떒怨??뱀씤?쒕룄 ???쒓뎅 以묎껄 ?쒖“???꾧껐洹쒖젙 諛섏쁺 (DataSynth v1.2.0)
    # Level 1~6: ?먮룞?뱀씤(10M) ???대떦??100M) ?????1B) ??蹂몃???5B) ??CFO(10B) ???댁궗??50B)
    approval_thresholds: list[int] = [
        10_000_000, 100_000_000, 1_000_000_000,
        5_000_000_000, 10_000_000_000, 50_000_000_000,
    ]
    @computed_field
    @property
    def approval_threshold(self) -> int:
        """?덇굅???명솚?? approval_thresholds??理쒓퀬 ?쒕룄 諛섑솚."""
        return max(self.approval_thresholds)

    near_threshold_ratio: float = 0.90  # ?쒕룄??90% ?댁긽?대㈃ ?뚮옒洹?
    round_unit: int = 1_000_000           # L2-02: ?뺤닔 ?⑥쐞 ?먯젙 湲곗? (100留뚯썝)
    zscore_threshold: float = 3.0         # L4-03: ?댁긽移?湲곗? (detection?먯꽌 ?ъ슜)
    midnight_start: int = 22  # L3-06: ?ъ빞 ?꾧린
    midnight_end: int = 6  # L3-06: ?ъ빞 ?꾧린
    period_end_margin_days: int = 5  # L3-04: 湲곕쭚 ?먯젙 留덉쭊 (?붾쭚 ?꾪썑 n??
    fiscal_year_start: int = 1       # ?뚭퀎?곕룄 ?쒖옉??(1=1?? 4=4??3??
    custom_holidays: list[str] = []  # ?뚯궗 吏???댁씪 ["2025-07-01"]

    # --- Detection Layer B 愿??---
    duplicate_payment_window_days: int = 30   # L2-02: 以묐났 吏湲??먯젙 湲곌컙 (??
    sod_process_threshold: int = 3            # L1-06: 吏곷Т遺꾨━ ?꾨컲 ?꾨줈?몄뒪 ???꾧퀎
    topside_threshold: int = 2               # L2-05: Top-side JE 媛???꾧퀎 (5??留뚯젏, ?섍린 ?꾩젣)

    # --- DuplicateDetector (WU-05) ---
    duplicate_fuzzy_threshold: int = 80          # L2-03b: ?곸슂 ?좎궗???꾧퀎 (rapidfuzz 0~100)
    duplicate_amount_tolerance: float = 0.02     # L2-03b/c: 湲덉븸 ?덉슜 ?ㅼ감 (2%)
    duplicate_split_window_days: int = 3         # L2-03c: 遺꾪븷 嫄곕옒 ?덈룄??(??
    duplicate_time_window_days: int = 7          # L2-03d: ?쒖감 以묐났 ?덈룄??(??
    duplicate_max_group_size: int = 1000         # 洹몃９ ?ш린 ?쒗븳 (珥덇낵 ???ㅽ궢)

    # --- Detection Layer C 愿??---
    backdated_threshold_days: int = 30          # L3-07: ?뚭툒 ?꾧퀎 ?쇱닔
    account_pair_rare_percentile: float = 0.01  # L4-04: ?ъ냼 ???섏쐞 諛깅텇??
    period_end_amount_quantile: float = 0.75    # L3-04: 湲곕쭚 ?洹쒕え 湲덉븸 遺꾩쐞??(Q3)
    c01_min_group_size: int = 30                 # L3-04: 怨꾩젙洹몃９蹂?Q3 理쒖냼 ?쒕낯 ??

    # --- Detection Layer C: L4-06 諛곗튂 ?꾪몴 ?댁긽 ---
    batch_source_values: list[str] = ["batch", "BATCH"]  # source 而щ읆 諛곗튂 ?앸퀎 媛?
    batch_period_end_ratio: float = 0.5                   # 湲곕쭚 吏묒쨷 鍮꾩쑉 ?꾧퀎
    batch_simultaneous_threshold: int = 50                # ?숈씪?쇱옄 ?숈떆 ?앹꽦 嫄댁닔 ?꾧퀎
    batch_amount_zscore: float = 3.0                      # 諛곗튂 ??湲덉븸 Z-score ?꾧퀎

    # --- Detection Layer C: L2-06 ??텇媛?---
    reversal_match_window_days: int = 1          # S1: 1:1 留ㅼ묶 ?덉슜 ?쇱닔
    reversal_rolling_window_days: int = 7        # S2: N:M 濡ㅻ쭅 ?덈룄??(??
    reversal_zero_threshold: float = 1000.0      # S2: ?쒖븸 0 ?섎졃 ?덉슜 ?ㅼ감 (KRW)
    reversal_score_threshold: float = 0.3        # 醫낇빀 ?먯닔 ?뚮옒洹??꾧퀎媛?

    # --- RelationalDetector (WU-08) ---
    rel_new_cp_large_quantile: float = 0.90        # R01: ???湲곗? 遺꾩쐞??
    rel_new_cp_lookback_days: int = 90              # R01: ?좉퇋 嫄곕옒泥??먯젙 湲곌컙 (??
    rel_dormant_inactive_days: int = 180            # R02: ?대㈃ 怨꾩젙 ?먯젙 湲곌컙 (??
    rel_dormant_reactivation_window_days: int = 7   # R02: ?곗쥖 ?뚮옒源??덈룄??(??
    rel_dormant_reactivation_min_amount: float = 0.0  # R02: ?ы솢?깊솕 理쒖냼 湲덉븸 (0=?쒗븳?놁쓬)
    rel_tp_ic_deviation_threshold: float = 0.15     # R03: IC 媛寃??몄감 ?덉슜 (15%)
    rel_tp_min_ic_pairs: int = 3                    # R03: 理쒖냼 鍮꾧탳 ????

    # --- GraphDetector (WU-22) ??networkx 湲곕컲 ?쒗솚/?댁쟾媛寃??먯? ---
    # Why: ?뚭퀎 ?λ? 100留? ?됱쓣 graph???щ━硫?OOM. pandas ?ъ쟾 ?꾪꽣 + from_pandas_edgelist 媛뺤젣.
    graph_gr01_max_cycle_length: int = 5            # GR01: simple_cycles length_bound (Johnson ??＜ 諛⑹?)
    graph_gr01_min_amount: float = 10_000_000.0     # GR01: ?ｌ? 理쒖냼 湲덉븸 (materiality 異붿젙移? 1泥쒕쭔??
    graph_gr01_max_edges: int = 50_000              # GR01: ?ｌ? ???곹븳 (珥덇낵 ??min_amount ?먮룞 ?곹뼢)
    graph_gr01_max_component_size: int = 500        # GR01: weakly_connected_component ?몃뱶 ?꾧퀎 (珥덇낵 ??skip)
    graph_gr03_min_path_length: int = 2             # GR03: 寃쎈줈 理쒖냼 ?몃뱶 ??
    graph_gr03_price_deviation_threshold: float = 0.20  # GR03: ?묐갑??媛寃??몄감 ?덉슜 (20%)

    # --- NLPDetector (WU-21) ???곸슂 ?꾨쿋??湲곕컲 ?섎? ?먯? ---
    # Why: ISA 315/240 寃쎌젣???ㅼ쭏 寃利? OpenAI ?꾨쿋??+ kiwipiepy morpheme_tokens.
    #      鍮꾩떇蹂꾪솕 ???먮낯 ?곸슂 ?꾩넚 湲덉?, ?뺥깭??join留?API ?꾨떖.
    nlp_header_account_threshold: float = 0.30      # NLP01: header-account 肄붿궗???좎궗??誘몃쭔 ??遺덉씪移?
    nlp_process_account_threshold: float = 0.30     # NLP02: process-account 肄붿궗???좎궗??誘몃쭔 ??遺덉씪移?
    nlp_anomaly_percentile: float = 0.95            # NLP03: gl_account 洹몃９ centroid 嫄곕━ ?곸쐞 遺꾩쐞??
    nlp_ic_similarity_threshold: float = 0.50       # NLP04: IC ?대윭?ㅽ꽣 ?됯퇏 嫄곕━ 湲곗?
    nlp_synonym_threshold: float = 0.70             # NLP05: risk keyword ?꾨쿋???좎궗???꾧퀎
    nlp_embedding_batch_size: int = 100             # ?꾨쿋??API 諛곗튂 ?ш린
    nlp_min_group_size: int = 5                     # NLP03/NLP04: centroid ?곗텧 理쒖냼 ?쒕낯 (?뚭퇋紐?洹몃９ ?ㅽ궢)

    # --- IntercompanyMatcher (WU-07) ---
    ic_amount_tolerance: float = 0.02       # IC01/IC02: 湲덉븸 ?덉슜 ?ㅼ감 (2%)
    ic_max_diff_ratio: float = 0.10         # IC02: 理쒕? 鍮꾩쑉 (10% ??score 1.0)
    ic_date_window_days: int = 5            # IC03: ?뺤긽 ?쒖감 ?덉슜 (??
    ic_max_day_diff: int = 30               # IC03: 理쒕? ?쒖감 (30????score 1.0)
    ic_min_ic_rows: int = 2                 # 理쒖냼 IC ????(誘몃떖 ???ㅽ궢 + warning)

    # --- Detection Layer C: L4-05 鍮꾩젙???쒓컙? 吏묒쨷 遺꾩꽍 ---
    normal_hours_start: float = 8.5             # ?뺤긽 ?낅Т?쒓컙 ?쒖옉 (08:30)
    normal_hours_end: float = 18.5              # ?뺤긽 ?낅Т?쒓컙 醫낅즺 (18:30)
    settlement_start_mmdd: str = "1220"         # 寃곗궛 吏묒쨷湲곌컙 ?쒖옉 (12??20??
    settlement_end_mmdd: str = "0115"           # 寃곗궛 吏묒쨷湲곌컙 醫낅즺 (1??15??

    @field_validator("settlement_start_mmdd", "settlement_end_mmdd")
    @classmethod
    def _check_mmdd_format(cls, v: str) -> str:
        """MMDD ?뺤떇 寃利????섎せ??媛믪? silent ?ㅽ깘 ?좊컻."""
        if len(v) != 4 or not v.isdigit():
            raise ValueError(f"MMDD ?뺤떇?댁뼱???⑸땲??(?? '1220'): {v!r}")
        m, d = int(v[:2]), int(v[2:])
        if not (1 <= m <= 12 and 1 <= d <= 31):
            raise ValueError(f"?좏슚?섏? ?딆? ???? month={m}, day={d}")
        return v

    abnormal_sigma_threshold: float = 3.0       # ?ъ슜?먮퀎 ?댁긽移??먯젙 ?
    rapid_approval_minutes: int = 5             # 遺??寃???섏떖 ?꾧퀎 (遺?
    min_abnormal_ratio: float = 0.1             # ? ?댁긽移섏뿬???덈? 鍮꾩쑉 10% 誘몃쭔?대㈃ 誘명뵆?섍렇
    min_midnight_entries: int = 3               # ?뚯닔 ?몄썝 ?대갚 ??理쒖냼 ?ъ빞 嫄댁닔
    min_user_entries: int = 10                  # L4-05: ?ъ슜?먮퀎 理쒖냼 ?꾪몴 嫄댁닔 (誘몃떖 ??遺꾩꽍 ?쒖쇅)
    auto_entry_sources: list[str] = [           # ?먮룞 ?꾧린 ?뚯뒪 (湲됱냽 ?뱀씤 寃利??쒖쇅 ???
        "batch", "interface", "system",
        "BATCH", "IF", "SYS",
    ]

    # --- Detection Layer D: ?꾧린 ?鍮?蹂??---
    variance_threshold: float = 0.5           # D01: 怨꾩젙 吏묎퀎 蹂?숇쪧 ?뚮옒洹??꾧퀎 (50%)
    monthly_pattern_threshold: float = 0.3    # D02: JSD ?뚮옒洹??꾧퀎
    min_monthly_data_months: int = 3          # D02: 鍮꾧탳 ?섑뻾 理쒖냼 ?붿닔

    # --- Detection Access Audit (WU-15) ---
    aa01_high_amount_quantile: float = 0.90   # AA01: 怨좎븸 ?먯젙 遺꾩쐞??
    aa04_max_delay_days: int = 3              # AA04: ?뱀씤 吏???꾧퀎 (?곸뾽??

    # --- Detection Evidence (WU-14) ---
    ev_tax_threshold: float = 30_000           # EV01: ?곴꺽利앸튃 ?꾩슂 湲덉븸 (?? ?쒓뎅 ?몃쾿 湲곗?)
    ev_split_max_amount: float = 29_000        # EV01: 遺꾪븷 ?섏떖 嫄대떦 ?곹븳
    ev_split_min_count: int = 3                # EV01: 遺꾪븷 ?섏떖 理쒖냼 嫄댁닔
    ev_revenue_cutoff_days: int = 5            # EV02: 留ㅼ텧 而룹삤???덉슜 ?쇱닔
    ev_expense_cutoff_days: int = 7            # EV02: 鍮꾩슜 而룹삤???덉슜 ?쇱닔
    ev_cutoff_period_end_weight: float = 1.5   # EV02: 湲곕쭚 媛以?怨꾩닔
    ev_cutoff_max_day_diff: int = 30           # EV02: 理쒕? 李⑥씠?쇱닔 (score=1.0 ?곹븳)
    ev_cutoff_use_business_days: bool = True   # EV02: ?곸뾽??怨꾩궛 ?ъ슜 ?щ?
    ev_amount_tolerance: float = 1.0           # EV03: 3-way matching ?덉슜 ?ㅼ감 (??
    ev_vat_rate: float = 0.10                  # EV03: 遺媛?몄쑉 (?쒓뎅 ?쒖? 10%)
    ev_vat_tolerance: float = 1.0              # EV03: 遺媛??寃利??덉슜 ?ㅼ감 (??

    # --- Detection TrendBreak (WU-16) ---
    trendbreak_min_periods: int = 2            # TB01/TB02: 理쒖냼 鍮꾧탳 湲곌컙 ??(3媛쒕뀈 ?붿븸 = 2媛?error)
    trendbreak_bias_ratio: float = 0.8         # TB01: ?숈씪 遺??鍮꾩쑉 ?꾧퀎
    trendbreak_extremity_quantile: float = 0.1  # TB02: 洹밸떒 ?곸뿭 遺꾩쐞??(???섏쐞 10%)
    trendbreak_max_years: int = 5              # ?ㅺ린媛?濡쒕뜑: 理쒕? 議고쉶 ?곕룄 ??
    trendbreak_min_years: int = 3              # ?ㅺ린媛?濡쒕뜑: 理쒖냼 ?좏슚 ?곕룄 ??

    # --- Detection Timeseries (TS01/TS02) ---
    burst_window_days: int = 7                # TS01: 濡ㅻ쭅 ?덈룄??(??
    burst_sigma: float = 3.0                  # TS01: 湲됱쬆 ?먯젙 ? 諛곗닔
    frequency_window_days: int = 7            # TS02: 鍮덈룄 吏묒쨷 ?덈룄??(??
    frequency_min_count: int = 5              # TS02: ?덈룄????理쒖냼 嫄곕옒 嫄댁닔

    # --- L3 ?듦퀎 寃利?(statistical_validator) ---
    monthly_volatility_zscore: float = 2.0      # ?붾퀎 蹂?숇쪧 ?댁긽 ?먯젙 Z-score
    shapiro_alpha: float = 0.05                  # ?뺢퇋??寃???좎쓽?섏?
    benford_mad_threshold: float = 0.012         # MAD ?댁긽 ?먯젙 (Nigrini "acceptable")
    benford_min_sample: int = 100                # Benford 理쒖냼 ?쒕낯
    benford_chi2_alpha: float = 0.05             # Chi-square ?좎쓽?섏?
    hhi_concentrated_threshold: float = 0.25     # HHI 吏묒쨷 ?먯젙
    cv_high_threshold: float = 1.0               # 怨꾩젙 CV 怨좊????먯젙

    # --- ?띿뒪???쇱쿂 愿??---
    min_description_length: int = 3  # L3-08: poor/normal 寃쎄퀎 湲?먯닔
    ttr_threshold: float = 0.3       # L3-08: TTR(?댄쐶?ㅼ뼇?? < 0.3 ??poor
    entropy_threshold: float = 1.0   # L3-08: Shannon entropy < 1.0 ??poor

    # --- 留ㅽ븨 ?꾨줈?뚯씪 愿??---
    profile_dir: str = "data/profiles"    # ?꾨줈?뚯씪 ????붾젆?좊━
    analysis_phase: str = "full"

    # --- ML Pipeline (Phase 2) ---
    phase2_allow_cold_start_bootstrap: bool = True
    vae_latent_dim: int = 32
    vae_epochs: int = 50
    vae_batch_size: int = 256
    if_contamination: float = 0.01          # IsolationForest
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
    ft_d_token: int = 64           # ?쇱쿂 ?좏겙 ?꾨쿋??李⑥썝
    ft_n_layers: int = 2           # Transformer ?몄퐫???덉씠????
    ft_n_heads: int = 4            # Multi-head attention ?ㅻ뱶 ??
    ft_d_ff: int = 128             # Feed-forward ???李⑥썝
    ft_dropout: float = 0.1        # Dropout 鍮꾩쑉
    ft_epochs: int = 50            # ?숈뒿 ?먰룺 ??
    ft_batch_size: int = 256       # 諛곗튂 ?ш린 (~300MB VRAM)
    ft_lr: float = 1e-3            # ?숈뒿瑜?(Adam)

    # --- BiLSTM Sequence (WU-01c) ---
    bilstm_hidden_size: int = 64       # BiLSTM ???李⑥썝 (bidirectional ??異쒕젰 128)
    bilstm_seq_len: int = 16           # ?쒗???덈룄??湲몄씠
    bilstm_stride: int = 1             # ?щ씪?대뵫 ?덈룄??蹂댄룺
    bilstm_epochs: int = 50            # ?숈뒿 ?먰룺 ??
    bilstm_batch_size: int = 256       # 諛곗튂 ?ш린 (~100MB VRAM)
    bilstm_lr: float = 1e-3            # ?숈뒿瑜?(Adam)
    bilstm_dropout: float = 0.3        # Dropout 鍮꾩쑉
    bilstm_num_layers: int = 1         # LSTM ?덉씠????

    # --- Stacking Meta-Learner (WU-03) ---
    # Why: MVP??3-fold + 蹂묐젹?붾줈 ?숈뒿 ?쒓컙 ?섎꼸???곸뇙 (BiLSTM/FT-T 5踰??ы븰??遺??.
    #      Phase 3 ?덉젙????5濡??밴꺽 沅뚯옣 (?듦퀎???쒖?).
    stacking_cv_folds: int = 3              # OOF fold ??(GroupKFold)
    stacking_oof_n_jobs: int = -1           # OOF fold 蹂묐젹 ?숈뒿 (joblib n_jobs)
    stacking_min_positive: int = 50         # fallback ?먯젙: ?묒꽦 理쒖냼 嫄댁닔
    stacking_fallback_threshold: float = 0.01  # fallback ?먯젙: ?묒꽦 鍮꾩쑉 誘몃쭔
    stacking_alpha: float = 1.0             # Ridge 洹쒖젣 媛뺣룄

    # --- Risk Level Classification ---
    # Why: Stacking Ridge 異쒕젰? 吏꾩쭨 ?뺣쪧???꾨땲誘濡?"HIGH=0.9 = 90% ?뺣쪧" ?댁꽍?
    #      ?ㅽ빐. 遺꾩쐞??紐⑤뱶??score 遺꾪룷 湲곗? ?곸쐞 N% 瑜?HIGH濡?遺꾨쪟?쒕떎.
    #      "absolute" = 湲곗〈 ?숈옉 (RISK_THRESHOLDS ?덈?媛?, "quantile" = 遺꾩쐞??
    risk_classification_mode: str = "absolute"
    risk_quantile_high: float = 0.90    # ?곸쐞 10% ??HIGH
    risk_quantile_medium: float = 0.75  # ?곸쐞 25% ??MEDIUM ?댁긽
    risk_quantile_low: float = 0.50     # ?곸쐞 50% ??LOW ?댁긽

    # --- Detection Parallelism (臾띠쓬 2) ---
    # Why: pandas/numpy ?대? ?곗궛? GIL ?댁젣 ??ThreadPoolExecutor濡??낅┰ ?먯?湲?
    #      蹂묐젹?? ProcessPool? DataFrame pickle 鍮꾩슜(1M ??湲곗? ??珥???而ㅼ꽌
    #      ?ㅽ엳???먮┝. None?대㈃ ?쒖감 ?ㅽ뻾(?뚯뒪???붾쾭源낆슜).
    detection_parallel_workers: int | None = 4

    # --- Detection execution scope ---
    # Why: ?꾩옱 ?쒗뭹??湲곕낯 寃쎈줈??Phase 1 猷?湲곕컲 + Phase 2 鍮꾩????ㅻ챸?대떎.
    #      洹몃옒??NLP/愿怨꾪삎/利앸튃/?묎렐媛먯궗/?ㅺ린媛?異붿꽭 ?먯???援ы쁽?섏뼱 ?덉뼱??
    #      湲곕낯 UX?먯꽌 ??긽 ?뚮━???듭떖 寃쎈줈媛 ?꾨땲?? ?뱁엳 NLP???몃? API timeout,
    #      Graph/TrendBreak???곗씠??洹쒕え???곕씪 湲??ㅽ뻾 ?쒓컙???좊컻?????덈떎.
    enable_relational_detection: bool = False
    enable_graph_detection: bool = False
    enable_nlp_detection: bool = False
    enable_access_audit_detection: bool = False
    enable_evidence_detection: bool = False
    enable_trendbreak_detection: bool = False
    enable_variance_detection: bool = False
    enable_ml_detection: bool = False

    # --- SHAP Explainer (WU-17) ---
    # Why: SHAP ?곗궛? 臾닿굅?(10留?嫄????섏떗 遺?. ?댁긽 ?꾪몴留??ㅻ챸?섎㈃ 異⑸텇.
    shap_threshold: float = 0.7    # anomaly_score ?섑븳 ?????댁긽???꾪몴留?SHAP 怨꾩궛
    shap_max_rows: int = 500       # ?덉쟾 ?곹븳 ??flagged rows媛 留롮븘???곸쐞 N嫄대쭔

    # --- DB ---
    duckdb_path: str = "data/audit.duckdb"

    # --- LLM API (Phase 3 OpenAI) ---
    # 2?곗뼱 遺꾨━: light(gpt-5.4-mini)=?쇱긽 ?몄텧, reasoning(gpt-5.4)=?ъ링 異붾줎쨌理쒖쥌 蹂닿퀬??
    openai_api_key: str = ""                                # AUDIT_OPENAI_API_KEY ?섍꼍蹂??二쇱엯
    openai_light_model: str = "gpt-5.4-mini"                # 寃쎈웾 ?몄텧??(?꾩쿂由??쒖븞, Text-to-SQL, NLP ??
    openai_reasoning_model: str = "gpt-5.4"                 # ?ъ링 異붾줎??(理쒖쥌 蹂닿퀬?? XAI ?대윭?곕툕)
    openai_embedding_model: str = "text-embedding-3-small"  # RAG ?꾨쿋??
    openai_temperature: float = 0.1                         # 媛먯궗 遺꾩꽍? ?뺥솗???곗꽑 ????? temperature
    openai_timeout: float = 60.0                            # 珥?

    # --- WU-25: LLM ?몄궗?댄듃 + XAI Narrative ---
    # Why: 湲?JSON 諛곗뿴????踰덉뿉 ?앹꽦?섎㈃ GPT媛 Laziness(以묎컙 ?앸왂/max_tokens ?섎┝)濡?
    #      ??ぉ???꾨씫?쒕떎(?? 50嫄??붿껌 ??34嫄?諛섑솚). 蹂듭옟 ?ㅽ궎留덉뿉?쒕뒗 10~20 沅뚯옣.
    narrative_batch_size: int = 15                          # Laziness 諛⑹뼱: 10~20 沅뚯옣, 50 湲덉?
    narrative_max_retries: int = 2                          # ?꾨씫 ?묐떟 ?ш? ?ъ떆???잛닔
    narrative_risk_levels: list[str] = ["High", "Critical"]  # ?ъ쑀???앹꽦 ???risk_level
    insight_significant_tx_top_n: int = 20                  # L4-03 AND L4-01 ?좎쓽??嫄곕옒 Top N

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
        """??誘몄꽕????寃쎄퀬留???濡쒖뺄/CI ?섍꼍?먯꽌 import媛 二쎌쑝硫????섎?濡?raise 湲덉?."""
        if not v:
            import logging
            logging.getLogger(__name__).warning(
                "openai_api_key 誘몄꽕????LLM 湲곕뒫 ?ъ슜 ??get_chat_client()媛 RuntimeError 諛쒖깮"
            )
        return v

    # --- ?꾩쿂由??먯젙 湲곗? (Heuristics) ---
    heuristic_skewness_threshold: float = 2.0      # |skewness| 珥덇낵 ??怨좎솢???먯젙 (imputer 遺꾧린)
    heuristic_log_skewness_threshold: float = 3.0  # |skewness| 珥덇낵 ??log 蹂??沅뚯옣 (outlier 遺꾧린)
    heuristic_outlier_rate_threshold: float = 0.10  # outlier_rate 珥덇낵 ???ㅼ닔 ?댁긽移?
    heuristic_high_cardinality_threshold: int = 50  # cardinality 珥덇낵 ??怨좎뭅?붾꼸由ы떚
    heuristic_imbalance_threshold: float = 0.05     # ?덉씠釉?鍮꾩쑉 誘몃쭔 ??遺덇퇏???먯젙
    heuristic_missing_rate_threshold: float = 0.10  # missing_rate 珥덇낵 ??怨좉껐痢??먯젙

    @field_validator("analysis_phase")
    @classmethod
    def _check_analysis_phase(cls, v: str) -> str:
        normalized = v.lower()
        if normalized not in {"full", "phase1", "phase2"}:
            raise ValueError("analysis_phase must be one of: full, phase1, phase2")
        return normalized

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="AUDIT_",
        extra="ignore",
    )


# --- YAML 濡쒕뜑 ---


def _load_yaml(filename: str) -> dict:
    """config/ ?붾젆?좊━??YAML ?뚯씪???쎌뼱 dict濡?諛섑솚."""
    path = CONFIG_DIR / filename
    try:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


@functools.lru_cache
def get_settings() -> AuditSettings:
    """?깃????????꾩껜?먯꽌 ?섎굹???ㅼ젙 ?몄뒪?댁뒪留??ъ슜."""
    return AuditSettings()


@functools.lru_cache
def get_schema() -> dict:
    """?쒖? 而щ읆 ?ㅽ궎留?濡쒕뱶."""
    return _load_yaml("schema.yaml")


@functools.lru_cache
def get_keywords() -> dict:
    """ERP蹂??ㅻ뜑 ?ㅼ썙???ъ쟾 濡쒕뱶."""
    return _load_yaml("keywords.yaml")


@functools.lru_cache
def get_risk_keywords() -> dict:
    """?꾪뿕 ?곸슂 ?ㅼ썙???ъ쟾 濡쒕뱶."""
    return _load_yaml("risk_keywords.yaml")


@functools.lru_cache
def get_cleaning_config() -> dict:
    """???罹먯뒪???꾩쿂由?洹쒖튃 濡쒕뱶. config/cleaning.yaml."""
    return _load_yaml("cleaning.yaml")


@functools.lru_cache
def get_audit_rules() -> dict:
    """媛먯궗 ?낅Т 猷??⑦꽩/?ㅼ썙?? 濡쒕뱶. config/audit_rules.yaml."""
    return _load_yaml("audit_rules.yaml")

