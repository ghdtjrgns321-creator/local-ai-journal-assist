# SoD(직무분리) toxic 업무조합 근거표 — L1-06 데이터 기반 탐지

작성일: 2026-06-17

이 문서는 L1-06(직무분리 위반) 탐지가 **"어떤 업무를 한 사람이 겸하면 위반인가"** 를 근거 기반으로 판정하도록, toxic 업무조합의 정의와 3축 근거를 모은 단일 출처(해설)다. 실제 탐지가 읽는 데이터(SoT)는 [`config/sod_toxic_combinations.yaml`](../../config/sod_toxic_combinations.yaml)이며, 본 문서는 그 YAML의 각 항목이 "왜 toxic인가"를 설명한다.

---

## §1. 문제 — 라벨 읽기에서 데이터 도출로

현재 `b07_segregation_of_duties()`(`src/detection/fraud_rules_access.py`)는 데이터에 주입된 `sod_violation`·`sod_conflict_type` 라벨을 그대로 읽는다.

```python
# fraud_rules_access.py (현행)
if "sod_violation" in df.columns:
    direct_sod_violation = human_mask & bool_column(df, "sod_violation")   # 1857행
if "sod_conflict_type" in df.columns:
    within_process_conflict = human_mask & df["sod_conflict_type"].notna() # 1862행
```

이 구조의 문제:

- **실데이터**: `sod_violation` 컬럼 자체가 없어 아무것도 못 잡는다.
- **합성데이터**: 우리가 주입한 정답 라벨을 우리가 다시 읽는 순환(정답 베끼기)이 된다. 탐지 성능이 아니라 라벨 존재 여부를 측정하게 된다.

**해결 방향**: 라벨 대신 전표가 원래 갖고 있는 세 컬럼 — `created_by`(기표자) / `approved_by`(승인자) / `business_process`(업무) — 만으로 위반을 도출한다. 그러려면 "어떤 업무 겸직이 toxic인가"의 정의가 필요하고, 그 정의가 본 근거표다.

---

## §2. 판정 원칙 — 4기능 프레임과 탐지 단위

### (1) SoD 4기능 (COSO / ICFR 개념체계 원칙 10)

양립불가능한 네 기능 중 **2개 이상이 한 사람에게 모이면 toxic**이다.

| 기능 | 의미 | 한 사람이 겸하면 |
|------|------|------------------|
| authorization (승인) | 거래를 일으킬 권한 | — |
| recording (기록) | 거래를 장부에 적음 | 승인+기록 = 허위거래 정당화 |
| custody (자산보관·집행) | 현금·자산을 만짐 | 보관+기록 = 훔치고 동시에 숨김 |
| reconciliation (대사·조정) | 장부를 실물과 맞춰봄 | 집행+대사 = 차이를 스스로 덮음 |

### (2) 탐지 단위

- **person = `created_by`**(기표자)를 기준으로 한 회기 내에 손댄 `business_process` 집합을 구한다.
- 그 집합이 §4 toxic 쌍을 포함하면 flag.
- `created_by == approved_by`(자기승인)면 단일 프로세스 내 겸직(§5 within-process)도 잡는다. `approved_by`도 동일 인물 집합에 포함해 판정.

### (3) 점수 단계 없음 — RED / YELLOW 2-class binary

L1-06은 점수 단계(0.5/0.7/0.8 같은 차등)가 없다. toxic 쌍은 **RED / YELLOW** 두 클래스로만 나뉘고, 발화 방식이 다르다:

- **RED → 정식 발화(primary).** 통합점수체계에서 다른 룰과 똑같이 흐른다 — 단독이면 **LOW**(검토), 행위신호(고액·역분개·수기·결산 등)와 **조합되면 HIGH**. 단독으로 HIGH를 만들지 않는다(겸직만으로 부정을 단정하지 않으므로).
- **YELLOW → 점수 미참여(리뷰 노트).** 단독으로는 큐에 **안 뜬다.** `row_annotation`에 `toxic_pair`·`signal_class=yellow`로 기록만 하여 감사인이 참고할 수 있게 둔다. (booster 배선·combo 가중은 추후 SoD combo 설계 시 검토 — 현재는 노트까지만.)

