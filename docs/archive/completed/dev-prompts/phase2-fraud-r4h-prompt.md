# r4h 수정 프롬프트 — FS03 횡령 규모 복원 (S13)

> r4g 는 12게이트 + 심층스캔 전부 통과(shortcut 완결)했으나, 소액 혼입 과정에서 FS03 횡령
> 누적 규모를 보존하지 않고 1/5 로 축소함. 규모보존 게이트 S13 추가(총 13게이트). 새 세션에 전문.

[작업] PHASE2 fraud overlay 의 FS03 횡령 누적 규모 복원 → r4h 생성.
base: data/journal/primary/datasynth_semantic_v1_normal_20260611_v41 (그대로)
직전: data/journal/primary/datasynth_semantic_v1_phase2_fraud_20260611_v1_r4g
규모기준(reference): data/journal/primary/datasynth_semantic_v1_phase2_fraud_20260611_v1_r4f_c
산출: data/journal/primary/datasynth_semantic_v1_phase2_fraud_20260611_v1_r4h
구현: tools/datasynth/crates/datasynth-cli/src/phase2_scheme_overlay.rs

[완료 조건 — 유일한 종료 기준]
  uv run python tools/scripts/phase2_shortcut_gate.py <r4h 경로> <r4f_c 경로> → exit 0 (13게이트 ALL PASS)
   ※ 두 번째 인자(reference)는 S13 규모비교용 — r4f_c 고정.
  + uv run python tools/scripts/verify_phase2_regression.py <r4h 경로> <v41 경로> 회귀 유지.
게이트 임계·화이트리스트·S13 제외목록 변경 금지(완화는 사용자 승인).

[결함 — r4g 실측 (S13 FAIL)]
소액 혼입 시 FS03 횡령 전체 금액을 축소 → 누적 현금유출 r4f_c 585M(총 debit 기준) → r4g 127M
(0.22배). 횡령이 6천만대로 비현실적으로 작아짐. 프롬프트 "쪼개되 누적 보존"을 어김.
※ FS14(유령직원)는 r4g 가 오히려 현실적(월급 280만, r4f_c 는 1,300만으로 비현실) → S13 제외,
  복원하지 말 것.

[수정 — FS03 규모 복원 + 소액 점증 유지]
FS03 누적 인출 규모를 r4f_c 수준(총 debit 0.5~2배 내, 즉 ~3.5억 현금유출대)으로 복원하되,
카탈로그 (d) "초기 소액 → 점증" 시계열은 유지한다:
  - 초기(2022) 인출은 소액(수십만~수백만)으로 시작 → 후기(2024) 인출은 큰 금액(수천만)으로 점증.
  - 즉 "건수를 늘리거나 후기 금액을 키워" 누적을 복원 — 전체를 일률 축소하지 말 것.
  - 일부 한도회피 분할(소액 다건)도 유지 → S12(소액 ≥5%) 동시 충족.
  - cash_withdrawal·balance_patching·recon_item_fabrication·temporary_return 의 회계 구조·방향·
    은닉처(단기투자/가지급금) 는 r4g 그대로. 금액 스케일만 복원.
판정선: S13 = FS03 총 debit 이 r4f_c 의 0.5~2배. + S12 소액 비율 ≥5% 유지.

[유지 — 건드리지 말 것]
- r4g 의 성과 전부: donor 상속(조합 누수 0), 소액 혼입(FS04/FS14 등), document_id 36자,
  시스템필드 채움, 월말 실재, S8 계정정합, 자연 단순분개, 경제효과 방향, 부작위 금액 파생.
- FS14 급여는 r4g 유지(복원 금지). 다른 scheme 규모도 r4g 유지(S13 통과 상태).
- base v41 무수정. 14 scheme 전수·prevalence 유지.

[검증 — 자동 루프]
1. 수정 → r4h 생성 → 게이트 13개(ref=r4f_c). exit 0 아니면 FAIL 읽고 재수정 (r4h_b, ...).
2. 회귀 스크립트 동반. 회계 내용 깨지면 롤백.
3. 심층 스캔(verify_phase2_deep_shortcut*.py 경로 교체) — FS03 규모 키워도 조합·금액 shortcut 0 유지.
4. 매 회차 reports/ + docs/debugging.md 누적 기록.

[금지]
- 게이트 통과를 위한 회계 훼손 우회 금지. FS03 외 scheme 금액 임의 변경 금지.
- 소액(S12)을 포기하고 규모만 키우기 금지 — 점증 시계열로 둘 다 충족.
- detector 성능으로 주입 튜닝 금지. 한국어 보고.
