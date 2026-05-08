# datasynth_manipulation 탐지 결과

## 2026-05-08 ranking quality calibration profile

## 2026-05-08 non-rule evidence booster rerun

**핵심 결론**: `audit_evidence_score`를 추가했지만 High floor는 추가하지 않았다. 결과적으로 포착률과 contract noise cap은 유지됐고, 전체 Top/Topic Top 지표는 거의 변하지 않았다. 즉 이번 변경은 fitting 위험은 낮지만, 현 단계에서는 품질 개선 폭도 작다.

| 항목 | 결과 |
|---|---:|
| manipulation truth docs | 420 |
| score/rule/review 포착 | 420 |
| 미포착 | 0 |
| 전체 case Top10 truth docs | 0 |
| 전체 case Top50 truth docs | 6 |
| 전체 case Top100 truth docs | 39 |
| 전체 case Top500 truth docs | 129 |
| 전체 case Top1000 truth docs | 162 |

새 실행 산출물:

- manipulation checkpoint: `artifacts/phase1_manipulation_evidence_profile.json`
- manipulation case input cache: `artifacts/phase1_manipulation_evidence_case_input.pkl`
- manipulation case artifact: `artifacts/phase1_cases/_anonymous/phase1case__anonymous_datasynth_v126_profiled_phase1_20260508T105341Z.json`
- contract checkpoint: `artifacts/phase1_contract_evidence_profile.json`
- contract case input cache: `artifacts/phase1_contract_evidence_case_input.pkl`
- contract case artifact: `artifacts/phase1_cases/_anonymous/phase1case__anonymous_datasynth_v126_profiled_phase1_20260508T110050Z.json`
- 비교 분석 JSON: `artifacts/phase1_ranking_evidence_analysis.json`

### non-rule evidence 적용 결과

| topic | audit evidence case | high case delta | Top100 truth delta | contract high delta | 판단 |
|---|---:|---:|---:|---:|---|
| 원장기록·데이터정합성 | 0 | +0 | +0 | +0 | 영향 없음 |
| 승인·권한·업무분장 통제 | 2,150 | +0 | +0 | +0 | 안전하지만 ranking 개선 없음 |
| 결산·기간귀속·입력시점 | 2,038 | +0 | +0 | +0 | 너무 흔한 context라 순위 개선 제한 |
| 계정분류·거래실질 불일치 | 28 | +0 | +0 | +0 | 영향 작음 |
| 중복·상계·자금유출 | 5 | +0 | +0 | +0 | 현 데이터에서 evidence 희소 |
| 관계사·내부거래·순환구조 | 0 | +0 | +0 | +0 | 현재 case rows만으로 cycle 증거 생성 안 됨 |
| 수익·금액·모집단 통계 이상 | 209 | +0 | +0 | +0 | 증빙 gap만으로는 부족 |

### 시나리오별 기대 topic 결과

| scenario | 기대 topic | truth docs | expected topic docs | high truth | Top50 | Top100 | Top200 |
|---|---|---:|---:|---:|---:|---:|---:|
| approval_sod_bypass | 승인·권한 | 29 | 15 | 13 | 4 | 10 | 13 |
| circular_related_party_transaction | 관계사·내부거래 | 34 | 13 | 0 | 0 | 0 | 0 |
| embezzlement_concealment | 중복·자금유출 | 76 | 0 | 0 | 0 | 0 | 0 |
| fictitious_entry | 수익·금액 | 168 | 0 | 0 | 0 | 0 | 0 |
| period_end_adjustment_manipulation | 결산·기간귀속 | 92 | 49 | 0 | 0 | 15 | 21 |
| unusual_timing_manipulation | 결산·기간귀속 | 21 | 7 | 0 | 0 | 0 | 1 |

### 판단

이번 변경은 fitting은 아니다. `is_fraud`, `fraud_type`, `manipulation_scenario`, label manifest를 scoring 입력으로 쓰지 않았고, 감사기준상 의미 있는 승인/증빙/마감/반제/관계사 context만 작은 booster로 반영했다. 다만 case row 안의 컬럼만으로 만든 evidence라서 실질적인 개선은 제한적이다. 다음 품질 개선은 전표 row가 아니라 master data, document flow, intercompany matched pair, approval matrix를 조인해서 독립 증거를 만들어야 한다.

