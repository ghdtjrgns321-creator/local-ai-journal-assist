# PHASE1 미해결/의심 이슈 추적 (고정, 2026-06-11)

> PHASE1 결과 재점검에서 추출한 미해결·미검증 전수. 우선순위대로 해결하며 상태를 갱신한다.
> 정상 과탐 측정: [PHASE1_NORMAL_FP.md](PHASE1_NORMAL_FP.md), 종합 검증:
> [PHASE1_VERIFICATION.md](PHASE1_VERIFICATION.md).

## 상태 요약

| # | 이슈 | 분류 | 상태 |
|---|------|------|------|
| — | L1-03 무효계정 과탐(신규계정 글로벌 CoA 누락) | 데이터정합 | ✅ 해결 (CoA 17계정 추가 → 0) |
| — | L1-02 필수필드 누락 거짓발화(document_date 형식 비일관) | 파이프라인 | ✅ 해결 (날짜 파싱 ISO8601 → 0) |
| 1 | 광역 발화 룰이 진짜 검토모집단인지 (priority band) | 미검증 | ⚠️ **부분 정정(2026-06-12)** — "정상 high/medium 0"은 legacy 경로 측정의 착시. 제품 경로(topic ON) 실측: high 0 유지·medium 3,516(9.3%). 수용성은 #14 |
| 2 | stale 테스트 2건 (rule_count·priority_band SoT-lag) | 회귀 | ✅ 해결 (테스트 SoT 정합: count 70, band 0.90/0.75) |
| 3 | Tier3 reversal disjoint 8문서 중복 소속 | 단위정합 버그 | ✅ 해결 (문서단위 dedup, v23 재빌드 8→0 disjoint_pass true) |
| 4 | KPI 가드 미작동 (아티팩트 노후 + raw 부재) | 검증 인프라 | ✅ 해결 (v32-full/r23 baseline 재정의, 가드 15/15 PASS·skip 0 — 2026-06-11) |
| 5 | L2-04 측정도구 부재, IC01 review detector-only 미집계 | 측정 갭 | ⬜ 보류 (+D01/D02 review 신호 미표면 확정 — case·macro 어느 레인에도 없음, 이슈 9 참조) |
| 6 | **L3-11 스펙-구현 갭** — DETECTION_RULES.md:306·settings 주석은 "기본 경로에서 `EvidenceDetector(rule_ids=("L3-11",))` 실행"을 선언하나 그 배선이 pipeline.py에 구현된 적 없음(git 전 이력 0건). IC/GR/EV 기본 제외는 **문서화된 의도**(DETECTION_RULES.md:307)로 확인 — 당초 "8룰 미실행" 과진단을 정정(2026-06-11 재검증) | 스펙-구현 불일치 | ✅ 해결 (base 경로에 L3-11-only EvidenceDetector 배선 + 회귀 테스트 2건 잠금. pipeline/detection/rulebase 1,587 passed 신규 실패 0 — 2026-06-11) |
| 11 | 죽은 코드 잔존 — `_try_evidence/graph/nlp_detection`(pipeline.py)은 enable 플래그를 켜도 호출부가 없음 (플래그 의미 불일치) | 코드 위생 | ⬜ 권고 (정리 또는 플래그 문서 정정) |
| 12 | L4-06 truth 30건 — detector 직접 발화(score>0)는 전건 포착되나 unit/case/macro 어디에도 미부착 (r23 실측). 발화 행이 단위 흡수에서 떨어지는 경로 규명 필요 | surface 정의 갭 | ⬜ 보류 (이슈 9와 함께 surface 정의 시 처리) |
| 13 | D01/D02 대시보드 "스킵됨" 오표시 — review 신호(점수 0)를 냈는데 flag_count 0이라 룰 패널이 스킵으로 표시 (`tab_phase1.py:826-832`) | 표시 정확성 | ⬜ 보류 (이슈 9 해소 방향과 함께 결정) |
| 7 | 침묵 비활성 룰 11개 — 필수 입력 부재 시 경고 없이 0건 (L2-01, L3-05~09, L2-05, L4-03/04/06, IC01~03) | 관측성 갭 | ⬜ 권고 (coverage_issues metadata 통일 노출) |
| 8 | 이슈 1 "정상 high/medium 0" 입증이 4트랙 기준 측정 — full 트랙(EV·IC·GR·D 포함) 재확인 필요 | 측정 도구 사각 | ⚠️ 당시 결론도 legacy 경로 한정 — topic ON 재측정으로 #14로 대체 |
| 14 | **정상 medium 3,516건(9.3%)의 운영 수용성** — topic scoring(검토모집단 룰 결합 floor)이 정상 케이스를 medium으로 올림 (v41 실측, high는 0). 검토 후보로 적정인가, floor 설계 조정 대상인가 | 도메인 결정 | ✅ **해소 (2026-06-12, 사용자 결정: 1+2 세트)** — 표본 검토 결과 대부분이 자동 결산 배치 전표를 fraud-combo floor가 오인 승격한 것. ① floor에 신뢰 자동전표 게이트(`source_trust.py` + `fraud_combo_rule_scope`) ② L4-06 `lone_batch_identity` 위장 탐지 확장을 한 세트로 적용. v41 medium **3,516→1,029(-71%)**·high 0 유지, r24 truth band(79.0%) 영향 0. 상세: [PHASE1_VERIFICATION.md](PHASE1_VERIFICATION.md) §2 |
| 15 | 측정 하니스 결함 2호 — 빈 phase1_case_config로 use_topic_scoring=False(legacy 경로 측정). get_phase1_case 로드로 수정, §9 절차에 체크 추가 | 검증 인프라 | ✅ 해결 (2026-06-12, r24·v41 topic ON 재측정 완료) |
| 16 | **source 위장 갭** — 39룰 전부 source 필드를 신뢰하는 전제. 사람이 source='automated'로 위장하면 L4-06은 배치로 분류하고 L3-06은 점수를 깎아 위장이 이득을 보는 구조였음 (#14 게이트 설계 중 발견) | 탐지 갭 | ✅ 해소 (2026-06-12) — L4-06 4번째 서브패턴 `lone_batch_identity`(자동 source ∧ batch_id/job_id 결측 ∧ 같은 날 동류 ≤10)로 위장 의심 전표를 별도 플래그. 게이트 면제도 동일 기준으로 차단(`trusted_automated_mask`). v41 실측 lone 82건, r24에서 L4-06 발화 28,546→29,525행으로 위반 데이터 발화 확인. 발견 위치: [PHASE1_VERIFICATION.md](PHASE1_VERIFICATION.md) §2, 스펙: docs/spec/DETECTION_RULES.md L4-06 |
| 9 | D01/D02 review 신호 완전 미표면 — r23 truth 40건이 case·macro finding 어느 표면에도 없음 | surface 정의 갭 | ⬜ 보류 (variance review surface 정의 필요 — 이슈 5와 함께 처리) |
| 10 | 위반 low 묻힘 패턴 — L2-02/L2-03 중복 70건 전부 low(rank 4.6k~14.4k), L4-05 30건 low, L3-04 30/40 low | ranking 특성 | ⬜ 기록 (개선은 도메인 정합성 경로로만 — truth recall 튜닝 금지) |
| 17 | **floor 정책 스펙-구현 불일치** — `apply_topic_floors`가 버킷 불문 적용: L1-04 boundary(약신호 0.35)도 0.75 medium 직행(스펙은 critical/non_approver 한정), L2-02는 스펙 0.45·reference 한정 vs 구현 0.75·전 발화. 콤보도 review_candidate 발화를 트리거로 인정 | 코드-스펙 불일치 | ✅ **부분 해소 (2026-06-13, R1-A)** — registry `floor_eligible_labels` 게이트로 L1-04는 critical/non_approver만, L2-02는 reference_match만(`duplicate_reference_match` 0.45, yaml 동기) floor 적용. 재측정: r24 truth 853→783(L2-02 30유닛 스펙 정합 이탈), high·Top500 불변, 가드 17/17. **잔여**: 콤보의 review_candidate 트리거 인정(강도 무시)은 미해소 — R4 설계 논의 |
| 18 | **source 신뢰 비대칭** — source_trust 게이트가 콤보에만 연결. detector 내부의 source 신뢰 감면/제외(L3-06 심야 0.45→0.20, L1-05 자기승인 0점 소멸, L4-05 통째 제외, L1-04 review 강등, L1-06 모집단 이탈)는 미연결 — 위장이 가장 의심스러운 신호에서 이득을 보는 역설 잔존 | 설계 결정 | ✅ **부분 해소 (2026-06-13, R1-B)** — L3-06·L1-05·L4-05·L1-04 4곳의 source-leg에 `lone_automated_mask` 게이트 연결(위장 의심 행은 감면/제외/강등 불가, persona-leg는 범위 밖). 스펙 반영 완료(DETECTION_RULES.md 위장 게이트 불릿 4개). **잔여**: L1-06 human filter(created_by substring)는 source 기반이 아니라 별도 — R4 합류 |
| 19 | **유령 승인자 사각** — 마스터에 없는 approved_by는 L1-04 제외 ∧ L1-07 비후보, 소유 룰 전무. 승인일 시퀀스 타당성(역전·미래일) 검증 룰도 부재 | 탐지 갭 | ✅ **부분 해소 (2026-06-13, R2-B)** — feature `approver_in_master`(user_id 마스터 멤버십) + L1-07 `unknown_approver` 서브패턴(비공란 ∧ 마스터 미존재 → score 0.55, 마스터 부재 시 graceful 비활성). v41 정상 실측 0건(합성데이터 한정). **실데이터 한계**: ① 퇴사자/시점 정합(마스터 유효기간 vs 전표일) ② 표기 정규화(대소문자 — 기존 한도 조인과 함께 R4) — 검토등급 0.55 + 승인자값 annotation 노출로 감사인 대조 위임. **잔여**: 승인일 시퀀스(역전·미래일) 검증은 R4 |
| 20 | **macro 신호 점수 기여 0** — `macro_context_score` 가중치(0.03)가 항상 0인 죽은 가중치 | 코드 버그 | ✅ **해소(2026-06-15)** — 점수체계 tier 전환으로 가중합(macro_context_score 포함) 폐기 + macro(D01/D02/L4-02/Benford)를 PHASE1-1 RULE_SCORING_REGISTRY에서 제거→PHASE1-2 family 이관(SoT `PHASE1_TIER_EVIDENCE_BASIS.md` §6/§7). "죽은 가중치" 문제 소멸. L4-02 canonical 32→31 lock 정합 완료(2026-06-15, RULE_DETAIL_METADATA_V1_LOCK·전 활성 문서 sweep). |
| 21 | **legacy 병렬 채널 생존** — unit 경로 `max(topic, legacy)` 머지로 high 판정 실권이 legacy 층 | 설계 결정 | 🔶 **대부분 해소(2026-06-15)** — tier 전환으로 활성 경로 band가 tier(`_score_unit_hits`→`_derive`)로 결정, `max(topic,legacy)` band 채널 제거. high band floor 0.75 도달불가 문제는 tier HIGH(config floor·fraud-combo)로 해소(recall high 129→438). 잔여 순수 legacy(`_composite_sort_score`+use_topic_scoring=False)는 운영 inert |
| 22 | **repeat_score≥0.70 무조건 medium 승급** — priority_score 무관 band 승급(`_priority_band`). 정상 월 반복 전표 자동 medium | 설계 결정 | ✅ **해소 (2026-06-13, R1-C)** — 승급 분기·`repeat_score_promote` 설정 제거(어떤 스펙/락 문서에도 없던 미문서 동작). repeat는 topic 점수 가중(0.05)·tiebreak로만 기여. **가설 정정**: "IC 전건 medium의 원인"이라던 도메인 리뷰 추정은 실측으로 반증 — 제거 후에도 IC01~03 122케이스 전건 medium 유지(콤보 점수 기인). 영향은 unit 경로 승급분(truth medium 일부 low행) |
| 23 | **L3-12 보강신호 user-year ANY 집계** — 1년 중 수기 1건+기말 1건이면 보강 2개 충족 → 0.65 전행 투영, 정상 발화 97%로 신호성 상실·콤보 퇴화. admin persona는 역으로 0점(일반 직원보다 관대) | 설계 결정 | ⬜ 보류 — RULE_DOMAIN_REVIEW §1 |
| 24 | **L2-02 fallback 3종 발화 제약** — 스펙의 blank/mixed/amount fallback이 코드에 reason은 있으나 recurring 게이트에 막혀 사실상 발화 불가. 무reference 일회성 거래처 이중지급(고전 패턴) 미탐 | 코드-스펙 불일치 | ✅ **해소 (2026-06-13, R2-A)** — 발화 제약 블록을 통합 fallback 루프로 교체: blank(정확 금액만)·mixed(허용오차)·amount_partner(서로 다른 ref) 3종, 우선순위 mixed>amount>blank, recurring 억제(`_l202_recurring_profile` 3회+ 시리즈) 재사용, 45일 윈도우. floor는 reference_match만(R1-A 게이트 — fallback 미부착). **제목 정정**: 당초 "미구현(reason 0곳)"은 부정확 — HEAD에 reason 코드 존재(1101·1152행)하나 recurring 게이트로 발화 제약이었음(가설 정정) |
| 25 | **탐지 회피 면적 카탈로그** — 분할(L2-01/GR01/L4-02), 윈도우(L2-05 1일/7일·L2-02 45일), 통계 모집단 자기오염(L4-01/03/05), 자기신고 필드(L3-09 settled·L1-09 승인일), 원천 자산화(L2-04) 등. 합성데이터 포트폴리오 주장 범위상 완성 차단 아님 — PHASE2/향후 설계 입력 | 데이터 특성/기록 | ⬜ 기록 — RULE_DOMAIN_REVIEW §1·§2.7 (+ variance_layer.py:112-113 한글 mojibake 소수정 후보) |

> 이슈 6~8 상세: [PHASE1_VERIFICATION.md](PHASE1_VERIFICATION.md) (시점 리포트: [archive](../../archive/completed/PHASE1_VERIFICATION_EXTENDED_20260611.md))

## 우선순위 1 — 광역 발화 룰 priority band 측정 (가장 의심)

정상 데이터(v32, 992,764행)에서 광역 발화:

```
L3-12 업무범위  97.05%   L1-09 승인일누락 71.56%   L1-07 승인생략 70.58%
L3-02 수기분개  24.23%   L3-04 결산기     22.60%   L3-06 심야     10.33%
L3-05 주말       9.29%   L4-02 Benford     4.92%   L4-05/04        4.7/4.5%
```

- **의심:** "설계상 검토모집단이라 점수/우선순위로 차등된다"는 주장이 **측정으로 입증 안 됨**. 발화율(행이
  울렸나)만 봤고, 이것들이 high/medium 우선순위로 얼마나 올라가는지(=진짜 감사인 부담)는 미측정.
  특히 L3-12 97%는 "거의 전 행이 검토 대상"이라 정상인지 의심.
- **측정:** v32 정상에 case/unit build → priority_band(high/medium/low) 분포. "정상인데 high/medium 몇 %"가
  진짜 운영 과탐 베이스라인. 광역 발화 룰이 우선순위에서 걸러지면 정상(검토모집단), 그대로 high면 과탐.

### 결과 (입증, 2026-06-11)

v32 정상 99만 행 case build: **cases 34,853 / units 97,334**.

```
priority_band 분포:  high 0건 (0%)  |  medium 0건 (0%)  |  low 100%
priority_score:      min 0  p50 0.27  p90 0.40  p99 0.51  max 0.66   (>0: 99.4%, 0.5+: 410 case)
                     medium 임계 0.75 / high 임계 0.90 — 정상 최댓값 0.66은 둘 다 미도달
```

- **광역 발화 룰(L3-12 97%·L1-07/09 71%·L3-02 24% 등)은 진짜 검토모집단으로 입증.** row 발화는 광역이나
  case/unit priority에서 **전부 low로 차등**된다. 정상 데이터의 high/medium(감사인 우선 검토 부담) = **0건**.
- **hollow-PASS 아님:** priority_score가 0~0.66으로 정상 분포(99.4% >0, 410 case가 0.5+). 계산이 죽어서
  0이 아니라, 정상이라 medium/high 임계(0.75/0.90)를 자연히 안 넘는 것. 위반이 들어오면 score/floor로
  0.75+ 도달(v23 위반 빌드에서 critical/high 케이스 확인됨, VERIFICATION 참조).
- **결론:** PHASE1은 정상 데이터를 high/medium으로 한 건도 올리지 않는다(운영 과탐 0). 광역 row 발화율
  (정상발화%)은 과탐이 아니라 설계상 검토모집단이며 priority에서 정밀 차등됨.
- 산출물: `artifacts/phase1_priority_band_v32/`, case artifact `artifacts/phase1_cases/_anonymous/...v32...json`.

### 룰별 확정 (L3-12만이 아니다)

전체 band가 100% low이므로 어떤 룰이든 high/medium 0이지만, 룰별로도 못박았다. case 기준(review-only
룰 L3-12·L1-07은 unit evidence에 score 0이라 안 잡혀 **case의 raw_rule_hits 기준**으로 분해):

```
룰      cases  high med  low    max_score
L3-12  34067    0   0  34067   0.6642
L1-07  17320    0   0  17320   0.6642
L1-09  18504    0   0  18504   0.6642
L3-02  26130    0   0  26130   0.6642
L3-04  33754    0   0  33754   0.6642
L3-05/06/L4-01~06/D01/D02/L2-03/L3-03/L1-04 ... 전부 high 0 medium 0 low 100%
```

- **case 기준 측정 19룰 전부 high 0·medium 0·low 100%, max_score ≤0.66**(임계 medium 0.75/high 0.90
  미달). high/medium을 가진 룰 = **0개**. L3-12만이 아니라 모든 광역 발화 룰이 priority에서 차등됨.
- **측정 표준화:** priority_band 분포(unit/case high·medium·low + 광역룰 high/medium 기여)를
  `measure_phase1_current_p3_2.py` summary에 통합(`_priority_band_summary`). **PHASE1 결과를 낼 때마다
  항상 함께 산출**된다 — detector 발화율(row)만으로 운영 과탐을 오판하지 않도록.

## 우선순위 2 — stale 테스트 2건

- `tests/modules/detection/test_constants.py::test_rule_count` (룰 수 SoT-lag)
- `tests/test_settings.py::test_phase1_case_has_required_sections` (priority_band high 0.75 단언, SoT 0.90)
- SoT(코드/yaml)가 이동했는데 테스트가 옛값 단언 → SoT 확인 후 테스트 갱신.

## 우선순위 3 — Tier3 reversal disjoint 8문서 (해결)

- **현상:** 역분개 8문서가 2개 역분개 흐름에 중복 소속 → disjoint_pass=false (전수 0.0087%, L2-05 한정).
- **원인:** `_flow_units_from_l205_minimal_link_keys`가 세 L2-05 빌더(structural→one_to_one→rolling)를
  합칠 때, `seen_doc_sets`가 **완전 동일 문서집합만 dedup**해서 부분 겹침(one_to_one `{A,B}` +
  rolling `{A,B,C}`)을 못 막았다. 8문서 전부 `one_to_one_match` flow와 `rolling_zero_out_set` flow에
  동시 소속이었다.
- **수정:** `seen_documents` 문서 단위 집합 추가 — 이미 다른 reversal flow에 흡수된 문서를 포함하는
  후속 flow는 skip(우선순위 structural>one_to_one>rolling). 한 문서는 단일 primary flow로만 흡수.
- **검증:** v23 재빌드 실측 `documents_in_multiple_units` **8→0**, `disjoint_pass` false→true
  (units 92,221→92,219, 중복 flow 정리). 단위 테스트 80 passed(흡수 불변·회귀 0).
  단위 테스트가 이 버그를 못 잡았던 전수 사각이므로 전수 재현으로 확정.

## 보류 (4·5)

- **KPI 가드 미작동:** 아티팩트 25일+ 노후, manipulation_v2/contract_v2 raw 부재로 현재 코드 재검증 불가.
  데이터 재확보 또는 v32/r2 기반 baseline 재정의 필요(도메인 사유 명시).
- **L2-04 측정도구 / IC01 review detector-only 미집계:** PHASE2 핸드오프 의미 확정 시 정리.
