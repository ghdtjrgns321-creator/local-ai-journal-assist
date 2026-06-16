# PHASE1 전 룰 근거 전수 조사 (basis audit)

> 목적: tier 전환으로 윗단(band) 숫자랭킹은 근거화했으나, 각 룰의 **발화조건·임계·계정목록·키워드·점수계수**는 아직 근거가 반쪽이다. 31 canonical + macro(L4-02/Benford·D01·D02)를 전수 조사해 근거 유무를 분류하고, 결손을 우선순위로 정리해 하나씩 고친다.
> 조사일: 2026-06-15. 방법: 병렬 4-agent로 detector 코드 + config(settings.py·audit_rules.yaml) + 근거문서(룰원칙해설·DETECTION_REFERENCE·DETECTION_RULES·TIER_EVIDENCE_BASIS) 대조. 표본 주장은 설계자가 직접 재현 검증(§9).
> 분류: **[STD]** 규정/기준서 명문(PCAOB AS·ISA·외감법·K-IFRS) · **[STAT]** 통계관행(3σ·Nigrini MAD) · **[CONV]** 도메인관행·감사인 조정 정책값 · **[NONE]** 근거없음/문서에 주장없음/확인불가.

## 1. 핵심 발견 — 보편 패턴

**모든 룰에서 "무엇을 보는가(발화조건)"는 [STD]에 닿지만, "얼마나·어떤 코드(숫자·목록·계수)"는 거의 전부 [CONV]/[NONE]이다.**

- 발화조건 근거: 31룰 중 대다수가 ISA 240 A45(a~e)·240§32·ISA 520·K-IFRS 15/1024·외감법 §8에 매핑됨.
- 결손은 3개 층위에 집중:
  1. **임계 숫자** (z>3, ±5일, 45일, 0.012, process≥3, JSD 0.3 …)
  2. **계정/키워드 목록** (denied accounts 45개, reversal 키워드 18종, 자산화 키워드, IC prefix, 민감계정)
  3. **점수 계수** (detector raw score 0.25~0.90, severity 1~5, rule_scoring 5-way 곱·버킷맵)
- 추가 구조 문제: **detector raw score와 rule_scoring 버킷맵이 이중 체계**(예 L4-03 detector 0.25/0.45/0.70 ↔ 정규화 0.45/0.70/1.0). 같은 신호를 두 곳에서 다른 숫자로 매김.

## 2. 결손 우선순위 (작업 백로그 — 하나씩 고칠 순서)

### 1순위 — 분석을 좌우하는 임계인데 근거 전무 [NONE] (CLAUDE.md §3 "리터럴 임계=버그" 위험)
| # | 룰 | 항목 | 위치 | 메모 |
|---|-----|------|------|------|
| 1 | **L3-12** | `min_process=3`·`min_company=2`·persona 임계(3/4/5·2/3/4) | audit_rules.yaml:54-94 | 후보군 규모를 직접 좌우. 근거 전무 + `sod_role_thresholds`(junior 1)와 **값 불일치**(junior 3). ※재설계 예정 |
| 2 | **D02** | jsd_threshold 0.3 + 게이트(min_account_docs 100·top_month_delta 0.25) | variance_rules.py:210,23,25 | JSD 채택·0.3 모두 근거 없음 (macro, 현재 중화) |
| 3 | **D01** | variance_threshold 0.5 + 가중치 0.5/0.3/0.2 | variance_rules.py:122,17-19 | 발화 직접 결정, 순서만 정성 주장 (macro, 현재 중화) |
| 4 | **L4-04** | 희소 percentile p01(1%) | anomaly_rules_statistical.py:202 | "희소" 정의 자체. 240 A45(a)는 정성근거이나 1% 정량화 무근거 |
| 5 | **L4-06** | simultaneous 50·period_end_ratio 0.5 | anomaly_rules_batch.py:24-25 | 발화 임계 절대값 근거 없음 |
| 6 | **L1-07** | 가중 component 식(7계수)+금액 임계(10M/100M/1B) | fraud_rules_access.py:2173-2181,2101-2103 | L1 중 가장 복잡한데 근거 가장 부실, 문서에 식 주장 없음 |

