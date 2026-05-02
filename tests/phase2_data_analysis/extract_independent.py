"""Phase 2 독자적 데이터 분석 프로파일 추출.

quality_gate3의 로직을 따라가지 않고, **Phase 2 ML/시퀀스/드리프트 관점에
특화된 8개 축**으로 전수 데이터를 프로파일링한다.

분석 축:
1. Temporal Granularity — posting_date 시:분:초 실제 분포 (BiLSTM 시퀀스 전제)
2. User-Sequence Structure — 사용자별 시퀀스 특성 (BiLSTM seq_len 적합성)
3. Label Quality for Stacking — GroupKFold 전제 조건 충족도
4. Amount Distribution Geometry — Benford/ML 피처 친화성
5. Drift Baseline Fit — 월별·회사별 분포 안정성 (PSI 베이스)
6. SOD × Persona Matrix — 내부통제 탐지 신호
7. Data Quality Fingerprint — null/중복/스키마 일관성
8. Fraud Signature Profile — 탐지 룰 vs 라벨 정합성

실행: uv run python -m tests.phase2_data_analysis.extract_independent
출력: tests/phase2_data_analysis/results/independent_profile.json
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import duckdb

_DATA_DIR = (
    Path(__file__).resolve().parents[2]
    / "data" / "journal" / "primary" / "datasynth"
)
_CSV = _DATA_DIR / "journal_entries.csv"
_OUT = Path(__file__).parent / "results" / "independent_profile.json"


def _q(con, sql):
    return con.execute(sql).fetchall()


def _q1(con, sql):
    row = con.execute(sql).fetchone()
    return row[0] if row else None


def _qd(con, sql) -> dict:
    return {r[0]: r[1] for r in _q(con, sql)}


# ── Axis 1: Temporal Granularity ─────────────────────────────


def axis_temporal_granularity(con) -> dict:
    """BiLSTM 시퀀스 전제조건 — posting_date 시:분:초 실제 분포."""
    out = {}

    # 전체 posting_date 중 00:00:00인 행 비율 (시간 정보 부재)
    out["midnight_rate"] = round(_q1(con, """
        SELECT COUNT(*) FILTER (
            WHERE EXTRACT(HOUR FROM CAST(posting_date AS TIMESTAMP)) = 0
              AND EXTRACT(MINUTE FROM CAST(posting_date AS TIMESTAMP)) = 0
              AND EXTRACT(SECOND FROM CAST(posting_date AS TIMESTAMP)) = 0
        ) * 1.0 / COUNT(*)
        FROM je
    """), 6)

    # 시간(0~23) 히스토그램
    out["hour_histogram"] = {int(r[0]): r[1] for r in _q(con, """
        SELECT EXTRACT(HOUR FROM CAST(posting_date AS TIMESTAMP)) h, COUNT(*)
        FROM je GROUP BY h ORDER BY h
    """)}

    # 분 단위 해상도 — 모든 초가 0인지, 분이 특정 값에 편중인지
    out["second_is_zero_rate"] = round(_q1(con, """
        SELECT COUNT(*) FILTER (
            WHERE EXTRACT(SECOND FROM CAST(posting_date AS TIMESTAMP)) = 0
        ) * 1.0 / COUNT(*) FROM je
    """), 6)

    # 같은 사용자 × 같은 분 내 다중 입력 (ISA 240 "30분 내 3건" 포착 가능성)
    out["same_minute_multi_entries"] = _q1(con, """
        SELECT COUNT(*) FROM (
            SELECT created_by, DATE_TRUNC('minute', CAST(posting_date AS TIMESTAMP)) m, COUNT(*) cnt
            FROM je WHERE created_by IS NOT NULL
            GROUP BY 1, 2 HAVING cnt >= 2
        )
    """)

    # 심야(22:00~05:59) 전표 건수와 사용자 집중도
    out["after_hours_docs"] = _q1(con, """
        SELECT COUNT(DISTINCT document_id) FROM je
        WHERE EXTRACT(HOUR FROM CAST(posting_date AS TIMESTAMP)) IN (22,23,0,1,2,3,4,5)
    """)
    out["top_after_hours_users"] = _qd(con, """
        SELECT created_by, COUNT(DISTINCT document_id) cnt FROM je
        WHERE EXTRACT(HOUR FROM CAST(posting_date AS TIMESTAMP)) IN (22,23,0,1,2,3,4,5)
          AND created_by IS NOT NULL
        GROUP BY 1 ORDER BY cnt DESC LIMIT 10
    """)
    return out


# ── Axis 2: User-Sequence Structure ──────────────────────────


def axis_user_sequence(con) -> dict:
    """BiLSTM seq_len=16 적합성 — 사용자당 전표 수 분포."""
    out = {}

    # 사용자별 전표(document_id) 수 분포
    out["docs_per_user_percentiles"] = dict(_q(con, """
        SELECT unnest(['min','P10','P25','P50','P75','P90','P99','max']) AS pct,
               unnest([
                   MIN(cnt), PERCENTILE_CONT(0.10) WITHIN GROUP (ORDER BY cnt),
                   PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY cnt),
                   PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY cnt),
                   PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY cnt),
                   PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY cnt),
                   PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY cnt),
                   MAX(cnt)
               ]) AS val
        FROM (SELECT created_by, COUNT(DISTINCT document_id) cnt FROM je
              WHERE created_by IS NOT NULL GROUP BY created_by)
    """))

    # seq_len=16 충족 사용자 비율 (windowing 가능 사용자)
    out["users_with_seq_len_16_pct"] = round(_q1(con, """
        SELECT COUNT(*) FILTER (WHERE cnt >= 16) * 1.0 / COUNT(*)
        FROM (SELECT created_by, COUNT(DISTINCT document_id) cnt FROM je
              WHERE created_by IS NOT NULL GROUP BY created_by)
    """), 4)

    out["total_unique_users"] = _q1(con, """
        SELECT COUNT(DISTINCT created_by) FROM je WHERE created_by IS NOT NULL
    """)

    # 1회 전표만 있는 사용자 (시퀀스 무의미)
    out["singleton_users"] = _q1(con, """
        SELECT COUNT(*) FROM (
            SELECT created_by FROM je WHERE created_by IS NOT NULL
            GROUP BY created_by HAVING COUNT(DISTINCT document_id) = 1
        )
    """)

    # user_persona별 평균 전표 (시퀀스 구성 시 persona 편중)
    out["avg_docs_per_persona"] = {r[0]: round(r[1], 2) for r in _q(con, """
        SELECT user_persona, AVG(cnt) FROM (
            SELECT user_persona, created_by, COUNT(DISTINCT document_id) cnt
            FROM je WHERE created_by IS NOT NULL AND user_persona IS NOT NULL
            GROUP BY user_persona, created_by
        ) GROUP BY user_persona ORDER BY 2 DESC
    """)}
    return out


# ── Axis 3: Label Quality for Stacking ───────────────────────


def axis_label_quality(con) -> dict:
    """GroupKFold OOF 전제 — 사용자 단위 양성 분포 균일성."""
    out = {}

    # 전체 라벨 비율 (is_fraud OR is_anomaly)
    out["fraud_or_anomaly_doc_count"] = _q1(con, """
        SELECT COUNT(DISTINCT document_id) FROM je
        WHERE is_fraud='true' OR is_anomaly='true'
    """)
    out["fraud_or_anomaly_rate"] = round(_q1(con, """
        SELECT COUNT(DISTINCT CASE WHEN is_fraud='true' OR is_anomaly='true'
                                    THEN document_id END) * 1.0
             / COUNT(DISTINCT document_id) FROM je
    """), 6)

    # 사용자별 양성 비율 히스토그램 (GroupKFold 안정성)
    out["user_positive_rate_bins"] = {r[0]: r[1] for r in _q(con, """
        SELECT CASE
            WHEN pos_rate = 0.0 THEN '0_clean'
            WHEN pos_rate <= 0.05 THEN '1_low_<=5%'
            WHEN pos_rate <= 0.25 THEN '2_med_<=25%'
            WHEN pos_rate <= 0.50 THEN '3_high_<=50%'
            ELSE '4_very_high_>50%'
        END bucket, COUNT(*) FROM (
            SELECT created_by,
                   COUNT(DISTINCT CASE WHEN is_fraud='true' OR is_anomaly='true'
                                        THEN document_id END) * 1.0
                 / COUNT(DISTINCT document_id) pos_rate
            FROM je WHERE created_by IS NOT NULL GROUP BY created_by
        ) GROUP BY bucket ORDER BY bucket
    """)}

    # GroupKFold 3-fold 시 각 fold의 예상 양성 수 (user 단위 분할 시뮬)
    out["fraud_contamination_per_user"] = _q1(con, """
        SELECT COUNT(DISTINCT created_by) FROM je
        WHERE is_fraud='true' AND created_by IS NOT NULL
    """)
    out["fraud_user_overlap_rate"] = round(_q1(con, """
        SELECT COUNT(DISTINCT created_by) FILTER (WHERE has_fraud)
             * 1.0 / COUNT(DISTINCT created_by)
        FROM (
            SELECT created_by,
                   BOOL_OR(is_fraud='true') has_fraud
            FROM je WHERE created_by IS NOT NULL GROUP BY created_by
        )
    """), 6)

    return out


# ── Axis 4: Amount Distribution Geometry ─────────────────────


def axis_amount_geometry(con) -> dict:
    """ML 피처 친화성 — Benford 선행 + 로그 분포 검증."""
    out = {}

    # 첫 자리 분포 (Benford)
    out["first_digit_raw"] = {int(r[0]): r[1] for r in _q(con, """
        SELECT CAST(SUBSTR(CAST(CAST(amt AS BIGINT) AS VARCHAR), 1, 1) AS INT) d, COUNT(*)
        FROM (
            SELECT CASE WHEN CAST(debit_amount AS DOUBLE) > 0
                        THEN CAST(debit_amount AS DOUBLE)
                        ELSE CAST(credit_amount AS DOUBLE) END amt
            FROM je WHERE CAST(debit_amount AS DOUBLE) > 0
                      OR CAST(credit_amount AS DOUBLE) > 0
        ) WHERE amt >= 1 GROUP BY d ORDER BY d
    """)}

    # 정상 Benford 기대 비율과 비교용으로 상대 편차 계산
    first_digit = out["first_digit_raw"]
    total = sum(first_digit.values()) or 1
    benford_expected = {d: round((((d + 1) / d) ** 0.434).__pow__(0) or 0, 6) for d in range(1, 10)}
    # log10(1 + 1/d) 정확식
    import math
    benford_expected = {d: round(math.log10(1 + 1 / d), 6) for d in range(1, 10)}
    mad = sum(
        abs(first_digit.get(d, 0) / total - benford_expected[d])
        for d in range(1, 10)
    ) / 9
    out["benford_mad"] = round(mad, 6)
    out["benford_expected"] = benford_expected

    # 금액 log10 bin 분포
    out["log10_amount_bins"] = {int(r[0]): r[1] for r in _q(con, """
        SELECT CAST(FLOOR(LOG10(amt)) AS INT) bin, COUNT(*)
        FROM (
            SELECT CASE WHEN CAST(debit_amount AS DOUBLE) > 0
                        THEN CAST(debit_amount AS DOUBLE)
                        ELSE CAST(credit_amount AS DOUBLE) END amt
            FROM je WHERE CAST(debit_amount AS DOUBLE) > 0
                      OR CAST(credit_amount AS DOUBLE) > 0
        ) WHERE amt >= 1 GROUP BY bin ORDER BY bin
    """)}

    # Round number bias (0으로 끝나는 금액 비율)
    out["round_number_rate"] = round(_q1(con, """
        SELECT COUNT(*) FILTER (WHERE amt % 10000 = 0) * 1.0 / COUNT(*)
        FROM (
            SELECT CAST(CASE WHEN CAST(debit_amount AS DOUBLE) > 0
                              THEN CAST(debit_amount AS DOUBLE)
                              ELSE CAST(credit_amount AS DOUBLE) END AS BIGINT) amt
            FROM je WHERE CAST(debit_amount AS DOUBLE) > 0
                      OR CAST(credit_amount AS DOUBLE) > 0
        )
    """), 6)

    # 양성 vs 음성 금액 중앙값 비교 (ML 분리가능성)
    out["amount_median_by_label"] = dict(_q(con, """
        SELECT CASE WHEN is_fraud='true' OR is_anomaly='true' THEN 'positive' ELSE 'negative' END k,
               MEDIAN(CASE WHEN CAST(debit_amount AS DOUBLE) > 0
                           THEN CAST(debit_amount AS DOUBLE)
                           ELSE CAST(credit_amount AS DOUBLE) END) v
        FROM je WHERE CAST(debit_amount AS DOUBLE) > 0
                  OR CAST(credit_amount AS DOUBLE) > 0
        GROUP BY k
    """))
    return out


# ── Axis 5: Drift Baseline Fit ───────────────────────────────


def axis_drift_baseline(con) -> dict:
    """PSI 기준 학습 안정성 — 월별·회사별 분포 변동 측정."""
    out = {}

    # 월별 평균 금액 (수치형 드리프트 시뮬)
    out["monthly_mean_amount"] = {int(r[0]): round(r[1], 2) for r in _q(con, """
        SELECT EXTRACT(MONTH FROM CAST(posting_date AS TIMESTAMP)) m, AVG(amt)
        FROM (
            SELECT posting_date,
                   CASE WHEN CAST(debit_amount AS DOUBLE) > 0
                        THEN CAST(debit_amount AS DOUBLE)
                        ELSE CAST(credit_amount AS DOUBLE) END amt
            FROM je WHERE CAST(debit_amount AS DOUBLE) > 0
                      OR CAST(credit_amount AS DOUBLE) > 0
        ) GROUP BY m ORDER BY m
    """)}

    # 월별 평균 표준편차 (월간 CoV 지수)
    out["monthly_std_amount"] = {int(r[0]): round(r[1], 2) for r in _q(con, """
        SELECT EXTRACT(MONTH FROM CAST(posting_date AS TIMESTAMP)) m, STDDEV(amt)
        FROM (
            SELECT posting_date,
                   CASE WHEN CAST(debit_amount AS DOUBLE) > 0
                        THEN CAST(debit_amount AS DOUBLE)
                        ELSE CAST(credit_amount AS DOUBLE) END amt
            FROM je WHERE CAST(debit_amount AS DOUBLE) > 0
                      OR CAST(credit_amount AS DOUBLE) > 0
        ) GROUP BY m ORDER BY m
    """)}

    # 회사별 document_type 분포 (범주형 드리프트 시뮬)
    out["company_doctype_share"] = {}
    for r in _q(con, """
        SELECT company_code, document_type, COUNT(*) FROM je
        GROUP BY 1,2 ORDER BY 1,3 DESC
    """):
        out["company_doctype_share"].setdefault(r[0], {})[r[1]] = r[2]

    # 연도별 fraud_rate 추세 (fold 기반 학습 안정성)
    out["yearly_fraud_rate"] = {int(r[0]): round(r[1], 6) for r in _q(con, """
        SELECT CAST(fiscal_year AS INT) y,
               COUNT(DISTINCT CASE WHEN is_fraud='true' THEN document_id END) * 1.0
             / COUNT(DISTINCT document_id)
        FROM je GROUP BY y ORDER BY y
    """)}

    return out


# ── Axis 6: SOD × Persona Matrix ─────────────────────────────


def axis_sod_persona(con) -> dict:
    """내부통제 탐지 신호 — user_persona 별 SOD 위반 편중."""
    out = {}

    out["sod_violation_count"] = _q1(con, """
        SELECT COUNT(DISTINCT document_id) FROM je WHERE sod_violation='true'
    """)

    # persona × SOD type 교차
    out["persona_sod_cross"] = {}
    for r in _q(con, """
        SELECT user_persona, sod_conflict_type, COUNT(DISTINCT document_id)
        FROM je WHERE sod_violation='true' AND sod_conflict_type IS NOT NULL
          AND CAST(sod_conflict_type AS VARCHAR) NOT IN ('','nan')
        GROUP BY 1,2 ORDER BY 1,3 DESC
    """):
        out["persona_sod_cross"].setdefault(r[0], {})[r[1]] = r[2]

    # self-approval × SOD (자기 승인 + SOD 중복)
    out["self_approval_with_sod"] = _q1(con, """
        SELECT COUNT(DISTINCT document_id) FROM je
        WHERE sod_violation='true' AND created_by = approved_by
    """)

    # approved_by 집중도 — 승인자 Top 3이 전체 승인의 몇 % 처리
    out["top3_approver_share"] = round(_q1(con, """
        WITH app AS (
            SELECT approved_by, COUNT(DISTINCT document_id) cnt
            FROM je WHERE approved_by IS NOT NULL
              AND CAST(approved_by AS VARCHAR) NOT IN ('','nan')
            GROUP BY 1 ORDER BY cnt DESC
        ),
        top3 AS (SELECT SUM(cnt) t FROM (SELECT cnt FROM app LIMIT 3)),
        total AS (SELECT SUM(cnt) t FROM app)
        SELECT (SELECT t FROM top3) * 1.0 / (SELECT t FROM total)
    """), 4)
    return out


# ── Axis 7: Data Quality Fingerprint ─────────────────────────


def axis_data_quality(con) -> dict:
    """데이터 품질 지표 — null 분포, 중복 document_id, line_number 연속성."""
    out = {}

    total = _q1(con, "SELECT COUNT(*) FROM je")
    out["total_rows"] = total

    # 핵심 컬럼 null_rate Top 5
    key_cols = ["document_id", "posting_date", "gl_account", "debit_amount",
                "credit_amount", "created_by", "approved_by", "fiscal_year",
                "business_process", "user_persona", "source", "document_type"]
    nulls: dict[str, float] = {}
    for col in key_cols:
        filled = _q1(con, f"""
            SELECT COUNT(*) FROM je WHERE {col} IS NOT NULL
              AND CAST({col} AS VARCHAR) NOT IN ('','nan')
        """)
        nulls[col] = round(1 - filled / total, 6) if total else 0.0
    out["null_rate_by_col"] = nulls

    # 중복 document_id (exact row duplicates)
    out["full_duplicate_rows"] = _q1(con, """
        SELECT COUNT(*) FROM (
            SELECT document_id, line_number, gl_account,
                   debit_amount, credit_amount, COUNT(*) c
            FROM je GROUP BY 1,2,3,4,5 HAVING c > 1
        )
    """)

    # line_number 연속성 (전표 내 1~N 연속)
    out["docs_with_gap_in_line_number"] = _q1(con, """
        SELECT COUNT(*) FROM (
            SELECT document_id,
                   MAX(CAST(line_number AS INT)) mx,
                   COUNT(DISTINCT line_number) cnt
            FROM je GROUP BY document_id HAVING mx != cnt
        )
    """)

    # gl_account 자릿수 일관성
    out["gl_account_digit_variance"] = _qd(con, """
        SELECT LENGTH(CAST(gl_account AS VARCHAR)) digits, COUNT(*)
        FROM je WHERE gl_account IS NOT NULL
          AND CAST(gl_account AS VARCHAR) NOT IN ('','nan')
        GROUP BY 1 ORDER BY 1
    """)

    return out


# ── Axis 8: Fraud Signature Profile ──────────────────────────


def axis_fraud_signature(con) -> dict:
    """탐지 룰이 잡을 수 있는 fraud 시그니처 — 사전 실사."""
    out = {}

    # fraud_type별 시간대 분포 (L3-06 심야, L3-05 주말 대응성)
    out["fraud_by_hour"] = {}
    for r in _q(con, """
        SELECT fraud_type,
               EXTRACT(HOUR FROM CAST(posting_date AS TIMESTAMP)) h,
               COUNT(DISTINCT document_id)
        FROM je WHERE is_fraud='true' AND fraud_type IS NOT NULL
          AND CAST(fraud_type AS VARCHAR) NOT IN ('','nan')
        GROUP BY 1,2 ORDER BY 1,3 DESC
    """):
        out["fraud_by_hour"].setdefault(r[0], {})[int(r[1])] = r[2]

    # fraud_type별 평균 금액 (L4-03 이상 고액 대응성)
    out["fraud_median_amount"] = dict(_q(con, """
        SELECT fraud_type, MEDIAN(amt) FROM (
            SELECT fraud_type, CASE WHEN CAST(debit_amount AS DOUBLE) > 0
                                    THEN CAST(debit_amount AS DOUBLE)
                                    ELSE CAST(credit_amount AS DOUBLE) END amt
            FROM je WHERE is_fraud='true' AND fraud_type IS NOT NULL
              AND CAST(fraud_type AS VARCHAR) NOT IN ('','nan')
        ) GROUP BY 1 ORDER BY 2 DESC
    """))

    # fraud_type별 월별 집중도 (L3-04 기말/기초 결산 검토 후보군 대응성)
    out["fraud_month_concentration"] = {}
    for r in _q(con, """
        SELECT fraud_type, EXTRACT(MONTH FROM CAST(posting_date AS TIMESTAMP)) m,
               COUNT(DISTINCT document_id)
        FROM je WHERE is_fraud='true' AND fraud_type IS NOT NULL
          AND CAST(fraud_type AS VARCHAR) NOT IN ('','nan')
        GROUP BY 1,2 ORDER BY 1,3 DESC
    """):
        out["fraud_month_concentration"].setdefault(r[0], {})[int(r[1])] = r[2]

    # 라벨과 탐지 피처의 직접 상관 (승인 생략 × fraud)
    out["skipped_approval_fraud_rate"] = round(_q1(con, """
        SELECT COUNT(DISTINCT CASE WHEN is_fraud='true' THEN document_id END) * 1.0
             / NULLIF(COUNT(DISTINCT document_id), 0)
        FROM je WHERE approved_by IS NULL
          OR CAST(approved_by AS VARCHAR) IN ('','nan')
    """) or 0.0, 6)

    # 자기 승인 × fraud 정합성
    out["self_approval_fraud_rate"] = round(_q1(con, """
        SELECT COUNT(DISTINCT CASE WHEN is_fraud='true' THEN document_id END) * 1.0
             / NULLIF(COUNT(DISTINCT document_id), 0)
        FROM je WHERE created_by = approved_by AND created_by IS NOT NULL
    """) or 0.0, 6)

    return out


# ── Axis 9: GL Account Classification Integrity ─────────────


def axis_gl_integrity(con) -> dict:
    """K-IFRS GL 계정 분류 × 차/대변 방향 정합성.

    정상 원리:
    - 자산(1xxx): 차변 증가 / 대변 감소  → debit_ratio ≥ 0.85 기대
    - 부채(2xxx): 차변 감소 / 대변 증가  → credit_ratio ≥ 0.85 기대
    - 자본(3xxx): 대변이 기본            → credit_ratio ≥ 0.80 기대
    - 수익(4xxx): 대변 (환입만 차변)      → credit_ratio ≥ 0.95 기대
    - 비용(5~6xxx): 차변 (환입만 대변)    → debit_ratio ≥ 0.95 기대
    """
    out = {}

    # 클래스별 debit/credit 라인 카운트 + 금액
    out["by_account_class"] = {}
    for r in _q(con, """
        SELECT
            CASE
                WHEN CAST(gl_account AS VARCHAR)[1]='1' THEN '1_자산'
                WHEN CAST(gl_account AS VARCHAR)[1]='2' THEN '2_부채'
                WHEN CAST(gl_account AS VARCHAR)[1]='3' THEN '3_자본'
                WHEN CAST(gl_account AS VARCHAR)[1]='4' THEN '4_매출수익'
                WHEN CAST(gl_account AS VARCHAR)[1] IN ('5','6') THEN '5_비용_원가판관'
                WHEN CAST(gl_account AS VARCHAR)[1]='7' THEN '7_영업외수익'
                WHEN CAST(gl_account AS VARCHAR)[1]='8' THEN '8_영업외비용'
                ELSE '9_기타_임시'
            END AS cls,
            SUM(CASE WHEN CAST(debit_amount AS DOUBLE) > 0 THEN 1 ELSE 0 END) debit_lines,
            SUM(CASE WHEN CAST(credit_amount AS DOUBLE) > 0 THEN 1 ELSE 0 END) credit_lines,
            ROUND(SUM(CAST(debit_amount AS DOUBLE)), 0) debit_amt,
            ROUND(SUM(CAST(credit_amount AS DOUBLE)), 0) credit_amt
        FROM je
        WHERE gl_account IS NOT NULL
          AND CAST(gl_account AS VARCHAR) NOT IN ('','nan')
        GROUP BY cls
        ORDER BY cls
    """):
        total_lines = (r[1] or 0) + (r[2] or 0)
        out["by_account_class"][r[0]] = {
            "debit_lines": r[1],
            "credit_lines": r[2],
            "debit_amount": r[3],
            "credit_amount": r[4],
            "debit_ratio": round((r[1] or 0) / total_lines, 4) if total_lines else 0,
        }

    # 이상 방향 집계 (K-IFRS 9분류)
    expected_debit = {
        "1_자산": 0.85,
        "5_비용_원가판관": 0.95,
        "8_영업외비용": 0.90,
    }
    expected_credit = {
        "2_부채": 0.85,
        "3_자본": 0.80,
        "4_매출수익": 0.95,
        "7_영업외수익": 0.90,
    }
    violations = {}
    for cls, stats in out["by_account_class"].items():
        dr = stats["debit_ratio"]
        cr = 1 - dr
        if cls in expected_debit and dr < expected_debit[cls]:
            violations[cls] = {
                "expected_debit_ratio": expected_debit[cls],
                "actual_debit_ratio": dr,
                "gap": round(expected_debit[cls] - dr, 4),
            }
        if cls in expected_credit and cr < expected_credit[cls]:
            violations[cls] = {
                "expected_credit_ratio": expected_credit[cls],
                "actual_credit_ratio": round(cr, 4),
                "gap": round(expected_credit[cls] - cr, 4),
            }
    out["direction_violations"] = violations

    return out


# ── Axis 10: Journal Entry Logic (분개 조합 논리) ────────────


def axis_journal_logic(con) -> dict:
    """전표 단위 차/대변 계정 조합의 논리적 정합성.

    정상 double-entry 패턴:
    - D:자산 / C:부채        (매입)
    - D:자산 / C:수익        (매출)
    - D:비용 / C:자산        (현금 지급)
    - D:비용 / C:부채        (미지급)
    - D:부채 / C:자산        (부채 상환)

    이상 조합:
    - D:수익 (환입 외 드물어야)
    - C:비용 (환입 외 드물어야)
    - D:자산 + D:자산만 (같은 클래스 내 이동)
    - 수익-부채, 자본-비용 직접 대응 등 비상식
    """
    out = {}

    # 전표별 차변/대변 계정 클래스 조합
    out["top_combinations"] = {}
    for r in _q(con, """
        WITH doc_cls AS (
            SELECT
                document_id,
                LIST(DISTINCT
                    'D_' || CASE
                        WHEN CAST(gl_account AS VARCHAR)[1]='1' THEN '자산'
                        WHEN CAST(gl_account AS VARCHAR)[1]='2' THEN '부채'
                        WHEN CAST(gl_account AS VARCHAR)[1]='3' THEN '자본'
                        WHEN CAST(gl_account AS VARCHAR)[1]='4' THEN '매출수익'
                        WHEN CAST(gl_account AS VARCHAR)[1] IN ('5','6') THEN '원가판관'
                        WHEN CAST(gl_account AS VARCHAR)[1]='7' THEN '영업외수익'
                        WHEN CAST(gl_account AS VARCHAR)[1]='8' THEN '영업외비용'
                        ELSE '기타_임시' END
                ) FILTER (WHERE CAST(debit_amount AS DOUBLE) > 0) debits,
                LIST(DISTINCT
                    'C_' || CASE
                        WHEN CAST(gl_account AS VARCHAR)[1]='1' THEN '자산'
                        WHEN CAST(gl_account AS VARCHAR)[1]='2' THEN '부채'
                        WHEN CAST(gl_account AS VARCHAR)[1]='3' THEN '자본'
                        WHEN CAST(gl_account AS VARCHAR)[1]='4' THEN '매출수익'
                        WHEN CAST(gl_account AS VARCHAR)[1] IN ('5','6') THEN '원가판관'
                        WHEN CAST(gl_account AS VARCHAR)[1]='7' THEN '영업외수익'
                        WHEN CAST(gl_account AS VARCHAR)[1]='8' THEN '영업외비용'
                        ELSE '기타_임시' END
                ) FILTER (WHERE CAST(credit_amount AS DOUBLE) > 0) credits
            FROM je WHERE gl_account IS NOT NULL
            GROUP BY document_id
        )
        SELECT
            array_to_string(list_sort(debits), '|') || ' / ' || array_to_string(list_sort(credits), '|') AS pattern,
            COUNT(*) AS cnt
        FROM doc_cls
        WHERE debits IS NOT NULL AND credits IS NOT NULL
        GROUP BY pattern
        ORDER BY cnt DESC
        LIMIT 20
    """):
        out["top_combinations"][r[0]] = r[1]

    # 이상 조합 카운트: 수익 차변/비용 대변만 (환입 제외하고 드물어야)
    out["revenue_on_debit_docs"] = _q1(con, """
        SELECT COUNT(DISTINCT document_id) FROM je
        WHERE CAST(debit_amount AS DOUBLE) > 0
          AND gl_account IS NOT NULL
          AND CAST(gl_account AS VARCHAR)[1]='4'
    """)
    out["expense_on_credit_docs"] = _q1(con, """
        SELECT COUNT(DISTINCT document_id) FROM je
        WHERE CAST(credit_amount AS DOUBLE) > 0
          AND gl_account IS NOT NULL
          AND CAST(gl_account AS VARCHAR)[1] IN ('5','6')
    """)

    # 비상식 조합: "수익 증가 ↔ 자본 감소" 같은 말이 안 되는 것
    # 자산-자산만 or 부채-부채만 (같은 클래스 내 rotation) 카운트
    # Why: 자산↔자산(현금을 예금으로 이체) 같은 정상 케이스도 포함되므로
    #      절대수치만으로 이상 판정 못함. 샘플 확인 필수.
    out["same_class_only_docs"] = _q1(con, """
        WITH cls_per_doc AS (
            SELECT document_id,
                   COUNT(DISTINCT
                       CASE
                           WHEN CAST(gl_account AS VARCHAR)[1]='1' THEN '자산'
                           WHEN CAST(gl_account AS VARCHAR)[1]='2' THEN '부채'
                           WHEN CAST(gl_account AS VARCHAR)[1]='3' THEN '자본'
                           WHEN CAST(gl_account AS VARCHAR)[1] IN ('4','7') THEN '수익'
                           WHEN CAST(gl_account AS VARCHAR)[1] IN ('5','6','8') THEN '비용'
                           ELSE '기타' END
                   ) cls_count
            FROM je WHERE gl_account IS NOT NULL GROUP BY 1
        )
        SELECT COUNT(*) FROM cls_per_doc WHERE cls_count = 1
    """)

    # Sample 전표 5건 확인 — 자산-자산 교환은 정상, 수익-수익 등은 이상
    out["same_class_samples"] = []
    for r in _q(con, """
        WITH cls_per_doc AS (
            SELECT document_id, COUNT(DISTINCT
                CASE
                    WHEN CAST(gl_account AS VARCHAR)[1]='1' THEN '자산'
                    WHEN CAST(gl_account AS VARCHAR)[1]='2' THEN '부채'
                    WHEN CAST(gl_account AS VARCHAR)[1]='3' THEN '자본'
                    WHEN CAST(gl_account AS VARCHAR)[1] IN ('4','7') THEN '수익'
                    WHEN CAST(gl_account AS VARCHAR)[1] IN ('5','6','8') THEN '비용'
                    ELSE '기타' END
            ) cls_count
            FROM je WHERE gl_account IS NOT NULL GROUP BY 1
        )
        SELECT document_id FROM cls_per_doc WHERE cls_count = 1 LIMIT 5
    """):
        doc_id = r[0]
        lines = _q(con, f"""
            SELECT gl_account, line_text,
                   CAST(debit_amount AS DOUBLE), CAST(credit_amount AS DOUBLE)
            FROM je WHERE document_id = '{doc_id}'
            ORDER BY CAST(line_number AS INT) LIMIT 6
        """)
        out["same_class_samples"].append({
            "document_id": doc_id,
            "lines": [
                {"gl": line[0], "text": (line[1] or "")[:40],
                 "debit": line[2], "credit": line[3]}
                for line in lines
            ],
        })

    return out


# ── Axis 11: Text-Account Semantic Match (적요-계정 정합성) ──


def axis_text_account_match(con) -> dict:
    """line_text/header_text 한국어 키워드와 gl_account 클래스의 정합성.

    예시: line_text에 "매출"이 있는데 gl_account가 부채(2xxx)라면 이상.
          "매입채무" 단어 → 2xxx 부채 계정이 정상.
    """
    out = {}

    # 키워드별 기대 클래스 정의 (K-IFRS 한국 중견기업 CoA 9분류)
    keyword_expected = {
        "매출": ["자산", "매출수익"],         # 매출채권(자산) or 매출(매출수익)
        "매출채권": ["자산"],
        "매입": ["자산", "부채"],             # 재고(자산) or 매입채무(부채)
        "매입채무": ["부채"],
        "급여": ["원가판관", "부채"],         # 인건비(원가판관) or 미지급급여(부채)
        "감가상각": ["원가판관", "자산"],      # 감가상각비 or 감가상각누계액
        "법인세": ["원가판관", "부채", "기타_임시"],
        "차입금": ["부채"],
        "대여금": ["자산"],
        "가수금": ["부채", "기타_임시"],       # 9xxx 임시 계정 허용
        "가지급": ["자산", "기타_임시"],
        "미지급": ["부채"],
        "선급": ["자산"],
        "선수": ["부채"],
        "이자수익": ["영업외수익", "매출수익", "기타_임시"],
        "이자비용": ["영업외비용", "원가판관"],
        "배당": ["자본", "영업외수익", "원가판관"],
    }

    out["keyword_classes"] = {}
    out["keyword_mismatches"] = {}
    for keyword, expected in keyword_expected.items():
        # Why: line_text만 체크. header_text는 전표 수준 설명이라 한 전표 내 여러 line이
        #      다양한 클래스를 가질 수 있으므로 line-level 검증에는 부적합.
        rows = _q(con, f"""
            SELECT
                CASE
                    WHEN CAST(gl_account AS VARCHAR)[1]='1' THEN '자산'
                    WHEN CAST(gl_account AS VARCHAR)[1]='2' THEN '부채'
                    WHEN CAST(gl_account AS VARCHAR)[1]='3' THEN '자본'
                    WHEN CAST(gl_account AS VARCHAR)[1]='4' THEN '수익'
                    WHEN CAST(gl_account AS VARCHAR)[1] IN ('5','6') THEN '비용'
                    ELSE '기타' END AS cls,
                COUNT(*) cnt
            FROM je
            WHERE line_text LIKE '%{keyword}%'
              AND gl_account IS NOT NULL
              AND CAST(gl_account AS VARCHAR) NOT IN ('','nan')
            GROUP BY cls
            ORDER BY cnt DESC
        """)
        if rows:
            classes_dict = {r[0]: r[1] for r in rows}
            total = sum(classes_dict.values())
            matched = sum(v for k, v in classes_dict.items() if k in expected)
            match_rate = round(matched / total, 4) if total else 0
            out["keyword_classes"][keyword] = classes_dict
            # 키워드 의미와 계정 클래스가 30% 이상 어긋나면 문제로 기록
            if match_rate < 0.70:
                out["keyword_mismatches"][keyword] = {
                    "expected": expected,
                    "actual_distribution": classes_dict,
                    "match_rate": match_rate,
                    "mismatched_lines": total - matched,
                }

    # 샘플 이상 분개: 매출채무(부채) 단어인데 자산으로 분류된 케이스
    # (이런 패턴이 존재하면 데이터 자체가 상식과 어긋남)
    out["sample_anomalies"] = []
    anomaly_queries = [
        ("매입채무_자산사용", """
            SELECT document_id, line_text, gl_account, debit_amount, credit_amount
            FROM je
            WHERE line_text LIKE '%매입채무%'
              AND CAST(gl_account AS VARCHAR)[1]='1'
            LIMIT 3
        """),
        ("매출_부채사용", """
            SELECT document_id, line_text, gl_account, debit_amount, credit_amount
            FROM je
            WHERE line_text LIKE '%매출%'
              AND CAST(gl_account AS VARCHAR)[1]='2'
              AND line_text NOT LIKE '%매출채무%'
              AND line_text NOT LIKE '%매출할인%'
            LIMIT 3
        """),
        ("급여_수익사용", """
            SELECT document_id, line_text, gl_account, debit_amount, credit_amount
            FROM je
            WHERE line_text LIKE '%급여%'
              AND CAST(gl_account AS VARCHAR)[1]='4'
            LIMIT 3
        """),
    ]
    for tag, sql in anomaly_queries:
        for r in _q(con, sql):
            out["sample_anomalies"].append({
                "type": tag,
                "document_id": r[0],
                "line_text": r[1],
                "gl_account": r[2],
                "debit": r[3],
                "credit": r[4],
            })

    return out


# ── 통합 실행 ────────────────────────────────────────────────


def extract(con) -> dict:
    return {
        "axis_1_temporal_granularity": axis_temporal_granularity(con),
        "axis_2_user_sequence": axis_user_sequence(con),
        "axis_3_label_quality": axis_label_quality(con),
        "axis_4_amount_geometry": axis_amount_geometry(con),
        "axis_5_drift_baseline": axis_drift_baseline(con),
        "axis_6_sod_persona": axis_sod_persona(con),
        "axis_7_data_quality": axis_data_quality(con),
        "axis_8_fraud_signature": axis_fraud_signature(con),
        "axis_9_gl_integrity": axis_gl_integrity(con),
        "axis_10_journal_logic": axis_journal_logic(con),
        "axis_11_text_account_match": axis_text_account_match(con),
    }


def main() -> None:
    start = time.perf_counter()
    print("=" * 60)
    print("Phase 2 독자 데이터 분석 (8 축)")
    print("=" * 60)

    con = duckdb.connect()
    print(f"\n  CSV 로드: {_CSV}")
    con.execute(f"""
        CREATE TABLE je AS
        SELECT * FROM read_csv_auto('{_CSV.as_posix()}', all_varchar=true)
    """)
    rows = con.execute("SELECT COUNT(*) FROM je").fetchone()[0]
    print(f"  -> {rows:,}행 로드 완료")

    print("\n  8-축 분석 중...")
    profile = extract(con)
    con.close()

    _OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(_OUT, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2, default=str)

    elapsed = time.perf_counter() - start
    print(f"  -> {_OUT} 저장 완료 ({elapsed:.1f}s)")


if __name__ == "__main__":
    main()