## 2026-05-08 independent evidence join rerun

**핵심 결론**: master data, document flows, intercompany matched pairs, approval matrix를 조인했지만 High floor는 추가하지 않았다. manipulation 포착률과 Top 지표는 유지됐고, contract High 증가도 0건이다. 다만 document flow orphan과 approval matrix gap이 정상군에도 매우 넓게 붙어서 ranking 개선 효과는 없었다.

새 실행 산출물:

- manipulation checkpoint: `artifacts/phase1_manipulation_independent_evidence_profile.json`
- manipulation case input cache: `artifacts/phase1_manipulation_independent_evidence_case_input.pkl`
- manipulation case artifact: `artifacts/phase1_cases/_anonymous/phase1case__anonymous_datasynth_v126_profiled_phase1_20260508T130507Z.json`
- contract checkpoint: `artifacts/phase1_contract_independent_evidence_profile.json`
- contract case input cache: `artifacts/phase1_contract_independent_evidence_case_input.pkl`
- contract case artifact: `artifacts/phase1_cases/_anonymous/phase1case__anonymous_datasynth_v126_profiled_phase1_20260508T131255Z.json`
- 비교 분석 JSON: `artifacts/phase1_ranking_independent_evidence_analysis.json`

### 독립 evidence 조인량

| evidence | manipulation rows | contract rows | 판단 |
|---|---:|---:|---|
| known counterparty | 277,504 | 536,574 | master join 정상 작동 |
| document flow orphan | 675,071 | 684,411 | 너무 넓음. 단독 ranking 근거로 부적합 |
| IC unmatched reference | 17 | 17 | 희소함. High floor 근거로 부족 |
| approval matrix gap | 617,266 | 826,935 | 너무 넓음. 정상 위임/시스템 흐름과 섞임 |
| approval limit exceeded | 1,344 | 10,629 | contract에서 더 큼. 단독 가점 확대 금지 |

### 결과 변화

| 항목 | 결과 |
|---|---:|
| manipulation truth docs | 420 |
| score/rule/review 포착 | 420 |
| 미포착 | 0 |
| 전체 case Top10 truth docs | 0 |
| 전체 case Top50 truth docs | 6 |
| 전체 case Top100 truth docs | 39 |
| 전체 case Top500 truth docs | 129 |
| 전체 case Top1000 truth docs | 162 |
| contract High delta | 0 |

### 이전 non-rule booster 대비 변화

| topic | audit evidence case delta | high case delta | Top100 truth delta | contract high delta |
|---|---:|---:|---:|---:|
| 원장기록·데이터정합성 | +0 | +0 | +0 | +0 |
| 승인·권한·업무분장 통제 | +431 | +0 | +0 | +0 |
| 결산·기간귀속·입력시점 | +0 | +0 | +0 | +0 |
| 계정분류·거래실질 불일치 | +33 | +0 | +0 | +0 |
| 중복·상계·자금유출 | +1 | +0 | +0 | +0 |
| 관계사·내부거래·순환구조 | +0 | +0 | +0 | +0 |
| 수익·금액·모집단 통계 이상 | +317 | +0 | +0 | +0 |

### 판단

이 변경은 fitting은 아니다. 조인 기준이 label/scenario가 아니라 master 존재성, 문서흐름 연결성, IC matched pair, 직원 승인권한이기 때문이다. 하지만 현재 구현의 `document_flow_orphan`과 `approval_matrix_gap`은 정상군에서도 너무 넓게 발생한다. 따라서 이 evidence를 High floor로 올리면 fitting은 아니더라도 noise 증폭이 된다.

다음 단계는 조인 자체가 아니라 조인 해석을 더 좁히는 것이다. 예를 들어 `document_flow_orphan`은 모든 reference 누락이 아니라 수익/지급/고액/수기 case에서 계약-출고-송장 또는 PO-GR-IV-PAY 중 핵심 선행문서가 누락된 경우만 써야 한다. `approval_matrix_gap`도 승인자 누락 전체가 아니라 승인한도 초과, 자기승인, 승인권한 없음, 작성자와 승인자의 관계 이상처럼 독립적으로 설명 가능한 항목만 남겨야 한다.

