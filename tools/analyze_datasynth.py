"""DataSynth 생성 데이터 현실성 종합 분석 스크립트.

한국 중견 제조업(3법인) 합성 전표 데이터의 수치를 직접 확인하고
실무 벤치마크와 비교한다.
"""

import numpy as np
import pandas as pd
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "journal" / "primary" / "datasynth"
JE_PATH = DATA_DIR / "journal_entries.csv"
LABEL_PATH = DATA_DIR / "labels" / "anomaly_labels.csv"

# 메모리 최적화를 위한 dtype 지정
DTYPES = {
    "company_code": "category",
    "fiscal_year": "int16",
    "fiscal_period": "int8",
    "document_type": "category",
    "currency": "category",
    "user_persona": "category",
    "source": "category",
    "business_process": "category",
    "is_fraud": "object",
    "is_anomaly": "object",
    "fraud_type": "str",
    "anomaly_type": "str",
    "sod_violation": "object",
    "gl_account": "str",
    "debit_amount": "float64",
    "credit_amount": "float64",
    "document_number": "str",
    "line_number": "int16",
    "created_by": "str",
    "approved_by": "str",
}


def fmt(n, unit=""):
    """숫자를 읽기 쉽게 포맷"""
    if abs(n) >= 1e12:
        return f"{n/1e12:,.1f}조{unit}"
    if abs(n) >= 1e8:
        return f"{n/1e8:,.1f}억{unit}"
    if abs(n) >= 1e4:
        return f"{n/1e4:,.0f}만{unit}"
    return f"{n:,.0f}{unit}"


def pct(part, total):
    """백분율 문자열"""
    return f"{part/total*100:.2f}%" if total > 0 else "N/A"


def section(title):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")


def load_data():
    print("데이터 로딩 중...")
    df = pd.read_csv(
        JE_PATH,
        dtype=DTYPES,
        parse_dates=["posting_date"],
        usecols=[
            "document_id", "company_code", "fiscal_year", "fiscal_period",
            "posting_date", "document_type", "currency", "user_persona",
            "source", "business_process", "is_fraud", "fraud_type",
            "is_anomaly", "anomaly_type", "sod_violation",
            "gl_account", "debit_amount", "credit_amount",
            "document_number", "line_number", "created_by", "approved_by",
        ],
    )
    # bool 변환 (csv에서 "true"/"false" 문자열)
    for col in ["is_fraud", "is_anomaly", "sod_violation"]:
        df[col] = df[col].astype(str).str.lower() == "true"

    print(f"  로딩 완료: {len(df):,}행, 메모리 {df.memory_usage(deep=True).sum()/1e6:.0f}MB")
    return df


def analyze_basic(df):
    """1. 기본 현황"""
    section("1. 기본 현황")
    n_rows = len(df)
    n_docs = df["document_id"].nunique()
    lines_per_doc = n_rows / n_docs

    print(f"  전체 행 수:        {n_rows:>12,}")
    print(f"  전표(document) 수: {n_docs:>12,}")
    print(f"  전표당 평균 라인:  {lines_per_doc:>12.1f}")

    print("\n  [회사별 전표 수]")
    doc_by_co = df.groupby("company_code")["document_id"].nunique().sort_values(ascending=False)
    for co, cnt in doc_by_co.items():
        print(f"    {co}: {cnt:>10,}건  ({pct(cnt, n_docs)})")

    print("\n  [회계연도별 전표 수]")
    doc_by_yr = df.groupby("fiscal_year")["document_id"].nunique().sort_values(ascending=False)
    for yr, cnt in doc_by_yr.items():
        print(f"    {yr}: {cnt:>10,}건")


