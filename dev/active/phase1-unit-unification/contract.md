# PHASE1 P2-4 Contract

## Done

- [x] priority_score / composite_sort_score / topic score를 document·flow unit에 산출
- [x] case(집계 뷰) 점수는 unit 점수의 derived(max/sum/count)만 — 독립 점수 0 (G1)
- [x] 점수 산출 단일 경로 — 나머지는 읽기만 (G2)
- [x] corroboration을 per-unit 재계산 (버킷 가짜 corroboration 제거)
- [x] L2-05 calibration: 링크된 정상 accrual 역분개 = LOW / 링크없거나 off-pattern = 높게
- [x] 2+ 케이스로 검증(ripple-search): 점수 소비처(dashboard/export/PHASE2 overlay) 무회귀
- [x] before/after 큐 정렬 diff 산출(순서 변경 허용, 결과만 보고)

## P2-4 검증 메모

- v29 전체 before/after diff는 `_build_cases` before/after 이중 실행 비용으로 20분, 15분 제한에서 각각 timeout.
- 대신 v29 동일 파일의 first 100,000 rows bounded sample에서 before/after queue diff를 산출했다.
  - legacy/after cases: 5,595 / 5,595
  - case derived mismatch: 0
  - top20 overlap: 3/20
  - after top20 score range: 0.1967~0.3068

## P2-4 성능 최적화 Contract

### Done

- [x] 병목 프로파일링: case/unit/flow build 단계별 소요시간 hotspot 식별(수치로)
- [x] hotspot 최적화: per-row 루프→벡터화, 반복 전체 스캔 제거, O(n^2)→그룹/인덱스, 불필요 재계산 캐시
- [x] 출력 동일성: 동일 샘플에서 before==after 완전 일치(units·cases·scores·flow·band) — 의미 변화 0
- [x] full v29 완주 + 소요시간 보고(목표: 단일 실행 timeout 없이)
- [x] full v29에서 P2-4 전수 검증 완성: case derived mismatch 0(전수), document/flow unit 수치
- [x] 2+ 케이스 ripple: 소비처(dashboard/export/PHASE2 overlay) 무회귀
- [x] baseline 37 신규 0

### P2-4 성능 검증 메모

- 병목 before sample: 6,000 rows / 3,000 docs / 3,000 document units build-only 14.827s.
  - `_score_phase1_units` 13.729s, `_score_unit_hits` 13.181s, `_case_audit_evidence_scores` 10.474s.
- 최적화:
  - unit/case audit evidence context와 posting month를 DataFrame 전체에서 1회 precompute.
  - document raw hits를 `document_id`별 index로 잡아 unit마다 `raw_hits` 전체를 다시 scan하지 않게 했다.
- after sample: 같은 6,000 rows / 3,000 docs build-only 2.479s.
- 샘플 출력 동일성: 느린 참조 audit evidence 경로와 최적화 경로의 `cases`/`units` payload 동일.
  - sample 240 rows, 26 cases, 89 units, payload bytes 364,243.
- full v29:
  - rows 983,028.
  - detectors 248.014s, case/unit/flow build 380.964s, total 640.292s.
  - cases 9,046, units 1,442(document 654 / flow 788).
  - flow complete/eligible 788/788, `case_derived_mismatches=0`, invalid evidence refs 0.
- 회귀:
  - export/PHASE2 overlay 164 passed.
  - L2-03/IC/GR 관련 104 passed.
  - 전체 suite `37 failed, 4453 passed, 133 skipped, 1 error`; 기존 baseline 37 failed / 1 error 대비 신규 실패 0.

## P3-2 overlay build 검증 + PHASE1 측정 Contract

### Done

- [x] evasion 케이스가 `phase1-evasion-injection-spec.md`의 룰별 특정 벡터와 일치하는지 대조
- [x] skip 룰(L1-04/L2-01/L3-04/L4-01/D01/D02) 필수 입력이 overlay에 존재하는지 확인
- [x] overlay의 정상 subset(truth 제외) realism gate 29 재실행 → 무회귀
- [x] full v29+overlay에 PHASE1(P2-4 점수 포함) 실행, 룰별 3열: 입력갖춤 / 발화함 / 표준위반 catch
- [x] evasion 측정: 룰별 evasion이 PHASE1에 잡히나 / 놓치나 + 등수 밀림
- [x] 2+ 케이스 ripple, baseline 37 신규 0

### P3-2 v10 측정 메모

- Overlay v10 structure:
  - truth units 156 = 39 rules * standard 2 + evasion 2.
  - truth documents 746, overlay rows 1,492, output rows 984,520.
  - journal forbidden truth/provenance columns 0, local oracle findings 0.
- Evasion vector:
  - 39/39 rule rows have nonblank, rule-specific vectors; generic/blank vectors 0.
  - 일부 영어 sidecar 문구와 한국어 spec 문구는 loose token matcher에서 false로 나왔지만 수동 확인상 generic은 아니다.
- Skip-rule input:
  - L1-04/L3-04/L4-01/D01/D02 필수 입력은 truth rows에서 존재/nonnull.
  - L2-01은 approval/local_amount/date 입력은 갖췄지만 truth rows의 `trading_partner`는 nonblank 0이다. L2-01 표준 미발화 원인 후보다.
- Normal subset realism:
  - truth documents 746 제외 후 rows 983,028.
  - verifier 호환을 위해 임시 subset에 `is_fraud/is_anomaly=false`, `fraud_type/anomaly_type=""` 추가.
  - result: 22 PASS / 7 BLOCKED / 3 INFO / 0 FAIL. BLOCKED는 임시 subset에 balance/TB/subledger artifact를 복사하지 않아 발생.
- PHASE1 full measurement:
  - detectors 314.060s, build 1,959.124s, total 2,324.787s.
  - cases 35,535, units 72,874.
  - `L3-04` 337,509 row flags, `L4-04` 44,493 row flags, `L3-02` 76,957 row flags.
  - v10은 clean benchmark로 바로 쓰기 어렵다. 특히 `is_period_end` object/string boolean을 detector가 `astype(bool)`로 처리하는 경로 때문에 normal/overlay rows에서 L3-04가 과발화한다.
- Measurement artifact:
  - `.tmp_pytest_workspace/p3_2_v10_measurement.json`
- Regression:
  - export/PHASE2 overlay ripple 164 passed.
  - 전체 suite `37 failed, 4453 passed, 133 skipped, 1 error`; 기존 baseline 대비 신규 실패 0.

## P3-2 측정 무효화 버그 수정 + 재측정 Contract

### Done

- [ ] `is_period_end`를 proper bool로 출력/로드해 `"False"` 문자열 truthy 문제 제거
- [ ] detector boolean 파싱 robust화: 문자열 `"False"`/`"true"` 등을 올바른 bool로 처리하고 `astype(bool)` 직접 사용 금지
- [ ] L2-01 표준 위반 주입에 `trading_partner` 등 필수 입력을 채워 발화 가능하게 수정
- [ ] realism subset harness: balance/TB/subledger artifact를 subset에 복사해 29 gate 전부 재실행
- [ ] full v29+overlay PHASE1(P2-4 점수) 재측정: 룰별 3열 + evasion catch/miss + 등수
- [ ] 정상 units가 버그 전 수준으로 복귀하고 build 시간 정상화 확인
- [ ] 2+ 케이스 ripple, baseline 37 신규 0
