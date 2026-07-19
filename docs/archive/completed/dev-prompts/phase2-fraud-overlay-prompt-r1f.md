# PHASE2 fraud overlay 재생성 프롬프트 (r1f — r1e 결함 수정)

> 새 세션에 아래 전문을 붙여넣어 사용.

[작업] PHASE2 woven fraud overlay 재생성. 직전 산출 r1e 의 회계 실질 결함 3건을 수정한다.
Base: data/journal/primary/datasynth_semantic_v1_normal_20260610_v31c (확정 normal)
직전(결함): data/journal/primary/datasynth_semantic_v1_phase2_fraud_20260610_v1_r1e
산출: data/journal/primary/datasynth_semantic_v1_phase2_fraud_<날짜>_v1_r1f
구현: tools/datasynth/crates/datasynth-cli/src/phase2_scheme_overlay.rs (기존 profile 수정)

[SoT — 반드시 먼저 읽을 것]
dev/active/phase2-fraud-scheme-catalog.md (FS01~FS14). 각 scheme의 (b)회계 메커니즘·
(c)다문서 구성·(d)component_role/시그니처·(e)anti-shortcut·(f)prevalence 를 그대로 구현.

[★ 절대 원칙 — ANTI-FITTING]
- 읽지 말 것: docs/spec/DETECTION_RULES.md, dev/active/phase1-evasion-injection-spec.md.
- detector 를 돌려 주입을 맞추는 루프 금지. 부정의 형태는 오직 카탈로그에서만 나온다.

────────────────────────────────────────────────────────────────────────
[수정 대상 결함 — r1e 독립 재검증에서 확정]
────────────────────────────────────────────────────────────────────────

결함 1 (치명) — 자기상쇄 분개 ~1/3
  전 scheme 의 부정 문서 33~36% 가 "같은 gl_account 에 차변과 대변을 동일/유사 금액으로 동시"
  보유 → 경제 실질 0. 예: FS09 한 문서가 매출(4000) 차변 46,420,403 / 매출(4000) 대변 46,420,403.
  "가공매출"인데 매출 순증이 0인 문서가 다수. 차대 균형 검사만으로는 통과(hollow-PASS).
  추정 근본원인: 역분개(next_period_reversal 등)를 별도 문서 + reversal_document_id 링크로 만들지
  않고 한 문서 안에 같은 계정 차/대변으로 욱여넣음 (r1e 의 reversal_document_id 전부 None).
  → 수정: 한 전표 내 동일 계정 차·대 동시 기입 금지. 분개는 항상 서로 다른 계정 간 상대.
     역분개·반품은 반드시 (a) 별도 document_id 로 생성하고 (b) reversal_document_id /
     original_document_id 로 원전표에 링크. component 의 회계 방향이 카탈로그 (b) 와 맞아야 함
     (가공매출=차 AR / 대 매출; 회수위장=차 현금 / 대 AR; 차입=차 현금 / 대 단기차입금 등).

결함 2 — delivery_date 전 scheme 0% 채움
  FS09(cutoff)·FS01(가공 O2C) 의 핵심 시그니처인 납품일자가 비어 cutoff 시점 조작이 표현 안 됨.
  → 수정: O2C 계열(FS01·FS05·FS09) 의 매출/납품 관련 전표에 delivery_date 를 정상 분포로 채우되,
     FS09 는 카탈로그 (c) 대로 "인식월(12월) vs 납품일(익기 1월)" 역전이 delivery_date 와
     posting_date 사이에 실제로 나타나게 한다 (정상에도 연말 납품·1월 납품이 존재 — 부정은
     문서 단위 짝으로만 구분).

결함 3 — FS09 시점 짝 불일치 + 카탈로그에 없는 role 발명
  r1e: 조기인식 2023-12 ↔ 반품 2023-01(11개월 앞, 역방향), cutoff_collection 이라는 카탈로그에
  없는 role 을 발명, 2024-07 에 배치.
  → 수정: FS09 component_role 은 카탈로그 (d) 의 3종만 사용 — pulled_forward_sale /
     post_period_delivery / next_period_return. 조기인식(12월) 과 그 짝 반품(익기 1월)이
     **같은 고객·문서 라인으로 연결**되고 시점이 순방향(매출 12월 → 반품 익년 1월)이어야 한다.
  → 동일 점검: FS03 component_role 도 카탈로그 (d) 와 정확히 일치시킨다
     (cash_withdrawal / balance_patching / recon_item_fabrication / temporary_return).
     모든 scheme 의 component_role 은 카탈로그 (d) 문자열과 1:1 일치 (발명·개명 금지).