> RED/YELLOW를 가르는 기준은 §4.1(빼돌리기 + 숨기기). `strength`(strong/medium/weak)는 별개로 3축 근거의 종합 강도다(확신도 표기용).

---

## §3. 7개 업무 → 4기능 매핑

우리 시스템의 `business_process`는 7종이다. 각 프로세스를 toxic-pair 판정에서 대표하는 기능(primary)으로 매핑했다.

| process | 풀네임 | primary 기능 | 매핑 근거 |
|---------|--------|--------------|-----------|
| R2R | Record-to-Report (기표·총계정원장·결산조정) | recording + reconciliation | 장부 그 자체 — 기표와 결산대사를 함께 보유 |
| O2C | Order-to-Cash (매출·매출채권·수금) | custody + recording | 수금(현금 보관)과 매출채권 기표 → skimming 진입점 |
| P2P | Procure-to-Pay (매입·매입채무·지급) | authorization + recording | 거래처 등록·발주 승인과 매입채무 생성(지급집행은 TRE와 중첩) |
| H2R | Hire-to-Retire (급여·인사) | authorization + recording | 인사·급여마스터 등록과 급여 기표(지급집행은 TRE와 중첩) |
| A2R | Acquire-to-Retire (유형자산 취득·처분) | custody + recording | 자산 보관·처분과 자산대장 제각 |
| TRE | Treasury (자금·은행·이체) | custody | 자금 이동 그 자체 — 모든 현금유출 조합의 공통 custody 축 |
| MFG | Manufacturing (제조·원가) | custody + recording | 재고 보관과 원가 기표(근거 상대적 약함) |

> 4기능 분해는 COSO 틀이며, 한국 내부회계관리제도 설계·운영 개념체계가 이를 채택했다(§7 참조).

---

## §4. toxic 조합 요약표 (RED / YELLOW)

프로세스 쌍 10종 + within-process 2종 = 총 12종. (상세 근거는 §6, 데이터는 YAML `signal_class` 필드)

### §4.1 RED / YELLOW를 가르는 기준 — 빼돌리기 + 숨기기

겸직만으로는 "유령직원·가짜 매입채무" 같은 부정 시나리오를 **단정할 수 없다**(그건 추정이다). 그래서 시나리오가 아니라 **그 겸직이 객관적으로 어떤 통제 기능을 합쳤는가** 로만 가른다. 부정이 완성되려면 두 능력이 동시에 필요하다:

- **빼돌리기 (custody)** — 현금·자산을 직접 만질 수 있나 (TRE 현금, O2C 수금현금, A2R 유형자산, MFG 재고)
- **숨기기 (recording / reconciliation)** — 그걸 장부에서 가릴 수 있나 (R2R 기표·대사, P2P 매입기록, O2C 채권기록, H2R 급여기록, A2R 자산기록)

```
RED    = 한 사람이 [빼돌리기] + [숨기기] 둘 다 가짐  → 가져가고 동시에 덮을 수 있음(완결) → primary 발화
YELLOW = 둘 중 하나만 (자산 못 만짐 / 못 숨김 / 저유동 자산)  → 반쪽 결함 → 점수 미참여(노트)
```

