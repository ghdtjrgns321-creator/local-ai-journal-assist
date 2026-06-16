# r4g 수정 프롬프트 — 메타 조합 누수 제거 (S11) + 소액 부정 혼입 (S12)

> r4f_c 는 단일 컬럼 게이트 10개를 통과했으나, ①컬럼 조합에서 정상에 없는 셀 발견(S11 신설),
> ②부정 금액이 7~8자리에 98% 집중되어 소액 부정 실재 게이트(S12 신설)도 미달.
> 게이트가 12개로 보강됨. 새 세션에 전문 붙여넣기.

[작업] PHASE2 fraud overlay ①메타 조합 누수 제거 ②소액 부정 혼입 → r4g 생성.
base: data/journal/primary/datasynth_semantic_v1_normal_20260611_v41 (그대로)
직전: data/journal/primary/datasynth_semantic_v1_phase2_fraud_20260611_v1_r4f_c
산출: data/journal/primary/datasynth_semantic_v1_phase2_fraud_20260611_v1_r4g
구현: tools/datasynth/crates/datasynth-cli/src/phase2_scheme_overlay.rs

[완료 조건 — 유일한 종료 기준]
  uv run python tools/scripts/phase2_shortcut_gate.py <r4g 경로> → exit 0 (12게이트 ALL PASS)
  + uv run python tools/scripts/verify_phase2_regression.py <r4g 경로> <v41 경로> 회귀 유지.
게이트 임계·화이트리스트·S11 조합목록·S12 floor 변경 금지(완화는 사용자 승인).

[결함 — r4f_c 실측 (S11 FAIL)]
부정 메타필드를 각각 독립적으로 정상 marginal 분포에서 샘플링한 결과, **정상에 존재하지 않는
조합 셀**이 생겨 그 셀이 정밀 식별자가 됨 (정상 0건 + 부정만 존재 = precision 100%):
  source×user_persona      = recurring|junior_accountant [10/10], automated|junior_accountant [44/79]
  source×document_type     = manual|IC [11/11], recurring|IC [12/12]
  user_persona×document_type = automated_system|DR [13/13], senior_accountant|IC [28/28]
  counterparty_type×document_type = InternalDepartment|IC [22/22], Lender|DR [11/11]
→ 부정의 약 30%가 2컬럼 조합만으로 완전 식별 가능.

[수정 — donor 상속 방식 (독립 샘플링 금지)]
메타필드를 개별 샘플링하지 말고, **정상 동종 문서 1건을 donor 로 뽑아 메타 묶음을 통째로 상속**:
1. donor 선정: 부정 문서와 같은 (business_process, document_type, 거래방향/계정유형) 조건의
   정상 문서 풀에서 무작위 1건.
2. donor 에서 묶음 상속: source, user_persona(및 그 persona 와 일관된 created_by 선택),
   counterparty_type, ip_address 대역, batch 관련, supporting_doc_type, has_attachment,
   tax_treatment 등 — **조합이 항상 정상에 실재하는 조합**이 되도록.
3. scheme 본질 필드는 예외 유지: 금액·계정·시점(기말 등)·approved_by 분산 규칙(S2/S5)·
   SoD 위반 component(FS03 자기승인 등)는 scheme 설계 우선. 단 그 결과 조합도 정상에
   같은 조합이 존재해야 함(예: 자기승인 조합은 정상 SoD 위반 문서에도 존재).
4. 분산 요건과의 양립: donor 를 매 문서 다른 정상 문서에서 뽑으면 승인자/작성자 분산(S2)은
   자동 충족 — 한 명에 몰리지 않음.

[결함 2 — 소액 부정 부재 (S12 FAIL: 소액 라인 2.1% < floor 5%)]
부정 금액이 7~8자리(천만~억)에 98% 집중, 1백만 미만 소액은 660라인 중 14라인(2.1%)뿐.
현실 부정엔 소액 구성요소가 실재하며 카탈로그에도 이미 명시돼 있다:
  - FS03 횡령: "금액: 초기 소액 → 점증 (실제 사례 공통 패턴)" — 카탈로그 (d). 계양전기도
    소액 인출로 시작해 195회 점증.
  - FS03 (c): "승인 한도 이하로 쪼개기" — 한도 회피 분할 인출.
  - FS04 횡령은폐: "서서히 소각 — 분기마다 소액 비용화 (차. OPEX / 대. 선급)" — 카탈로그 (c)4.
  - FS14 유령직원: 월 급여는 정상 급여 수준(수백만 원, 6~7자리)이어야 자연.
→ 수정: 위 카탈로그 메커니즘을 충실 구현해 소액 라인이 자연 발생하게 한다.
  ① FS03 인출을 점증 시계열로(초기 수십만~수백만 → 후기 수천만), 일부 한도회피 분할.
  ② FS04 gradual_expense_writeoff 를 분기별 소액(수십만~수백만) 다건으로.
  ③ FS14 월 급여를 정상 급여 분포(employees 급여 수준)에서.
  ④ 다른 scheme 의 금액은 손대지 않는다(중요성 있는 규모가 정당 — FS01 가공매출이 소액일 이유 없음).
판정선(S12): 부정 라인 중 1백만 미만 비율 ≥ 5% + 어떤 자릿수 셀도 precision<25%.
★ 금지: 자릿수 분포를 맞추려고 scheme 메커니즘과 무관한 금액을 인위 축소(그건 fitting).
  소액은 반드시 위 ①~③의 회계 메커니즘에서 자연히 나와야 한다. instance 합계 금액(경제효과
  방향·부작위 파생값)은 의미 있게 유지 — 건수로 쪼개되 누적 규모는 보존.

[유지 — 건드리지 말 것]
- r4f_c 까지의 성과: document_id 36자, event_type/exchange_rate/ip_address 채움, 월말 실재,
  메타결측률, 계정 세부코드 분산(S8), 자연 단순분개, 경제효과, 부작위 금액 파생, flow 멤버십.
- base v41 무수정. 14 scheme 전수 유지. 문서수는 소액 분할로 330에서 증가 가능(자연) —
  단 prevalence 합계 가이드(전체 0.25% 이내) 준수, 라벨·provenance 정합 유지.

[검증 — 자동 루프]
1. 수정 → r4g 생성 → 게이트 12개. exit 0 아니면 FAIL 읽고 재수정 (r4g_b, ...).
2. 회귀 스크립트 동반. 회계 내용 깨지면 롤백.
3. 심층 스캔(tools/scripts/verify_phase2_deep_shortcut*.py 경로 교체)으로 조합·시간·금액 재확인.
4. 매 회차 reports/ + docs/debugging.md 누적 기록.

[금지]
- 게이트 통과를 위한 회계 훼손 우회 금지(무관계정·가짜분할·식별자 변형 재발 금지).
- 새 메타 조합 발명 금지 — 조합은 반드시 정상 데이터에 실재하는 것만.
- detector 성능으로 주입 튜닝 금지. 한국어 보고.
