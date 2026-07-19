# v33(flow sidecar 보강) + r3(14 scheme 전수) 2단계 프롬프트

> 2단계. STEP 1(v33 base) 검증 통과 후 STEP 2(r3 overlay)로 진행. 새 세션에 전문 붙여넣기.

[배경]
v32 에서 journal_entries.delivery_date 22,192 채움으로 row-feature 경계는 닫혔으나,
대응 document_flows/deliveries.json(29문서)·customer_invoices.json(27문서)이 보강되지 않아
"매출 분개엔 납품일이 있는데 대응 납품 문서가 없는" flow 정합 갭이 남았다.
원인: normal_coa_v30.rs 의 `write_normal_o2c_flow_links` 가 stub(빈 구현, 420행 `Ok(())`).
필요 정보는 이미 `O2cDeliveryDoc`(document_id·company·fiscal_year/period·posting_date·delivery_date·
reference·customer_id·created_by·currency)에 다 있다 — 쓰기만 하면 된다.

════════════════════════════════════════════════════════════════════════
STEP 1 — flow sidecar 보강 → base normal v33
════════════════════════════════════════════════════════════════════════
구현: tools/datasynth/crates/datasynth-cli/src/normal_coa_v30.rs
산출: data/journal/primary/datasynth_semantic_v1_normal_<날짜>_v33

[작업]
1. `write_normal_o2c_flow_links(target, docs)` stub 을 실제 구현으로 채운다.
   - docs(=delivery_docs, 정상 O2C product+AR 매출 22,192건)로부터 각 매출에 대응하는
     · delivery 문서 1건 → document_flows/deliveries.json 에 append
     · customer_invoice 문서 1건 → document_flows/customer_invoices.json 에 append
   - 기존 base 의 deliveries.json/customer_invoices.json **스키마와 동일 형식**으로 생성
     (먼저 base 파일 1건을 읽어 header 구조 확인 후 동일 형식 — 자체 포맷 발명 금지).
     header 필드: document_id, document_type, company_code, fiscal_year, fiscal_period,
     document_date, posting_date, entry_date, status, created_by, currency, reference,
     journal_entry_id, document_references[...] 등.
2. 날짜 정합: delivery 문서의 날짜 = journal delivery_date(O2cDeliveryDoc.delivery_date)와 동일.
   customer_invoice 문서의 posting_date = 매출 분개 posting_date 와 동일.
3. 체인 연결: document_references 로 sales_order→delivery→customer_invoice→journal_entry 연결.
   journal_entry_id 를 대응 journal document_id 로 채워 1:1 추적 가능하게.
4. 식별자: 문서번호(DLV-*/CINV-*)는 기존 generator 규칙·stride 따름(충돌 금지).
5. 기존 base 의 deliveries 29 / customer_invoices 27 는 유지하고 append (덮어쓰기 금지).
6. RUST 로 구현. Python 후처리 금지. delivery_date 외 journal 컬럼·다른 산출물 무수정.

[STEP 1 검증]
- S1. deliveries.json 문서수 29 → 약 22,221(29+22,192) 대폭 증가. customer_invoices.json 동일 증가.
- S2. journal delivery_date 채운 문서 ↔ deliveries.json 문서 1:1 대응
     (journal 22,192 = 신규 delivery 22,192, 누락·고아 0).
- S3. 날짜 일치: 표본 N건에서 journal.delivery_date == deliveries.json 날짜.
- S4. base 회귀: journal_entries 는 v32 와 동일(delivery sidecar 추가 외 변경 0), 불변량·차대균형·
     shortcut scan 0·KPI 가드 유지. COA 16계정 유지.
- S5. document_references 체인 무결성: 신규 delivery/customer_invoice 가 대응 journal_entry_id 보유.

════════════════════════════════════════════════════════════════════════
STEP 2 — fraud overlay 14 scheme 전수 → r3
════════════════════════════════════════════════════════════════════════
Base: STEP 1 산출 v33
구현: tools/datasynth/crates/datasynth-cli/src/phase2_scheme_overlay.rs (기존 7 scheme 자리에 추가)
산출: data/journal/primary/datasynth_semantic_v1_phase2_fraud_<날짜>_v1_r3

