# r4m 수정 프롬프트 — 부수필드 도너상속 + 거래처분산 + 정상 역분개 주입

> 배경: r4l_b 전 컬럼 전수 누출 스캔(tools/scripts/audit_full_leak_scan.py, 71컬럼)에서
> 게이트 17개가 못 본 누출 5종(+기지 sub_type)을 색출. 2벌(대표본·seed1) 재현 확인.
> 공통 뿌리: overlay가 부정 분개의 **부수 필드**(금액·계정·증빙·sub_type)를 정상 생성기와
> 다른 규칙으로 채움/비움 → "부수필드 비정상=부정"이 성립. 처방: 도너 상속.
> 새 세션에 전문 붙여넣기. base 는 L6(역분개) 한정 수정 → v43, 그 외 overlay만.

[작업] r4l_b 의 누출 제거 → r4m + r4m_seed1~5. base: v42j → **v43**(역분개 추가).
직전(누출 잔존): data/journal/primary/datasynth_semantic_v1_phase2_fraud_20260613_v1_r4l_b
산출 base: data/journal/primary/datasynth_semantic_v1_normal_<날짜>_v43
산출 fraud: data/journal/primary/datasynth_semantic_v1_phase2_fraud_<날짜>_v1_r4m + r4m_seed1~5
구현: tools/datasynth/crates/datasynth-cli/src/ (normal 생성기 + phase2_scheme_overlay.rs)

[완료 조건] (각 벌 전부 exit 0)
- 전수 누출 스캔: uv run python tools/scripts/audit_full_leak_scan.py <벌> → exit 0 (신규 누출 0)
- shortcut 게이트: uv run python tools/scripts/phase2_shortcut_gate.py <벌> <r4m대표본> → exit 0 (17게이트)
- 다양성: uv run python tools/scripts/verify_phase2_seed_diversity.py <r4m> <seed1..5> → exit 0
- 회귀: uv run python tools/scripts/verify_phase2_regression.py <벌> <v43> 유지
- 도메인 감사: audit_{amounts_tax,temporal,masterdata,balance_integrity}.py v43 통과 유지
게이트 임계·화이트리스트 변경은 아래 [지정 변경] 외 금지.

──────────────────────────────────────────────────────────────────
[결함 — r4l_b 실측, 2벌 재현]

■ 공통 처방(도너 상속): 부정 분개를 **정상 분개를 도너로 삼아** 생성한다.
  부정의 본질(금액 조작·계정 선택·기간)만 변형하고, 나머지 **부수 필드는 도너(정상)
  값 그대로 상속**한다. 대상 부수필드 = semantic/debit/credit_account_subtype,
  invoice_amount, supply_amount, tax_code, tax_amount, auxiliary_account_number,
  auxiliary_account_label, event_type, supporting_doc_type, cost_center, profit_center.
  → 이 하나로 L1·L2·L5 가 동시 해결된다.

L1 (S16) sub_type 라벨 불일치: 같은 gl_account 인데 정상/부정이 다른 sub_type 어휘.
  131100 정상 'intangible_assets'(374) vs 부정 'intangible_development_cost'(10);
  116100 정상 'contract_assets'(345) vs 부정 'contract_asset'(16, 단복수);
  'payroll_expense'·'prepaid_assets'·'long_term_contract_revenue' 부정전용.
  → 도너 상속으로 gl_account 의 정상 sub_type 어휘를 그대로 사용. debit/credit_subtype 동일.
  판정선: S16 = 부정전용(정상0) sub_type 값 0건.

L2 (S17) 부정전용 세부계정 15개: 현금세부 100420/100460/100470/100780/100790,
  매출세부 400560~400790 등 정상 0줄. → 부정 gl_account 를 **정상에 라인이 존재하는
  세부계정 풀**에서만 선택. 세부코드 분산은 유지하되 정상 쌍둥이 있는 코드로.
  판정선: S17 = 부정전용 gl_account 0개.

L4 (신규) trading_partner 거래처 집중: 단일 거래처 V-000001 에 부정 14~17% 집중
  (precision 48~54%). vendor/IC scheme 이 동일 거래처를 반복 사용.
  → 부정 거래처를 **정상 거래처 마스터 풀에서 분산** 선택(scheme 인스턴스마다 다른
  거래처). 동일 거래처 부정 precision 이 정상 분포 대비 튀지 않게.
  판정선: 전수스캔 [1] 에서 trading_partner 단일값 precision ≥25%(부정≥5) 0건.

