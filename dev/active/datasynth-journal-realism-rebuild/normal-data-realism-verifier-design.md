# Synthetic NORMAL 전표 현실성 검증기 운영 설계

## 목적

이 문서는 `normal-data-realism-test-catalog.md`의 검사 항목을 P3-1 정상 데이터 검증기에서 어떤 순서와 판정 모델로 적용할지 정의한다.
검사 항목의 의미와 측정 정의는 카탈로그가 소유하고, 이 문서는 gate, verdict, required fields, diagnostic 운영 기준을 소유한다.

## 판정 모델

```text
Verdict   의미
--------  ---------------------------------------------------------------------------
PASS      required fields가 존재하고 측정값이 해당 gate 기준을 충족한다.
FAIL      required fields가 존재하며 측정 결과가 hard invariant 또는 정상 범위를 위반한다.
BLOCKED   required fields, master, sidecar, metadata가 없어 검사를 의미 있게 수행할 수 없다.
MONITOR   강제 실패는 아니지만 분포 거리, 경제성, 샘플 진단에서 후속 검토가 필요한 신호다.
```

`BLOCKED`는 PASS가 아니다.
필드 부재로 검사를 수행하지 못한 항목은 리포트에서 누락 검사가 아니라 데이터 계약 미충족으로 표시한다.

## Gate 적용 순서

Gate는 P3-1 normal baseline의 최소 통과 기준과 후속 진단 기준을 분리하기 위한 운영 순서다.
동일 항목이 여러 성격을 가지면 더 강한 gate 판정을 먼저 적용하고, 분포 또는 diagnostic 결과는 보조로 남긴다.

```text
Gate        목적                         대표 항목
----------  ---------------------------  ----------------------------------------------------------------------
Gate 0      정상 전용 데이터 오염 제거와 회계·스키마 기본 불변 조건 확인 O01, A01, A02, A05, D01, D02, E05, F01, F02, F05, F08
Gate 1      v2에서 실제 실패한 joint semantics와 생성기 지문 결함 확인    B15, B16, B17, H02, H04, E11, E12, G08, G09, A06, C10, I01/I03/I04, I05, J04/J07, J08, J09, K01~K05, O01, O02
Gate 2      전수 분포·잔액·경제성·보조원장 정합 확인                    B13, B14, C01~C09, D03~D10, M01~M07, N01~N06, K06, K07
Diagnostic  전수 규칙 누락과 root cause attribution 보조                 P01, G08, O02, B13 low-support tuple analysis
```

P3-1 정상 baseline은 Gate 0과 Gate 1 통과를 우선 요구한다.
Gate 2는 데이터 규모, 보조원장, TB, master 준비 상태에 따라 `PASS`, `FAIL`, `BLOCKED`, `MONITOR`를 분리한다.

## Required Fields Matrix 원칙

검증기는 모든 검사 항목에 대해 필드 요구사항을 선언한다.
필드 요구사항은 `required`, `derived`, `optional_context` 세 등급으로 나눈다.
derived field는 원천 필드에서 결정적으로 계산 가능하면 BLOCKED로 처리하지 않는다.

```text
등급              설명
----------------  ----------------------------------------------------------------------
required          항목 판정에 반드시 필요한 필드 또는 master다. 누락 시 FAIL 또는 BLOCKED다.
derived           원천 필드에서 결정적으로 계산 가능한 대체 필드다. 계산 가능하면 누락으로 보지 않는다.
optional_context  판정 근거 설명과 exception 해소에 도움을 주지만 단독 누락으로 BLOCKED 처리하지 않는다.
```

required fields는 최소한 아래 네 그룹으로 나눈다.

```text
필드 그룹       설명
--------------  --------------------------------------------------------------------
core_gl         document_id, row_index, debit_amount, credit_amount, posting_date, account
semantic        semantic_account_subtype, line_text_family, raw_keyword, business_process, document_type
master          account_master, counterparty_master, user_master, approval_matrix, fiscal_calendar
provenance      source, scenario_id, archetype_id, batch_id, job_id, quality_issue_id, mutation fields
```

