# PHASE1 전 룰 도메인 리뷰 (전수, 2026-06-12)

> 41개 룰(canonical 31 + macro L4-02 + 보조 IC01~03·GR01/03·EV01/03·D01/02) + 스코어링 층을 3축으로 전수 검토한
> 결과. 측정(리콜 계약·도달성·발화율) 전수와 별개로 "룰 의도 vs 구현"의 의미 검토는 본 문서가
> 최초다. 3축: ① 못잡는 구멍(회피 경로) ② 과승격(정상을 high/medium으로 올리는 경로)
> ③ 저승격(위험한데 low에 깔리는 경로). 발견은 [PHASE1_OPEN_ISSUES.md](PHASE1_OPEN_ISSUES.md)
> #17~#25로 등록. 종합 검증: [PHASE1_VERIFICATION.md](PHASE1_VERIFICATION.md).

## 검토 방법과 신뢰 수준

- 6그룹 병렬 리뷰(L1/L2/L3전반/L3후반/L4/보조+스코어링층) — 전 발견에 파일:라인 근거 요구.
- 보고를 좌우하는 "높음" 주장 7건은 코드 직접 재확인으로 검증 완료(아래 ✓ 표기).
- 합성데이터 포트폴리오 범위 원칙: 회피 경로(축①)는 "실데이터 운영 성능을 주장하지 않는다"는
  주장 범위상 완성 차단 요소가 아니며, 기록과 PHASE2/향후 설계 입력으로 관리한다.

## 종합 판정 (3단 분류)