def analyze_amounts(df):
    """2. 금액 분포"""
    section("2. 금액 분포")

    # 라인 레벨 금액 (0 제외)
    debit = df["debit_amount"]
    credit = df["credit_amount"]
    amounts = pd.concat([debit[debit > 0], credit[credit > 0]])

    print("  [라인 레벨 금액 (0 제외)]")
    print(f"    건수:    {len(amounts):>12,}")
    print(f"    평균:    {fmt(amounts.mean(), '원')}")
    print(f"    중앙값:  {fmt(amounts.median(), '원')}")
    print(f"    표준편차: {fmt(amounts.std(), '원')}")
    print(f"    최소:    {fmt(amounts.min(), '원')}")
    print(f"    최대:    {fmt(amounts.max(), '원')}")

    percentiles = [0.01, 0.05, 0.25, 0.50, 0.75, 0.95, 0.99]
    pvals = amounts.quantile(percentiles)
    print("\n    분위수:")
    for p, v in pvals.items():
        print(f"      P{int(p*100):>2}: {fmt(v, '원')}")

    # LogNormal(14.0, 2.5) 기대값
    mu, sigma = 14.0, 2.5
    expected_median = np.exp(mu)
    expected_mean = np.exp(mu + sigma**2 / 2)
    print(f"\n  [LogNormal(μ=14, σ=2.5) 비교]")
    print(f"    기대 중앙값: {fmt(expected_median, '원')}  |  실제: {fmt(amounts.median(), '원')}")
    print(f"    기대 평균:   {fmt(expected_mean, '원')}  |  실제: {fmt(amounts.mean(), '원')}")

    # 1조원 초과
    over_1t = (amounts > 1e12).sum()
    print(f"\n  1조원 초과 건수: {over_1t}")

    # 전표 단위 총액
    doc_totals = df.groupby("document_id")["debit_amount"].sum()
    print(f"\n  [전표 단위 총액 (debit 합계)]")
    print(f"    중앙값: {fmt(doc_totals.median(), '원')}")
    print(f"    평균:   {fmt(doc_totals.mean(), '원')}")
    print(f"    최대:   {fmt(doc_totals.max(), '원')}")

    # Round / Nice number 비율
    round_mask = (amounts % 10000 == 0)
    nice_mask = (amounts % 1000 == 0)
    print(f"\n  [Round/Nice Number 비율 (라인 레벨)]")
    print(f"    만원 단위 (round): {pct(round_mask.sum(), len(amounts))}")
    print(f"    천원 단위 (nice):  {pct(nice_mask.sum(), len(amounts))}")


def analyze_balance(df):
    """3. 차대변 균형"""
    section("3. 차대변 균형")
    doc_bal = df.groupby("document_id").agg(
        debit_sum=("debit_amount", "sum"),
        credit_sum=("credit_amount", "sum"),
    )
    doc_bal["diff"] = (doc_bal["debit_sum"] - doc_bal["credit_sum"]).abs()
    n_docs = len(doc_bal)
    unbal = doc_bal[doc_bal["diff"] > 1]  # 1원 이상 차이

    print(f"  전표 수:             {n_docs:>10,}")
    print(f"  균형 전표 (차이≤1원): {n_docs - len(unbal):>10,}  ({pct(n_docs - len(unbal), n_docs)})")
    print(f"  불균형 전표:         {len(unbal):>10,}  ({pct(len(unbal), n_docs)})")
    if len(unbal) > 0:
        print(f"    불균형 금액 범위: {fmt(unbal['diff'].min(), '원')} ~ {fmt(unbal['diff'].max(), '원')}")
        print(f"    불균형 금액 중앙값: {fmt(unbal['diff'].median(), '원')}")


