# r4f 수정 프롬프트 — 심층 스캔 발견 shortcut 3종 제거

> r4e 는 기존 게이트 8개를 통과했으나, 심층 스캔에서 신규 shortcut 이 발견되어 게이트가
> 10개로 보강됨(S2 확장 + S9 식별자형식 + S10 기말월말실재). 새 세션에 전문 붙여넣기.

[작업] PHASE2 fraud overlay 의 신규 발견 shortcut 제거 → r4f 생성.
base: data/journal/primary/datasynth_semantic_v1_normal_20260611_v36 (그대로)
직전: data/journal/primary/datasynth_semantic_v1_phase2_fraud_20260611_v1_r4e
산출: data/journal/primary/datasynth_semantic_v1_phase2_fraud_20260611_v1_r4f
구현: tools/datasynth/crates/datasynth-cli/src/phase2_scheme_overlay.rs

[완료 조건 — 유일한 종료 기준]
  uv run python tools/scripts/phase2_shortcut_gate.py <r4f 경로> → exit 0 (10게이트 ALL PASS)
  + uv run python tools/scripts/verify_phase2_regression.py <r4f 경로> <v36 경로> 회귀 유지.
게이트 임계·화이트리스트 변경 금지. 회계 구조 훼손 우회 금지(r4b 무관계정·r4d 가짜분할 재발 금지).

[결함과 수정 — r4e 실측]

D1 (S9, 치명) document_id 길이 누수: 부정 330개 전부 37자(36자 UUID 뒤에 'e' 접미),
   정상은 전부 36자 → 길이 하나로 precision/recall 100% 완전 분리.
   예: 부정 '91b739fc-8397-4539-9e53-ac0428c05370e' vs 정상 '9c8c87c4-9409-4ed9-ad11-015a89f0faa0'
   → 수정: 부정 document_id 를 정상과 동일한 36자 UUID 형식으로 생성(접미 제거). 기존 원칙
     "식별자는 정상과 같은 generator 경유"의 위반 — generator 를 실제로 공유하게.
   ※ ripple: document_id 변경 시 labels/provenance·truth 의 member_document_ids, reversal/
     original_document_id 링크, flow sidecar 의 journal_entry_id 참조도 전부 새 ID 로 정합.

D2 (S2) 시스템 필드 NULL 누수: 부정 330개 전부 event_type·exchange_rate·ip_address 가 NULL.
   - event_type: NULL 전체 438 중 부정 330 (precision 75%). 정상은 99.97% 채움.
   - exchange_rate: 정상 KRW 거래는 '1' → 부정도 동일하게 채움.
   - ip_address: 정상 사내 IP 풀(10.x) 분포에서 샘플.
   - event_type: 정상 동종 거래의 event_type 값(O2C_CUSTOMER_INVOICE 등 scenario 계열)을
     business_process·거래유형에 맞게 채움. semantic_scenario_id/scenario_id 와 정합.
   판정선: 각 필드의 (IS NULL) 규칙이 precision<25% AND (recall<25% OR lift<5).

D3 (S10, 회계정합) 기말조작 scheme 의 월말 부재: 부정 330개 중 28일 이후 분개 0건.
   카탈로그 (c)상 기말 직전이어야 하는 FS02(분기말 수정분개)·FS06(기말 D-5~D0 부채 제거)·
   FS07(기말 직전 재고 부풀리기)·FS09(12월 마지막 주 매출)조차 월말 0 — scheme 메커니즘 위반.
   → 수정: FS02/06/07/09 의 기말 component 를 실제 월말(28~31일·해당 기말월)에 배치.
     다른 scheme 도 posting_date 일자 분포가 정상(월말 ~20%)을 따르게 — 월말 회피 금지.
   판정선: S10 = FS02/06/07/09 각각 월말(28+) 문서 ≥1. (선택) 전체 부정의 월말 비율이
     정상과 큰 차이 없게.

D4 (S2, 경미) line_text_family='RAW_MATERIAL_PURCHASE' 부정 집중(recall 28%, lift 10x):
   부정 P2P 문서의 line_text_family 를 정상 P2P 분포에서 다양화.

[유지 — 건드리지 말 것]
- r4e 까지의 성과 전부: 메타필드/승인자/counterparty/기간 분산, 계정 세부코드 분산(S8 정합),
  자연 단순분개(가짜 분할 금지), 경제효과 방향, 부작위 금액 instance 파생, flow sidecar 멤버십.
- base v36 무수정. 14 scheme 전수·문서수(330)·prevalence 유지.

[검증 — 자동 루프]
1. 수정 → r4f 생성 → 게이트 10개 실행. exit 0 아니면 FAIL 읽고 재수정 반복(r4f-b, ...).
2. 회귀 스크립트 동반 실행 — 회계 내용 깨지면 즉시 롤백.
3. D1 ripple 확인: 라벨↔전표 정합 0/0/0, reversal 링크, flow 멤버십이 새 ID 로도 유지.
4. 매 회차 결과를 reports/ 와 docs/debugging.md 에 누적 기록.

[금지]
- 게이트 임계 완화·화이트리스트 임의 수정 금지. 빈 집합/fallback PASS 금지.
- 회계 구조·메커니즘 훼손 금지. detector 성능으로 주입 튜닝 금지. 한국어 보고.
