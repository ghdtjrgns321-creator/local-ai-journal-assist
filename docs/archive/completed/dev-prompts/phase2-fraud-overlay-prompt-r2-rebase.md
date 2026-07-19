# base normal delivery_date 재생성 + PHASE2 fraud overlay 재실행 프롬프트

> 2단계 작업. STEP 1(base 재생성)을 끝내고 검증 통과 후 STEP 2(overlay)로 간다.
> 새 세션에 전문 붙여넣기.

[배경]
직전 fraud overlay r1f_c 는 회계 실질(자기상쇄·role·시점·reversal 링크) 결함을 모두 해소했으나,
잔여 리스크가 1건 남았다: **base normal(v31c)의 journal_entries.delivery_date 가 32만 문서 전부
비어 있다.** 그래서 overlay 만 delivery_date 를 채워 "delivery_date 채워진 문서 = overlay 산물"
이라는 경계가 생겼다. deliveries.json 에는 납품일(document_date/posting_date)이 실재하는데
journal_entries.delivery_date 컬럼으로 전파가 안 된 것이 원인이다.
→ base normal 부터 정상 O2C 에 delivery_date 를 부여해 근본 해소한 뒤 overlay 를 재실행한다.

════════════════════════════════════════════════════════════════════════
STEP 1 — base normal 재생성 (delivery_date 전파)
════════════════════════════════════════════════════════════════════════
Base 생성기: tools/datasynth (기존 normal 생성 profile — v31c 를 만든 그 profile)
산출: data/journal/primary/datasynth_semantic_v1_normal_<날짜>_v32

[핵심 변경 — 이것만]
- 정상 O2C 매출인식 분개(customer_invoice / 매출(4000번대)·AR(1100) 전표)의 journal_entries
  delivery_date 컬럼을, 그 거래에 대응하는 deliveries.json 납품 문서의 날짜로 채운다.
  (deliveries.json 에 이미 document_date/posting_date 존재 — 새 날짜 발명이 아니라 전파.)
- 대응 납품이 없는 매출(선수금·서비스매출 등)은 delivery_date 비움(정상).
- RUST 로 근본 구현. Python 후처리 금지.

[정상 분포 요건 — 이게 shortcut 방지의 핵심]
- 정상 O2C 의 delivery_date 는 자연 분포여야 한다:
  · 대다수: 납품 후 인식 (delivery_date <= posting_date)
  · 자연 변동: 일부 선인식/후납품 포함 (delivery_date > posting_date 도 정상적으로 존재)
  · 계절성: 연말(12월)·연초(1월) 납품이 자연스럽게 분포 — 그래야 cutoff(FS09) 역전이 부정
    전용 시그니처가 되지 않는다.
- 결과적으로 정상 O2C 문서 대다수가 delivery_date 를 갖는다(현재 0 → 대량). 이래야 overlay 의
  delivery_date 가 "특별한 것"이 아니게 된다.

[base 재생성 검증]
- B1. journal_entries.delivery_date 채운 문서 수 >> 0 (정상 O2C 대다수). 현재 0 에서 대폭 증가.
- B2. delivery_date↔posting_date 관계가 자연 분포(역전 일부 포함, 연말·연초 존재).
- B3. 기존 normal 불변량·품질 회귀 유지(문서 수, 차대 균형, shortcut scan 0, KPI 가드).
- B4. delivery_date 외 다른 컬럼·분포는 v31c 와 동일(이번 변경은 delivery_date 전파로 국한).
- B5. COA·계정 구조는 v31c 확장본 유지(무형자산·충당부채·투자자산 등 16계정).

════════════════════════════════════════════════════════════════════════
STEP 2 — fraud overlay 재실행 (r1f_c 로직 유지 + control 제거)
════════════════════════════════════════════════════════════════════════
Base: STEP 1 산출 v32
구현: tools/datasynth/crates/datasynth-cli/src/phase2_scheme_overlay.rs (r1f_c profile 재사용)
산출: data/journal/primary/datasynth_semantic_v1_phase2_fraud_<날짜>_v1_r2

[SoT] dev/active/phase2-fraud-scheme-catalog.md (FS01~FS14).
[ANTI-FITTING] docs/spec/DETECTION_RULES.md·phase1-evasion-injection-spec.md 읽기 금지.
              detector 로 주입 맞추는 루프 금지.

[r1f_c 에서 유지할 것 — 깨지면 실패]
- 자기상쇄 0 (동일 gl_account 차/대 동시 기입 금지).
- component_role 카탈로그 (d) 문자열 1:1 일치 (발명·개명 금지).
- 역분개·반품은 별도 문서 + reversal_document_id/original_document_id 링크.
- scheme별 경제효과 방향(FS01 매출순증·FS03 현금순감→은폐·FS07 재고순증+COGS과소·
  FS09 당기매출순증 일부환입·FS11 IC비대칭·FS12 충당부채부재).
- FS09 시점 순방향(12월 인식 → 익년 1월 납품/반품, 같은 고객·문서 라인 짝).
- 실제 flow 멤버십, 식별자 generator, 데이터 품질 동일비율, base 무수정, scheme 7종(FS01·03·05·07·09·11·12).

[변경 — delivery control 제거]
- r1f_c 의 normal delivery control 864 문서를 **추가하지 않는다.** base v32 가 이미 정상 O2C
  delivery_date 자연 분포를 가지므로 희석용 control 이 불필요.
- fraud O2C(FS01·05·09)의 delivery_date 는 base 와 같은 의미로 채우되, FS09 만 카탈로그대로
  인식월 vs 납품월 역전이 문서 단위 짝으로 나타나게 한다(정상에도 역전이 있으므로 짝·고객으로만 구분).

[검증 — 회귀 R1~R7 + 신규 N1~N6 (r1f_c 와 동일) + 경계해소 D1~D2]
- R1~R7: 불변량, base무수정, 라벨정합, 표면누수0, 정상쌍둥이, flow멤버십, shortcut scan 0.
  (재검증 스크립트 재사용: tools/scripts/verify_phase2_r1fc.py 의 BASE/OUT 경로만 교체)
- N1 자기상쇄 0 / N2 경제효과 방향 / N3 delivery 채움 / N4 role 일치 / N5 reversal 링크 / N6 균형+연도.
- D1. delivery_date 채운 문서가 base(정상) 에 대량 존재 — overlay 만의 특징이 아님
     (base delivery 채움 >> overlay delivery 채움).
- D2. "delivery_date not null" 집단의 is_fraud 비율이 모집단 base rate 수준으로 희석
     (overlay 만 채운 게 아니므로 자동 충족) — fraud 쪽 쏠림 없음 확인.
- D3. fraud O2C 와 정상 O2C 의 delivery↔posting 관계 분포가 겹침(역전이 부정 전용 아님).

리포트: <출력경로>/reports/ 저장, 회차별 누적 기록. 완료 후 docs/debugging.md 갱신.

[금지]
- 검증 실패 상태 완료 선언 금지. hollow-PASS 금지.
- base v32 의 delivery_date 가 여전히 0 이거나 소수면 STEP 1 미완 — STEP 2 진행 금지.
- detector 성능으로 주입 수정 금지. 한국어 보고.
