rows=[]
with open("extract.tsv", encoding="utf-8") as f:
    for line in f:
        parts=line.rstrip("\n").split("\t")
        ln, case_id, combo, tier, reason = parts[0], parts[1], parts[2], parts[3], parts[4]
        cond1 = ("L3-04" in combo) or ("L3-11" in combo)
        cond2 = ("L3-10" in combo) or ("L4-04" in combo) or ("L4-03" in combo)
        code_fire = cond1 and cond2
        rows.append((ln,case_id,combo,tier,reason,code_fire))

N=len(rows)
high=[r for r in rows if r[3]=="HIGH"]
A=len(high)
A1=[r for r in high if r[5]]
A2=[r for r in high if not r[5]]
overfire=[r for r in rows if r[3] in ("MEDIUM","LOW") and r[5]]

print("N=",N)
print("HIGH A=",A)
print("A1=",len(A1))
print("A2=",len(A2))
print("---A2 list---")
for r in A2:
    print(r[0],r[1],r[2],r[3])
print("---overfire list---")
for r in overfire:
    print(r[0],r[1],r[2],r[3])
print("overfire count", len(overfire))
