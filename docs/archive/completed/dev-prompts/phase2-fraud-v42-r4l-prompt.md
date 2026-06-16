# v42 + r4l 통합 수정 프롬프트 — 도메인 감사 발견 전체 수정

> 배경: r4k 계열(14게이트+다양성v2 통과)은 부정 표면 기준 완성. 그러나 도메인 전수 감사
> (7구역 멀티에이전트, docs/guide/users/18_DATASYNTH_DOMAIN_AUDIT.md)에서 base normal 자체와
> PHASE2 인터페이스의 결함이 발견됨. 본 프롬프트는 발견 전부를 3단계로 수정한다.
> 새 세션에 전문 붙여넣기. 단계 순서 엄수(base가 바뀌므로 overlay는 그 뒤).

[전체 구조]
  STEP 1: normal 생성기 수정 → base v42 생성
  STEP 2: overlay 재실행(r4k 로직 그대로 + NULL 마커 동률화) → r4l + r4l_seed1~5
  STEP 3: PHASE2 코드 방어선(deny-list 등) 수정
완료 조건은 각 STEP 말미에 명시. 게이트 임계 완화 금지. detector 튜닝 금지. 한국어 보고.

═══════════════════════════════════════════════════════════════════════
STEP 1 — normal 생성기 수정 → base v42
═══════════════════════════════════════════════════════════════════════
구현: tools/datasynth (Rust — RUST로 근본 수정, Python 덧대기 금지)
현 base: data/journal/primary/datasynth_semantic_v1_normal_20260611_v41
산출: data/journal/primary/datasynth_semantic_v1_normal_<날짜>_v42

[N1 — 치명] 부가세 계산 버그: taxable_10 거래 134,626행 중 37,556행(27.9%)에서
  tax_amount ≠ supply_amount×10% (일부 1% 수준 저산정. 예: supply 1,085,336,895 → tax 7,051,708,
  기대 108,533,690). 연쇄로 invoice_amount = supply+tax 불일치 25.3%.
  → 세액 계산 로직을 근본 수정: taxable_10이면 tax = round(supply×0.10), invoice = supply+tax.
    면세/영세(tax_treatment exempt/zero)는 tax 0/NULL 일관 유지.
  검증: 오차>1원 건수 0 (전 taxable_10), invoice=supply+tax 불일치 0.

[N2] KRW 거래 exchange_rate≠1: 10,124건 — 주입 정상행(확장계정 쌍둥이 등) 수와 일치.
  → 주입 경로의 환율을 KRW=1로. 검증: currency='KRW' AND exchange_rate≠'1' 건수 0.

[N3 — 치명연관] 주입 정상행 NULL 마커: 주입행(~10,124)이 is_synthetic/is_mutated/ledger/
  line_number/user_persona 등에서 본 생성행과 다른 결측 패턴 → "주입행 식별자"가 됨.
  → 주입 정상행도 본 생성행과 동일 스키마/결측률로 채움(ledger '0L', is_synthetic/is_mutated
    본 생성 분포, line_number 정상 채번).
  검증: 주입행과 본 생성행의 컬럼별 결측률 차 ≤ 1%p.

[N4] sod_violation 플래그 미사용: 전부 false, 자기승인(created_by=approved_by) 8건도 false.
  → 자기승인 발생 시 sod_violation=true 설정(정상 데이터의 드문 통제 예외로 소량 유지).
  검증: 자기승인 행의 플래그 정합 100%, 전체 true 비율은 극소(<0.1%) 유지.

[N5] cost_center 이중 체계: 직원 마스터(CC-C00X-DEPT 18개) vs 저널(CC1000 등 240개) 완전 불일치.
  → 한 체계로 통일(저널 체계를 마스터에 등록하거나 저널이 마스터 체계 사용 — 기존 데이터 호환
    관점에서 결정하고 사유 기록). 검증: 저널 cost_center의 마스터 존재율 100%.