### 2순위 — 핵심 일수/비율 임계가 "회사 조정" 명목뿐, 숫자 출처 없음 [CONV·약함]
| 룰 | 항목 | 값·위치 | 메모 |
|-----|------|---------|------|
| L3-04 | 기말 마진 ±5일 | settings.py:102 | "회사별 확정 필요" 명시는 있음(의도된 default) |
| L3-07 | backdated 30일 | settings.py:176 | "회사 정책상" 표현뿐, 기준 미제시 |
| L3-09 | aging 30일 + 30/60/90 버킷 | settings.py:177 | 채권 aging 관행이나 문서 근거 미기재, ×2/×3 파생 무근거 |
| L3-11 | 매출 5일/비용 7일 컷오프 + 기말 1.5x | settings.py:384-386 | 서열 의도만 추정, 1.5 무근거 |
| L2-02 | tolerance 2%·cap 10만원·window 45일 | fraud_rules_groupby.py:1008-1010 | 임의 |
| L2-01 | near ratio 0.90·close 0.95·razor 0.98 | settings.py:96, amount_features.py:312-314 | 단조성만 lock, 컷값 임의 |
| L2-05 | window 1일/7일·zero_threshold 1000원·S0~S5 가중치 | anomaly_rules_reversal.py:16-23,796-799 | **절대금액 1000원 = 소액통화 회귀 위험(§3 위반 소지)** |
| L4-01/03/05 | z>3·sigma 2.5·rapid 5분 | 각 detector | 3σ는 [STAT]이나 "왜 3"·"왜 2.5" 명시 없음 |

### 3순위 — 계정/키워드 목록의 출처 부재 [NONE→CONV] (선정 근거 문서 없음, "CoA 조정"으로 결손 정당화)
| 룰 | 목록 | 위치 |
|-----|------|------|
| L3-01 | process_denied_accounts 45개 계정번호 | audit_rules.yaml:563-610 (DataSynth CoA 역산 추정) |
| L2-05 | reversal_keywords 18종 (+코드 fallback과 불일치) | audit_rules.yaml:433-451 vs :37-60 |
| L2-04 | 자산화/의심 키워드 | audit_rules.yaml:261-293 ("시작점일 뿐"이라 자인) |
| L3-09/L3-10/L1-05 | 가계정·고위험 계정코드(1190/2190·prefix 111-113) | audit_rules.yaml (starter default) |

### 4순위 — 점수 계수·severity 전반 [NONE] (전 룰 공통)
- detector raw score(0.20~0.90) + rule_scoring 5-way 곱(signal×sev/5×evidence×role) + 버킷맵(L305/L307/L309/L403/L201/L202/L103/L104) **절대값은 어느 룰도 근거 없음**. 순서(서열)만 일부 문서화.
- SEVERITY_MAP 1~5: **L3-08(=1, "가장 약한 신호"로 정당화)만 예외**, 나머지 전부 근거 없음.

## 3. 룰별 발화조건 근거 요약 (압축)

> 발화조건(트리거)의 분류만. 임계·계수 결손은 §2 참조. 출처는 4-agent 보고의 file:line / doc 섹션 기반.

| 룰 | 발화조건 | 발화근거 분류 | 근거 출처(요지) |
|-----|---------|:---:|------|
| L1-01 | 차대불일치 > tol | [STD] | 240§32 복식부기, 외감법 §8①2호 |
| L1-02 | 필수필드 NULL | [STD] | 240-A45(d) (필수필드 전반은 외삽) |
| L1-03 | CoA 밖 계정 | [STD] | 240-A45(a)·315 (CoA밖≠저사용, 의미차) |
| L1-04 | 승인한도 초과 | [STD] | K-SOX·외감법 §8①5호 |
| L1-05 | created=approved | [STD] | 외감법 §8①5호 + FSS 오스템 2,215억 |
| L1-06 | sod_conflict_type 마커 | [STD] | 외감법 §8①5호 (단 toxic pair는 점수 미기여·라벨 의존) |
| L1-07 | 승인자 공백+승인필요 | [STD] | 외감법 §8② |
| L1-08 | fiscal_period 불일치 | [STD] | 240§32(b) |
| L1-09 | approval_date 공백 | **[CONV·약함]** | **9개 L1 중 유일하게 조문 인용 없음**("추적성 훼손" 일반론뿐) |
| L2-01 | 한도 직하 구간 | [STD] | 240-A45(e)·K-SOX |
| L2-02 | 중복지급 | [STD] | 240§32 (포괄) |
| L2-03(a-d) | 중복전표 | [STD] | 240§32·A45 |
| L2-04 | 자산차변+비용대변 | [STD] | 240§32, FSS 개발비 과대자산화 |
| L2-05 | 역분개 패턴 | [STD] | 240§32(a)(ii) 기말 재분개 + SAP reversal 절차 |
| L3-01 | process×category 불일치 | [STD] | 240-A45(c)·315 |
| L3-02 | 수기전표 | [STD] | 240-A45(b)·외감법 §8② (근거 가장 견고) |
| L3-03 | IC prefix 매칭 | [STD] | IFRS 10 §B86·K-IFRS 1024 §18·ISA 600/550 (조문 풍부) |
| L3-04 | is_period_end | [STD] | 240§32(a)(ii)·A44 |
| L3-05 | 주말/공휴일 | [STD] | 240-A45(c) (주말 직접명시 아님, 포괄) |
| L3-06 | 심야 22-06 | [STD]발화/[CONV]시간 | 240-A45(c)+KLCA. **시간대는 시프티 2024 실증(REF §6.5)=최선 문서화** |
| L3-07 | backdated > 임계 | [STD] | 240-A45(c) |
| L3-08 | 적요 결손/파손 | [STD] | 240-A45(c)·외감법 §8①1호 |
| L3-09 | 가수금 장기체류 | [STD] | 외감법 §8①2호, FSS 횡령은폐 |
| L3-10 | 고위험계정 사용 | **[CONV]** | 규정인용 없음, "감사인 지정" 위임 |
| L3-11 | 컷오프 위반 | [STD] | 240§32(b)·K-IFRS 15 |
| L3-12 | user-year 업무범위 | [STD]/[CONV] | K-SOX 최소권한·직무분리(포괄, 조문 없음) |
| L4-01 | 매출 z>3 | [STD]발화/[STAT]z | ISA 240 보론2·§32(c) (z>3은 240에 없음) |
| L4-02 | Benford MAD>0.012 | [STD]/[STAT] | ISA 520§5(Benford 직접명시 아님)+Nigrini 2012(MAD 출처 명확) |
| L4-03 | z>3 + p90 가드 | [STD]/[STAT] | 240§33(b) 고액위험 + 3σ |
| L4-04 | 희소 차대쌍 | [STD] | 240-A45(a) 비경상 계정 |
| L4-05 | 비정상시간 집중 | **[CONV·약함]** | KLCA IT 체크리스트(조문·항목 없음) = 근거 가장 빈약 |
| L4-06 | 배치 이상 | [CONV] | 통제취약성 일반론 + lone_identity v41 실측(82/202,102) |
| D01 | 계정활동 급변 | [STD]발화/[NONE]임계 | ISA 520 분석절차 (가중식·0.5 무근거) |
| D02 | 월분포 JSD 변화 | [STD]발화/[NONE]임계 | ISA 520 (JSD·0.3 무근거) |

