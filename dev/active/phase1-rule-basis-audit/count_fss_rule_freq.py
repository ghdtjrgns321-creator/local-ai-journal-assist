"""FSS 태깅 474건에서 tier별 룰 출현 빈도 집계 (금감원 기준 강축 룰 재분류용)."""

import re
from collections import Counter
from pathlib import Path

PATH = Path("dev/active/phase1-rule-basis-audit/fss_case_combo_tagging.md")
RULE_RE = re.compile(r"L\d-\d{2}")

rows = []
for line in PATH.read_text(encoding="utf-8").splitlines():
    if not line.startswith("| "):
        continue
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    if len(cells) < 8:
        continue
    if cells[0] in ("case_id", "") or set(cells[0]) <= set("-: "):
        continue  # header / separator
    rows.append(cells)

print(f"추출 데이터 행수: {len(rows)} (기대 474)")

# 컬럼: 0 case_id | 1 source | 2 원문 | 3 6대패턴 | 4 룰조합 | 5 연결주제 | 6 tier | 7 근거
tier_counter = Counter()
high_rules = Counter()
all_rules = Counter()
high_case_count = 0

for r in rows:
    tier = r[6].upper()
    tier_counter[tier] += 1
    combo = r[4]
    rules = set(RULE_RE.findall(combo))  # 케이스당 중복 룰 1회만
    for rule in rules:
        all_rules[rule] += 1
    # HIGH(NEW조합) 등 HIGH 변형 포함, N/A 제외
    is_high = tier.startswith("HIGH") and "N/A" not in tier
    if is_high:
        high_case_count += 1
        for rule in rules:
            high_rules[rule] += 1

print(f"\ntier별 행수 (합계 {sum(tier_counter.values())}):")
for t, c in tier_counter.most_common():
    print(f"  {t:12s} {c}")

print(f"\nHIGH 케이스 수: {high_case_count}")
print("\n=== HIGH 케이스 룰별 출현 빈도 (high_count / 전체_count) ===")
universe = sorted(set(all_rules) | set(high_rules))
for rule in sorted(universe, key=lambda x: (-high_rules[x], x)):
    h = high_rules[rule]
    a = all_rules[rule]
    pct = (h / high_case_count * 100) if high_case_count else 0
    print(f"  {rule:8s} HIGH={h:3d} ({pct:4.1f}% of HIGH)  전체={a:3d}")