**한 줄 결론**: `manipulated_entry_truth` 420건은 계속 모두 score/rule/review 기준으로 포착된다. 이번 quality calibration은 High/Top 지표를 억지로 올리는 변경이 아니라, 정상 실무에서도 흔한 weak medium floor를 제거해 fitting 위험을 낮춘 변경이다. topic별 High/Top 지표는 이전 anti-fitting run과 동일하고, 약한 combo reason만 제거됐다.

## 실행 기준

- 실행 명령:
  `.venv\Scripts\python.exe tools\scripts\profile_phase1_v126.py --data-dir data\journal\primary\datasynth_manipulation --checkpoint artifacts\phase1_manipulation_quality_profile.json --cache-path artifacts\phase1_manipulation_quality_case_input.pkl`
- checkpoint: `artifacts/phase1_manipulation_quality_profile.json`
- case input cache: `artifacts/phase1_manipulation_quality_case_input.pkl`
- case artifact: `artifacts/phase1_cases/_anonymous/phase1case__anonymous_datasynth_v126_profiled_phase1_20260508T095701Z.json`
- 상세 산출 JSON: `artifacts/phase1_ranking_quality_analysis.json`
- 비교 기준 anti-fitting artifact: `artifacts/phase1_cases/_anonymous/phase1case__anonymous_datasynth_v126_profiled_phase1_20260508T090512Z.json`

산출 기준은 topic별 case를 `topic_score desc`, `triage_rank_score desc`, `total_amount desc`, `rule_count desc` 순서로 정렬한 뒤 Top10/Top50/Top100/Top200의 unique `manipulated_entry_truth.document_id`를 계산했다. High는 해당 topic score `>= 0.75` 기준이다.

## 전체 요약

| 항목 | 값 |
|---|---:|
| journal rows | 1,095,158 |
| documents | 317,505 |
| truth docs | 420 |
| score/rule/review 포착 | 420 |
| 미포착 | 0 |
| case count | 4,218 |
| 전체 case Top10 truth docs | 0 |
| 전체 case Top50 truth docs | 6 |
| 전체 case Top100 truth docs | 39 |
| 전체 case Top500 truth docs | 129 |
| 전체 case Top1000 truth docs | 162 |

새 8번째 topic/queue는 생성하지 않았다. 산출물의 topic은 기존 7개 topic이며, `fraud_scenario_tags`는 badge/context와 breakdown reason 추적에만 사용된다.

## Topic별 High Truth Docs

| topic | topic case | topic truth docs | high case | high truth docs |
|---|---:|---:|---:|---:|
| 원장기록·데이터정합성 | 132 | 0 | 0 | 0 |
| 승인·권한·업무분장 통제 | 2,732 | 234 | 157 | 75 |
| 결산·기간귀속·입력시점 | 2,814 | 197 | 8 | 0 |
| 계정분류·거래실질 불일치 | 895 | 4 | 0 | 0 |
| 중복·상계·자금유출 | 581 | 0 | 56 | 0 |
| 관계사·내부거래·순환구조 | 963 | 35 | 6 | 0 |
| 수익·금액·모집단 통계 이상 | 591 | 9 | 5 | 0 |

## Topic별 Top Truth Docs

| topic | Top10 truth | Top50 truth | Top100 truth | Top200 truth |
|---|---:|---:|---:|---:|
| 원장기록·데이터정합성 | 0 | 0 | 0 | 0 |
| 승인·권한·업무분장 통제 | 0 | 22 | 52 | 85 |
| 결산·기간귀속·입력시점 | 0 | 0 | 20 | 40 |
| 계정분류·거래실질 불일치 | 0 | 0 | 0 | 0 |
| 중복·상계·자금유출 | 0 | 0 | 0 | 0 |
| 관계사·내부거래·순환구조 | 0 | 0 | 1 | 13 |
| 수익·금액·모집단 통계 이상 | 1 | 4 | 4 | 4 |