[N6] 연도 간 drift 부재: 2022/23/24 문서수 편차 1.2%, 계정 382개 완전 동일 — 거의 복제.
  → 연도별 자연 변화 주입: 거래량 성장/감소(예: 연 ±3~8%), 일부 거래처·계정 신규/소멸,
    금액 수준 drift. 합성 티 나는 동일성 제거. 검증: 연도별 문서수 편차 ≥3%, 연도별 계정
    집합이 완전 동일하지 않음(신규/소멸 존재).

[N7] timestamp 중복: 고유 timestamp 322,490개에 993k행(중복 100%, 최대 533행/초).
  → 초·분 단위 자연 분산(같은 초 대량 몰림 제거). 검증: 동일 timestamp 최대 중복 < 50행.

[N8] trading_partner V-* 28개 마스터 미등록(2,202행) → vendors.json 등록. 검증: 고아 0.

[N9 — 선택] 월말 집중 17.9%→현실 수준(20%+), 심야(22~06) 10.9%→감소, posting lag ±대칭 제거.
  여력 있으면 반영, 아니면 사유와 함께 보류 기록.

[N10 — 잔액·재무제표 (A구역 감사 발견)] TB↔JE 대사 단절: trial_balances.json 이 JE 와 어떤
  정의(월 차대합·월 net·YTD)로도 전수 일치하지 않음. 일부 P&L 계정은 월 단위와 근사(차이 수십만),
  이익잉여금(3200)엔 JE 와 무관한 거액(예: C002 2024FP1 6,785억 vs JE -3,311만) — TB 모듈이
  JE 와 독립 산출되는 구조적 결함.
  → TB 를 JE 집계 + 기초이월 + 마감분개 체계로 파생 생성하도록 수정(단일 진실 = JE).
  검증: 전 TB 라인이 "기초이월 + 당기 JE 누적" 과 1원 내 일치 (마감·이월 규칙 문서화).

[N11] 연도 이월 미구현: opening_balances.json 이 3레코드·48계정 더미 수준, TB FP1 과 42/48 불일치
  (최대 132억). → 2022 기초를 제대로 깔고, 2023/2024 기초 = 전년 기말(손익→RE 마감 포함) 이월.
  검증: 연도별 기초 = 전년 기말 전 계정 1원 내.

[N12] 보조원장 recon hollow: subledger_reconciliation.json 은 difference 0 이라 주장하나 실측
  AR 보조원장 합 232만 vs GL 1100 잔액 115억 (C001). recon 산출물이 실측 없이 0 을 기록.
  → AR/AP 보조원장을 GL 통제계정과 실제 대사되게 생성하고, recon 파일은 실측 difference 기록.
  검증: 보조원장 합 = GL 통제계정 잔액 (회사별), recon difference 실측치와 일치.

[STEP 1 회귀 — 깨지면 실패]
- 기존 v41 보존 항목 전부 유지: COA 확장 16계정+110010, delivery_date 22k, deliveries/
  customer_invoices sidecar 22k, 469100 정상쌍둥이 ≥300, 차대균형(balance_validation), TB·보조원장 대사.
- 검증: 기존 normal realism verifier + 감사 스크립트 재실행:
  uv run python tools/scripts/audit_amounts_tax.py (N1·N2 잔존 0 확인 — 경로를 v42로),
  audit_temporal.py(N6·N7), audit_masterdata.py(N4·N5·N8). 모두 해당 FAIL 해소.

═══════════════════════════════════════════════════════════════════════
STEP 2 — overlay 재실행 → r4l + r4l_seed1~5 (base v42 위)
═══════════════════════════════════════════════════════════════════════
구현: tools/datasynth/crates/datasynth-cli/src/phase2_scheme_overlay.rs (r4k 로직 유지)
산출: ..._phase2_fraud_<날짜>_v1_r4l + r4l_seed1~5
규모기준(reference): 기존 r4l_b (S13용)