대표 필드 요구사항은 아래와 같이 둔다.
구현 시 전체 120개 항목에 대해 동일 형식의 matrix를 생성한다.

```text
검사ID  Required                                      Derived / optional_context                         판정 원칙
------  --------------------------------------------  ---------------------------------------------------  ------------------------------------------------
B15     counterparty_subtype, semantic_account_subtype  raw_keyword는 line_text에서 추출 가능              allowlist가 없으면 BLOCKED. 대체 추출 가능하면 raw_keyword 누락은 BLOCKED 아님.
B16     document_id, line_text_family, document_type    batch/summary exception label은 optional_context   고라인 문서에서 예외 라벨도 batch 근거도 없으면 BLOCKED.
B17     source, document_type, semantic_account_subtype inferred_archetype 가능, explicit archetype_id 권장 explicit archetype_id 누락은 별도 표시하고, migration mode에서는 inferred_archetype으로 계속 검사한다.
E05     sod_violation, sod_conflict_type, created_by, business_process, user_persona  audit_rules sod policy는 optional context  normal baseline에서 `sod_violation=true` 또는 `sod_conflict_type` nonblank는 direct confirmed SoD marker이므로 FAIL. 현실적 role breadth는 direct marker 없이 별도 review context로만 남긴다.
E11     source, approval policy metadata                approval_lag는 approval_date-posting_date로 계산 가능 approval policy 원천 누락 시 BLOCKED.
E12     created_by, user_type, source, business_process user_role은 user master에서 파생 가능              user_type 또는 role master 누락 시 BLOCKED.
G08     noise_flag 또는 quality_issue_id                semantic fail reason은 validator 결과에서 파생 가능 attribution metadata 누락 시 BLOCKED.
I01/I03/I04 document_id, document_number/accounting_document_number, reference, document_type, source  flow role은 document_type/source에서 파생 가능 document_number는 company/year/document_type 번호 체계에서 고유해야 한다. reference 재사용은 같은-role 무관 전표가 아니라 source-document 흐름 링크에서만 허용한다.
I05     document_id, source_document_id/reference, document_type, source, amount      flow role/source document type은 derived 가능 DuplicateDetector retained pair artifact가 같은 document line pair를 포함하면 FAIL. flow link와 duplicate candidate를 분리한다.
J04/J07 document_id, original_document_id, reversal_document_id, reversal_type, reversal_reason_code, gl_account, debit_amount, credit_amount, posting_date  reversal scenario/text는 optional context 정상 reversal은 원전표 링크가 있어야 하고, 원전표 대비 이후 전기되며, GL 계정별 pair net이 0이어야 한다. unlinked reversal은 normal baseline에서 FAIL.
J09     document_id, original_document_id, reversal_document_id, reversal_type, reversal_reason_code, source, posting_date, gl_account, debit_amount, credit_amount  line_text_family/source_document_id는 optional context 정상 baseline에는 원전표 링크가 있는 정상 역분개 배경이 있어야 한다. linked normal reversal count, original/reversal non-null 정상 비율, reason/type/source 분포, pair net 0, 원전표 존재, 이후 전기를 수치로 보고한다. 정상 linked reversal이 0 또는 설정 floor 미만이면 FAIL/BLOCKED이며, PHASE2 overlay에서만 original_document_id가 non-null인 상태는 허용하지 않는다.
J08     line_count, source, document_type               batch_id/job_id/batch_type은 대형 전표 설명 필드   대형 전표에서 batch 설명 필드 누락 시 FAIL 또는 BLOCKED.
K01     company_code                                      primary company config는 C001                       distinct company_code set이 정확히 `{C001}`이어야 한다. 복수 회사, 공란 회사코드, C002/C003 잔재는 FAIL.
K02     is_intercompany, counterparty_type, semantic_scenario_id, business_process, document_type  line_text는 보조  단일법인 normal에는 저빈도 관계사 IC surface가 있어야 한다. IC row 0이면 BLOCKED/FAIL.
K03     reference 또는 deterministic pair key, company_code, trading_partner, posting_date, amount  audit_rules intercompany.pairs는 prefix 검사에 사용  IC GL prefix 1150/4500/2050/2700 모집단이 모두 존재해야 한다.
K04     posting_date, reference/pair key                  document_date/fiscal_period는 보조                    IC 날짜·참조가 채워지고 stale close-lag pattern이 없어야 한다.
K05     trading_partner                                   company_code distinct fallback                    C002/C003는 IC row의 trading_partner로만 허용한다. C001 자기거래 또는 `IC-*` namespace는 FAIL.
K06     company_code, trading_partner, is_intercompany, amount  GraphDetector metadata 사용 가능              company-node graph edge/cycle/cycle_instance_count가 0이어야 한다.
K07     company_code, trading_partner, amount, direction pair  quantity/unit_price는 있으면 보조           IC direction pair count가 0보다 크고 high asymmetry rate가 설정 상한 이하여야 한다.
K08     master/flow/subledger/balance/financial_reporting/intercompany JSON  journal doc id는 보조           C002/C003가 company_code/company 필드에 남으면 FAIL. related_party partner code와 IC trace sidecar는 허용한다.
O01     is_fraud, is_anomaly, mutation_*, truth sidecar fraud_type/anomaly_type은 label sidecar로 대체 가능 normal-only subset에 label/provenance 값이 있으면 FAIL.
O02     전체 컬럼 값, scenario_id/source/archetype_id   domain-determined enum allowlist                  generator-artifact purity 기준 초과 시 FAIL 또는 MONITOR.
P01     sampling strata fields, review rubric           document text bundle은 row text 집계로 구성 가능   fixed seed, sample size, document_id 저장 누락 시 BLOCKED.
```