| # | 조합 | signal_class | 빼돌리기(custody) | 숨기기(record/recon) | 판정 사유 |
|---|------|:---:|---|---|---|
| 1 | TRE+P2P | **RED** | ✅ 현금(TRE) | ✅ 매입기록(P2P) | 현금 인출 + 매입채무로 정당화 |
| 2 | TRE+R2R | **RED** | ✅ 현금(TRE) | ✅ 기표+대사(R2R) | 현금 유출 + 본인이 장부 마감 은폐 |
| 3 | TRE+O2C | **RED** | ✅ 수금현금 | ✅ 채권기록(O2C) | 수금 가로채고 매출채권에서 은폐(skimming) |
| 4 | O2C+R2R | **RED** | ✅ 수금현금(O2C) | ✅ 기표+대사(R2R) | 수금 가로채고 후속 입금으로 메움(lapping) |
| 5 | H2R+TRE | **RED** | ✅ 현금(TRE) | ✅ 급여기록(H2R) | 급여 발생 + 본인이 지급 집행 |
| 6 | A2R+R2R | **RED** | ✅ 유형자산(A2R) | ✅ 기표+대사(R2R) | 자산 반출 + 자산대장 제각 은폐 |
| 11 | P2P 단독 | **RED** | ✅ 지급집행 | ✅ 매입기록 | 발주·승인·지급 1인 완결 |
| 12 | TRE 단독 | **RED** | ✅ 현금집행 | ✅ 자기승인(견제 부재) | 기안·승인·집행 1인 완결 |
| 7 | P2P+R2R | **YELLOW** | ❌ 자산접근 없음 | ✅ | 장부상 가짜 매입은 만들어도 **직접 인출 불가**(TRE 필요) |
| 9 | H2R+R2R | **YELLOW** | ❌ 자산접근 없음 | ✅ | 가짜 급여 기록은 가능해도 **현금 인출 불가**(TRE 필요) |
| 8 | A2R+TRE | **YELLOW** | ✅✅ 자산+현금 | ❌ 장부통제 없음 | 가져가도 **GL에서 독립적으로 못 덮음**(R2R 필요) |
| 10 | MFG+R2R | **YELLOW** | △ 재고(저유동·물리반출) | ✅ | 전표 겸직만으론 미완 — 수량 측정·물리 반출 별도 필요 |

> 참고 메타: `severity_hint`(critical/high/medium)와 `strength`(strong/medium/weak)는 YAML에 남기되 **점수가 아니다** — severity는 우선순위 참고, strength는 3축 근거 확신도. 발화는 오직 `signal_class`(RED/YELLOW)로 결정된다.

**가장 단단한 RED**(3축 모두 직접 근거 + 금감원 실사례 일치)은 **TRE+P2P**(현금 인출 + 매입채무 정당화)와 **TRE+R2R**(현금 유출 + 본인 장부 마감 은폐)다. 나머지 RED는 빼돌리기+숨기기 구조는 동일하나 금감원 직접 사례가 없어 `strength`로 확신도를 구분한다(§9).

---

## §5. within-process(단일 프로세스 내) 중대 겸직

프로세스 간 쌍이 아니어도, 한 프로세스 안에서 1인이 발생·승인·집행을 모두 통제하면 toxic이다. 핵심 신호는 `created_by == approved_by`(자기승인).

