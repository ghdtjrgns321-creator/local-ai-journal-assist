import re

path = r"dev/active/phase1-rule-basis-audit/fss_case_combo_tagging.md"
rows = []
for line in open(path, encoding="utf-8"):
    if not line.startswith("|"):
        continue
    c = [x.strip() for x in line.strip().strip("|").split("|")]
    if len(c) < 8 or c[0] == "case_id" or set(c[0]) <= set("-"):
        continue
    rows.append(c)
rr = re.compile(r"L\d+-\d+(?:-\d+)?[a-z]?")
recs = [(c[0], set(rr.findall(c[4])), c[5], c[6].upper()) for c in rows]
HIGH = [(c, rs, tp) for (c, rs, tp, ti) in recs if ti.startswith("HIGH")]

BYPASS = {"L1-04", "L1-05", "L1-06", "L1-07", "L1-07-02"}
SEC = {"L4-04", "L3-03", "L1-05", "L3-11"}


def has_dup(rs):
    return any(r.startswith("L2-03") for r in rs)


def outflow(rs):
    return ("L2-02" in rs) or ("L2-05" in rs) or has_dup(rs)


def h1(rs):
    return bool(rs & {"L4-01", "L4-03"}) and "L3-02" in rs and (bool(rs & SEC) or has_dup(rs))


def h2(rs):
    return outflow(rs) and (bool(rs & BYPASS) or ({"L2-05", "L3-02", "L4-03"} <= rs))


def h3(rs):
    return "L3-09" in rs and outflow(rs) and "L4-03" in rs


def h4(rs):
    return bool(rs & {"L3-04", "L3-11"}) and bool(rs & {"L3-10", "L4-04", "L4-03"})


def h5(rs):
    return bool(rs & BYPASS) and "L4-03" in rs


def h9(rs):
    return "L2-04" in rs and "L3-02" in rs and bool(rs & {"L4-03", "L3-04"})


ALL = [h1, h2, h3, h4, h5, h9]

# 1) UNION coverage (전 HIGH 158, 단 6/8/10 미구현 scheme 포함)
u = sum(1 for c, rs, tp in HIGH if any(f(rs) for f in ALL))
print(f"[UNION] 전 HIGH {len(HIGH)}건 중 어느 조합이라도 발화 = {u} ({u / len(HIGH) * 100:.0f}%)")


# 2) scheme별 정확 분모 + 누락 다리 분해
def report(name, denom_fn, fn, slots):
    pool = [(c, rs) for c, rs, tp in HIGH if denom_fn(rs, tp)]
    n = len(pool)
    miss = [(c, rs) for c, rs in pool if not fn(rs)]
    print(
        f"\n=== {name}  분모 n={n}, 발화 {n - len(miss)} = {(n - len(miss)) / n * 100:.0f}%"
        if n
        else f"\n=== {name} n=0"
    )
    if miss:
        print(f"  미발화 {len(miss)}; 누락 슬롯:")
        for sname, stest in slots:
            lack = [c for c, rs in miss if not stest(rs)]
            if lack:
                print(f"    [{sname}] 없음 {len(lack)}: {lack[:8]}")


report(
    "H1 가공전표",
    lambda rs, tp: "수익통계" in tp,
    h1,
    [
        ("anchor L4-01|L4-03", lambda rs: bool(rs & {"L4-01", "L4-03"})),
        ("L3-02 수기", lambda rs: "L3-02" in rs),
        ("2차정황", lambda rs: bool(rs & SEC) or has_dup(rs)),
    ],
)
report(
    "H2 횡령(가수금 L3-09 제외)",
    lambda rs, tp: "중복자금유출" in tp and "L3-09" not in rs,
    h2,
    [
        ("outflow", outflow),
        (
            "control bypass|역분개수기고액",
            lambda rs: bool(rs & BYPASS) or ({"L2-05", "L3-02", "L4-03"} <= rs),
        ),
    ],
)
report(
    "H3 가수금(L3-09 보유)",
    lambda rs, tp: "중복자금유출" in tp and "L3-09" in rs,
    h3,
    [("outflow", outflow), ("L4-03 고액", lambda rs: "L4-03" in rs)],
)
report(
    "H4 결산조작",
    lambda rs, tp: "결산시점" in tp,
    h4,
    [
        ("timing L3-04|L3-11", lambda rs: bool(rs & {"L3-04", "L3-11"})),
        ("보강 L3-10|L4-04|L4-03", lambda rs: bool(rs & {"L3-10", "L4-04", "L4-03"})),
    ],
)
report(
    "H5 승인우회",
    lambda rs, tp: "승인통제" in tp,
    h5,
    [("bypass", lambda rs: bool(rs & BYPASS)), ("L4-03 고액", lambda rs: "L4-03" in rs)],
)
report(
    "H9 비용자산화(L2-04 보유)",
    lambda rs, tp: "계정분류" in tp and "L2-04" in rs,
    h9,
    [
        ("L3-02 수기", lambda rs: "L3-02" in rs),
        ("L4-03|L3-04", lambda rs: bool(rs & {"L4-03", "L3-04"})),
    ],
)