## 조작 시나리오별 기대 Topic 진입

| scenario | 기대 topic | truth docs | expected topic docs | high truth | Top10 | Top50 | Top100 | Top200 | 판정 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| approval_sod_bypass | 승인·권한 | 29 | 15 | 13 | 0 | 4 | 10 | 14 | 일부 충족 |
| circular_related_party_transaction | 관계사·내부거래 | 34 | 13 | 0 | 0 | 0 | 0 | 0 | 후순위 |
| embezzlement_concealment | 중복·자금유출 | 76 | 0 | 0 | 0 | 0 | 0 | 0 | 미진입 |
| fictitious_entry | 수익·금액 | 168 | 0 | 0 | 0 | 0 | 0 | 0 | 미진입 |
| period_end_adjustment_manipulation | 결산·기간귀속 | 92 | 49 | 0 | 0 | 0 | 15 | 20 | 낮은 순위 |
| unusual_timing_manipulation | 결산·기간귀속 | 21 | 7 | 0 | 0 | 0 | 0 | 1 | 낮은 순위 |

참고로 `fictitious_entry`를 계정분류·거래실질 topic 기준으로도 확인했지만 High/Top100 truth는 0건이었다.

## combo profile 대비 변화

| topic | high truth delta | Top100 truth delta | high case delta | topic case delta |
|---|---:|---:|---:|---:|
| 원장기록·데이터정합성 | +0 | +0 | +0 | +0 |
| 승인·권한·업무분장 통제 | -6 | +0 | -12 | +0 |
| 결산·기간귀속·입력시점 | +0 | +5 | +0 | +0 |
| 계정분류·거래실질 불일치 | +0 | +0 | +0 | +0 |
| 중복·상계·자금유출 | +0 | -30 | +0 | -122 |
| 관계사·내부거래·순환구조 | -16 | -15 | -96 | +0 |
| 수익·금액·모집단 통계 이상 | +0 | -8 | +0 | -2,488 |

## quality calibration 대비 변화

이번 quality calibration은 약한 medium floor 제거가 목적이다. 따라서 topic별 High/Top100 수치는 이전 anti-fitting run과 동일하다.

| topic | topic case delta | high case delta | topic truth delta | high truth delta | Top100 truth delta |
|---|---:|---:|---:|---:|---:|
| 원장기록·데이터정합성 | +0 | +0 | +0 | +0 | +0 |
| 승인·권한·업무분장 통제 | +0 | +0 | +0 | +0 | +0 |
| 결산·기간귀속·입력시점 | +0 | +0 | +0 | +0 | +0 |
| 계정분류·거래실질 불일치 | +0 | +0 | +0 | +0 | +0 |
| 중복·상계·자금유출 | +0 | +0 | +0 | +0 | +0 |
| 관계사·내부거래·순환구조 | +0 | +0 | +0 | +0 | +0 |
| 수익·금액·모집단 통계 이상 | +0 | +0 | +0 | +0 | +0 |

## 제거된 weak medium floor reason

| weak medium floor | manipulation previous | manipulation now | contract previous | contract now | 판단 |
|---|---:|---:|---:|---:|---|
| `period_end + manual_adjustment + weak_description` | 1 | 0 | 119 | 0 | 결산수정 조작 floor가 아니라 context로 둠 |
| `reversal_or_offset + work_scope_concentration + manual_adjustment` | 7 | 0 | 112 | 0 | 횡령은폐 floor가 아니라 context로 둠 |
| `approval_bypass + manual_adjustment` | 20 | 0 | 14 | 0 | 승인우회 High/Medium floor 금지 |
| `approval_bypass + non_business_day_timing` | 2 | 0 | 14 | 0 | 휴일 승인만으로는 floor 금지 |

이 변경은 성능을 올리는 보정이 아니라 fitting 방지 보정이다. 실제 High/Top ranking은 변하지 않았지만, `topic_score_breakdown.fraud_combo_policy_ids`에서 정상 실무에서도 흔한 약한 reason이 제거됐다. 즉 감사인에게 보여주는 점수 근거의 품질이 올라갔다.

