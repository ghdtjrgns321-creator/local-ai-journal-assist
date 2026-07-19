# PHASE2 fraud shortcut 제거 — 자동 루프 수정 프롬프트

> 목표: 부정이 회계 외 부수신호로 정상과 구별되지 않게 만든다(shortcut 제거).
> 완료 판정은 **정량 게이트 스크립트 exit 0**. 그 전까지 수정-생성-측정 자동 반복.
> 새 세션에 전문 붙여넣기.

═══════════════════════════════════════════════════════════════════════
[완료 조건 — 이것이 유일한 종료 기준]
═══════════════════════════════════════════════════════════════════════
  uv run python tools/scripts/phase2_shortcut_gate.py <새 데이터셋 경로>
→ exit 0 (RESULT: ALL PASS) 이면 완료. exit 1 이면 FAIL 게이트를 보고 수정 후 재생성·재측정 반복.

게이트 8개: 회귀4(R-COV/R-SELF/R-BAL/R-DIR) + shortcut3(S1/S2/S4) + 회계정합1(S8). (S7 폐기)
**임계(TH_*)를 낮춰 통과시키는 것은 금지(hollow-PASS).** 임계·S8 화이트리스트 변경은 사용자 승인.

⚠ r4b/r4d 교훈: shortcut 통과를 위해 회계를 망가뜨리는 우회 금지.
- r4b: loans_receivable 등 scheme-무관 계정을 채우기용 남용 → S8 FAIL. 정당 계정 내에서만.
- r4d: same-side split(같은 계정 2줄 쪼개기)으로 라인수 채움 → 가짜 복합분개. S7 자체가 잘못된
  게이트(라인수 분리력 0)였음 → S7 폐기 + 분할 되돌림. 부정 단순분개(2라인)는 회계적으로 정상.
원칙: shortcut 제거는 **회계 구조를 건드리지 않고 부수 표면(메타·승인자·계정세부코드)만** 조정.

[현재 baseline = r4d (8게이트 PASS, 단 same-side split 잔존)]
  8게이트 ALL PASS. 그러나 부정 3+라인 86건이 same-side split(동일계정 분할)로 회계 부자연.
  → A5 대로 분할 코드 제거하고 부정을 자연 단순분개로 되돌려 r4e 생성(게이트 8개 유지 확인).
  잔여 실질 결함은 same-side split 하나. 그 외 메타·승인자·counterparty·계정정합·경제효과 정상.

[원조 baseline = r3g (S1/S2/S4/S7 다 FAIL — 처음부터 할 경우)]
  PASS: R-COV, R-SELF, R-BAL, R-DIR (회계 내용 — 유지할 것)
  FAIL S1 메타결측률차: user_persona(정상1%/부정100%), auxiliary_account_label(17%/100%),
       cost_center(65%/0%), supporting_doc_type(41%/100%)
  FAIL S2 단일피처분리: approved_by='JYOUNG004'(부정54%), counterparty_type=None(prec87%)·Vendor(28%),
       has_attachment/tax_treatment/ledger/is_intercompany/user_persona IS NULL(부정 recall100%),
       fiscal_period 2·7(각 36~37%)
  FAIL S4 확장계정정상쌍둥이: 469100(allowance_reversal) 정상 263 < 300
  FAIL S7 라인수분포: 부정 전부 2라인(정상 평균 3.05)

═══════════════════════════════════════════════════════════════════════
[근본원인 & 수정 방향]
═══════════════════════════════════════════════════════════════════════
원인: ①정상 데이터가 일부 계정을 부정만큼 안 깖 ②overlay가 부정 문서의 메타·플래그·승인자·
라인수·계정선택을 정상 분포에서 샘플링하지 않고 고정/누락.
핵심 원칙: **부정 문서의 모든 비-회계 표면(메타필드·플래그·승인자·작성자·counterparty·라인수·
계정 세부선택)은 "같은 표면을 갖는 정상 동종 문서"의 분포에서 상속/샘플링**한다. 부정의 차이는
오직 회계 구조(계정 조합·금액·시점·흐름)여야 한다.

STEP A — overlay 수정 (tools/datasynth/crates/datasynth-cli/src/phase2_scheme_overlay.rs)

A1 (S1·S2 메타/플래그 결측): 부정 문서가 비워둔 필드를 정상 동종 분포로 채운다.
   - user_persona: 정상은 99% 채움 → 부정도 created_by(작성자)의 persona로 채움.
   - auxiliary_account_label: 정상 83% 채움 → 해당 계정·거래의 정상 라벨 분포에서.
   - cost_center: 정상은 손익계정 위주로 65% 채움/35% 빔 → 부정도 계정유형 따라 정상과 같은 비율.
     (현재 부정 0% 빔 = 전부 채움 → 정상처럼 비기도 해야).
   - supporting_doc_type: 정상 분포(세금계산서 등) 따름.
   - has_attachment, tax_treatment, ledger, is_intercompany: 정상은 거의 다 채움(NULL 1.5%) →
     부정도 정상값으로 채움(현재 부정 100% NULL = 전부 누락). 거래유형에 맞는 값.
   판정선: S1 = 모든 메타필드 |정상-부정 결측률| ≤ 8%p. S2 = 어떤 (필드 IS NULL) 규칙도
   recall<25% 또는 lift<5.

A2 (S2 승인자/작성자 집중): approved_by·created_by 를 정상 사용자 풀에서 분산 샘플.
   - 현재 JYOUNG004 한 명이 부정 54% 승인 → 여러 정상 승인자로 분산.
   - 단 SoD 위반이 scheme 본질인 부분(FS03 횡령의 자기승인 등)은 해당 component 에서만 의도적 —
     그래도 instance마다 다른 사용자. 어떤 단일 사용자도 부정의 25% 미만 포함.
   판정선: 어떤 approved_by/created_by 값도 recall<25%(부정의 1/4 미만) 그리고 lift<5 (단 precision<25%).

