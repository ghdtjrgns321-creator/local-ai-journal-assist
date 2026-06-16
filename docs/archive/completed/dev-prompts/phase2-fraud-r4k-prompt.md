# r4k 수정 프롬프트 — 잔여 경미 3건 정리 (FS01 외부고객·FS03 점증·배정 셔플)

> r4i/r4j_seed 는 14게이트+다양성(내용) 통과했으나, 잔여 경미 3건을 게이트화하여 적발:
> ①FS01 가공매출 상대가 내부부서/계열사 ②FS03 점증 시계열 미구현 ③scheme→회사 배정이
> mod3 로테이션(3쌍 동일). S14 확장 + 다양성 게이트 v2(배정 검사) 반영됨. 새 세션에 전문.

[작업] 잔여 3건 수정 → 대표본 r4k + 시드 5벌 r4k_seed1~5 재생성.
base: data/journal/primary/datasynth_semantic_v1_normal_20260611_v41 (그대로)
직전: r4i, r4j_seed1~5 (전부 보강 게이트에서 FAIL — 재생성 대상)
규모기준(reference): data/journal/primary/datasynth_semantic_v1_phase2_fraud_20260611_v1_r4f_c
산출: data/journal/primary/datasynth_semantic_v1_phase2_fraud_20260611_v1_r4k
       + r4k_seed1 ~ r4k_seed5
구현: tools/datasynth/crates/datasynth-cli/src/phase2_scheme_overlay.rs

[완료 조건 — 셋 다 충족해야 종료]
1. 각 벌(r4k + seed1~5): uv run python tools/scripts/phase2_shortcut_gate.py <벌> <r4f_c>
   → exit 0 (14게이트, S14 확장판 포함)
2. 다양성 v2: uv run python tools/scripts/verify_phase2_seed_diversity.py <r4k> <seed1> ... <seed5>
   → exit 0 (내용 차이 ≥50% **그리고** 배정 동일 쌍 0)
3. 회귀: verify_phase2_regression.py <벌> <v41> 유지.
게이트·다양성 임계 변경 금지.

[결함 3건 — 실측]

D1 (S14) FS01 가공매출 상대가 내부/계열: fictitious_sale 의 trading_partner 에 DEPT-*(내부부서)·
  C001~C003(계열 코드)이 등장 (r4i 8건, seed2 9건 등). 가공매출 상대는 카탈로그 (d)대로
  **외부 가공 고객**(customers.json 정상 형식, C-* 외부처)이어야 회계 현실적.
  → 수정: FS01 fictitious_sale(및 fake_collection 등 매출·회수 체인)의 거래처를 외부 고객
    풀에서만 선정. donor 상속 시 거래처는 "외부 고객 거래의 donor"에서만 받기.
    반복 구조(한 고객 ≥3건, 소수 고객 집중)는 유지.

D2 (S14) FS03 점증 시계열 미구현: 인출(cash_withdrawal) 전반 1/3 평균 23.1M ≥ 후반 1/3 평균
  17.1M — "초기 소액 → 점증"(카탈로그 (d), 계양전기 패턴)과 반대.
  → 수정: 인출 금액을 시계열 점증으로 — 초기(2022) 소액(수십만~수백만), 후기(2024) 대액(수천만).
    판정선: 후반 1/3 평균 > 전반 1/3 평균 (S14 자동검사). 누적 규모는 S13(r4f_c 0.5~2배) 유지.
    소액 비율(S12 ≥5%)도 유지 — 초기 인출이 소액이므로 자연 충족.

D3 (다양성 v2) scheme→회사 배정 mod3 로테이션: r4i=seed3, seed1=seed4, seed2=seed5 의 배정
  벡터 동일(3쌍). 전체를 통째로 회전시키지 말고 **scheme별 독립 셔플**.
  → 수정: seed 가 각 scheme 의 회사 배정을 독립적으로 선택(조합 공간 3^N). 단 FS05 는 항상
    3사 원환(시작점만 회전), FS11 은 IC 구조 유지. 카탈로그 §4 분산 원칙(한 회사 과밀 금지) 유지.
    판정선: 다양성 v2 배정 동일 쌍 0.

[유지 — 건드리지 말 것]
- r4i/r4j 의 성과 전부: FS01 고객반복(≥3)·FS05 3사원환·donor 상속(조합누수 0)·소액 혼입·
  FS03 규모(S13)·document_id 36자·시스템필드·월말·reference 정상샘플링·seed 별 금액/일자 상이.
- base v41 무수정. 부정 밀도 0.1%·14 scheme 전수·prevalence 유지.

[검증 — 자동 루프]
1. 수정 → r4k + seed1~5 생성 → 각 벌 14게이트 + 회귀.
2. 다양성 v2 (6벌 전체).
3. 실패 시 FAIL 출력 읽고 재수정 반복(r4k_b, ...). 매 회차 reports/ + docs/debugging.md 누적.
4. 통과 후: 구 r4j_seed1~5 와 r4i 는 보존(이력) — 단 docs/debugging.md 에 "최종은 r4k 계열" 명시.

[금지]
- 게이트 통과용 회계 훼손 우회 금지. 다양성 임계·S14 floor 완화 금지.
- 점증을 만들려고 누적 규모(S13)나 소액(S12)을 깨기 금지 — 셋 동시 충족.
- detector 튜닝 금지. 한국어 보고.