def analyze_temporal(df):
    """4. 시간 패턴"""
    section("4. 시간 패턴")

    df_doc = df.drop_duplicates(subset="document_id")

    # 월별
    monthly = df_doc.groupby(df_doc["posting_date"].dt.month).size()
    avg_month = monthly.mean()
    dec = monthly.get(12, 0)
    print("  [월별 전표 건수]")
    for m in range(1, 13):
        cnt = monthly.get(m, 0)
        ratio = cnt / avg_month
        bar = "#" * int(ratio * 10)
        print(f"    {m:>2}월: {cnt:>8,}  ({ratio:.2f}x)  {bar}")
    print(f"\n    12월/평월 배수: {dec/avg_month:.2f}x  (기대 ≥3x)")

    # 요일별
    dow = df_doc.groupby(df_doc["posting_date"].dt.dayofweek).size()
    dow_names = ["월", "화", "수", "목", "금", "토", "일"]
    weekday_total = sum(dow.get(i, 0) for i in range(5))
    weekend_total = sum(dow.get(i, 0) for i in range(5, 7))
    print("\n  [요일별 전표 건수]")
    for i in range(7):
        cnt = dow.get(i, 0)
        print(f"    {dow_names[i]}: {cnt:>8,}")
    print(f"    주말 비율: {pct(weekend_total, weekday_total + weekend_total)}")

    # 시간대별
    hours = df_doc["posting_date"].dt.hour
    time_bins = [
        ("심야 (00-06)", (0, 6)),
        ("오전 (06-09)", (6, 9)),
        ("업무 (09-12)", (9, 12)),
        ("점심 (12-13)", (12, 13)),
        ("오후 (13-18)", (13, 18)),
        ("야근 (18-22)", (18, 22)),
        ("심야 (22-24)", (22, 24)),
    ]
    print("\n  [시간대별 전표 건수]")
    for name, (s, e) in time_bins:
        cnt = ((hours >= s) & (hours < e)).sum()
        print(f"    {name}: {cnt:>8,}  ({pct(cnt, len(df_doc))})")

    # 기말 vs 비기말
    is_year_end = (df_doc["posting_date"].dt.month == 12) & (df_doc["posting_date"].dt.day >= 25)
    ye_days = is_year_end.sum()
    non_ye = len(df_doc) - ye_days
    # 7일(25~31) vs 나머지 날
    ye_daily = ye_days / 7 if ye_days > 0 else 0
    non_ye_daily = non_ye / 358  # 대략 365-7
    print(f"\n  기말(12/25~31) 일평균: {ye_daily:,.0f}건")
    print(f"  비기말 일평균:         {non_ye_daily:,.0f}건")
    print(f"  기말/비기말 배수:      {ye_daily/non_ye_daily:.2f}x" if non_ye_daily > 0 else "")


def analyze_gl(df):
    """5. GL 계정 분포"""
    section("5. GL 계정 분포")

    gl_counts = df["gl_account"].value_counts()
    print("  [상위 20개 GL 계정]")
    for gl, cnt in gl_counts.head(20).items():
        print(f"    {gl}: {cnt:>8,}  ({pct(cnt, len(df))})")

    # 대분류 (첫 자리 기준: 1=자산, 2=부채, 3=자본, 4=수익, 5-6=비용, 7-9=기타)
    first_digit = df["gl_account"].str[0]
    categories = {
        "1": "자산", "2": "부채", "3": "자본",
        "4": "수익", "5": "비용(매출원가)", "6": "비용(판관비)",
        "7": "기타수익/비용", "8": "기타", "9": "기타",
    }
    print("\n  [대분류별 비율]")
    cat_counts = first_digit.value_counts().sort_index()
    for digit, cnt in cat_counts.items():
        label = categories.get(str(digit), "기타")
        print(f"    {digit}xxx ({label}): {cnt:>10,}  ({pct(cnt, len(df))})")

    # 가계정 분석
    suspense_gls = ["1190", "2190", "1290", "9990"]
    for gl in suspense_gls:
        mask = df["gl_account"] == gl
        if mask.sum() > 0:
            fraud_cnt = (mask & df["is_fraud"]).sum()
            normal_cnt = (mask & ~df["is_fraud"]).sum()
            print(f"\n    가계정 GL {gl}: 정상 {normal_cnt:,}건 / fraud {fraud_cnt:,}건")


def analyze_process_user(df):
    """6. 프로세스 & 사용자"""
    section("6. 프로세스 & 사용자")

    df_doc = df.drop_duplicates(subset="document_id")

    print("  [business_process별 비율]")
    bp = df_doc["business_process"].value_counts()
    for proc, cnt in bp.items():
        print(f"    {proc}: {cnt:>8,}  ({pct(cnt, len(df_doc))})")

    print("\n  [user_persona별 비율]")
    up = df_doc["user_persona"].value_counts()
    for persona, cnt in up.items():
        print(f"    {persona}: {cnt:>8,}  ({pct(cnt, len(df_doc))})")

    print("\n  [source별 비율]")
    src = df_doc["source"].value_counts()
    for s, cnt in src.items():
        print(f"    {s}: {cnt:>8,}  ({pct(cnt, len(df_doc))})")


