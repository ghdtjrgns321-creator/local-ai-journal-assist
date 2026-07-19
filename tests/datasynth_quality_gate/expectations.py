"""datasynth.yaml에서 기대값 추출.

품질 게이트 체크에서 사용할 기대값(expected)을 config에서 파싱하여
flat dict로 제공. 각 체크 모듈은 이 dict를 참조하여 PASS/FAIL 판정.
"""
from __future__ import annotations

import calendar
import datetime
from pathlib import Path

import yaml


def load_expectations(config_path: Path | None = None) -> dict:
    """datasynth.yaml을 파싱하여 flat dict로 반환."""
    if config_path is None:
        config_path = Path(__file__).resolve().parents[2] / "config" / "datasynth.yaml"
    with open(config_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    exp: dict = {}

    # 글로벌 — 기간, 시드
    gl = cfg.get("global", {})
    exp["start_date"] = gl.get("start_date", "2022-01-01")
    exp["period_months"] = gl.get("period_months", 12)
    exp["seed"] = gl.get("seed", 2024)

    # 법인
    exp["companies"] = [c["code"] for c in cfg.get("companies", [])]
    exp["volume_weights"] = {
        c["code"]: c.get("volume_weight", 1.0) for c in cfg.get("companies", [])
    }

    # 금액 분포 파라미터
    amt = cfg.get("transactions", {}).get("amounts", {})
    exp["min_amount"] = amt.get("min_amount", 100)
    exp["max_amount"] = amt.get("max_amount", 100_000_000_000)
    exp["lognormal_mu"] = amt.get("lognormal_mu", 14.0)
    exp["lognormal_sigma"] = amt.get("lognormal_sigma", 2.5)
    exp["decimal_places"] = amt.get("decimal_places", 0)
    exp["round_number_probability"] = amt.get("round_number_probability", 0.25)
    exp["nice_number_probability"] = amt.get("nice_number_probability", 0.15)
    exp["round_number_unit"] = amt.get("round_number_unit", 1_000_000)
    exp["nice_number_unit"] = amt.get("nice_number_unit", 100_000)

    # 시계열/계절성
    seas = cfg.get("transactions", {}).get("seasonality", {})
    exp["weekend_activity"] = seas.get("weekend_activity", 1.0)
    exp["holiday_activity"] = seas.get("holiday_activity", 0.05)
    exp["month_end_multiplier"] = seas.get("month_end_multiplier", 2.5)
    exp["quarter_end_multiplier"] = seas.get("quarter_end_multiplier", 4.0)
    exp["year_end_multiplier"] = seas.get("year_end_multiplier", 6.0)
    exp["dow_multipliers"] = {
        0: seas.get("monday_multiplier", 1.3),
        1: seas.get("tuesday_multiplier", 1.1),
        2: seas.get("wednesday_multiplier", 1.0),
        3: seas.get("thursday_multiplier", 1.0),
        4: seas.get("friday_multiplier", 0.85),
    }

    # 시간대 segment (업무시간/점심/야간 등)
    tp = cfg.get("temporal_patterns", {}).get("intraday", {})
    exp["intraday_segments"] = tp.get("segments", [])

    # 사용자 페르소나별 인원수
    up = cfg.get("user_personas", {}).get("users_per_persona", {})
    exp["users_per_persona"] = up

    # anomaly 주입률
    ai = cfg.get("anomaly_injection", {}).get("rates", {})
    exp["total_anomaly_rate"] = ai.get("total_rate", 0.05)
    exp["fraud_rate"] = ai.get("fraud_rate", 0.02)
    exp["error_rate"] = ai.get("error_rate", 0.02)
    exp["process_rate"] = ai.get("process_rate", 0.01)

    # 내부거래(IC)
    ic = cfg.get("intercompany", {})
    exp["ic_transaction_rate"] = ic.get("ic_transaction_rate", 0.10)

    # 직무분리(SoD)
    ctrl = cfg.get("internal_controls", {})
    exp["sod_violation_rate"] = ctrl.get("sod_violation_rate", 0.01)
    exp["anomalous_assignment_rate"] = ctrl.get("anomalous_assignment_rate", 0.07)

    # 부정 유형 분포
    ftd = cfg.get("fraud", {}).get("fraud_type_distribution", {})
    exp["fraud_type_distribution"] = ftd

    # 데이터 품질 (결측)
    dq = cfg.get("data_quality", {}).get("missing_values", {})
    exp["missing_rate"] = dq.get("rate", 0.02)
    exp["protected_fields"] = dq.get(
        "protected_fields", ["document_id", "company_code", "posting_date"]
    )

    # 마스터 데이터 건수
    md = cfg.get("master_data", {})
    exp["vendor_count"] = md.get("vendors", {}).get("count", 500)
    exp["customer_count"] = md.get("customers", {}).get("count", 300)
    exp["employee_count"] = md.get("employees", {}).get("count", 300)

    # anomaly 전략 파라미터
    strat = cfg.get("anomaly_strategies", {})
    exp["approval_thresholds"] = strat.get("approval", {}).get("thresholds", [])
    exp["dormant_accounts"] = strat.get("dormant_account", {}).get("accounts", [])
    exp["invalid_accounts"] = strat.get("invalid_account", {}).get("codes", [])

    # 기간 파생 필드 — T1-07, T4-14, T4-15에서 동적 기간 계산에 사용
    start_dt = datetime.date.fromisoformat(exp["start_date"])
    pm = exp["period_months"]
    end_year = start_dt.year + (start_dt.month - 1 + pm) // 12
    end_month = (start_dt.month - 1 + pm) % 12 + 1
    end_dt = datetime.date(end_year, end_month, 1) - datetime.timedelta(days=1)
    exp["end_date"] = end_dt.isoformat()
    exp["start_year"] = start_dt.year
    exp["end_year"] = end_dt.year
    exp["valid_fiscal_years"] = list(range(start_dt.year, end_dt.year + 1))
    exp["num_years"] = end_dt.year - start_dt.year + 1

    # Stage 2 completeness 기준
    exp["completeness"] = {
        "has_attachment": 0.80,
        "ip_address": 0.95,
    }

    # IP 대역 매핑 (법인별)
    exp["ip_subnets"] = {
        "C001": "10.1",
        "C002": "10.2",
        "C003": "10.3",
    }

    return exp