────────────────────────────────────────────────────────────────────────
[구현 원칙 — r1 과 동일, 유지]
────────────────────────────────────────────────────────────────────────
1. RUST 근본 구현 (Python 덧대기 금지).
2. 실제 flow 멤버십: 진짜 document_flows/·intercompany/·relationships/·subledger/·master_data/
   파일에 삽입. 가짜 sidecar flow 금지.
3. 식별자: document_id/UUID·document_number 는 정상과 같은 generator 경유.
4. 데이터 품질(결측·오타·서식) 정상/부정 동일 비율.
5. 라벨: scheme_id·scheme_instance_id·component_role·is_fraud·fraud_type·severity. FS10·12·13
   부작위 미인식 금액은 instance 메타 sidecar.
6. base 문서 1건도 수정·삭제 금지 (순수 overlay).
7. scheme 선택은 r1 과 동일 7종(FS01·03·05·07·09·11·12). 나머지 7종은 r2 회차.

────────────────────────────────────────────────────────────────────────
[검증 — 전 항목 통과해야 완료. 재검증 스크립트 재사용]
────────────────────────────────────────────────────────────────────────
회귀 가드 (r1e 에서 통과한 것 — 깨지면 실패):
  R1. 문서 불변량: base 문서 수 + 주입 N = 출력 문서 수 정확 일치.
  R2. base 무수정: base 전 컬럼 EXCEPT output = 0 행.
  R3. 라벨↔전표 정합: orphan 0, is_fraud↔provenance 양방향 0.
  R4. 표면 누수 0: mutation_reason·detection_surface_hints·batch_type 등 부정전용 값 없음.
  R5. 정상 쌍둥이: 부정 사용 계정·문서유형이 정상에도 존재 (부정 전용 0).
  R6. 실제 flow 파일 멤버십 증가 (가짜 sidecar 없음).
  R7. shortcut scan findings 0 (tools/scripts/scan_overlay_shortcuts.py) + 전 컬럼 오라클 스캔 0.

신규 가드 (r1e 결함 수정 확인):
  N1. 자기상쇄 0: 어떤 fraud 문서도 동일 gl_account 에 차·대 동시 기입 없음
      (tools/scripts/verify_phase2_dr_cr.py 의 selfcancel 카운트 = 0).
  N2. scheme별 경제효과 방향 floor (각 instance 순효과 검증):
      FS01 매출 계정(4000번대) 순증 > 0; FS05 각 사 매출 순증 > 0;
      FS07 재고(1200/123100) 순증 > 0 & COGS 과소; FS09 당기(12월) 매출 순증 > 0 이고
      익기 반품으로 일부만 환입(전액 자기상쇄 아님); FS03 현금(1000/1010) 순감 > 0 이고
      은폐계정(가지급·투자) 으로 이전; FS11 IC 채권/채무 비대칭 잔액 > 0; FS12 충당부채 설정 부재.
  N3. delivery_date: O2C scheme 의 납품 관련 전표 채움 > 0; FS09 는 인식월 vs 납품월 역전 존재.
  N4. component_role 카탈로그 일치: 모든 scheme 의 role 집합이 카탈로그 (d) 문자열과 정확히 일치
      (발명·누락 0).
  N5. 역분개 링크: next_period_reversal/return 문서는 reversal_document_id 또는 original_document_id
      로 원전표에 연결 (None 아님).
  N6. 차대 균형 유지 (문서 단위) + 다기간 scheme 연도 경계 실제 걸침.

리포트:
  - 측정 결과를 <출력경로>/reports/ 에 저장. 회차(r1f/r1f-b…)별 결과는 파일에 즉시 누적 기록.
  - 완료 후 docs/debugging.md 업데이트.

[금지]
- 검증 실패 상태 완료 선언 금지. hollow-PASS 금지 — N1~N6 중 하나라도 미달이면 미완.
- 빈 집합/fallback 을 통과로 둔갑 금지 (floor: 주입 문서 > 0, scheme 7종 instance ≥ 1,
  자기상쇄 = 0, 경제효과 방향 전부 양).
- PHASE1/PHASE2 detector 성능을 보고 주입을 고치는 행위 금지 (사후 측정은 별도 태스크).
- 한국어 보고.
