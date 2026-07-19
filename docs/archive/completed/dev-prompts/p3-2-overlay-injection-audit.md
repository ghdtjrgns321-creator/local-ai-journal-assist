# P3-2 Overlay 주입 156건 전수 규명 (2026-06-07)

대상: `data/journal/primary/datasynth_semantic_v1_p3_2_overlay_20260607_v12`
방법: 156 truth unit(표준78+우회78) 전부의 실제 주입 저널 행을 추출해 detector catch와 대조.
도구: `tools/scripts/audit_overlay_injection.py` → `reports/phase1_detector_catch/overlay_injection_audit.csv`

## 결론 요약

표준위반조차 못 잡는 원인은 detector 부실이 아니라 **overlay 주입이 detector가 실제로 보는 조건을 재현하지 못한 것**이 다수다. 3대 근본 메커니즘:

1. **flag override** — overlay가 파생 플래그(is_period_end, sod_violation 등)나 한도 컬럼을 박지만, Python feature 파이프라인이 raw 필드에서 그 값을 **재계산해 덮어쓴다.** 주입은 raw 조건을 만들어야 한다.
2. **threshold/label miss** — 위반의 정도가 detector 임계 미달(평일을 주말로, 1원 초과, 3% 금액차, 1일 날짜차, min 미달) 또는 정상 라벨 재사용(normal_accrual_reversal, NORMAL-BATCH).
3. **unit mismatch** — 집계·모집단·생애주기 단위 룰(Benford, 변동, 분포, 클러스터, 집중, suspense lifecycle)을 2줄짜리 전표 1건으로는 구조적으로 만들 수 없다.

## 분류 (39룰 전수)

| 분류 | 룰 | 건수 | 근거 |
|------|----|------|------|
| 정상 catch | L1-01,L1-02,L1-05,L1-08,L1-09,L2-02,L2-03,L3-02,L3-03,L3-06,L3-07,L3-11,GR03 | 13 | 의도 트리거 실제 존재 → 발화. 우회는 신호 제거돼 정상 miss |
| 주입결함·flag override | L1-04,L1-06,L3-04,L3-08 | 4 | 파생값/한도만 박고 raw 미설정. feature가 덮어씀 |
| 주입결함·threshold/label | L3-05,L2-05,L4-06,IC02,IC03,GR01,L4-03,L1-07 | 8 | 임계 미달 또는 정상 라벨 재사용 |
| 구조적·unit mismatch | L3-09,L3-12,L4-01,L4-02,L4-04,L4-05,D01,D02 | 8 | 집계/모집단/생애주기 단위 — 단건 주입 불가 (D01/02 details=0, L3-12 score=0) |
| detector/config 갭 | L1-03,L3-01,L3-10,L2-04,IC01 | 5 | 트리거 존재하나 미발화 (COA/high-risk/IC pair 설정 또는 details 괴리) |
| 추가확인 필요 | L2-01 | 1 | split/reference 패턴 추가 해부 필요 |

## 실증 검증 (2건, ripple)

- **L3-04**: `period_end_margin_days=5`. feature `time_features.add_is_period_end`가 posting_date로 재계산.
  - sta0 2024-12-31(결산 0일전)→True→HIT / eva1 2023-12-26(5일전)→True→HIT
  - sta1 2022-12-21(10일전)→False→miss / eva0 2023-12-25(6일전)→False→miss
  - 주입한 `is_period_end=true`는 무시됨. catch 패턴이 margin 규칙과 정확히 일치 → flag override 확정.
- **L3-05**: 주입 날짜 2024-06-03(월)·2024-06-04(화) = 평일. 주말/공휴일 룰이 발화할 수 없음 → 주입 결함 확정.

## 핵심 사례 근거 (대표)

- L1-04: `approval_limit=금액-1`(1원 초과)만 설정. detector는 feature `exceeds_threshold`를 봄 → 미발화.
- L1-06: `sod_violation=true`·`sod_conflict_type=preparer_approver` 박았으나 created_by≠approved_by → 실제 동일인 충돌 없음.
- L3-08: line_text 비웠으나 line_text_family 채워져 description_quality가 정상으로 판정.
- L2-05: `reversal_type=normal_accrual_reversal` = 정상 역분개로 주입.
- L4-06: batch_id/job_id가 `JOB-NORMAL-BATCH-...` = 정상 배치 재사용.
- IC02: 금액차 sta0 12%→HIT, sta1 3%→tolerance 미달 miss.
- L1-03: gl_account=999999(무효 계정) 주입됐으나 miss → COA 검증 detector 갭.

## detector/config 갭 5건 점검 결과 (실증 확정)