| 분류 | 항목 | 이슈 |
|------|------|------|
| **코드 버그 / 스펙 불일치** (수정 후보) | floor 정책 스펙 불일치(L1-04·L2-02), L2-02 fallback 미구현, macro 점수 기여 0, L4-02 macro context 미부착, L3-11 단독 Medium 불가(스펙 약속 위반), config weights 드리프트, variance_layer 한글 mojibake | #17, #20, #24 |
| **설계 결정 필요** (도메인 판단) | source 신뢰 비대칭(게이트 미연결 detector들), repeat 무조건 medium 승급, legacy 병렬 채널 정리, L3-12 ANY 집계 재정의, 콤보 강도 무시(set membership), dead zone(0.75~0.90) | #18, #21, #22, #23 |
| **데이터 특성 / 의도 범위** (기록) | 회피 면적 카탈로그(분할·윈도우·모집단 오염·자기신고 필드), 침묵 비활성 계열(#7 기존), prefix/목록 의존 사각 | #25 |

---

## §1 룰별 전수 요약표

심각도 = 3축 중 최고. ✓ = 직접 재검증 완료.

```
룰      심각도   핵심 발견 (축)
─────────────────────────────────────────────────────────────────────────────
L1-01   중간    document_id 위조로 차대 상쇄 회피(①)
L1-02   중간    placeholder 채움값 회피(①) · 매핑 사고 시 floor 0.90 일괄 high(②)
L1-03   중간    CoA 내 휴면계정 미커버(①) · fictitious 콤보 비참여(③)
L1-04   높음✓   boundary(약신호)도 approval_control_high 0.75 무차별(②) · 유령 승인자 사각(①)
L1-05   높음    source/persona 위조 시 0점 소멸 + 전 queue 제외(①) · 결산기 야근 0.80 승격(②)
L1-06   높음    direct conflict가 입력 라벨 전적 의존(①) · human filter substring 위조 회피(①)
L1-07   높음    가짜 승인자 한 칸으로 L1-04/07 동시 회피(①) · 단발 거액 critical 미달(③)
L1-08   중간    기수거리 무차등 flat 0.80 — 1기수(흔함)와 6기수(심각) 동일(②③ 양방향)
L1-09   중간    승인일 위조 무방비 — 시퀀스 타당성 검증 룰 부재(①)
L2-01   높음    임계밴드 밖 분할 사각 + 스펙의 L2-03 결합 보완 실효 부재(①)
L2-02   높음✓   fallback 3종 미구현 — 무reference 이중지급 영구 미탐(①) · floor 스펙 불일치(②)
L2-03   중높    exact_duplicate가 거래처·적요 무시 → 동액 다거래처 정상 발화(②)
L2-04   높음    원천 자산화(처음부터 자산 분개) 구조적 사각 — 재분류형만 탐지(①)
L2-05   높음    S1 1일/S2 7일 윈도우 — 8일 후 역분개 escape · 부분금액·제외계정 회피(①)
L3-01   중간    카테고리 텍스트가 prefix 추론을 무조건 이김 — 비표준 라벨로 무력화(①)
L3-02   중간    source 위조 시 수기 모집단 누락(①) · 정상 수기 결산조정 콤보 잔존(②)
L3-03   중간    관계사 식별 고정 prefix 4개 의존 — 목록 밖 관계사 전체 사각(①)
L3-04   중간    공휴일 미고려 ±5 달력일 윈도우(①) · 광역 발화의 콤보 재료화 잔존(②)
L3-05   중간    holidays 패키지/custom 의존 silent-degradation(①)
L3-06   높음✓   system source 점수 감면(0.45→0.20)이 source_trust 게이트 미연결 — 위장이 이득(①③)
L3-07   중간    document_date 위조 시 무력(스펙 인지) · 행 결측=정상 처리 비대칭(①)
L3-08   중간    garbage 토큰 영어 6개뿐 — 정상 단어 하나로 회피(①) · 콤보 제3요소 노이즈(②)
L3-09   높음    자기신고 정산 필드 신뢰 + 25일 주기 재계상 세탁 + materiality 부재(①③)
L3-10   중간    기말·주말 단독으로 priority_case 0.65 — "기말 현금계정 접촉" 과관대(②)
L3-11   높음    단독 극단 컷오프 상한 0.45 — 스펙 "단독 Medium" 약속과 불일치(③) · 콤보 크기 게이트 부재(②)
L3-12   높음    보강신호 user-year ANY 집계 → 정상 97% 발화·콤보 퇴화(②) · admin 0점 역전(③)
L4-01   높음    z-score 모집단 자기오염 — 대량 주입이 분모를 키워 자기 은폐(①)
L4-02   높음✓   n<500 분산 회피(①) · case macro_context 부착 제외 — D01/D02와 비대칭(③)
L4-03   높음    동일 모집단 오염(①) · 정상 기말 CAPEX가 L3-04+L4-04 콤보로 0.75(②)
L4-04   높음    threshold=1 — 같은 비정상 쌍 2회 반복이면 "희소 아님"(①) · 정규화 인플레이션(②)
L4-05   높음    source 자동 위장 시 행동통계·급속승인 통째 제외(①)
L4-06   높음    lone 임계 11건 묶음·가짜 batch_id로 우회(①) · 위장 신호가 surface 최약(#12 결합)(③)
IC01    중간    reference 하드 AND 조인 — 양사 상이 reference면 매칭 전제 붕괴(①)
IC02    중간    한 다리 외화 기표 시 점수 전면 억제 — 회피 통로(①)
IC03    중간    그룹 median 비교 — 단건 백데이트 희석(①) · 복수 매칭 첫 그룹만 비교(버그성)(①)
GR01    높음    per-row min_amount 필터 — 분할 기표 순환 미탐(①) · cycle이 콤보 입력 아님(③)
GR03    중간    양방향 동일 GL 전제 — 매출/매입 GL 분리 관행에서 main lane 무력(①)
EV01    중간    gap band(29k~30k) 분할 회피(①) · 케이스 층 미등록 — 활성화해도 점수 기여 0(③)
EV03    낮음    라인 금액 vs 문서 총액 비교 구조적 FP(①)
D01     중간    운영 산출물에 bucket 분류 입력 필드 부재 — confirmed 보강이 사실상 죽은 경로(③)
D02     낮중    min_account_docs=100 — 저빈도 계정 월패턴 사각(①, L3-04/L4-03 보완으로 수용 가능)
─────────────────────────────────────────────────────────────────────────────
```

## §2 횡단 발견 (룰 하나가 아니라 구조의 구멍)

### 2.1 source 신뢰 비대칭 (✓ 검증, #18)

`source_trust`(자동 위장 의심 판정)는 **fraud-combo 게이트와 L4-06에만** 연결됐다. 정작 source
필드를 믿고 **점수를 깎거나 모집단에서 빼는** detector 내부 경로들은 미연결:

| 위치 | 동작 | 코드 |
|------|------|------|
| L3-06 심야 | system source면 0.45→0.20 감면 + confirmed 제외 | `anomaly_rules_simple.py` c03 (source_trust import 0건 ✓) |
| L1-05 자기승인 | automated면 score 0 + 전 queue 제외 | `fraud_rules_access.py:1302-1305` |
| L4-05 시간대 집중 | 자동 계열이면 행동통계·급속승인 전체 제외 | `anomaly_rules_simple.py:1485-1509` |
| L1-06 직무분리 | source/계정명 substring으로 모집단 이탈 | `fraud_rules_access.py:1560-1580` |
| L1-04 한도초과 | 자동 source면 critical도 review 0.40 강등 | `fraud_rules_feature.py:228-232` |

결과: 위장 전표가 **가장 의심스러운 신호(심야·자기승인·한도초과)에서 오히려 점수가 깎이는 역설**.
#16(L4-06 위장 플래그)은 보완 신호를 추가했을 뿐, 감면 경로 자체는 그대로다.

### 2.2 승인통제 공동 사각 — 유령 승인자 (#19)

`approved_by`에 직원 마스터에 없는 ID(또는 "-", "N/A")를 넣으면: 한도 미해소 → L1-04 제외
(`fraud_rules_feature.py:215-216`), 비공란 → L1-07 비후보(`fraud_rules_access.py:1974`).
**"마스터에 없는 승인자"를 소유하는 룰이 전무** — 한 칸 위조로 승인통제 전 구간 회피.
승인일도 존재 여부만 보고(L1-09) 시퀀스 타당성(승인일<전기일 역전, 미래일) 검증 룰이 없다.

### 2.3 floor 정책의 스펙-구현 불일치 (✓ 검증, #17)

`apply_topic_floors`는 **버킷·신호강도 불문** normalized_score>0이면 floor를 적용한다
(`topic_scoring.py:238-251`). registry가 룰 단위로 floor를 부착하기 때문:

- L1-04: 스펙은 "critical/non_approver만 단독 High floor"(DETECTION_RULES.md:461-464)인데
  구현은 boundary(한도 소폭 초과, 검토용 0.35)도 `approval_control_high` 0.75
  (`rule_scoring.py:191`). r24에서 L1-04 168케이스 중 medium+ 153의 주요 동력.
- L2-02: 스펙은 reference_match에 floor **0.45**(DETECTION_RULES.md:799-800), fallback 제외인데
  구현은 전 발화 **0.75**(`rule_scoring.py:245`, `topic_scoring.py:25`). r24 L2-02 12건 전부
  medium 0.75 스냅과 정합.
- 콤보도 동일 구조: `normalized_score>0`이면 review_candidate(annotation 점수 승격,
  `phase1_case_builder.py:1292-1297` ✓)도 콤보 트리거 자격 동일(`topic_scoring.py:392-393`).

### 2.4 macro 신호의 점수 기여 0 (✓ 검증, #20)

> **해소(2026-06-15)**: 점수체계 tier 전환으로 가중합(macro_context_score 포함) 폐기 + macro(L4-02/D01/D02)를 PHASE1-1 registry에서 제거→PHASE1-2 family 이관. "죽은 가중치" 문제 소멸. 아래는 발견 당시 기록. (해결 위치: `PHASE1_OPEN_ISSUES.md` #20)

- macro 룰(L4-02·D01·D02·GR01·GR03)은 case hit 수집에서 제외(`phase1_case_builder.py:111,
  1221-1222` ✓) → macro_only view가 존재하지 않아 `macro_context_score` 가중치 0.03은
  **항상 0인 죽은 가중치**(`topic_scoring.py:18,159`).
- case macro_context 부착 대상도 `{D01,D02,GR01,GR03}`만 — **L4-02 Benford는 제외** ✓
  (`phase1_case_builder.py:3964`). 강한 Benford 위반 계정이 다른 룰 hit 없으면 거래 큐
  어디에도 연결 안 됨.
- GR01의 실제 그래프 순환은 `circular_transaction_high` 콤보의 입력이 아니다 — cycle 조건을
  repeat_score(월 반복)로 근사(`topic_scoring.py:477-484`). 순환거래 topic의 핵심 증거가
  점수 기여 0.

### 2.5 legacy 병렬 채널 생존 (✓ 검증, #21)

unit 경로에서 legacy 점수(`_apply_priority_adjustments`+`_apply_priority_floors`)가
`max(topic, legacy)`로 머지되어 topic cap·D065 IC 상한·trusted-automated 게이트를 전부
우회한다. 특히 `_l301_priority_adjustment`(`phase1_case_builder.py:5404-5449` ✓):
`{approval_issue, intercompany, repeat_pattern}` 중 **태그 1개**면 strong_context_floor
**0.90**(high 직행), 3태그면 0.95. intercompany 태그는 `is_intercompany=True`만으로 성립.
v41 정상에서 high 0인 것은 정상 데이터에 L3-01+태그 동시발생이 없었기 때문 — 경로는 열려 있다.
부수: high band(0.90)는 floor 체계상 topic 경로로 도달 불가(`*_high` floor 최대 0.75)라
**high 판정의 실권이 legacy 층에 있다** (dead zone 0.75~0.90).

### 2.6 repeat 무조건 medium 승급 (✓ 검증, #22 — 해소·가설 정정)

`_priority_band`는 priority_score와 무관하게 `repeat_score ≥ 0.70`(3개월+ 반복)이면 medium
(`phase1_case_builder.py:5646-5652` ✓). 정상 월 반복 전표(임차료·경영수수료)가 자동 medium.
**2026-06-13 해소(R1-C: 분기 제거) 후 정정**: "r24 IC 전건 medium의 유력 메커니즘"이라던 본
리뷰의 추정은 재측정으로 **반증**됐다 — 제거 후에도 IC01~03 122케이스는 전건 medium 유지
(콤보 점수로 0.75+ 도달). 실제 영향은 unit 경로 승급분이었다(truth medium 일부 low행).
리뷰 추정은 측정으로 확인하기 전까지 가설이다.

### 2.7 통계 룰 공통: 모집단 자기오염 (#25)

L4-01/L4-03 z-score는 그룹 transform 기반(`amount_features.py:178-185`) — 공격 행 자체가
mean/std에 들어가므로 대량 주입이 자기 은폐. L4-05 sigma 임계도 동일(결산기 전원 야근 시
임계 상승). L4-02 n<500 분산, L4-04 빈도 반복과 함께 "통계 룰은 분모를 공격당한다"는 공통
패턴. 합성데이터 검증 범위에서는 기록, robust 통계(median/MAD)·고정 floor는 PHASE2/향후.

## §3 실측과의 정합 확인

- 본 리뷰의 과승격 발견은 기존 실측과 모순되지 않는다: v41 정상 high 0은 "high 경로(legacy
  0.90 floor)의 발화 조건이 정상 데이터에 없었음"이고, medium 1,029 잔존은 §2.3(floor 무차별)
  + §2.6(repeat 승급) + 수기 결산조정 콤보(게이트 비대상)의 합으로 설명된다.
- 저승격 발견(#20 macro 기여 0)은 기존 #12(L4-06 미부착)·#9(D01/D02 미표면)와 같은 계열의
  더 넓은 구조 문제로, "표면 미노출"이 아니라 "점수 경로 차단"이라는 별개 메커니즘이다.

## §4 후속 처리

- 수정 여부·우선순위는 사용자 결정 대기 (§8 게이팅). 이슈 등록: OPEN_ISSUES #17~#25.
- 본 리뷰는 코드 정적 검토 + 표적 재검증이다. 발견별 영향 정량화(예: L1-04 boundary가 r24
  medium 153 중 몇 건인지)는 수정 결정 후 측정으로 확인한다.