## 약한 floor 제거 영향

| 제거/약화한 조건 | 이전 효과 | anti-fitting 후 결과 |
|---|---|---|
| `L3-02 + L3-04 + L3-12` | 가공전표·결산수정 Medium floor를 넓게 생성 | 수익 topic case가 3,079건에서 591건으로 감소 |
| `approval_bypass + L3-02 + L3-12` | 횡령은폐 Medium floor로 승격 | 중복·상계·자금유출 topic truth가 0건으로 정리 |
| `L3-03 + L3-05 + (L3-02 or L3-12)` | 관계사 High floor를 넓게 생성 | 관계사 High truth 16건이 0건으로 감소 |
| `approval_bypass + L3-02/L3-05` | 승인우회 High 후보로 쉽게 승격 | 승인 topic High truth 81건에서 75건으로 소폭 감소 |

이 변화는 성능 악화라기보다 fitting 제거의 직접 결과다. datasynth truth 중 상당수는 금감원 지적사례나 감사이론상 강한 조작 근거라기보다 `manual`, `closing`, `work scope`, `timing` 같은 약한 context 조합으로 생성돼 있다. 해당 조합을 High/Medium floor로 쓰면 datasynth 점수는 좋아지지만 실제 회사 데이터에서는 정상 전표 noise까지 같이 끌어올릴 위험이 크다.

## 현재 score band

| band | case count | truth docs |
|---|---:|---:|
| closing_timing:low | 2,805 | 197 |
| approval_control:medium | 2,573 | 167 |
| intercompany_cycle:medium | 957 | 35 |
| account_logic:low | 894 | 4 |
| duplicate_outflow:low | 518 | 0 |
| revenue_statistical:low | 350 | 7 |
| revenue_statistical:medium | 236 | 4 |
| approval_control:high | 157 | 75 |
| duplicate_outflow:high | 56 | 0 |
| closing_timing:high | 8 | 0 |
| intercompany_cycle:high | 6 | 0 |
| revenue_statistical:high | 5 | 0 |

핵심은 `closing_timing`, `intercompany_cycle`, `revenue_statistical`에 truth가 아예 없는 것이 아니라 대부분 low/medium 또는 topic 외부에 머문다는 점이다. 따라서 다음 조정은 약한 rule 조합을 다시 floor로 되돌리는 방식이 아니라, 실제 조작 맥락을 설명하는 비-rule feature를 추가해야 한다.

## contract noise split 확인

- 실행 명령:
  `.venv\Scripts\python.exe tools\scripts\profile_phase1_v126.py --data-dir data\journal\primary\datasynth_contract --checkpoint artifacts\phase1_contract_quality_profile.json --cache-path artifacts\phase1_contract_quality_case_input.pkl`
- checkpoint: `artifacts/phase1_contract_quality_profile.json`
- case input cache: `artifacts/phase1_contract_quality_case_input.pkl`
- case artifact: `artifacts/phase1_cases/_anonymous/phase1case__anonymous_datasynth_v126_profiled_phase1_20260508T100428Z.json`
- noise 분석 JSON: `artifacts/phase1_ranking_quality_analysis.json`

`datasynth_contract`는 완전한 실제 정상 회사 데이터는 아니고 rule contract 검증용 fixture가 섞인 데이터다. 그래도 악의적 manipulation truth가 없는 비교군으로 보면, fraud combo가 정상/검증 fixture에서 얼마나 넓게 뜨는지 확인할 수 있다.

| topic | manipulation topic case | contract topic case | manipulation high case | contract high case | 해석 |
|---|---:|---:|---:|---:|---|
| 원장기록·데이터정합성 | 132 | 387 | 0 | 0 | 조작 전용 issue 아님 |
| 승인·권한·업무분장 통제 | 2,732 | 12,391 | 157 | 492 | 정상 운영/contract에서도 매우 넓음 |
| 결산·기간귀속·입력시점 | 2,814 | 13,875 | 8 | 907 | 가장 큰 noise 위험 |
| 계정분류·거래실질 불일치 | 895 | 4,764 | 0 | 0 | low context가 대부분 |
| 중복·상계·자금유출 | 581 | 769 | 56 | 439 | contract fixture 영향이 큼 |
| 관계사·내부거래·순환구조 | 963 | 6,750 | 6 | 7 | topic은 넓지만 High는 제한적 |
| 수익·금액·모집단 통계 이상 | 591 | 3,793 | 5 | 700 | 강한 noise 위험 |

