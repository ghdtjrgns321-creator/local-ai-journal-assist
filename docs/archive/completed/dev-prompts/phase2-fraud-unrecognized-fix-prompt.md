# r3f unrecognized_amount 상수 하드코딩 수정 프롬프트

> r3f 작위 데이터는 정상 — 재생성 불요. 부작위 메타 금액 산출만 고쳐 r3g 산출.
> 새 세션에 전문 붙여넣기.

[작업] PHASE2 fraud overlay 의 부작위 미인식 금액(unrecognized_amount_krw)이 상수로 박혀 있어
각 scheme 의 실제 작위 거래 규모에서 파생되도록 수정.
구현: tools/datasynth/crates/datasynth-cli/src/phase2_scheme_overlay.rs
base: data/journal/primary/datasynth_semantic_v1_normal_20260611_v33 (그대로)
산출: data/journal/primary/datasynth_semantic_v1_phase2_fraud_<날짜>_v1_r3g

[결함 — 독립 재검증으로 확정]
r3f 의 labels/phase2_scheme_truth.csv 에서 부작위형 3개 scheme 의 unrecognized_amount_krw 가
**셋 다 정확히 148,750,000 동일**:
  FS10(대손충당금 과소) = 148,750,000
  FS12(충당부채 미인식) = 148,750,000
  FS13(투자손상 미인식) = 148,750,000
서로 다른 거래(부실 AR / 소송·보증 의무 / 부실 투자자산)인데 금액이 같을 수 없다.
CLAUDE.md §3 위반(계산 구동값을 리터럴로 박지 말 것). r1e 때 FS12 값이 FS10/FS13 에 복사된 것.

[수정 — instance 작위 금액에서 파생]
각 scheme 의 unrecognized_amount_krw 를 그 instance 가 실제로 만든 작위 분개 금액에서 계산한다.
상수·매직넘버 금지. 파생 근거(카탈로그 (b)~(d) 기준):

- FS10 (대손 회피): 미인식 대손 = 위장·차환된 부실 채권 모집단 규모.
  파생: 해당 instance 의 `fake_collection_refinance` + `receivable_reclass` component 가 다룬
  AR/loans_receivable 금액 합계 × 적정 대손율(예: 카탈로그·설정에서 받는 비율, 리터럴 금지).
  즉 "정상이라면 인식했어야 할 충당금"을 부실 채권 규모에서 산출.

- FS13 (투자손상 미인식): 미인식 손상 = 손상 처리하지 않은 투자자산 규모.
  파생: 해당 instance 의 `investment_acquisition` + `propping_injection` 으로 쌓인 investments
  순증액 기반(부실 비율 적용). r3f 기준 investments 순증 ≈ 77,342,601 → 이 규모에서 파생.

- FS12 (충당부채 미인식): 미인식 충당부채 = 컨텍스트가 시사하는 의무 추정액.
  파생: 해당 instance 의 `litigation_context_fees` + `guarantee_fee_flow` 금액 합계 기반
  추정(수수료 대비 충당부채 배수 — 배수도 설정/카탈로그에서, 리터럴 금지).

세부 비율·배수는 코드 상수로 박지 말고 config/카탈로그 파라미터로 외부화하거나, 최소한
"instance 작위 금액에 비례"하는 함수로 구현(서로 다른 instance·scheme 이면 값이 달라야 함).

[유지 — 건드리지 말 것]
- 작위 분개·flow·라벨·component_role·reversal 링크·경제효과는 r3f 그대로(검증 통과분).
- 이번 변경은 truth.csv 의 unrecognized_amount_krw 산출 한 곳으로 국한.
- evaluation_stratum=low_trace 유지. base 무수정. 14 scheme 전수·분산 유지.

[검증]
- F1. FS10/FS12/FS13 unrecognized_amount_krw 가 **서로 다른 값**이고 각각 해당 instance 의
  작위 금액(위 파생 근거)에 비례. 148,750,000 같은 동일 상수 0건.
- F2. 값이 0 또는 음수 아님(부작위 금액 > 0). 작위 금액 바뀌면 미인식 금액도 따라 바뀜(2케이스:
  서로 다른 두 instance/scheme 에서 값이 다름 확인 = ripple).
- F3. 회귀: tools/scripts/verify_phase2_r3f.py 경로를 r3g 로 교체 재실행 →
  자기상쇄0·14scheme전수·role일치·균형0·base무수정·불변량·라벨정합 전부 유지.
- F4. 작위 금액(현금·계정 순효과)은 r3f 와 동일(이번 변경이 분개를 안 건드림).

리포트: <출력경로>/reports/ 저장. 완료 후 docs/debugging.md 갱신.

[금지]
- 검증 실패 상태 완료 선언 금지. 새 상수/매직넘버로 교체 금지(또 다른 하드코딩).
- 작위 분개·다른 scheme 건드리기 금지(범위 = unrecognized_amount 산출).
- detector 성능으로 주입 수정 금지. 한국어 보고.
