# 핸드오프 — PHASE2 datasynth 누출 제거 작업 (2026-06-13)

> 컴팩트 후 이 문서로 이어받는다. 끝 안 난 작업: ①전 컬럼 전수 누출 스캔 ②r4m 프롬프트 보강 ③r4m 실행.

## 0. 지금 당장 할 일 (TODO, 순서대로)

1. ~~전 컬럼 전수 누출 스캔~~ ✅ 완료(2026-06-14). `tools/scripts/audit_full_leak_scan.py` 작성.
   r4l_b+seed1 2벌 실행. 결과: `reports/phase2_full_leak_scan_r4l_b.md`.
   - 도구 자체 검증: 1차 19건 거짓양성(결측률차 단독) → precision/lift 가드 → 9건/6건.
   - 신규 누출 5종: L4 trading_partner 거래처집중(prec 48~54%), L5 부수필드(invoice/supply/
     auxiliary NULL·event조합), L6 original_document_id 채움(정상 역분개 부재), L7 라운드금액(약).
   - 공통뿌리: overlay가 부수필드를 정상과 다르게 채움/비움 → **도너 상속**으로 통합 처방.
2. ~~r4m 프롬프트 L4~ 추가~~ ✅ 완료. `phase2-fraud-r4m-prompt.md` 재작성: L4~L7 + base v43
   (정상 역분개 주입, 사용자 승인) + 도너상속(L1/L2/L5 통합) + 완료조건에 전수스캔 exit 0 추가.
   게이트 S18 개별추가 대신 **전수스캔 자체를 r4m 완료게이트로 상시화**(하드코딩 회피).
3. **다음**: r4m 프롬프트를 새 세션에 넣어 실행 → v43(역분개) + `r4m` + `r4m_seed1~5` 생성.

## 1. 최종 산출물 (현재 확정본)

- NORMAL base: `data/journal/primary/datasynth_semantic_v1_normal_20260613_v42j`
- PHASE2 fraud 대표본: `data/journal/primary/datasynth_semantic_v1_phase2_fraud_20260613_v1_r4l_b`
- 모의고사(시드회전 5벌): `..._r4l_b_seed1` ~ `..._r4l_b_seed5`
- ⚠ r4l_b 는 **누출 2건 잔존** → r4m 으로 교체 예정. 구버전(v41, r4f~r4k, r4l 비-b) 삭제 가능.

## 2. 이번에 발견한 누출 (r4m 에서 고칠 것) — 이미 r4m 프롬프트에 L1~L3 들어있음

PHASE1용 데이터에서 "부정을 구조 아닌 표시로 들키는 누출 4종"이 보고됐고(계정세부유형 OTHER,
라운드 금액, 시각 지문 10:05/14:05, 부정전용 플래그), PHASE2 r4l_b 에 동형이 있는지 측정한 결과:

- **L1 (S16, 치명)** sub_type 라벨 불일치: 같은 gl_account 인데 정상/부정이 다른
  semantic_account_subtype 어휘. 131100 정상 `intangible_assets` vs 부정 `intangible_development_cost`,
  116100 정상 `contract_assets`(복수) vs 부정 `contract_asset`(단수), `payroll_expense`·
  `prepaid_assets`·`long_term_contract_revenue` 부정전용. **PHASE2가 sub_type 을 ML 피처로 소비**.
- **L2 (S17)** 부정전용 세부계정 15개: 현금세부(100420/100460/100470/100780/100790),
  매출세부(400560~400790 등) — 정상 0줄. 부정이 세부코드 분산 시 정상 안 쓰는 계정 선택.
- **L3 (약함)** 라운드 금액 25,000,000·40,000,000 부정전용 6건(r4l_b 대표본만, seed 엔 없음).
- 시각 지문(분 단위)·'OTHER' sub_type = PHASE2 엔 **없음**(깨끗).

## 3. "왜 게이트가 못 찾았나" (근본 원인 — 전수 스캔 필요한 이유)

- 게이트 S2(단일피처)는 **선별된 컬럼 화이트리스트(S2_COLS)** 만 본다 — semantic_account_subtype 이
  목록에 없어서 sub_type 누출을 못 봄.
- S4(확장계정 쌍둥이)는 **확장 16계정 문서수** 만 검사 — 기존 세부계정(100420 등)·sub_type 라벨 미검사.
- S8(scheme계정정합)은 sub_type 을 **scheme 화이트리스트** 로만 봄 — "정상과 같은 어휘인가" 미검사.
- 세부계정은 계정당 부정 1~2건이라 S2 최소표본(5) 미달로 빠짐.
→ 교훈: 게이트가 "내가 의심한 컬럼"만 본다. 전 컬럼을 화이트리스트 없이 전수 스캔해야 미지의 누출을 잡음.

## 4. 전 컬럼 전수 스캔 — 만들어야 할 스크립트 설계

파일: `tools/scripts/audit_full_leak_scan.py` (인자: fraud_dataset_dir). r4l_b + seed1 양쪽 실행.
모든 컬럼(72개)에 대해 자동으로:
- **범주형/문자열 컬럼**: 값별 (부정전용=정상0&부정>0) 와 (precision≥25% & 부정≥5) 색출.
  대상: 모든 컬럼 — created_by, approved_by, source, user_persona, counterparty_type,
  semantic_account_subtype, debit/credit_account_subtype, line_text_family, scenario_id,
  event_type, batch_type, tax_treatment, supporting_doc_type, reversal_*, sod_*, cost_center,
  profit_center, currency, ledger, business_process, document_type, gl_account, trading_partner,
  auxiliary_account_label, header_text, line_text 등 전부.