## v29 현행 구현 상태

2026-06-07 v29 기준 `tools/scripts/normal_data_realism_verifier_20260603.py`는 아래 항목을 실제 리포트로
산출한다. 문서상 카탈로그 120개 전 항목을 모두 구현했다는 뜻이 아니며, 미구현 항목은 PASS로 간주하지
않는다.

```text
영역                    구현/산출 항목
----------------------  -------------------------------------------------------------------------
normal contamination    O01, E05_SOD_DIRECT_MARKER
basic accounting        A01, A02
document identity       I01_I03_I04, I05_DUPLICATE_ARTIFACT_DOCUMENT_SCOPE
semantic coherence      B15_B16_H04, B17
tax/noise/amount        tax treatment, noise attribution/rate, C10/O02 계열 synthetic marker scan
batch/reversal          J08, J04_J07, J09
single-company scope    K01~K07
financial statements    M01~M07
diagnostic              P01 fixed-seed sample, S09_RECLASS, S09_M06_IS_REVERSE
```

v29 acceptance snapshot:

- Dataset: `data/journal/primary/datasynth_semantic_v1_normal_20260607_v29`
- Report: `artifacts/datasynth_normal_semantic_v1_realism_gate_audit_20260607_v29.json`
- Summary: `PASS 29`, `INFO 3`, FAIL/BLOCKED 0.
- E05 direct SoD marker: 320,312 documents checked, `sod_violation=true` 0 docs,
  `sod_conflict_type` nonblank 0 docs.
- L1-06 read-only detector component: v28 `6,327` docs / `18,533` rows → v29 `0` docs / `0` rows.
- A01, B15/B16/H04, K01~K07, J04/J07, J09, M01~M07는 PASS 유지.

## K01~K08 단일법인 범위·관계사 거래 검증 운영 원칙

K01~K08은 fraud/anomaly 주입 검증이 아니라 정상 baseline의 scope와 관계사 거래 배경 검증이다.
이 프로젝트는 단일법인 입사용 프로젝트이므로 normal 원장 안에 C001/C002/C003 장부가 함께 들어가면
PHASE1-1, PHASE1-2, PHASE2가 회사 구분 없이 합산 실행된다. 하지만 단일법인 C001에도 관계사
C002/C003와의 정상 거래는 존재한다. 따라서 C002/C003는 journal `company_code`가 아니라
`trading_partner`/관계사 master/IC sidecar에만 존재해야 한다.