## contract에서 많이 뜨는 fraud combo

| combo policy | contract case | 판단 |
|---|---:|---|
| `approval_control:work_scope_combo` | 12,356 | fraud floor가 아니라 운영 집중도 context로만 유지 |
| `intercompany_cycle:related_party_or_ic + amount_or_timing_anomaly` | 6,640 | 관계사+시점/금액만으로는 너무 넓음 |
| `revenue_statistical:revenue_or_amount_outlier + closing_or_batch_context` | 919 | 수익 조작 후보로 쓰기에는 정상 outlier가 많음 |
| `closing_timing:period_end_or_late_posting + high_amount + weak_description_or_sensitive_account` | 907 | 결산 High noise의 핵심 |
| `revenue_statistical:revenue_or_amount_outlier + manual_adjustment + rare_or_duplicate_pattern` | 700 | 수익 High noise의 핵심 |
| `approval_control:approval_bypass + high_amount_or_cutoff_or_strong_abnormal_timing` | 487 | 승인 High는 유지 가능하지만 정상군 비교 필요 |
| `closing_timing:period_end + manual_adjustment + weak_description` | 0 | 이번 calibration에서 floor 제거 |
| `duplicate_outflow:reversal_or_offset + work_scope_concentration + manual_adjustment` | 0 | 이번 calibration에서 floor 제거 |

따라서 다음 tuning에서 단순히 datasynth manipulation truth를 Top100에 더 넣기 위해 위 combo를 다시 올리면 contract 쪽 정상/fixture case도 같이 폭증한다. 특히 결산·수익은 manipulation보다 contract에서 High case가 훨씬 많아서, rule 조합 floor를 강화하는 방향은 맞지 않다.

## 확인 항목 결론

| 확인 항목 | 결과 |
|---|---|
| 못 잡은 문서가 있는가 | score/rule/review 기준 미포착 0건 |
| 악의적 조작 truth가 각 주제 High에 들어왔는가 | 승인 topic만 75건. 결산·관계사·수익·중복자금 High에는 기대 truth가 거의 없음 |
| 왜 Top에 못 들어오는가 | 약한 datasynth floor 제거 후 강한 감사 근거가 없는 truth는 low/medium 또는 topic 밖에 남음 |
| noise가 줄었는가 | 수익 topic case가 -2,488건, 중복자금 topic case가 -122건 줄어 fitting성 noise는 감소 |
| 문제는 무엇인가 | score 포착은 됐지만 기대 topic ranking으로 승격할 feature가 부족함 |

## 후속 조정 필요점

1. 결산 topic은 단순 `manual + closing + work scope`가 아니라 결산월 집중, 사후입력, 고액, 설명부족, 민감계정, 반복 수정 중 최소 2개 이상을 결합해야 한다.
2. 가공전표/수익 topic은 `L4-01/L4-03` 외에 수익성 계정, 비정상 document source, customer/vendor 실재성, 계정군 amount percentile 같은 비-rule feature를 붙여야 한다.
3. 횡령은폐 topic은 approval context만으로 올리지 말고 자금성 계정, 반제·상계, 중복 지급, vendor/employee 연결, 승인자-작성자 관계가 같이 나와야 한다.
4. 순환거래 topic은 관계사 flag만으로 High를 만들지 말고 counterparty chain, 같은 금액의 왕복, 월말 반복, 내부거래 제거/상계 불일치 같은 graph/relational feature가 필요하다.
5. ranking 목표는 `truth fitting`이 아니라 `contract noise cap`을 같이 둬야 한다. 예를 들어 조작 truth Top100을 올릴 때 contract High case가 함께 증가하면 실패로 본다.
