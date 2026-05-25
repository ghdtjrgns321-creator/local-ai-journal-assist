"""감사 프리셋 12종 — Text-to-SQL 템플릿 + Chat UI 버튼.

기본 분석 6종 + 프로세스별 6종.
각 프리셋은 자연어 질문, 템플릿 SQL, 키워드 매칭 정보를 포함한다.
"""

from __future__ import annotations

from dataclasses import dataclass

# ── 데이터 모델 ──────────────────────────────────────────────

@dataclass(frozen=True)
class AuditPreset:
    """감사 프리셋 단일 항목."""

    key: str
    label: str
    question: str
    sql: str
    category: str  # "basic" | "process"
    keywords: tuple[str, ...]


# ── 프리셋 정의 ──────────────────────────────────────────────

AUDIT_PRESETS: dict[str, AuditPreset] = {
    # ── 기본 분석 6종 ──
    "high_risk_overview": AuditPreset(
        key="high_risk_overview",
        label="고위험 전표 현황",
        question="고위험으로 분류된 전표의 건수와 금액 분포는?",
        sql="""
SELECT risk_level,
       COUNT(*) AS cnt,
       SUM(debit_amount) AS total_debit,
       SUM(credit_amount) AS total_credit
FROM general_ledger
WHERE upload_batch_id = ?
  AND risk_level = 'HIGH'
GROUP BY risk_level
LIMIT 1000
""".strip(),
        category="basic",
        keywords=("고위험", "high risk", "위험", "risk_level"),
    ),
    "weekend_midnight": AuditPreset(
        key="weekend_midnight",
        label="심야/주말 전표",
        question="심야 또는 주말에 처리된 전표 목록은?",
        sql="""
SELECT document_id, posting_date, posting_time, created_by,
       business_process, debit_amount, credit_amount,
       is_weekend, is_after_hours
FROM general_ledger
WHERE upload_batch_id = ?
  AND (is_weekend = true OR is_after_hours = true)
ORDER BY posting_date DESC
LIMIT 1000
""".strip(),
        category="basic",
        keywords=("심야", "주말", "야간", "weekend", "midnight", "after hours"),
    ),
    "period_end_large": AuditPreset(
        key="period_end_large",
        label="기말 고액 전표",
        question="기말에 입력된 고액 전표 목록은?",
        sql="""
SELECT document_id, posting_date, gl_account, created_by,
       debit_amount, credit_amount, header_text, source
FROM general_ledger
WHERE upload_batch_id = ?
  AND is_period_end = true
  AND (debit_amount >= 50000000 OR credit_amount >= 50000000)
ORDER BY debit_amount + credit_amount DESC
LIMIT 1000
""".strip(),
        category="basic",
        keywords=("기말", "고액", "period end", "large", "결산"),
    ),
    "reversal_pairs": AuditPreset(
        key="reversal_pairs",
        label="역분개 전표 쌍",
        question="동일 계정에서 차변/대변이 교차되는 역분개 전표 쌍은?",
        sql="""
SELECT a.document_id AS doc_a, b.document_id AS doc_b,
       a.gl_account, a.debit_amount, b.credit_amount,
       a.posting_date AS date_a, b.posting_date AS date_b
FROM general_ledger a
JOIN general_ledger b
  ON a.upload_batch_id = b.upload_batch_id
  AND a.gl_account = b.gl_account
  AND ABS(a.debit_amount - b.credit_amount) < 0.01
  AND a.debit_amount > 0 AND b.credit_amount > 0
  AND a.document_id < b.document_id
WHERE a.upload_batch_id = ?
ORDER BY a.debit_amount DESC
LIMIT 1000
""".strip(),
        category="basic",
        keywords=("역분개", "reversal", "반대 분개", "차대변 교차"),
    ),
    "top_accounts": AuditPreset(
        key="top_accounts",
        label="이상 집중 계정 TOP10",
        question="이상 점수가 높은 전표가 집중된 계정 상위 10개는?",
        sql="""
SELECT gl_account,
       COUNT(*) AS flagged_cnt,
       ROUND(AVG(anomaly_score), 4) AS avg_score,
       SUM(debit_amount) AS total_debit
FROM general_ledger
WHERE upload_batch_id = ?
  AND anomaly_score > 0
GROUP BY gl_account
ORDER BY flagged_cnt DESC
LIMIT 10
""".strip(),
        category="basic",
        keywords=("이상 계정", "top accounts", "집중 계정", "anomaly"),
    ),
    "benford_deviation": AuditPreset(
        key="benford_deviation",
        label="Benford 편차",
        question="Benford 법칙에서 가장 큰 편차를 보이는 자릿수는?",
        sql="""
SELECT digit, observed_freq, expected_freq,
       ROUND(ABS(deviation), 6) AS abs_deviation
FROM benford_digits
WHERE upload_batch_id = ?
ORDER BY ABS(deviation) DESC
LIMIT 9
""".strip(),
        category="basic",
        keywords=("benford", "벤포드", "첫째 자릿수", "digit"),
    ),
    # ── 프로세스/부정유형별 6종 ──
    "fraud_by_process": AuditPreset(
        key="fraud_by_process",
        label="프로세스별 부정 분포",
        question="비즈니스 프로세스별 부정 유형 분포는?",
        sql="""
SELECT business_process, fraud_type, COUNT(*) AS cnt
FROM general_ledger
WHERE upload_batch_id = ?
  AND is_fraud = true
GROUP BY business_process, fraud_type
ORDER BY cnt DESC
LIMIT 1000
""".strip(),
        category="process",
        keywords=("프로세스별", "부정", "fraud", "business_process"),
    ),
    "sod_violations": AuditPreset(
        key="sod_violations",
        label="SoD 위반 목록",
        question="직무분리(SoD) 위반 전표의 작성자와 승인자 목록은?",
        sql="""
SELECT document_id, created_by, approved_by,
       sod_conflict_type, business_process,
       debit_amount, posting_date
FROM general_ledger
WHERE upload_batch_id = ?
  AND sod_violation = true
ORDER BY debit_amount DESC
LIMIT 1000
""".strip(),
        category="process",
        keywords=("SoD", "직무분리", "segregation", "sod_violation"),
    ),
    "duplicate_payments": AuditPreset(
        key="duplicate_payments",
        label="중복 지급 상세",
        question="중복 지급으로 탐지된 전표 상세 목록은?",
        sql="""
SELECT document_id, reference, posting_date, created_by,
       debit_amount, gl_account, trading_partner
FROM general_ledger
WHERE upload_batch_id = ?
  AND fraud_type = 'DuplicatePayment'
ORDER BY debit_amount DESC
LIMIT 1000
""".strip(),
        category="process",
        keywords=("중복 지급", "duplicate", "이중 결제"),
    ),
    "intercompany_check": AuditPreset(
        key="intercompany_check",
        label="내부거래 법인간 잔액",
        question="내부거래에서 법인 간 순잔액은?",
        sql="""
SELECT company_code, trading_partner,
       SUM(debit_amount) AS total_debit,
       SUM(credit_amount) AS total_credit,
       SUM(debit_amount) - SUM(credit_amount) AS net_balance
FROM general_ledger
WHERE upload_batch_id = ?
  AND is_intercompany = true
GROUP BY company_code, trading_partner
ORDER BY ABS(SUM(debit_amount) - SUM(credit_amount)) DESC
LIMIT 1000
""".strip(),
        category="process",
        keywords=("내부거래", "intercompany", "법인간", "IC", "관계사"),
    ),
    "suspense_aging": AuditPreset(
        key="suspense_aging",
        label="가계정 체류 현황",
        question="가계정 전표의 lettrage 상태별 건수는?",
        sql="""
SELECT gl_account,
       CASE WHEN lettrage IS NOT NULL THEN 'cleared' ELSE 'open' END AS status,
       COUNT(*) AS cnt,
       SUM(debit_amount) AS total_debit
FROM general_ledger
WHERE upload_batch_id = ?
  AND is_suspense_account = true
GROUP BY gl_account, status
ORDER BY cnt DESC
LIMIT 1000
""".strip(),
        category="process",
        keywords=("가계정", "suspense", "체류", "lettrage", "미결"),
    ),
    "user_risk_profile": AuditPreset(
        key="user_risk_profile",
        label="사용자 위험 프로필",
        question="사용자별 이상 점수 평균과 수기/심야 전표 비율 상위 10명은?",
        sql="""
SELECT created_by,
       COUNT(*) AS total_cnt,
       ROUND(AVG(anomaly_score), 4) AS avg_score,
       ROUND(AVG(CASE WHEN is_manual_je THEN 1.0 ELSE 0.0 END), 4) AS manual_rate,
       ROUND(AVG(CASE WHEN is_after_hours THEN 1.0 ELSE 0.0 END), 4) AS after_hours_rate
FROM general_ledger
WHERE upload_batch_id = ?
GROUP BY created_by
ORDER BY avg_score DESC
LIMIT 10
""".strip(),
        category="process",
        keywords=("사용자", "user", "입력자", "위험 프로필", "risk profile"),
    ),
}


# ── 매칭/필터 함수 ───────────────────────────────────────────

def match_preset(question: str) -> AuditPreset | None:
    """자연어 질문 → 프리셋 매칭 (정확 매칭 → 키워드 매칭).

    Returns:
        매칭된 AuditPreset 또는 None.
    """
    q_lower = question.strip().lower()

    # 1순위: 정확 매칭
    for preset in AUDIT_PRESETS.values():
        if q_lower == preset.question.lower():
            return preset

    # 2순위: 키워드 매칭 — 가장 많은 키워드가 매칭된 프리셋 선택
    best: AuditPreset | None = None
    best_count = 0
    for preset in AUDIT_PRESETS.values():
        count = sum(1 for kw in preset.keywords if kw.lower() in q_lower)
        if count > best_count:
            best = preset
            best_count = count

    return best if best_count > 0 else None


def get_presets_by_category(category: str) -> list[AuditPreset]:
    """카테고리별 프리셋 목록 반환."""
    return [p for p in AUDIT_PRESETS.values() if p.category == category]