- **(컬럼 IS NULL) 규칙**: 모든 컬럼에서 결측이 부정 식별자인지 (recall·precision).
- **수치형 컬럼**: 부정전용 반복값(정상0 & 부정≥3) — local_amount, debit/credit_amount,
  supply_amount, invoice_amount, tax_amount, exchange_rate, line_number, fiscal_period.
- **시각**: posting_date 의 시:분(HH:MM) 부정 집중 + 분(MM) 단독 집중.
- **결측률 표**: 전 컬럼 정상 vs 부정 결측률 차 > 5%p.
- **2-컬럼 조합**: 의미 있는 쌍 몇 개(이미 S11 이 일부 봄 — 거기 없는 새 쌍).
출력: 컬럼별 발견 + "신규 누출 후보" 목록. 이미 게이트가 잡는 것(S16 sub_type, S17 계정)은
"기지(known)"로 표기하고 **그 외 새로운 것**을 강조.

발견된 새 누출은 → r4m 프롬프트 L4~ 추가 + 게이트 S18~ 추가(부정전용=정상0 일반 규칙으로 통합 가능).

## 5. 도구·게이트 현황

- **게이트**: `tools/scripts/phase2_shortcut_gate.py <dataset> [reference]` — 현재 **17게이트**.
  R-COV/SELF/BAL/DIR(회귀4) + S1 메타결측 + S2 단일피처(prec/recall) + S4 확장계정쌍둥이 +
  S8 scheme계정정합 + S9 식별자형식 + S10 기말월말 + S11 조합분리 + S12 소액부정 + S13 규모보존(ref) +
  S14 구조신호floor(FS01외부고객·FS03점증·FS05원환) + S15 라벨인터페이스(anomaly_type) +
  **S16 sub_type라벨누출(신규)** + **S17 부정전용계정(신규)**. S7(라인수)은 폐기됨.
  ref(S13규모기준)는 이제 **r4l_b** (r4f_c 은퇴). r4l_b 검증 시 `<r4l_b> <r4l_b>` 로 호출(자기참조 규모 1.0).
  → r4m 부터는 ref 를 **r4l_b** 로 (r4m 규모가 r4l_b 와 같아야).
- **다양성**: `verify_phase2_seed_diversity.py <d1> <d2> ...` — 내용 차이≥50% + 배정 동일쌍 0.
- **회귀**: `verify_phase2_regression.py <fraud> <base>`.
- **심층(구)**: `verify_phase2_deep_shortcut*.py` (경로 하드코딩 일회성 — §4 새 스크립트로 대체).
- **도메인 감사**: `tools/scripts/audit_{amounts_tax,temporal,masterdata,balance_integrity}.py` (v42j 검증 통과).
- r4l_b 게이트 호출 예: `uv run python tools/scripts/phase2_shortcut_gate.py <r4l_b경로> <r4l_b경로>`

## 6. 전체 작업 맥락 (큰 그림)

PHASE2 datasynth = "현실 부정"이 woven 으로 주입된 감사 데이터. 카탈로그(SoT):
`dev/active/phase2-fraud-scheme-catalog.md` — 14 scheme(FS01~FS14), anti-fitting(룰 역설계 금지).
긴 여정에서 hollow-PASS 를 여러 번 적발하며 게이트를 키워왔다:
자기상쇄→상수하드코딩→메타shortcut→무관계정침입→가짜분할→ID/시스템필드/월말누수→조합누수→규모축소
→ 7구역 도메인감사(세금버그·NULL마커 등 12종, v42j 로 수정)→ **sub_type/세부계정 누출(지금, r4m 대기)**.
원칙: 검증 도구 자체도 검증 대상. 게이트가 못 본 차원을 계속 찾아 게이트에 박는다.

문서:
- 모의고사 전략: `docs/guide/users/17_PHASE2_MOCKEXAM_SEED_ROTATION.md`
- 도메인 감사: `docs/guide/users/18_DATASYNTH_DOMAIN_AUDIT.md`
- 검증 카탈로그(baseline): `dev/active/datasynth-journal-realism-rebuild/phase2-overlay-verification-catalog.md`
- 메모리: `project_phase2_fraud_datasynth.md`

## 7. anti-fitting 가드 (PHASE1/PHASE2 진행 시)

- PHASE2 datasynth 로 PHASE1 을 돌린 결과(탐지율 등)를 보고 **datasynth 를 거꾸로 고치지 말 것**.
  탐지 성능은 사후 관찰일 뿐 데이터 설계 입력이 아니다.
- 읽기 금지(데이터 설계 시): `docs/spec/DETECTION_RULES.md`, `dev/active/phase1-evasion-injection-spec.md`.

## 8. 다음 단계 (r4m 이후)

전수 스캔 + r4m 누출 제거 완료되면 → ①PHASE1 전수점검 끝난 뒤 ②r4m 으로 PHASE1 실행(현실부정
review-worthy 농축 관찰 + PHASE2 입력 생성) ③결과 보고 ④PHASE2 ML 구현(모의고사 seed 로 scheme별 탐지율).