- **P2P 단독(#11)**: 발주(authorization) → 승인 → 지급(custody)을 1인이 완결 → 견제 없이 허위 매입·지급 billing scheme 완성.
- **TRE 단독(#12)**: 이체 기안 → 승인 → 집행을 1인이 완결 → 임의 자금유출. 결산 분개로 은폐 시 TRE+R2R(#2)로 승격.

---

## §6. 조합별 3축 근거 (상세)

각 조합의 3축: **standard**(감사기준·내부회계) / **fss_korea**(금감원) / **external**(ACFE·COSO). 못 찾은 축은 "약함/미확보"로 명시한다.

### #1 TRE + P2P — critical / strong
- **부정 루트**: 허위 거래처·매입채무(AP)를 본인이 생성한 뒤, 본인이 자금이체로 지급해 인출. 가공 채무가 곧 현금유출로 직결.
- **standard**: KSA 240(부정·management override) + ICFR 원칙10(양립불가능 직무분리) + COSO authorization·custody 분리. 국제: ISA 240 / PCAOB AS 2401.
- **fss_korea**: 금감원 회계부정 사례 — 자금담당자가 본인 계좌로 자금을 빼돌리며 장부에는 '매입채무 지급'으로 위장, 결산 후 취소로 흔적 제거.
- **external**: ACFE 2024 RTTN — billing scheme(자산횡령의 22%, 중앙손실 $100K). "거래처를 등록하는 사람과 송장 지급을 승인하는 사람은 분리."
- **종합**: 3축 모두 직접 근거. 금감원 실사례가 본 조합과 정확히 일치.

### #2 TRE + R2R — critical / strong
- **부정 루트**: 자금이체로 현금 유출(custody)하고, 동일인이 총계정원장 기표·결산대사(recording+reconciliation)로 은폐. 결산 후 분개 취소로 흔적 제거.
- **standard**: KSA 240(부적절 분개·통제무력화, 분개 검사) + KSA 265(분개 단일통제=유의적 미비점) + ICFR 원칙10. 국제: ISA 240 / PCAOB AS 2401.
- **fss_korea**: 금감원 — 인건비 절감 명목 1인이 자금·회계 겸직, 영업임원이 재무 겸직 → 현금 횡령을 경영진이 인지 못함.
- **external**: ACFE — "한 개인이 회계거래 전체/다수를 통제하면 현금부정 기회 발생." COSO custody↔reconciliation 분리.
- **종합**: 감사기준·금감원 실사례 모두 직접. 본 도구의 핵심 toxic.

### #3 TRE + O2C — critical / medium
- **부정 루트**: 고객 수금(O2C custody)과 은행 입금·계좌 집행(TRE custody)을 1인이 통제 → 수금 가로채기 후 입금 조작(skimming), 입금지연으로 lapping.
- **standard**: ICFR 원칙10(현금 수령·보관·집행 분리) + KSA 240(현금수령 통제취약=부정위험) + COSO. 국제: ISA 240.
- **fss_korea**: 직접 매칭 사례 미확보 — 약함.
- **external**: ACFE skimming/lapping — "한 사람이 현금 수령·입금·기록·자금집행을 모두 하면 부정 위험 높음."
- **종합**: standard/external 강함, 금감원 직접 사례 미확보로 medium.

### #4 O2C + R2R — high / strong
- **부정 루트**: 고객 수금(custody)을 가로채고, 동일인이 매출채권 원장 기표·대사로 후속 입금으로 메우는 lapping(teeming and lading).
- **standard**: ICFR 원칙10(현금 custody↔매출채권 recording 분리) + KSA 240(수익·채권 부정위험) + COSO. 국제: ISA 240.
- **fss_korea**: 직접 매칭 사례 미확보 — 약함.
- **external**: ACFE lapping — "수금을 훔치고 이후 입금으로 부족분을 덮는다. 수금일↔입금일 시차가 적신호."
- **종합**: external(lapping) 매우 강함. 금감원 축 약함.

### #5 H2R + TRE — critical / strong
- **부정 루트**: 유령직원(ghost employee)을 인사·급여마스터에 등록하고, 동일인이 급여 지급(TRE custody)을 집행해 본인/공모자 계좌로 수령.
- **standard**: ICFR 원칙10(HR 마스터 승인↔급여 지급집행 분리) + KSA 240(급여 부정) + COSO. 국제: ISA 240.
- **fss_korea**: 직접 매칭 사례 미확보 — 약함.
- **external**: ACFE — "신규입사를 HRIS에 등록하는 사람이 급여처리·최종지급 승인을 겸하면 안 된다." 급여부정 조직 27%, 중앙손실 $120K.
- **종합**: 표준+외부 직접 근거로 strong. 금감원 직접 사례는 미확보.

### #6 A2R + R2R — high / medium
- **부정 루트**: 유형자산을 물리적으로 처분·반출하고, 동일인이 자산대장 제각·de-recognition 기표로 장부 흔적 제거(scrap 절도).
- **standard**: ICFR 원칙10(자산 처분 custody↔기록 recording 분리, 자산조정 승인자는 자산 접근 금지) + KSA 240. 국제: PCAOB AS 2401.
- **fss_korea**: 직접 매칭 사례 미확보 — 약함.
- **external**: ACFE asset misappropriation — "폐기자산 절도", "자산을 처분하는 사람과 회계기록자는 분리."
- **종합**: standard/external 명확. 금감원 직접 사례 미확보로 medium.

### #7 P2P + R2R — high / medium
- **부정 루트**: 매입채무 생성(P2P recording)과 총계정원장 마감·조정(R2R reconciliation)을 겸직 → 가공 채무를 독립검증 없이 장부에 매장.
- **standard**: KSA 240(결산조정 분개 override) + ICFR 원칙10(recording↔reconciliation 분리) + COSO. 국제: PCAOB AS 2401.
- **fss_korea**: 금감원 '매입채무 지급' 위장·결산 후 취소 사례가 본 조합의 R2R 마감 은폐와 연결.
- **external**: ACFE billing — fictitious vendor가 독립 기록검증 없이 통과될 때 발생.
- **종합**: 두 프로세스 모두 recording 성격이라 TRE 미동반 시 현금유출 직결성은 약함. 결산은폐 경로로 high.

### #8 A2R + TRE — high / medium
- **부정 루트**: 자산 처분 권한(A2R custody)과 처분대금 수령·이체(TRE custody)를 겸직 → 자산 매각대금 횡령.
- **standard**: ICFR 원칙10(자산 처분↔대금 수령 custody 분리) + KSA 240 + COSO.
- **fss_korea**: 직접 매칭 사례 미확보 — 약함.
- **external**: ACFE asset misappropriation / fixed asset fraud.
- **종합**: external 보조 근거. 금감원 직접 사례 미확보.

### #9 H2R + R2R — high / medium
- **부정 루트**: 유령직원 급여(H2R)를 발생시키고, 동일인이 총계정원장 기표·조정(R2R)으로 인건비를 묻어 은폐. TRE 미동반이라 현금화 직결성은 #5보다 약함.
- **standard**: ICFR 원칙10(authorization↔recording 분리) + KSA 240(급여) + COSO. 국제: ISA 240.
- **fss_korea**: 직접 매칭 사례 미확보 — 약함.
- **external**: ACFE ghost employee + 회계기록 은폐.
- **종합**: external 강하나 현금집행(TRE) 없이는 완성되지 않음 → medium.

### #10 MFG + R2R — medium / weak
- **부정 루트**: 재고·재공품을 물리적으로 보관(MFG custody)하면서 원가·재고 기표(R2R recording)를 겸직 → 재고 횡령을 원가차이·제각으로 은폐.
- **standard**: ICFR 원칙10 / COSO custody↔recording 분리 일반 원칙.
- **fss_korea**: 직접 매칭 사례 미확보 — 약함.
- **external**: ACFE — "재고를 개인용도/판매목적으로 절도"(일반). 본 쌍 특화 출처는 약함.
- **종합**: 원가 은폐 경로가 간접적이고 재고 단위 측정이 별도 필요 → weak.

### #11 P2P 단독 / #12 TRE 단독 — critical / strong
- **standard**: ICFR 원칙10(한 사람이 한 거래의 한 기능 이상 통제 금지) + KSA 265(단일통제=유의적 미비점) + COSO.
- **fss_korea**: #11 금감원 '매입채무 지급' 위장 횡령 / #12 자금·회계 1인 겸직 현금 횡령.
- **external**: #11 ACFE — "구매·검수보고서 서명·지급승인을 한 사람이 모두 가지면 안 된다." / #12 ACFE check tampering — "수표 승인자가 대사도 하면 안 된다."

---

## §7. standard 축 근거 프레임 — 한국 기준 우선

| 약칭 | 기준 | 직무분리 관련 |
|------|------|---------------|
| KSA 240 | 회계감사기준서 240(재무제표감사에서의 부정에 관한 감사인의 책임). 한국공인회계사회 제정, ISA 240 채택 | 부정위험요소·내부통제(직무분리) 이해, 분개를 통한 경영진 통제무력화 대응 |
| KSA 265 | 회계감사기준서 265(내부통제 미비점의 지배기구·경영진 커뮤니케이션) | 직무분리 결여 등 통제 미비점을 유의적 미비점으로 식별·소통 |
| ICFR 원칙10 | 내부회계관리제도 설계·운영 개념체계 원칙 10(통제활동 선택·구축, COSO 기반) | "이해상충을 일으키는 양립불가능한 업무를 한 사람에게 부여하지 않도록 직무 배분" |
| 외감법 | 주식회사 등의 외부감사에 관한 법률 | 내부회계관리제도 구축·운영 의무의 법적 근거 |
| ISA 240 / PCAOB AS 2401 | KSA 240의 원천 국제기준 | 분개·management override 대응(분개 검사) |
| COSO | Internal Control Framework | SoD 4기능 분리 원칙, ICFR 개념체계의 원천 |

---

## §8. 근거 약함 / 제외한 조합

직관상 toxic 같지만 SoD 단독 근거가 약해 제외했다.

| 조합 | 제외 사유 | strength |
|------|-----------|:---:|
| P2P + O2C | 매입(지출)·매출(수입)은 상대방·자금흐름이 달라 단일인 직접 횡령경로 약함. 특수관계 가공매출은 SoD 아닌 PHASE1-2 순환거래 룰 소관 | weak |
| A2R + P2P | 유형자산 취득은 P2P 조달과 기능 중첩 → 별개 toxic 쌍으로 보기 어려움 | weak |
| H2R + O2C | 급여와 수금 간 직접 부정경로 없음, 기능 충돌 부재 | none |
| MFG + P2P | 제조 원가와 조달은 정상 업무흐름상 연속(원자재 매입) | weak |

---

## §9. 한계 (정직한 미확보 항목)

- **금감원 직접 사례**: TRE+P2P·TRE+R2R(및 within-process)만 한국 금감원 실사례와 직접 매칭됐다. TRE+O2C·O2C+R2R·H2R 계열·A2R 계열은 ACFE/COSO/KSA 원칙은 강하나 한국 금감원 직접 사례를 못 찾아 해당 축을 "약함/미확보"로 표기하고 strength를 medium으로 낮췄다.
- **ICFR 개념체계 원문 verbatim**: "승인·기록·보관·대사 4기능"을 명시한 구절의 그대로 인용은 미확보. 원문이 로그인·PDF 뒤에 있다. 검색으로 "양립불가능 업무 분리" 원칙은 확인했고, 4기능 분해는 채택원천인 COSO 기준으로 기재했다. 원문 verbatim이 필요하면 한국공인회계사회/내부회계관리제도운영위원회 공식 PDF를 직접 확보해야 한다.
- **MFG+R2R**: 가장 약한 조합(weak). 재고 단위 측정이 별도로 필요하고 은폐 경로가 간접적이다.

---

## §10. 출처

**감사기준 / 내부회계 (한국)**
- 회계감사기준서 2023 개정 — 삼일: https://www.samili.com/acc/MasterTree.asp?op=4&op2=1&bcode=413-1
- 한국공인회계사회 회계감사기준: https://www.kicpa.or.kr/portal/default/kicpa/gnb/kr_pc/menu08/menu01/menu01.page
- KSA 265 유의적 미비점 — kifrs.com: https://www.kifrs.com/s/265/01ceff
- 내부회계관리제도 원칙10 — kifrs.com: https://www.kifrs.com/s/3004/e603ac
- 내부회계관리제도 모범규준 — k-icfr.org: https://www.k-icfr.org/sub/menu/guideline.asp?rWork=TblRead&rNo=8&rSchText=&rType=2

**감사기준 (국제)**
- PCAOB AS 2401: https://pcaobus.org/oversight/standards/auditing-standards/details/AS2401
- PCAOB Audit Focus — Journal Entries: https://pcaobus.org/resources/staff-publications/audit-focus/audit-focus-journal-entries

**금감원 / 한국 실무**
- 회계 오류·부정 방지 위해 자금담당·회계담당 분리 — intn.co.kr: https://www.intn.co.kr/news/articleView.html?idxno=2002996
- 회계감리 횡령 분야 지적 사례 — daeryunlaw-audit.com: https://www.daeryunlaw-audit.com/lawInfo_new/3669

**외부 (ACFE / COSO)**
- ACFE billing/payroll/cash disbursement — bonadio.com: https://www.bonadio.com/article/protecting-your-organization-common-cash-disbursement-fraud-schemes-how-to-prevent-them/
- AP segregation of duties — ramp.com: https://ramp.com/blog/accounts-payable/segregation-of-duties-in-accounts-payable
- Ghost employee 내부통제 — sikich.com: https://www.sikich.com/insight/ghost-employee-importance-of-internal-controls-in-payroll-processing/
- Lapping fraud — accountingtools.com: https://www.accountingtools.com/articles/what-is-lapping-fraud.html
- Asset misappropriation — weaver.com: https://weaver.com/resources/asset-misappropriation-in-cases-of-fraud/
- Fixed asset disposal 통제 — assetcues.com: https://www.assetcues.com/blog/fixed-asset-disposal-accounting/

---

## 관련 문서

- 데이터(SoT): [`config/sod_toxic_combinations.yaml`](../../config/sod_toxic_combinations.yaml)
- 탐지 룰 목록: [DETECTION_RULES.md](DETECTION_RULES.md) (L1-06)
- 활성 plan: [`dev/active/l1-06-sod-scoring/`](../../dev/active/l1-06-sod-scoring/)