L5 (신규, 부수필드 — 도너상속으로 해결) 부정 분개의 부수필드가 정상과 다른 NULL/조합:
  - invoice_amount·supply_amount 부정 100% NULL(정상 98% 채움) → lift 57.
  - auxiliary_account_number 부정 100% NULL(정상 84% 채움) → lift 6.
  - event_type×supporting_doc_type 부정전용 조합((R2R_ACCRUAL_ADJUSTMENT,세금계산서) 등).
  → 도너 상속: 송장 있는 거래면 정상처럼 invoice/supply_amount 채움, 보조계정·증빙·
  event_type 도 도너 값 사용. 정상이 안 쓰는 event_type/증빙 조합을 부정이 신설하지 않음.
  판정선: 전수스캔 [2]/[6] 에서 해당 컬럼·조합 신규 누출 0건.

L6 (신규, base 수정 — 사용자 승인 2026-06-14) 정상 역분개 부재:
  부정 역분개가 original_document_id 를 채우는데 **정상 base(v42j)엔 역분개가 거의 없어**
  (정상 not-null 396 vs 부정 108) original_document_id 채움 precision 35%(lift 531).
  → **v43 = v42j + 정상 역분개 소량 주입**. 정상 회사도 오기입 정정·기간귀속 정정으로
  취소전표(역분개)를 낸다. 정상 역분개를 현실적 빈도(예: 전표의 0.3~1%)로 생성하고
  original_document_id/reversal_document_id/reversal_type/reversal_reason_code 를
  정상 규칙대로 채운다. 그러면 "역분개 메타가 채워짐=부정"이 깨진다.
  판정선: 전수스캔 [2] 에서 original_document_id·reversal_* 신규 누출 0건.
  ★ 단, 역분개 주입이 R-SELF(자기상쇄)·R-BAL(균형) 회귀를 깨지 않게(정상 역분개는
    별도 취소전표로, 동일전표 차대변 동시 상쇄 금지 — r1e 결함 재발 방지).

L7 (약함) 라운드금액 부정전용: 대표본 25,000,000·40,000,000·2,490,000 부정전용 3~6건
  (seed엔 없음). 여력 시 FS 금액에 자연 단수(끝자리 비0) 부여. 강제 아님.

──────────────────────────────────────────────────────────────────
[지정 변경 — 허용]
- S8(scheme계정정합) 화이트리스트: 부정어휘(contract_asset, intangible_development_cost
  등)로 돼 있으면 정상어휘(contract_assets, intangible_assets ...)로 동시 갱신.
  (S8·S16 이 같은 정상어휘 기준이 되도록.)
- v43 도메인 감사 baseline(reports/) 갱신.

[유지 — 건드리지 말 것]
- r4l_b 의 성과 전부: NULL마커 동률·anomaly_type·document_id 36자·FS01 외부고객반복·
  FS03 점증·FS05 3사원환·donor 상속·소액·규모·seed 다양성.
- v42j 의 정상 분개 회계 구조: L6 역분개 주입 외 **무수정**. 14 scheme 전수·부정 밀도 0.1%.
- sub_type/부수필드를 정상값으로 상속해도 회계 구조(어느 계정에 무슨 분개)는 동일 —
  라벨·부수표기만 정상과 동기화.

[검증 — 자동 루프]
1. v42j → v43(역분개 주입) 생성. overlay 도너상속 + 거래처분산 적용 → r4m + seed1~5.
2. 각 벌: 전수스캔 + 17게이트 + 회귀 + 다양성 + 도메인감사. exit 0 아니면 FAIL 읽고 재수정.
3. 심층 재측정: 정상/부정 sub_type 집합 일치, 부정 gl_account ⊆ 정상, 부수필드 NULL률
   정상≈부정, trading_partner precision 정상범위, 역분개 메타 정상·부정 양측 존재.
4. 매 회차 reports/ + docs/debugging.md 누적. 통과 후 catalog/users18/검증카탈로그
   baseline 을 v43/r4m 으로 갱신.

[금지]
- 게이트·전수스캔 통과용 회계 훼손 우회 금지. 부수필드를 정상과 다르게 두는 것 금지.
- S16/S17/전수스캔 임계 완화 금지. detector 튜닝 금지(anti-fitting). 한국어 보고.
- 역분개 주입 시 정상 역분개를 부정과 구분되는 표식으로 채우지 말 것(그 자체가 새 누출).
