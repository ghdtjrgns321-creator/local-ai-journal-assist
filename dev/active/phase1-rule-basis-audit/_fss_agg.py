import re
from collections import Counter

path = r"C:\Users\ghdtj\workspace\portfolio\local-ai-assist\dev\active\phase1-rule-basis-audit\fss_case_combo_tagging.md"
rows = []
with open(path, encoding="utf-8") as f:
    for line in f:
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 8 or cells[0] == "case_id" or set(cells[0]) <= set("-"):
            continue
        rows.append(cells)

rule_re = re.compile(r"L\d+-\d+(?:-\d+)?[a-z]?")


def tier_of(t):
    t = t.upper()
    for k in ("HIGH", "MEDIUM", "LOW"):
        if t.startswith(k):
            return k
    return "OTHER"


# 각 행: (case, ruleset, topic, tier)
recs = [(r[0], set(rule_re.findall(r[4])), r[5], tier_of(r[6])) for r in rows]


def high_for(keyword):
    return [(c, rs) for (c, rs, tp, ti) in recs if ti == "HIGH" and keyword in tp]


def freq(cases):
    cnt = Counter()
    for _, rs in cases:
        for ru in rs:
            cnt[ru] += 1
    return cnt


for kw in ["수익통계", "중복자금유출", "결산시점", "계정분류", "승인통제"]:
    cs = high_for(kw)
    print(f"\n##### topic '{kw}' HIGH 포함행 n={len(cs)}")
    for ru, c in freq(cs).most_common():
        print(f"  {ru}: {c}")

# HIGH-1 2차정황 풀: 1차(L3-02 & (L4-01|L4-03)) 충족한 수익통계 HIGH 중 2차룰 보유율
sec_pool = ["L4-04", "L2-03", "L3-03", "L3-10", "L1-05", "L3-11"]
rev = high_for("수익통계")
base = [(c, rs) for (c, rs) in rev if "L3-02" in rs and ({"L4-01", "L4-03"} & rs)]
print(f"\n##### HIGH-1 1차(L3-02 & 매출/고액) 충족 수익통계HIGH n={len(base)}; 2차정황 보유:")
for ru in sec_pool:
    n = sum(1 for _, rs in base if ru in rs)
    print(f"  {ru}: {n}/{len(base)}")

# HIGH-2 분기: 중복자금유출 HIGH 에서 자금유출/승인우회/역분개+수기
dup = high_for("중복자금유출")
outflow = {"L2-02", "L2-05", "L2-03"}
byp = {"L1-04", "L1-05", "L1-06", "L1-07"}
print(f"\n##### HIGH-2 중복자금유출 HIGH n={len(dup)}")
print("  자금유출(L2-02|05|03) 보유:", sum(1 for _, rs in dup if outflow & rs))
print("  +승인우회(L1-04~07) 보유:", sum(1 for _, rs in dup if (outflow & rs) and (byp & rs)))
print(
    "  +역분개&수기(L2-05&L3-02):",
    sum(1 for _, rs in dup if (outflow & rs) and {"L2-05", "L3-02"} <= rs),
)
for ru in ["L1-04", "L1-05", "L1-06", "L1-07"]:
    print(f"  {ru}: {sum(1 for _, rs in dup if ru in rs)}")

# HIGH-3 가수금: L3-09 보유 중복자금유출 HIGH
print(
    "\n##### HIGH-3 L3-09 보유 중복자금유출HIGH:",
    sum(1 for _, rs in dup if "L3-09" in rs),
    "그중 +고액L4-03:",
    sum(1 for _, rs in dup if "L3-09" in rs and "L4-03" in rs),
)

# HIGH-4 결산: timing_seed & weak/sensitive
cl = high_for("결산시점")
print(f"\n##### HIGH-4 결산시점 HIGH n={len(cl)}")
for ru in ["L3-04", "L3-07", "L3-11", "L1-08", "L3-08", "L3-10", "L4-04"]:
    print(f"  {ru}: {sum(1 for _, rs in cl if ru in rs)}")

# HIGH-5 승인통제: 강맥락 leg
ap = high_for("승인통제")
print(f"\n##### HIGH-5 승인통제 HIGH n={len(ap)}")
for ru in [
    "L1-04",
    "L1-05",
    "L1-06",
    "L1-07",
    "L3-11",
    "L3-04",
    "L3-02",
    "L3-06",
    "L3-05",
    "L3-12",
]:
    print(f"  {ru}: {sum(1 for _, rs in ap if ru in rs)}")

# HIGH-7 역분개+관계사+기말, HIGH-9 비용자산화
print(
    "\n##### HIGH-7 {L2-05,L3-03,L3-04} 동시보유(전 HIGH):",
    sum(1 for (c, rs, tp, ti) in recs if ti == "HIGH" and {"L2-05", "L3-03", "L3-04"} <= rs),
)
acc = high_for("계정분류")
print(
    f"##### HIGH-9 계정분류 HIGH n={len(acc)}; L2-04:",
    sum(1 for _, rs in acc if "L2-04" in rs),
    "L2-04&L3-02:",
    sum(1 for _, rs in acc if {"L2-04", "L3-02"} <= rs),
    "L2-04&L3-04:",
    sum(1 for _, rs in acc if {"L2-04", "L3-04"} <= rs),
    "L2-04&L3-02&L3-04:",
    sum(1 for _, rs in acc if {"L2-04", "L3-02", "L3-04"} <= rs),
)
# L3-08 전역
print(
    "\n##### L3-08(적요부실) 전 HIGH 출현:",
    sum(1 for (c, rs, tp, ti) in recs if ti == "HIGH" and "L3-08" in rs),
    "/ 전체출현:",
    sum(1 for (c, rs, tp, ti) in recs if "L3-08" in rs),
)