```text
측정 축                         판정 의미
------------------------------  -----------------------------------------------------------------------
Single company scope            distinct company_code set. 정확히 `{C001}`이어야 한다.
IC surface presence             is_intercompany, IC/INTERCOMPANY/RELATED scenario/process/document/counterparty surface가 저빈도로 존재해야 한다.
IC GL population                1150/4500/2050/2700 prefix row가 모두 0보다 커야 한다.
Partner namespace integrity     C002/C003는 IC row trading_partner로만 허용한다. C001 자기거래와 `IC-*` namespace는 금지한다.
Graph cycle absence             company-node edge/cycle/cycle_instance_count. 모두 0이어야 한다.
Detector input isolation        PHASE1/PHASE2 입력에서 회사 장부는 C001 하나로 유지되는지 확인한다.
Sidecar isolation               sidecar의 company_code/company는 C001만 허용하고, related_party partner code와 IC trace sidecar는 허용한다.
```

anti-fitting 제약:

- verifier threshold는 detector recall을 올리기 위한 사후 튜닝값이 아니다. 기준은 제품 범위인 단일법인
  원장 isolation이다.
- `is_intercompany=true`와 `trading_partner=C002/C003`는 단일법인 normal에서 정상 저빈도 feature다.
  다만 C002/C003의 별도 journal company ledger, TB, FS는 만들지 않는다.
- O02 synthetic marker scan은 K 계열 scope 오염과 별개로 generator fingerprint를 본다. K01~K07 FAIL은
  label leakage가 아니라 제품 범위 위반이다.

B17은 migration mode를 가진다.
초기 baseline에서 explicit `archetype_id`가 없으면 `inferred_archetype`을 임시 계산해 B15/B16/O02 계열 검사를 계속 수행한다.
동시에 explicit `archetype_id` 누락 자체는 별도 FAIL 또는 BLOCKED finding으로 표시한다.

## LLM·전문가 샘플 진단 가드

LLM 또는 전문가 샘플 리뷰는 deterministic 전수 검사를 대체하지 않는다.
샘플 리뷰는 아래 목적에만 사용한다.
샘플은 fixed seed, strata별 sample size, document_id 목록을 리포트에 저장한다.
이전 run 대비 동일 document_id 재평가 옵션을 제공해야 회귀 비교가 가능하다.

```text
허용 목적            설명
------------------  -------------------------------------------------------------------
규칙 누락 발견       전수 allowlist나 distribution 항목이 잡지 못한 비현실 조합을 찾는다.
진단 우선순위 지정   semantic mismatch가 생성기 joint draw 문제인지 noise 문제인지 분리한다.
리뷰 문구 생성       사람이 확인할 수 있는 짧은 근거와 예시 document_id를 제공한다.
```

LLM 판정은 단독 FAIL 근거가 아니다.
LLM이 비현실 판정을 내린 경우에는 B15, B16, B17, G08, O02 같은 전수 항목 후보로 환원한다.
환원할 수 없는 경우에는 `MONITOR` 또는 `Diagnostic finding`으로만 리포트한다.
LLM/전문가 output schema는 `plausible`, `questionable`, `impossible`, `rule_gap_candidate`로 고정한다.

## 리포트 형식

검증기 리포트는 gate별로 결과를 분리한다.
각 항목은 verdict, 측정값, 기준, required field 상태, 대표 예시를 함께 출력한다.

```text
필드                 설명
-------------------  ---------------------------------------------------------------
gate                 Gate 0, Gate 1, Gate 2, Diagnostic
test_id              카탈로그 검사ID
verdict              PASS, FAIL, BLOCKED, MONITOR
metric               전수 계산 결과
threshold_source     정상 범위 임계 출처
required_fields      present, missing, partial
example_keys         document_id, row_index, scenario_id, archetype_id 등 최소 식별자
notes                사람이 이해할 수 있는 짧은 판정 근거
```

## 구현 범위 제외

이 문서는 검증기 운영 설계다.
데이터 생성기 수정, 검증기 코드 구현, threshold calibration, LLM prompt 작성은 이 문서의 범위가 아니다.