A3 (S2 counterparty_type 등): 부정 거래의 counterparty_type 을 거래 성격에 맞게 정상 분포로.
   - None 금지(현재 부정이 None 집중). Vendor/Customer/IntercompanyAffiliate 등 거래에 맞게,
     정상 동종 거래의 분포 비율로.
   판정선: 어떤 counterparty_type 값도 precision<25% 그리고 (recall<25% 또는 lift<5).

A4 (S2 fiscal_period 분산): 부정을 특정 월(2·7)에 과집중하지 말고 연중 분산.
   - 기말 조작이 본질인 scheme(FS07 재고·FS09 cutoff 등)은 기말 집중이 정당 — 단 모든 scheme이
     같은 월에 몰리지 않게. 여러 월에 분산.
   판정선: 어떤 fiscal_period 도 recall<25% 또는 lift<5.

A5 (폐기 — S7 라인수 게이트 제거됨): 부정을 인위적으로 3+라인으로 만들지 말 것.
   - 라인수는 fraud precision≈base(분리력 0)로 shortcut 이 아님이 실측됨 → S7 게이트 폐기.
   - ★★ same-side split(같은 계정을 2줄로 쪼개 라인수 채우기) 코드를 **제거**하고, 부정을
     scheme 메커니즘 그대로의 자연스러운 분개로 되돌린다. 횡령(차 가지급금/대 현금)·가공매출
     (차 AR/대 매출)이 2라인인 것은 회계적으로 정상.
   - 결과 점검: 동일계정 한문서 중복 비율이 정상 수준(약 9%)으로 내려가야 함(현재 부정 26%).

A6 (S2 gl_account 세부선택): 부정이 대표/통제 계정(4000·1200·5000·1100)에 몰리지 않게,
   정상이 쓰는 세부계정(400000~·100280~·500000~) 분포에서 선택.
   - 단 **같은 sub_type 의 세부코드로만 분산**한다(매출 4000→400000~ 매출세부, AR 1100→100120~
     AR세부, 재고 1200→100280~ 재고세부). sub_type 자체를 바꾸는 계정 교체 금지(S8 위반).
   판정선: 어떤 gl_account 도 precision<25% 그리고 (recall<25% 또는 lift<5).

A7 (S8 scheme-계정정합): 각 scheme 의 사용 sub_type 이 카탈로그 (b)(c)(d) 정당 계정 집합 내.
   - 게이트 S8 의 SCHEME_ACCT 화이트리스트 참조. 침입계정(현재 loans_receivable 12 scheme,
     contract_asset 5 scheme, FS04 short_term_investments, FS12 amortization_expense,
     FS14 operating_expenses 등) 0 건이어야 PASS.
   - 화이트리스트가 카탈로그상 정당한 계정을 빠뜨렸다면 카탈로그 근거 제시 후 사용자 승인하에 보정
     (단 명백한 무관계정 남용은 보정 아닌 제거 대상).

STEP B — normal 생성기 수정 (정상 쌍둥이 부족분만)
B1 (S4): 469100(allowance_reversal) 을 정상 거래에서 ≥300 문서 생성(현재 263).
   - 정상적 대손충당금 환입(회수 시) 분개를 정상 데이터에 충분히 추가.
   - 다른 확장 15계정은 이미 정상 ≥300 충족 — 469100만 보강.
   - normal 재생성 시 base 버전 올라가면 overlay base 경로·게이트 경로도 갱신(ripple).

═══════════════════════════════════════════════════════════════════════
[회귀 가드 — 유지(게이트 R-* + 기존 검증)]
═══════════════════════════════════════════════════════════════════════
- R-COV 14 scheme 전수 / R-SELF 자기상쇄0 / R-BAL 부정 차대균형0 / R-DIR 방향 안티패턴0.
- 기존 PASS(이전 회차): 불변량, base 무수정(overlay), 라벨정합, flow sidecar 멤버십,
  reversal 링크, scheme별 경제효과 방향, FS10/12/13 부작위금액 instance 파생,
  delivery 경계해소(verify_phase2_r3g.py / verify_phase2_r2.py 재사용).
- 회계 구조(가공매출·횡령·자본화 등 메커니즘)는 절대 훼손 금지 — 이번 수정은 "부수 표면"만.

═══════════════════════════════════════════════════════════════════════
[자동 루프 절차]
═══════════════════════════════════════════════════════════════════════
1. 수정(overlay/normal) → 새 데이터셋 생성 (r4, r4b, ... 회차 증가).
2. uv run python tools/scripts/phase2_shortcut_gate.py <경로>  실행.
3. exit 0 이면 종료. exit 1 이면 FAIL 게이트 세부를 읽고 해당 STEP 재수정 → 1로.
4. 매 회차 게이트 출력을 <경로>/reports/ 와 docs/debugging.md 에 누적 기록(유실 금지).
5. 회귀 검증(verify_phase2_r3g.py 경로 교체)도 매 회차 동반 — 회계 내용 깨지면 즉시 롤백.

[금지]
- 게이트 임계(TH_*) 낮춰 통과 금지. 빈 집합/fallback PASS 금지.
- 회계 구조·메커니즘 훼손 금지(부수 표면만 수정). detector 성능으로 주입 튜닝 금지.
- "거의 다 됐다"로 미달 게이트 남긴 채 종료 금지 — exit 0 아니면 미완. 한국어 보고.