## 4. 고치는 원칙 (tier 철학을 룰 단위까지 적용)

tier가 band에서 한 것을 룰 단위에 동일 적용:

1. **순서(order)는 살리고 크기(magnitude)·곱셈은 폐기.** 각 룰의 버킷은 이미 순서형 이름(lower/close/razor, moderate/large/extreme, 30/60/90)을 가짐 → 점수를 "임의 magnitude 곱"이 아니라 **순서형 등급**으로. detector·rule_scoring 이중 숫자 체계 일원화.
2. **임계는 출처 태그를 박는다.** 각 임계에 (a) 출처(STD/STAT/CONV), (b) 조정 주체(감사인), (c) truth-튜닝 금지 가드. [STD]/[STAT](z3σ·Nigrini·세법·기말관행)은 고정, [CONV](심야·45일·process≥3)는 "도메인 디폴트·조정가능"으로 정직하게 표기. [NONE]은 근거를 찾거나 도메인 디폴트로 강등.
3. **목록은 CoA 의존 명시 + 선정 근거 기록.** denied accounts·키워드는 "어떤 분석/규정에서 나왔는지" 추적 가능하게. 불일치(reversal yaml vs 코드, L3-12 persona vs sod_role)는 단일 출처로 통합.
4. **절대금액 임계 제거(§3).** L2-05 zero_threshold 1000원 등은 통화/규모 상대화.
5. **fitting 금지 유지.** 임계를 DataSynth truth recall에 맞춰 옮기지 않는다(config 주석에 이미 금지 원칙 존재).

## 5. 검증 기록 (§9)
- 설계자 직접 재현: L4-03 c08(z>3·z≥5/z≥10·0.25/0.45/0.70) anomaly_rules_simple.py:989-1007 일치; D02 jsd_threshold=0.3 variance_rules.py:210 일치; L3-12 persona(junior 3) vs sod_role(junior 1) 불일치 audit_rules.yaml:71/391 일치. → 4-agent 보고 신뢰 가능.
- 미검증(이월): 나머지 file:line 인용은 agent 보고 기준. 각 룰 수정 착수 시 해당 위치 직접 재확인.

## 5-1. 진행 기록 — 데이터 정합성 트랙 분리 (2026-06-15)