[O1 — 치명] 부정 주입행 NULL 마커 동률화: r4k의 부정 660행이 is_synthetic/is_mutated/
  line_number IS NULL(정상은 채워짐) → recall 100% 분리기. 게이트 S2에 세 컬럼이 추가되어
  현재 r4k는 S2 FAIL.
  → 부정 행도 정상 분포대로 채움(is_synthetic/is_mutated 정상값 분포, line_number 정상 채번,
    ledger '0L' 등). truth 는 labels sidecar와 is_fraud/fraud_type 으로만 식별.
[O2] anomaly_type 기재: 현재 100% 결측 — fraud 행에 fraud_type 과 정합하는 anomaly_type 기재
  (is_anomaly=true 인 행). multi-class 평가 경로 확보.
[O3] r4k 로직 전부 유지: FS01 외부고객 반복·FS03 점증·FS05 3사원환·배정 해시·donor 상속·
  소액·규모·document_id 36자.

[STEP 2 완료 조건]
- 각 벌(r4l + seed1~5): uv run python tools/scripts/phase2_shortcut_gate.py <벌> <r4l_b>
  → exit 0 (14게이트 — S2에 is_synthetic/is_mutated/line_number 포함된 보강판)
- uv run python tools/scripts/verify_phase2_seed_diversity.py <r4l> <seed1..5> → exit 0
- uv run python tools/scripts/verify_phase2_regression.py <벌> <v42> 유지
- 주의: base 가 v42로 바뀌므로 S4(확장계정 쌍둥이)·S13(규모) 재확인. N6 연도 drift 가
  S13 비교(ref=r4l_b)와 충돌하면 안 됨 — scheme 누적규모는 유지.

═══════════════════════════════════════════════════════════════════════
STEP 3 — PHASE2 코드 방어선 (데이터와 독립적 이중 방어)
═══════════════════════════════════════════════════════════════════════
구현: src/preprocessing/constants.py (deny-list), src/preprocessing/phase2_plan.py 등

[P1 — 치명] deny-list 보강: LEAKAGE_DENY_COLUMNS(또는 SYNTHETIC_ONLY_COLUMNS)에
  is_synthetic, is_mutated 추가. is_fraud/is_anomaly/fraud_type/anomaly_type 라벨 격리 재확인.
  데이터(O1)를 고쳐도 코드 방어선은 별도로 필요(미래 데이터셋 변형 대비).
[P2] gl_account 타입: 정수 파싱되어 numeric z-score 처리되는 문제 — categorical(코드값) 강제
  (dtype str 캐스팅 또는 role 오버라이드). 계정코드는 크기가 의미 없음.
[P3 — 기록만] row matrix 금액 피처 전무(V6/V7 deny 정책)는 정책 결정이므로 변경하지 않되,
  docs/spec/PHASE2_INTERFACE_DESIGN.md 에 "r4l 기준 numeric 생존 컬럼 목록" 1줄 현행화.

[STEP 3 완료 조건]
- 단위테스트: deny-list에 두 컬럼 포함 + gl_account categorical 처리 확인 (pytest).
- r4l 로 phase2 전처리 1회 실행(스모크): KeyError 0, 입력 matrix에 is_synthetic/is_mutated 부재 확인.

═══════════════════════════════════════════════════════════════════════
[공통 금지·기록]
═══════════════════════════════════════════════════════════════════════
- 읽기 금지: docs/spec/DETECTION_RULES.md, dev/active/phase1-evasion-injection-spec.md (anti-fitting).
- hollow-PASS 금지: 게이트·감사 스크립트 임계 완화 금지. 빈 집합 PASS 금지.
- 매 회차 결과를 reports/ 와 docs/debugging.md 에 누적 기록. 실패본은 접미사 보존.
- 완료 후 docs/guide/users/18_DATASYNTH_DOMAIN_AUDIT.md 말미에 "수정 반영 완료(v42/r4l)" 1줄 추가.
