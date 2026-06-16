# r4j 수정 프롬프트 — 시드 회전이 가짜(복사본) → 진짜 RNG 회전으로

> r4i 의 STEP 1(FS01 고객반복·FS05 3사원환 복원)은 검증 통과. 그러나 STEP 2 시드 회전이
> **가짜**로 판명: r4i·seed1~5 여섯 벌의 부정 내용(scheme·role·금액·일자·계정)이 전 쌍 차이
> 0행 = 완전 동일 복사본. 회사 배정만 주기 3으로 로테이션(r4i=seed3, seed1=seed4, seed2=seed5)
> 했고 금액·시점·고객 RNG 에 seed 가 전혀 반영되지 않음. 새 세션에 전문 붙여넣기.

[작업] seed 가 부정 생성 RNG 전체에 반영되게 수정 → 진짜 서로 다른 사례 N벌 재생성.
base: data/journal/primary/datasynth_semantic_v1_normal_20260611_v41 (그대로)
유지: data/journal/primary/datasynth_semantic_v1_phase2_fraud_20260611_v1_r4i (대표본 — 재생성 불요)
산출: data/journal/primary/datasynth_semantic_v1_phase2_fraud_20260611_v1_r4j_seed1 ~ seed5
구현: tools/datasynth/crates/datasynth-cli/src/phase2_scheme_overlay.rs

[완료 조건 — 둘 다 충족해야 종료]
1. 각 seed 벌: uv run python tools/scripts/phase2_shortcut_gate.py <seedN> <r4f_c> → exit 0 (14게이트)
2. 다양성: uv run python tools/scripts/verify_phase2_seed_diversity.py <r4i> <seed1> ... <seed5>
   → exit 0 (전 쌍에서 부정 내용 차이 비율 ≥50%)
다양성 게이트 임계(TH_MIN_DIFF_RATIO) 변경 금지.

[결함 — 실측]
- 6벌 전 15쌍: (scheme_id, component_role, local_amount, posting_date, gl_account) 멀티셋
  차이 0행. FS01 누적 금액 644.0M 이 6벌 모두 동일.
- 원인: seed offset 이 회사 배정 로테이션(mod 3)에만 쓰이고, 금액·시점·고객·문서 배치 RNG 에
  주입되지 않음. "같은 문제지를 표지만 바꿔 6부 복사" — 모의고사 표본 가치 0.

[수정]
- overlay 의 **모든 확률적 선택**에 seed 를 주입: 금액 샘플링, posting/document 일자, 고객·
  거래처 선정(FS01 가공고객, FS05 원환 시작점), scheme 의 회사 배정, 점증 시계열 패턴,
  donor 선택, 소액 분할 위치 등. ChaCha8 등 기존 deterministic RNG 에 seed 를 시드로.
- 같은 seed → 같은 출력(재현성)은 유지하되, 다른 seed → 금액·일자·고객·배치가 실질적으로
  다른 사례(쌍별 내용 차이 ≥50%)가 되어야 한다.
- 부정 밀도(0.1%)·scheme 구성(14종)·prevalence·회계 메커니즘은 seed 와 무관하게 동일 유지.
- 각 seed 도 S14(FS01 한고객≥3건·FS05 회사≥3) 등 14게이트를 통과해야 함 — 다양화가 구조신호를
  깨면 안 됨.

[유지 — 건드리지 말 것]
- r4i 대표본은 그대로 둔다(재생성 불요 — 14게이트 통과 확정본).
- r4i 에서 통과한 로직 전부: FS01 반복·FS05 원환·donor 상속·소액·규모·reference 정상샘플링.
- base v41 무수정.

[검증 — 자동 루프]
1. 수정 → seed1~5 재생성 → 각 벌 14게이트 + 회귀(verify_phase2_regression.py <seedN> <v41>).
2. verify_phase2_seed_diversity.py 로 6벌(r4i 포함) 전 쌍 다양성 확인.
3. 실패 시 FAIL 출력 읽고 재수정 반복. 기존 가짜 seed 벌(r4i_seed1~5)은 r4j 통과 후
   _failed_identical 로 표기 보존하거나 사용자 확인 후 정리.
4. 매 회차 reports/ + docs/debugging.md 누적 기록.

[금지]
- 다양성을 만들려고 부정 밀도·scheme 수·회계 구조를 바꾸기 금지(배치·금액·시점·고객만 달라짐).
- 게이트/다양성 임계 완화 금지. detector 튜닝 금지. 한국어 보고.