def analyze_fraud(df):
    """7. Fraud / Anomaly"""
    section("7. Fraud / Anomaly")

    df_doc = df.drop_duplicates(subset="document_id")
    n_docs = len(df_doc)

    fraud_cnt = df_doc["is_fraud"].sum()
    anomaly_cnt = df_doc["is_anomaly"].sum()
    print(f"  전체 전표 수: {n_docs:,}")
    print(f"  fraud 전표:   {fraud_cnt:,}  ({pct(fraud_cnt, n_docs)})")
    print(f"  anomaly 전표: {anomaly_cnt:,}  ({pct(anomaly_cnt, n_docs)})")

    # 회사별
    print("\n  [회사별 fraud 비율]")
    for co in sorted(df_doc["company_code"].unique()):
        co_df = df_doc[df_doc["company_code"] == co]
        f = co_df["is_fraud"].sum()
        print(f"    {co}: {f:,}/{len(co_df):,}  ({pct(f, len(co_df))})")

    # fraud_type별
    print("\n  [fraud_type별 건수]")
    ft = df_doc[df_doc["is_fraud"]]["fraud_type"].value_counts()
    for t, cnt in ft.items():
        if pd.notna(t) and t != "" and t.lower() != "nan":
            print(f"    {t}: {cnt:>6,}")

    # anomaly_type별
    print("\n  [anomaly_type별 건수 (상위 15)]")
    at = df_doc[df_doc["is_anomaly"]]["anomaly_type"].value_counts()
    for t, cnt in at.head(15).items():
        if pd.notna(t) and t != "" and t.lower() != "nan":
            print(f"    {t}: {cnt:>6,}")

    # 월별 fraud율 변동
    df_doc = df_doc.copy()
    df_doc["month"] = df_doc["posting_date"].dt.month
    monthly_fraud = df_doc.groupby("month").agg(
        total=("is_fraud", "size"),
        fraud=("is_fraud", "sum"),
    )
    monthly_fraud["rate"] = monthly_fraud["fraud"] / monthly_fraud["total"]
    cv = monthly_fraud["rate"].std() / monthly_fraud["rate"].mean() if monthly_fraud["rate"].mean() > 0 else 0

    print("\n  [월별 fraud율]")
    for m, row in monthly_fraud.iterrows():
        bar = "#" * int(row["rate"] * 200)
        print(f"    {m:>2}월: {row['rate']:.3f}  ({row['fraud']:.0f}/{row['total']:.0f})  {bar}")
    print(f"    변동계수(CV): {cv:.3f}  (기대 >0.1)")


def analyze_controls(df):
    """8. 내부통제"""
    section("8. 내부통제")

    df_doc = df.drop_duplicates(subset="document_id")
    n_docs = len(df_doc)

    # SoD 위반
    sod = df_doc["sod_violation"].sum()
    print(f"  SoD 위반: {sod:,}건  ({pct(sod, n_docs)})")

    # 자기승인
    self_approve = (df_doc["created_by"] == df_doc["approved_by"]).sum()
    print(f"  자기승인: {self_approve:,}건  ({pct(self_approve, n_docs)})")

    # approved_by 상위 10
    print("\n  [승인자 상위 10명]")
    ab = df_doc["approved_by"].value_counts()
    for u, cnt in ab.head(10).items():
        if pd.notna(u) and u != "" and u.lower() != "nan":
            print(f"    {u}: {cnt:>6,}건")