[SoT] dev/active/phase2-fraud-scheme-catalog.md (FS01~FS14).
[ANTI-FITTING] docs/spec/DETECTION_RULES.md·phase1-evasion-injection-spec.md 읽기 금지.
              detector 로 주입 맞추는 루프 금지.

[작업]
- 기존 7 scheme(FS01·03·05·07·09·11·12)에 더해 **나머지 7개 FS02·FS04·FS06·FS08·FS10·FS13·FS14**
  를 카탈로그 (b)~(f) 대로 구현. 최종 14개 전부 한 데이터셋에 주입(검증 커버리지 완성).
- 신규 7 scheme 의 (d) component_role·계정·문서흐름은 카탈로그 문자열과 1:1 일치(발명 금지).
  · FS02 진행기준: 계약자산(116100)·용역매출·재공품(123100)·후속손실
  · FS04 횡령은폐: 선급금(100400~)·단기대여금(117100)·가지급금(117900)·CIP(151900)
  · FS06 부채누락: AP 기말제거↔기초원복(reversal 링크)·가공외화 AR
  · FS08 부당자본화: 무형자산-개발비(131100)·무형자산상각비(681100)·CIP·후속손상(682100)
  · FS10 대손회피: 대손충당금(119100) 과소·충당금환입(469100)·위장입금↔차환 짝·부작위 메타
  · FS13 손상미인식: 투자자산(160100)·손상차손(682100)·평가충당금(169100)·부작위 메타
  · FS14 유령직원: employees 마스터 + 월별 급여(6100)·payroll clearing(9100)·계좌중복

[과밀 금지 — 카탈로그 §4]
- 14개를 한 데이터셋에 넣되 **서로 다른 회사(C001~C003)·기간에 분산**. "한 회사에 모든 부정"
  금지. scheme당 instance 1개 기준, 전체 부정 문서 0.07~0.21%(카탈로그 §4.1 최대 시나리오) 이내.

[r1f_c/r2 가드 — 유지(깨지면 실패)]
- 자기상쇄 0(동일 gl_account 차/대 동시 금지).
- component_role 카탈로그 (d) 1:1 일치(발명·개명 0).
- 역분개·반품·기초원복은 별도 문서 + reversal_document_id/original_document_id 링크.
- scheme별 경제효과 방향(신규: FS02 계약자산↑·용역매출↑/FS04 현금↓→자산둔갑↑/FS06 기말 AP↓·
  기초 AP↑/FS08 비용↓·무형자산↑/FS10 충당금 과소·AR aging 위장/FS13 투자자산 유지·손상부재/
  FS14 급여비용↑·현금↓ 정상외형).
- FS10·FS13 부작위(미인식 금액)는 instance 메타 sidecar(문서 라벨 아님), evaluation_stratum=low_trace.
- 실제 flow 멤버십·식별자 generator·품질 동일비율·base 무수정.

[STEP 2 검증 — 재검증 스크립트 재사용]
- tools/scripts/verify_phase2_r2.py 의 V32/OUT 경로를 v33/r3 로 교체해 재실행.
- 회귀 R1~R7(불변량·base무수정·라벨정합·표면누수0·정상쌍둥이·flow멤버십·shortcut scan 0).
- N1~N6(자기상쇄0·경제효과방향·delivery·role일치·reversal링크·균형+연도).
- 신규 C1~C3:
  · C1. 14 scheme 전부 instance ≥ 1(전수 커버리지). 누락 0.
  · C2. scheme 회사·기간 분산 — 단일 회사 부정 문서 비율이 특정 회사에 쏠리지 않음.
  · C3. FS10·FS13 instance 메타에 unrecognized_amount + low_trace stratum 존재.
- D1~D3(delivery 경계해소) 유지: delivery 채운 문서가 base에 압도적, fraud 쏠림 없음.

리포트: <출력경로>/reports/ 저장, 회차별 누적. 완료 후 docs/debugging.md 갱신.

[금지]
- 검증 실패 상태 완료 선언 금지. hollow-PASS 금지(S1~S5/N1~N6/C1~C3 중 하나라도 미달=미완).
- v33 의 deliveries 보강이 미완(문서수 그대로)이면 STEP 2 진행 금지.
- detector 성능으로 주입 수정 금지. 한국어 보고.