원래 "트리거 존재하나 미발화"로 분류했던 5건을 detector 코드·설정으로 직접 확인. 실제 detector 문제는
1건(IC01)뿐이고 나머지는 주입/설정/측정 문제였다.

| 룰 | 실측 원인 | 분류 |
|----|-----------|------|
| L1-03 | gl_account 999999가 실제 COA(config/chart_of_accounts.csv, 458코드)에 **유효 계정으로 존재** → detector 정상(안 잡음) | 주입 결함 (무효 아닌 계정 사용) |
| L3-10 | high-risk 목록=`[1190,2190]`+접두`[111,112,113]`인데 주입 계정=15110 → 목록 밖 | 주입/설정 불일치 |
| L3-01 | denied 계정 config가 6자리(`500000`,`500060`…)인데 데이터 계정은 4자리(`6300`,`4000`) → 영구 미스매치, emitted 0 (no-op) | PHASE1 config-데이터 코드체계 불일치 (수정 대상) |
| IC01 | pair_map `{1150<->2050,4500<->2700}`. matcher는 기존 IC 항목을 조인 → 상대측이 통째로 없는 unmatched는 구조적으로 미탐 | 진짜 detector 한계 (PHASE1 보강 또는 PHASE2) |
| L2-04 | rule_flag로 2건 발화하나 details 컬럼에 행별 점수 미노출 → row-document 매칭 불가 | 측정 도구 (detail 노출) |

검증(ripple): L1-03(COA 포함여부)·L3-01(denied 계정 vs 데이터 코드)·IC01(pair_map) 3건을 실제 detector
설정으로 직접 재현해 확정.

## v17 재설계 독립 검증 (2026-06-07)

다른 컨텍스트가 overlay를 v17로 재생성. measure_phase1_detector_catch.py 독립 재실행으로 재현.

- detector-expected standard **62/62 caught, missed 0** (재현 일치). hollow 아님: 전건 positive_rows>0.
- population/blind standard 0/16, evasion 0/78 — 의도된 분리 일치.
- 이전 미탐 15룰(L1-03/04/06/07, L2-01/05, L3-04/05/08/10, L4-03/06, IC02/03, GR01) 전부 standard 2/2 catch.
- 수정 방식 raw 조건 확인(스팟 5건): L3-04 is_period_end 플래그 제거+실제 분기말 날짜, L3-05 실제 주말,
  L3-08 line_text/family 전부 공백, L1-06 created_by==approved_by 실제 동일인, L1-03 무효계정 교체.
  → flag override가 아니라 raw 조건 재주입. 정상.

### 그러나 남은 DATA SHORTCUT (그쪽 "shortcut 0" 주장과 배치 — PHASE2 누수)
PHASE1 catch엔 영향 없으나(룰은 구조 사용) PHASE2 ML 학습에서 truth/normal을 라벨 없이 분리 가능:
1. **reference 형식/범위 truth 전용**: 주입 `PO-Cxxx-YYYY-5NNNNN`(접미 500000~532999), normal은
   `PO-Cxxx-YYYY-NNNNNN-Cxxx-YYYY-KR-NNNNNN`(다른 형식, 해당 범위 0건). 모델이 형식만으로 분리 가능.
2. **reversal_type="manual_self_reversal" truth 전용**: normal v29는 normal_accrual_reversal 396건뿐.
3. **reversal 텍스트 "기말 수동 역분개" truth 전용**: L2-05 _s4 키워드 부분 누수(단 _s3 source/timing은 구조적).
→ 그쪽 scan(17 token/id 컬럼, N>=5&&normal==0)이 reference 형식·범위와 reversal 컬럼을 못 잡음.
   PHASE2 학습 데이터로 쓰기 전 reference/reversal 네임스페이스를 normal과 동일 분포로 교정 필요.

## v23 누수 교정 독립 검증 (2026-06-08)

v17 누수(reference 형식/범위·document_number·document_id·batch/job·reversal 토큰)를 v23에서 교정.
`data/journal/primary/datasynth_semantic_v1_p3_2_overlay_20260608_v23`. 독립 재현:

- scan_overlay_shortcuts.py v23: **FINDINGS 0** (동일 코드가 v17엔 16건 검출 → 0 전환).
- measure v23: detector-expected std **62/62 caught, miss 0**, population 0/16, evasion 0/78 (catch 회귀 0, hollow 아님).
- 누수 교정이 catch 구조 안 깸 확인(스팟):
  - reference: `PO-Cxxx-YYYY-NNNNNN-Cxxx-YYYY-KR-NNNNNN`(normal 형식·범위)로 교체. 단 L2-02/03 중복쌍은
    여전히 같은 reference 공유 → 중복탐지 구조 유지.
  - L2-05: 토큰(manual_self_reversal/기말 수동 역분개) 제거, normal_accrual_reversal+source=manual+
    reversal_document_id 링크로 구조만 표현. document_id도 normal형 UUID(019e9dbc-…).
  - GR03: debit 44501523 vs 89003046 = 실제 IC 금액 비대칭(shortcut 아님).