사용자 결정: 데이터 품질 룰을 부정 위험 큐(HIGH/MEDIUM/LOW)에서 분리해 별도 트랙으로.
- 구현(L1-01·L1-02·L1-03): `_DATA_INTEGRITY_TRACK_RULES`로 `phase1_case_builder` case_hits에서 제외(macro 옆) → 위험 topic/tier/priority 기여 0. `_build_data_integrity_findings`가 raw 결과에서 룰별 발화 건수 집계 → `metadata.data_integrity_findings`. ledger_integrity는 primary가 없어 위험 큐에 안 뜸(실질 주제 6→5).
- L1-08(기간불일치)은 위험 큐 잔류(사용자 결정).
- **L3-08(적요 결손) 보류**: 데이터 품질이지만 fraud combo("고액+기말+적요없음" = period_end_adjustment_high의 weak-description 다리)에서 보강 신호로도 쓰임(load-bearing). 데이터 트랙으로 빼면 그 조합이 약해짐 → 사용자 결정 대기.
- 검증: detection 1449 passed/0 failed. 옛 위험-동작 테스트 6개를 새 계약(위험 케이스 미생성 + 데이터 트랙 집계)으로 전환.
- 이월: 광범위 spec 문서(주제 6→5·DETECTION_RULES 등) 정합은 트랙 최종확정(L3-08·화면 탭) 후. TOPIC_REGISTRY의 ledger_integrity 물리 제거 여부도 그때.

## 5-2. 룰별 표시·근거 결정 (2026-06-15, 사용자)

데이터 정합성 트랙 표시:
- **L1-01**: 불일치 **차이금액 큰 순** 정렬로 표시.
- **L1-02**: HIGH/MEDIUM 아님. **누락 칸의 영향도 3등급**으로 표시 — ① 데이터 성립 불가(금액·전표번호 등 없으면 전표 자체 무효) ② 특정 룰 탐지 불가(예: 날짜 없으면 시점 룰, 계정 없으면 계정 룰) ③ 없어도 무관. → 필드→등급 매핑표 필요(미확정).
- **L1-03**: 현행 유지.

L1-04/L1-05 HIGH/MEDIUM 근거 질의 답(아래 §5-3) → 근거화 대상 확정.

## 5-3. L1-04 / L1-05 HIGH·MEDIUM 근거 실태 (코드 확인)

> **정정(2026-06-15)**: 아래 초판은 DETECTION_RANKING_CRITERIA.md를 정독하지 않고 작성해 "명문 근거 없음"으로 과일반화했다. 정독 결과 — **조합→tier(HIGH/MEDIUM)의 "구조" 근거는 명문 존재**: ① §점수 근거 요약(각 축→감사기준 240/315/520/550/500/1100·외감법) ② §High 승격 가능 조건(조합→HIGH 표 + 금감원 건수·기준서 근거) ③ "강한 정황 2개+ = HIGH, 약한 정황 1개 = MEDIUM"은 PCAOB AS 2401 §61(복수 특성 필요) + 정상 noise 관찰 근거. **근거 없는 것은 "구조"가 아니라 조건을 정의하는 "숫자"**(z>3·10억·±5일·100% excess·aging 30일)와 폐기된 floor 숫자(0.90/0.80/0.75). 아래 줄의 "명문 근거 없음"은 이 정정으로 대체한다.

- **L1-04 "심각 초과"** = 초과율 **100% 초과**(한도의 2배 넘음, `_approval_excess_bucket` critical, amount_features.py:431). 버킷 경계 10/50/100%는 **외부 근거 없음**(임의).
- **L1-04 HIGH(고액·컷오프) vs MEDIUM(수기·심야·주말)**: topic_scoring fraud combo — strong context(L4-03 고액 / L3-11 컷오프 / L3-04+L3-02 / L3-06+L3-02)=approval_bypass_high, 그 외 수기/심야/주말=approval_bypass_medium. 설계 의도(강한 정황 vs 약한 정황)뿐, **명문 근거 없음**.
- **L1-05 금액 기준** = **10억**(audit_rules `self_approval_immediate_override.materiality_amount`, 코드가 "universal 아님·placeholder"로 자인). 근거 없음 → 회사별 입력 필요.
- **L1-05 민감계정** = audit_rules `high_risk_accounts`(1190 가지급금·2190 가수금) + prefix 111/112/113(현금성). "conservative starter, 감사인 CoA 조정" — **권위 출처 없음**(시작 디폴트).
- **L1-05 비정상시점=MEDIUM, 금액·민감=HIGH**: config floor 숫자 0.80(시점) vs 0.90(금액/민감) 차이로 등급 갈림. **숫자 근거 없음**(magic).
- **이중 cut 불일치**: registry/combo floor는 ≥0.75=HIGH(`_floor_value_tier`), config priority_floor는 ≥0.90=HIGH/≥0.75=MEDIUM(`_legacy_floor_tier`). **같은 0.75가 경로에 따라 HIGH/MEDIUM 다름** = 근거화 시 통합 필요.

## 6. 다음
- §2 우선순위대로 룰 하나씩: 발화조건 근거 확정 → 임계/목록/계수 근거화(또는 도메인 디폴트 강등) → 회귀 가드(truth 미탐 0·정상 과탐 측정).
- L3-12는 §2-1순위이자 별도 재설계 대기 중(plan: phase1-rule-defect-fixes #23). basis 정리 후 복귀.