def benchmark_table(df):
    """9. 한국 실무 벤치마크 비교표"""
    section("9. 한국 실무 벤치마크 비교표")

    df_doc = df.drop_duplicates(subset="document_id")
    amounts = pd.concat([
        df["debit_amount"][df["debit_amount"] > 0],
        df["credit_amount"][df["credit_amount"] > 0],
    ])

    # 전표당 라인 수
    lines_per_doc = len(df) / df["document_id"].nunique()

    # 12월 스파이크
    monthly = df_doc.groupby(df_doc["posting_date"].dt.month).size()
    dec_ratio = monthly.get(12, 0) / monthly.mean() if monthly.mean() > 0 else 0

    # 주말 비율
    dow = df_doc["posting_date"].dt.dayofweek
    weekend_pct = (dow >= 5).sum() / len(df_doc) * 100

    # fraud율
    fraud_pct = df_doc["is_fraud"].sum() / len(df_doc) * 100

    # SoD
    sod_pct = df_doc["sod_violation"].sum() / len(df_doc) * 100

    # 차대변 불균형
    doc_bal = df.groupby("document_id").agg(d=("debit_amount", "sum"), c=("credit_amount", "sum"))
    unbal_pct = ((doc_bal["d"] - doc_bal["c"]).abs() > 1).sum() / len(doc_bal) * 100

    # round number
    round_pct = (amounts % 10000 == 0).sum() / len(amounts) * 100

    # 자기승인
    self_appr = (df_doc["created_by"] == df_doc["approved_by"]).sum() / len(df_doc) * 100

    # 심야(22-06) 비율
    hours = df_doc["posting_date"].dt.hour
    late_pct = ((hours >= 22) | (hours < 6)).sum() / len(df_doc) * 100

    benchmarks = [
        ("금액 중앙값",         f"{fmt(amounts.median(), '원')}",     "~120만원",         ""),
        ("금액 평균",           f"{fmt(amounts.mean(), '원')}",       "~2,900만원",       ""),
        ("전표당 라인 수",       f"{lines_per_doc:.1f}",              "2~5",              ""),
        ("12월/평월 배수",       f"{dec_ratio:.2f}x",                 "≥3x",              ""),
        ("주말 전표 비율",       f"{weekend_pct:.1f}%",               "5~15%",            ""),
        ("심야(22-06) 비율",    f"{late_pct:.2f}%",                  "<3%",              ""),
        ("fraud 비율",          f"{fraud_pct:.2f}%",                 "~2%",              ""),
        ("fraud CV(월별)",      f"{_compute_fraud_cv(df_doc):.3f}",  ">0.1",             ""),
        ("SoD 위반률",          f"{sod_pct:.2f}%",                   "≤2%",              ""),
        ("차대변 불균형",        f"{unbal_pct:.3f}%",                 "<0.5%",            ""),
        ("round number(만원)",  f"{round_pct:.1f}%",                 "15~35%",           ""),
        ("자기승인 비율",        f"{self_appr:.2f}%",                 "<1%",              ""),
    ]

    # 판정
    results = []
    for name, actual, expected, _ in benchmarks:
        results.append((name, actual, expected))

    print(f"  {'지표':<20} {'실제값':>18} {'기대 범위':>14}")
    print(f"  {'-'*20} {'-'*18} {'-'*14}")
    for name, actual, expected in results:
        print(f"  {name:<20} {actual:>18} {expected:>14}")


def _compute_fraud_cv(df_doc):
    """월별 fraud율의 변동계수 계산"""
    df_doc = df_doc.copy()
    df_doc["month"] = df_doc["posting_date"].dt.month
    rates = df_doc.groupby("month")["is_fraud"].mean()
    return rates.std() / rates.mean() if rates.mean() > 0 else 0


def main():
    print("=" * 70)
    print("  DataSynth 생성 데이터 현실성 종합 분석")
    print("  대상: 한국 중견 제조업 3법인 합성 전표")
    print("=" * 70)

    df = load_data()

    analyze_basic(df)
    analyze_amounts(df)
    analyze_balance(df)
    analyze_temporal(df)
    analyze_gl(df)
    analyze_process_user(df)
    analyze_fraud(df)
    analyze_controls(df)
    benchmark_table(df)

    print(f"\n{'='*70}")
    print("  분석 완료")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