- 스캐너 변별: created_by/source/persona 등 정상 컬럼은 오탐 없이 통과(truth가 normal과 섞임).

판정: **v23 PASS** — PHASE2 학습 누수 닫힘 + PHASE1 catch 구조 보존. PHASE2 입력 데이터로 적합.
도구: tools/scripts/scan_overlay_shortcuts.py (누수 게이트), measure_phase1_detector_catch.py, audit_overlay_injection.py.

## PHASE1 갭 마무리 (2026-06-08)

detector갭 5건 중 L3-01·IC01을 PHASE1 측에서 처리. 도메인 정합으로만 정당화(truth-recall 추구 아님).

### L3-01 — 실제 버그, 수정함
- 근본: `category_mismatch = ~account_configured & disallowed` 에서 process_denied_accounts(6자리
  500xxx)가 설정돼 있다는 이유만으로 `account_configured=True` → category 경로 봉쇄. 데이터는 4자리
  계정(6300 등) 사용 → exact는 못 맞추고 category는 봉쇄돼 L3-01이 전 프로세스 no-op(emitted 0).
- 수정: `category_mismatch = disallowed` (src/detection/integrity_layer.py). exact와 category는 같은
  정책의 두 코드체계 표현 → 둘 다 적용(exact score 0.65 > category 0.45, 중복점수 없음).
- 검증: v23 주입 O2C+expense standard 2/2 flagged. 정상 v29 전수 L3-01 발화 0/983,028 (과탐 0,
  KPI 가드 충족). 5개 process×disallowed-category 정상 위반 모두 0건 사전 측정.

### IC01 — 버그 아님 (review-only 설계)
- ic01_unmatched_intercompany는 짝없는 IC를 탐지하나, 상대가 그룹사(master 존재)면
  mapping_uncertain → evidence_level="review", **score=0.0** (D065/AGENTS.md "review-only signals must
  not become confirmed violations"). high(score 1.0)는 master에 없는 partner만.
- 주입 IC01은 상대 C003(그룹사) → review 분류. detector-only catch(score>0)가 review를 안 세서 miss로
  보였을 뿐 — 측정 의미 문제지 detector 버그 아님. score_aggregator가 evidence_level로 Low floor 부여.
- 1차 결론: review-only(score 0)이나 score_aggregator가 evidence_level로 floor 부여(high→Medium 0.40,
  review→Low 0.20). 즉 무시가 아니라 Low로 surfacing.
- 사용자 결정(옵션3, 2026-06-08): 아는 그룹사 미대사를 결산기 근접/이탈로 분기.
  - 결산기 근접(is_period_end) → review (Low 0.20, cutoff 타이밍 설명 가능, 현행)
  - 결산기 이탈(mid-period) → review_stale (Medium 0.40, 타이밍으로 설명 안 됨, ISA 600 그룹감사 예외)
  - 구현: intercompany_rules.ic01(분기) + score_aggregator(review_stale→Medium) + phase2_case_family_aggregator
    (review_only 집계 포함). D065 유지(details score 0). 단위테스트 2케이스 + 전체 1420 passed.
  - 새 flag 추가 없음(기존 review 신호의 Low→Medium 재배정만) → 과탐 볼륨 불변.

### 정리
- L2-04: 측정도구(details 노출), L3-10: overlay에서 교정됨(v23 catch). PHASE1 detector 실 버그는 L3-01 1건.

## 함의

- **overlay(P3-2) 재설계 필요**: 주입은 파생 플래그가 아니라 **raw 조건**을 만들어야 하고(=feature 재계산 후에도 살아남게), 임계를 넘기고, 집계 단위 룰은 **분포/모집단/prior 베이스라인**을 함께 흔들어야 한다.
- **PHASE2 타깃 후보는 "구조적·집계 단위" 룰**(변동/분포/클러스터/Benford/생애주기)에 자연 정렬됨 — PHASE1 단건 룰의 사각.
- **detector/config 갭(5룰)**은 PHASE1 측 별도 점검(COA 목록, high-risk 계정, IC pair 설정, L2-04 details 산출).
- 측정 도구는 보강 완료(IC/graph/evidence/variance 실행 추가). 단 D-series는 prior_summary, review-pop은 score 기준 보강이 후속 과제.
