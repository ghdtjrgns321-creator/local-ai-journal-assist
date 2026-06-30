# PHASE1 Detection Ranking Criteria

> **PHASE1 역할 원칙**: PHASE1은 `fraud`를 확정하거나 정답 라벨을 맞히는 단계가 아니다. PHASE1의 목적은 전수 모집단에서 규칙 위반, 정책 위반, 이상 징후, 분석적 검토 신호를 넓게 올려 **감사인이 봐야 할 항목과 우선순위**를 만드는 것이다. DataSynth의 `is_fraud`/`is_anomaly`와 precision/recall은 개발 검증 보조 지표이며, 운영 해석은 예외 처리 대상, 감사인 리뷰 대상, 고위험 후보를 구분하는 review queue 기준으로 한다.


> **포트폴리오 주장 범위 (2026-05-19)**: 이 프로젝트는 `fraud`를 판정하거나 실제 운영 부정 탐지 성능을 보장하는 모델이 아니다. 전수 모집단에서 감사인이 먼저 볼 review queue를 만들고, 무작위 검토 대비 상위 구간에 review-worthy synthetic anomaly를 강하게 농축하는 로컬 감사 분석 보조 도구다. DataSynth 기반 precision/recall은 개발 검증 보조 지표이며, 실데이터 운영 성능으로 주장하지 않는다.
> **금지 표현**: "부정을 정확히 탐지", "실무 운영 성능 검증 완료", "TOP100 precision 충분", "fraud 확정/자동 적발"처럼 확정적이거나 운영 성능을 보장하는 표현은 사용하지 않는다.

Updated: 2026-05-20

> **Superseded by [PHASE1_TIER_EVIDENCE_BASIS.md](PHASE1_TIER_EVIDENCE_BASIS.md) (tier 체계, 2026-06-14)**: 아래의 가중합 점수식·floor 숫자값·`topic_score >= 0.90/0.75` band 컷은 근거 없는 숫자 정밀도로 판단되어 폐기됐다. band는 명명된 결정규칙(tier: HIGH/MEDIUM/LOW/CONTEXT, 순서형)으로 직접 결정하며, 연속 점수(`composite_sort_score`)는 tier 내부 정렬 tiebreak 전용이다. 또한 주제는 7개에서 6개로 줄었다(intercompany_cycle 삭제 → PHASE1-2 family로 이관). 본 문서의 가중합/숫자 band 서술은 역사적 맥락으로만 읽고, 운영 기준은 SoT를 따른다.

## 목적

이 문서는 PHASE1 결과를 어떤 기준으로 High/Top ranking에 올릴지 고정한다. 목표는 datasynth truth에 맞춘 점수 fitting이 아니라, 감사인이 먼저 볼 가치가 있는 전표와 case를 주제별로 정렬하는 것이다.

PHASE1 ranking은 전체 Top 하나로 판단하지 않는다. 결과는 6개 topic별로 정렬한다.

1. 원장기록·데이터정합성
2. 승인·권한·업무분장 통제
3. 결산·기간귀속·입력시점
4. 계정분류·거래실질 불일치
5. 중복·상계·자금유출
6. 수익·금액·모집단 통계 이상

> 옛 7번째 topic(관계사·내부거래·순환구조 / `intercompany_cycle`)은 삭제됐다. 순환거래·내부거래·관계사 구조는 한 전표로 안 보이는 구조 신호이므로 PHASE1-1 룰 topic이 아니라 PHASE1-2 family(graph/relational)의 정식 대상으로 이관됐다(SoT §7.3). IC01~03·GR01/03의 PHASE1 점수경로는 제거됐고, L3-03만 account_logic topic의 booster로 잔존한다.

`조작 후보`, `맥락 검토대상`, `추가검토사항`, `Audit Risk` 같은 표현은 primary ranking queue로 쓰지 않는다. 조작 해석은 6개 topic 내부의 `fraud_scenario_tags`, `topic_score_breakdown`, case narrative로만 표시한다.

## 기본 정렬 기준

Topic별 case ranking은 아래 순서로 정렬한다.

```text
topic_score desc
triage_rank_score desc
abs(total_amount) desc
rule_count desc
document_count desc
```

Topic tier는 명명된 결정규칙(순서형 HIGH/MEDIUM/LOW/CONTEXT)으로 직접 매핑한다. 구 숫자 컷(`topic_score >= 0.90/0.75/0.20`)은 폐기됐다. tier 정의·트리거는 SoT [`PHASE1_TIER_EVIDENCE_BASIS.md`](PHASE1_TIER_EVIDENCE_BASIS.md) §4~§6, [`PHASE1_TIER_SCORING_SPEC.md`](PHASE1_TIER_SCORING_SPEC.md) §2~§3 참조.

| tier    | 트리거                                                       | 의미                   |
| ------- | ------------------------------------------------------------ | ---------------------- |
| HIGH    | 해당 topic의 HIGH 조합 트리거 발화 + standalone primary 존재 | 먼저 봐야 할 case      |
| MEDIUM  | HIGH 없음 + MEDIUM 트리거 발화                               | 그다음 볼 case         |
| LOW     | HIGH/MEDIUM 없음 + primary 룰 단독 발화                      | 참고/drill-down        |
| CONTEXT | booster/macro/combo_only만 존재 (primary 없음)               | 단독 ranking 근거 아님 |

### Band 축 표기 정책

PHASE1 문서, 리포트, dashboard 설명에서는 band 축을 반드시 prefix로 명시한다. 단순 `high band`, `medium band`, `low band` 표현은 금지한다.

| 표기                               | 기준                                                                                                                                                                         | 사용 예                                                              |
| ---------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| `priority high/medium/low`         | case의 `priority_band` = case tier(HIGH/MEDIUM/LOW). 순서형 tier 직접 매핑(구 `priority_score >= 0.90/0.75` 컷 폐기). HIGH 즉시검토, MEDIUM 검토 후보, LOW 참고 후보.        | `priority high immediate review`, `priority medium review candidate` |
| `{topic_id} topic high/medium/low` | case의 topic별 tier(SoT `PHASE1_TIER_SCORING_SPEC.md` §2 cascade). HIGH=HIGH 조합 트리거 발화, MEDIUM=MEDIUM 트리거, LOW=primary 단독. (구 `>= 0.90/0.75/0.20` 숫자 컷 폐기) | `approval_control topic high`, `closing_timing topic medium`         |
| `{topic_id} topic membership`      | band와 무관하게 `topic_scores[topic_id] > 0`인 case membership.                                                                                                              | `closing_timing topic membership truth 410`                          |
| row `risk_level`                   | row-level `anomaly_score` 기준. case band와 별개다.                                                                                                                          | `row risk_level High 244`                                            |

운영 보고에서는 `priority high`, `approval_control topic high`, `closing_timing topic membership`처럼 축과 topic을 함께 적는다. `High 큐`, `medium 보존`, `high band 약점`처럼 축이 생략된 표현은 새 문서에서 사용하지 않는다.

### PHASE2 이관 전 priority medium 운영 정책

PHASE1 `priority medium` 및 topic별 `topic medium`은 보강 근거를 기다리는 review 보관소다. `closing_timing`처럼 High 승격 근거가 아직 부족하지만 추가 evidence로 보강될 수 있는 영역은 해당 priority/topic medium 축에 남겨 감사인이 검토할 수 있어야 한다. (단, 보강 surface는 단일 PHASE2가 아니라 PHASE1-2 family(graph/relational/시계열)와 PHASE2 VAE로 분리됐다 — SoT §7. 순환거래·관계사 구조는 PHASE1-2 family로 이관됐으므로 이 medium 보관소의 대상이 아니다.)

운영 기준은 다음과 같다.

| 기준      | 정책                                                                                                                                                       |
| --------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 노출      | topic 탭 ribbon과 룰 expander 헤더에 Medium case 수를 표시한다.                                                                                            |
| 상세 접근 | expander는 성능상 기본 collapsed 상태일 수 있으나, 사용자가 펼치면 case 목록과 위반 전표가 렌더되어야 한다.                                                |
| 정렬      | 전체 category queue는 `priority_band`를 먼저 적용하고 같은 band 안에서 `composite_sort_score`를 우선한다. topic-specific Top-N은 `topic_score`를 우선한다. |
| 해석      | Medium은 confirmed violation이 아니라 PHASE2 또는 감사인 검토에서 보강 판단할 review candidate다.                                                          |

`fraud_scenario_tags`는 display/context 필드다. tag가 있다고 해서 자동으로 High나 Top ranking에 올리지 않는다. High 승격은 topic score floor나 충분한 보강 근거가 있을 때만 가능하다.

> 행 `RISK_THRESHOLDS`(HIGH=0.50 / MEDIUM=0.25 / LOW=0.10, `src/detection/constants.py`)와 case `priority_band`(High=0.90 / Medium=0.75)는 서로 다른 축이다. 행 단위 risk_level은 `anomaly_score` 정규화 합산 기준이고, case 단위 priority_band는 case priority score 기준이다. 동일 case 내에서 행 risk_level과 case priority_band가 달라도 모순이 아니다 (산출 경로가 다름; `artifacts/archive/tier_superseded_20260615/phase1_score_band_audit.md` §4-2 참조).
>
> 한 줄 요약 (§9.4 §5-4): **행 risk_level (anomaly_score 축, warm 톤 ● 기호) ≠ case priority_band (priority_score 축, cool 톤 ◆ 기호)**. v2 high case 229 건 안의 row 68% 가 Normal/Low (`artifacts/archive/tier_superseded_20260615/phase1_score_band_audit.md` §4-2 crosstab) 인 것은 정상이며, dashboard 는 두 축을 다른 라벨·색상으로 분리 표시한다.

## 점수 구성 원칙

PHASE1 topic score는 단일 rule hit가 아니라 서로 다른 감사 증거 축의 결합으로 계산한다.

> 구 가중합 점수식(`0.62·max_primary + 0.08·secondary + …`)은 **제거됐다**. 근거 없는 임의 계수로 판단되어 tier(명명된 결정규칙)로 대체됐다(SoT `PHASE1_TIER_EVIDENCE_BASIS.md` §3). 아래 "점수 구성 원칙"은 가중합 식이 아니라 **tier 트리거 설계 원칙**으로 읽는다 — 어떤 증거 축이 결합돼야 HIGH가 되는가에 대한 정책이며, 숫자 가중치는 없다.

원칙은 다음과 같다.

| 원칙                | 설명                                                                                                             |
| ------------------- | ---------------------------------------------------------------------------------------------------------------- |
| Primary seed 필요   | topic에 들어오려면 해당 topic의 primary evidence가 있어야 한다. booster, macro, tag만으로 Top N에 올리지 않는다. |
| 강한 floor는 제한   | High floor는 감사기준·금감원 지적사례상 강한 조합에만 둔다.                                                      |
| 약한 context는 보조 | 수기, 결산, 업무범위 집중, 휴일 입력은 정상 실무에서도 흔하므로 단독 또는 약한 조합으로 High를 만들지 않는다.    |
| 주제별 ranking 유지 | 전체 Top이 아니라 topic별 High/Top을 본다. 조작 subtype도 해당 topic 안에서 평가한다.                            |
| noise cap 병행      | manipulation truth Top100이 올라가더라도 contract/normal High case가 같이 폭증하면 실패로 본다.                  |

## 점수 근거 요약

점수는 임의 가중치가 아니라 [DETECTION_REFERENCE.md](DETECTION_REFERENCE.md)의 감사기준, 금감원 감리지적사례, 내부회계 근거를 기준으로 부여한다.

| 근거                 | ranking 반영                                                                                                                                                                                                        |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 감사기준서 240호 §32 | 감사인은 총계정원장의 분개기입과 재무제표 작성 과정의 기타 수정사항 적정성을 테스트해야 한다. 따라서 PHASE1 전체 rule hit는 journal entry test 모집단 식별 근거다.                                                  |
| 감사기준서 240호 A44 | 부정은 보고기간 말 또는 보고기간 전체의 비인가·부적절 분개기입으로 발생할 수 있다. 따라서 결산말, 마감후, 연중 반복 이상을 ranking 보강 축으로 둔다.                                                                |
| 감사기준서 240호 A45 | 부정한 분개는 비경상 계정, 통상 입력하지 않는 사용자, 기말/마감후 입력, 설명 부족, 계정번호 누락, round number 같은 식별 특성을 가진다. 이 항목을 High floor의 seed/booster로 쓴다.                                 |
| 감사기준서 240호 A46 | CAATs로 비정상 분개기입을 식별할 수 있다. PHASE1 rule scoring과 topic ranking은 이 CAATs 선별 절차의 구현이다.                                                                                                      |
| 외감법 §8 / K-SOX    | 업무분장, 승인권한, 내부회계관리제도에 따른 회계정보 작성 의무를 요구한다. 자기승인, SoD 충돌, 승인생략, 승인한도 초과는 승인·권한 topic의 핵심 근거다.                                                             |
| 감사기준서 315호 §26 | 분개기입 통제와 비표준 분개기입 통제 이해가 필요하다. 수기전표, 비표준 전표, 승인흐름 이상은 단독 확정이 아니라 통제 위험 근거로 반영한다.                                                                          |
| 감사기준서 550호 §23 | 정상 영업과정을 벗어난 유의적 특수관계자 거래의 사업상 합리성과 승인조건을 평가해야 한다. 관계사·내부거래·순환구조 신호는 PHASE1-1 룰 topic이 아니라 PHASE1-2 family(graph/relational)의 근거로 이관됐다(SoT §7.3). |
| 감사기준서 520호 §5  | 기대값 개발과 차이 분석을 통한 분석적절차를 요구한다. 금액·분포·모집단 이상은 수익·금액 topic의 보조 근거다.                                                                                                        |
| 감사기준서 500호     | 감사증거의 충분성과 적합성이 필요하다. rule hit만으로 조작 확정하지 않고 증빙, 상대방, 문서흐름 같은 비-rule feature를 요구하는 근거다.                                                                             |
| 감사기준서 1100호    | 내부회계관리제도 감사 관점에서 통제 운영 효과성을 본다. 승인·업무분장·수기전표 통제 실패를 case ranking에 반영한다.                                                                                                 |

금감원 감리지적사례 189건 분석 결과도 floor 우선순위에 직접 반영한다.

| 금감원 패턴    | 건수 | ranking 반영                                                                                                                                                                                                                                                                            |
| -------------- | ---: | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 가공 전표      |   50 | 최다 패턴이다. 수익/금액 이상, 수기전표, 희소계정, 중복·비정상 문서흐름이 결합될 때 수익·금액 topic High 후보로 본다.                                                                                                                                                                   |
| 결산 수정 조작 |   27 | 손상 미인식, 충당금 환입, 원가 이연 등 결산 judgment 조작이 핵심이다. 결산말/사후입력 + 고액 + 설명부족/민감계정 조합을 High 후보로 본다.                                                                                                                                               |
| 횡령 은폐      |   24 | 선급금, 대여금, 매출채권 허위계상 등으로 횡령액을 숨기는 패턴이다. 자금성 계정, 중복/상계/반제, 승인통제 실패가 함께 있어야 High로 올린다.                                                                                                                                              |
| 순환거래       |   10 | 페이퍼컴퍼니·특수관계자 간 가공매출 순환이다. 관계사 flag만으로 부족하고 counterparty cycle, 동일 금액 왕복, IC exception이 필요하다. → 한 전표로 안 보이는 구조 신호이므로 PHASE1-1 룰 topic이 아니라 **PHASE1-2 family(graph)로 이관**됐다(SoT §7.3). 아래 건수는 역사적 분류 수치다. |
| 승인/SoD 위반  |    5 | 1인 입력·승인·실행, 이사회 미의결 등 통제 우회 사례다. 단독 subtype보다는 횡령은폐와 승인우회 승격 근거로 쓴다.                                                                                                                                                                         |
| 비정상 시점    |    4 | 연말 밀어내기, 납품 전 조기인식 같은 시점 조작이다. 단독 High가 아니라 cutoff, 수익, 결산, 증빙 근거와 결합해야 한다.                                                                                                                                                                   |

이 근거 때문에 High floor는 “rule이 많이 걸림”이 아니라 “감사기준과 금감원 사례에서 반복적으로 확인된 조작 구조가 결합됨”일 때만 적용한다.

## Fitting 없이 품질을 높이는 실행 정책

검색으로 확인한 외부 기준과 연구 결과를 PHASE1 운영 정책에 반영한다.

| 외부 근거                             | 적용 정책                                                                                                                                                                                                      |
| ------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| PCAOB Audit Focus: Journal Entries    | fraud criteria에 걸린 전표를 선정하고, 선정/제외 근거를 문서화해야 한다. 따라서 `topic_score_breakdown`에 floor reason을 남기고, 약한 context만으로 제외/승격하지 않는다.                                      |
| PCAOB AS 2401 / AU 316.61             | manual 여부만으로 충분하지 않고 unusual account, uncommon user, period-end, little/no explanation, intercompany, nonstandard entry 등 복수 특성을 함께 본다. 따라서 High는 최소 2~3개 독립 증거 축이 필요하다. |
| AS 1105 audit evidence                | journal population의 완전성·정확성과 증거 적합성이 필요하다. 따라서 rule hit만으로 조작 확정하지 않고 증빙, 상대방, 승인흐름, 문서흐름 feature를 붙인다.                                                       |
| Imbalanced data cross-validation 연구 | synthetic minority pattern을 train/test에 같이 넣으면 성능이 과대평가된다. 따라서 random split이 아니라 scenario, 연도, 회사, 정상군 holdout을 둔다.                                                           |
| Concept drift 연구                    | 회사별 정상 업무 패턴은 시간에 따라 바뀐다. 따라서 고정 threshold만 쓰지 않고 회사/기간별 baseline과 drift monitor를 둔다.                                                                                     |

실행 기준은 다음과 같다.

| 기준                   | 통과 조건                                                                                                                       |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| manipulation recall    | `manipulated_entry_truth`가 score/rule/review 기준으로 포착되어야 한다.                                                         |
| topic precision@K      | 전체 Top100이 아니라 기대 topic별 Top50/Top100 truth를 본다.                                                                    |
| contract noise cap     | 새 floor 추가 후 contract High case가 크게 늘면 reject한다.                                                                     |
| weak context demotion  | `manual`, `closing`, `work_scope`, `holiday`, `related_party` 단순 조합은 floor가 아니라 context/tag로 둔다.                    |
| holdout validation     | 특정 datasynth subtype에 맞춘 변경은 scenario/year/company holdout에서 다시 본다.                                               |
| non-rule feature first | 성능 부족을 rule floor 강화로 해결하지 않고, source, approval matrix, counterparty chain, 증빙 연결 같은 feature를 먼저 붙인다. |

이번 scoring 수정의 적용 원칙은 “High를 더 많이 만드는 것”이 아니라 “정상 실무에서도 흔한 medium floor를 제거하여 Top/High ranking의 설명력을 높이는 것”이다.

### 2026-05-08 non-rule evidence calibration

> **[역사 기록 — 가중치 폐기]** 아래 `audit_evidence_score 0.06 가중치` 등 가중합 booster 수치는 tier 전환으로 폐기됐다. 다만 "어떤 비-rule 증거 축을 어느 topic에 붙이는가"라는 피처 설계 의도는 tier 트리거의 2차정황 풀로 계승됐으므로, 아래 표는 **피처-topic 매핑 설계 근거**로만 읽는다(가중치 숫자는 무효).

이번 단계에서는 High floor를 추가하지 않고 `audit_evidence_score`를 0.06 가중치의 작은 booster로만 추가한다. 이 score는 topic에 이미 rankable primary rule hit가 있을 때만 반영되며, 단독으로 topic score나 High case를 만들 수 없다.

| evidence axis             | source columns                                                    | affected topic                                        | fitting guardrail                                                                                                                    |
| ------------------------- | ----------------------------------------------------------------- | ----------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| approval relationship gap | `created_by`, `approved_by`, `approval_date`, `posting_date`      | approval_control                                      | label/scenario를 보지 않고 자기승인, 승인자 누락, 승인일 역전만 본다.                                                                |
| support/documentation gap | `has_attachment`, `supporting_doc_type`, `source`, `user_persona` | revenue_statistical, account_logic                    | 수기 context와 고액/수익 이상 rule이 있을 때만 작은 booster로 반영한다.                                                              |
| post-close context        | `posting_date`, `document_date`                                   | closing_timing                                        | 결산/마감 context를 High floor로 쓰지 않고 rule hit가 있는 case의 정렬 보조로만 쓴다.                                                |
| reversal/clearing context | `lettrage`, `settlement_status`, `is_cleared`                     | duplicate_outflow                                     | duplicate/outflow rule이 있는 case 안에서만 보조 점수로 쓴다.                                                                        |
| related-party context     | `trading_partner`, `business_process`, `reference`                | PHASE1-2 family (구 intercompany_cycle topic, 이관됨) | 관계사 자체를 High로 올리지 않는다. 관계사·내부거래·순환구조 신호는 PHASE1-2 family(graph/relational)의 책임으로 이관됐다(SoT §7.3). |

이 보정은 datasynth의 `is_fraud`, `fraud_type`, `scenario`, `manipulated_entry_truth`, label manifest를 scoring 입력으로 사용하지 않는다.

### 2026-05-08 independent evidence join calibration

다음 단계에서는 전표 row 안의 얕은 context만 보지 않고, 실제 감사 증거에 가까운 독립 파일을 조인한다. 단, 이 조인도 High floor를 만들지 않고 `audit_evidence_score`의 작은 booster로만 쓴다.

| independent source                           | join key                                                    | generated evidence                                                                              | affected topic                                                  | fitting guardrail                                                                                                                         |
| -------------------------------------------- | ----------------------------------------------------------- | ----------------------------------------------------------------------------------------------- | --------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| `master_data/vendors.json`, `customers.json` | `auxiliary_account_number`, `trading_partner`               | `master_counterparty_known`, `master_counterparty_inactive`, `master_counterparty_intercompany` | account_logic, duplicate_outflow, PHASE1-2 family (관계사 속성) | 특정 거래처 id를 외우지 않고 존재/활성/관계사 속성만 본다. 관계사 속성 신호는 PHASE1-2 family로 이관됨(SoT §7.3).                         |
| `document_flows/*.json`                      | `reference`에서 추출한 PO/GR/VI/PAY/SO/CI/DLV id            | `document_flow_linked`, `document_flow_orphan`                                                  | revenue_statistical, account_logic, duplicate_outflow           | 문서흐름 존재 여부만 보며 manipulation label을 보지 않는다.                                                                               |
| `intercompany/ic_matched_pairs.json`         | `reference`의 IC reference 또는 IC seller/buyer document id | `ic_matched_pair_found`, `ic_unmatched_reference`                                               | PHASE1-2 family (구 intercompany_cycle, 이관됨)                 | 관계사 자체가 아니라 matched pair 존재/누락만 본다. IC matched pair·순환구조 신호는 PHASE1-2 family(graph/relational)로 이관됨(SoT §7.3). |
| `master_data/employees.json`                 | `created_by`, `approved_by`                                 | `approval_matrix_gap`, `approval_limit_exceeded_independent`                                    | approval_control                                                | 사용자 id 자체가 아니라 승인권한/승인한도/회사권한만 본다.                                                                                |

이 조인은 synthetic label과 무관해야 하며, manipulation Top100 개선만으로 채택하지 않는다. 채택 기준은 `manipulation recall 유지`, `topic Top 개선`, `contract High 증가 제한`, `feature reason 설명 가능성`을 동시에 본다.

## High 승격 가능 조건

아래 조건은 fraud 확정이 아니라 감사 검토 우선순위 승격 기준이다.

| 조작 subtype       | 승격 topic                 | High 승격 기준                                                                                                                                                                                                                                         | 점수 근거                                                                                                                                                                                                                   |
| ------------------ | -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 가공전표 의심      | 수익·금액·모집단 통계 이상 | `(L4-01 or L4-03) + L3-02 + 2차정황1개` <br>2차정황 = `L4-04/L2-03/L3-03/L3-10/L1-05/L3-11` 중 하나 (A안 확장, L3-04·L1-09는 과탐 가드 제외, `HIGH_COMBO_GROUNDING.md` §5b)                                                                            | 금감원 189건 중 가공 전표 50건으로 최다. 240호 A45의 수기/비경상/희소계정/분포 이상 특성과 PCAOB AS 2401의 unusual journal entry 특성에 해당한다. HIGH 17건 재감사로 2차정황 풀 확장 후 정상 데이터 과탐 측정(0.334% ≤ 2%). |
| 결산수정 조작 의심 | 결산·기간귀속·입력시점     | `(L3-04 or L3-07 or L3-11 or L1-08) + L4-03 + (L3-10 or L4-04)`                                                                                                                                                                                        | 금감원 결산 수정 27건. 240호 §32(a)(ii)는 보고기간 말 분개 검사를 요구하고, A45(c)는 기말/마감후 입력과 설명 부족을 부정 분개 특성으로 본다.                                                                                |
| 횡령은폐 의심      | 중복·상계·자금유출         | `(L2-02 or L2-03 or L2-05) + [승인우회(L1-04~07) or (L2-05 역분개 + L3-02 수기)]` (A안 완화, `HIGH_COMBO_GROUNDING.md` §5b)                                                                                                                            | 금감원 횡령 은폐 24건, 오스템 사례처럼 입력·승인·이체 통제 우회가 동반된다. 외감법 §8/K-SOX의 업무분장·승인통제 근거와 연결된다. 단 승인 흔적 없는 은폐(역분개+수기)도 실증에서 확인돼 분기 추가.                           |
| 순환거래 의심      | (→ PHASE1-2 family로 이관) | PHASE1-1 룰 조합 아님. 한 전표로 안 보이는 구조 신호이므로 **PHASE1-2 family(graph/relational) 탐지기**가 맡는다(counterparty cycle, 동일 금액 왕복, IC 제거 불일치). IC01~03·GR01/03 PHASE1 점수경로는 제거됐고 L3-03만 account_logic booster로 잔존. | 금감원 순환거래 10건, 감사기준서 550호 §23·IFRS 10 §B86·K-IFRS 1110/1024·ISA 600/550은 PHASE1-2 귀속 근거다(SoT §7.3).                                                                                                      |
| 승인우회 조작 의심 | 승인·권한·업무분장 통제    | `(L1-04 or L1-05 or L1-06 or L1-07) + 강한 보강근거`                                                                                                                                                                                                   | 금감원 승인/SoD 위반 5건과 K-SOX 통제 운영 효과성 근거가 있다. 단독 승인 예외가 아니라 고액·수기·결산·비정상시간과 결합될 때 High로 본다.                                                                                   |

승인우회의 강한 보강근거는 `L4-03`, `L3-11`, `L3-04 + L3-02`, `L3-06 + L3-02`처럼 고액, cutoff, 결산 수기, 강한 비정상 시간대와 결합된 경우를 말한다.

## High 금지 또는 약화 조건

아래 조합은 datasynth 조작 truth에는 맞을 수 있지만 실제 정상 전표 noise가 크므로 High floor로 쓰지 않는다.

| 약한 조합                          | 금지 정책                           | 이유                                                                                                                                                                    |
| ---------------------------------- | ----------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `L3-02 + L3-04 + L3-12`            | 가공전표/결산수정 Medium floor 금지 | 수기 + 결산 + 업무범위 집중은 정상 결산조정에서도 흔함                                                                                                                  |
| `approval_bypass + L3-02 + L3-12`  | 횡령은폐 Medium floor 금지          | 자금유출/상계/중복 근거 없이 승인 context만 있음                                                                                                                        |
| `L3-03 + L3-05 + (L3-02 or L3-12)` | 순환거래 High floor 금지 (PHASE1-1) | 관계사 + 휴일/수기/업무범위는 순환 구조 증거가 아님. 순환거래 탐지 자체는 PHASE1-2 family로 이관됨(SoT §7.3) — PHASE1-1 룰에서는 어차피 순환거래 floor를 만들지 않는다. |
| `approval_bypass + L3-02`          | 승인우회 High floor 금지            | 수기 승인 예외는 정상 위임/긴급 승인에서도 발생                                                                                                                         |
| `approval_bypass + L3-05`          | 승인우회 High floor 금지            | 휴일 승인만으로는 조작 근거가 약함                                                                                                                                      |
| `L3-12` 단독                       | fraud floor 금지                    | 업무범위 집중은 booster/context다                                                                                                                                       |
| `L4-06` 단독                       | High 금지                           | batch anomaly는 모집단 이상이지 개별 조작 증거가 아님                                                                                                                   |
| `D01`, `D02`, Benford 단독         | transaction High 금지               | PHASE1-2 macro family이며 row-level 조작 증거가 아님(PHASE1-1 점수 기여 0, 이관 2026-06-15)                                                                             |

## 비-rule feature를 붙이는 근거

비-rule feature는 점수를 예쁘게 만들기 위한 보정이 아니다. 정상 실무에서도 자주 발생하는 rule 신호와 실제 조작 맥락을 분리하기 위한 근거다.

감사기준과 금감원 지적사례는 journal entry risk를 단일 rule hit로 판단하지 않는다. 수기전표, 기말 전표, 고액, 설명 부족, 희소 계정, 승인 우회, 특수관계자 거래가 서로 어떤 업무 맥락에서 결합됐는지를 본다.

| 주제                         | rule만으로 부족한 이유                                                                                                    | 붙일 비-rule feature                                                                |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| 결산수정 조작                | 정상 결산조정도 수기·기말·고액으로 발생                                                                                   | 결산월 집중, 사후입력, reversal, 민감계정, 설명 빈약도, 반복 수정                   |
| 가공전표/수익조작            | 고액 수익·수기 매출은 정상 거래에도 존재                                                                                  | 수익성 계정, customer 실재성, 신규/비활성 거래처, source, 계약/출고/세금계산서 연결 |
| 횡령은폐                     | 반제/상계는 정상 clearing에서도 빈번                                                                                      | 자금성 계정, vendor/employee 연결, 중복 지급, 지급 후 reversal, 작성자-승인자 관계  |
| 순환거래 (→ PHASE1-2 family) | 관계사 거래 자체는 정상 내부거래일 수 있음. 한 전표로 안 보이는 구조라 PHASE1-2 family(graph/relational)가 맡음(SoT §7.3) | counterparty chain, 동일 금액 왕복, 월말 반복, 내부거래 제거/상계 불일치            |
| 승인우회                     | 위임·긴급·대체승인은 정상 운영일 수 있음                                                                                  | 승인권한 matrix, 금액한도 초과, 휴가/대체승인 기록, 작성자=승인자 관계              |

## 정상 noise가 섞이는 이유

현재 PHASE1 rule은 조작 전용 증거가 아니라 감사 검토 신호를 잡는다. 따라서 아래 신호는 악의적 조작과 정상 실무 양쪽에서 모두 발생한다.

| rule 신호                  | 조작 맥락                | 정상 실무 맥락                                                               |
| -------------------------- | ------------------------ | ---------------------------------------------------------------------------- |
| 수기전표                   | 가공전표, 결산조작       | 결산조정, accrual, 재분류                                                    |
| 결산말 입력                | cutoff 조작, 이익조정    | 정상 결산마감                                                                |
| 고액                       | 중요 왜곡, 가공 거래     | 대량 매입, 정산, 배부                                                        |
| 관계사 (→ PHASE1-2 family) | 순환거래, 매출 부풀리기  | 내부거래, 원가배부, 대여금 정리 (구조 신호는 PHASE1-2 family 귀속, SoT §7.3) |
| 반제/상계                  | 횡령은폐, 지급 취소 은폐 | clearing, refund, reversal                                                   |
| 승인 예외                  | 승인우회                 | 위임, 긴급승인, 휴가 대체승인                                                |
| 업무범위 집중              | 권한 남용                | SSC, 결산 담당자, ERP batch user                                             |

따라서 ranking은 rule hit 개수보다 독립적인 증거 축이 결합됐는지를 우선한다.

## Topic별 승격 기준

### 원장기록·데이터정합성

원장기록 topic은 fraud High 승격 topic이 아니라 품질 게이트다. 필수값 누락, 원장 필드 불일치, 설명 누락은 전표 신뢰성 문제로 검토하되, 단독으로 조작 High를 만들지 않는다.

High 또는 Top 우선순위는 데이터 결함이 여러 문서에 반복되거나, 다른 topic의 조작 combo를 은폐하는 보조 근거로 붙을 때만 강화한다.

### 승인·권한·업무분장 통제

High 승격은 승인권한 초과, 자기승인, SoD 충돌, 승인생략이 고액·수기·결산·비정상 시간대와 결합될 때 가능하다.

단순 위임승인, 긴급승인, 휴일승인, 업무범위 집중은 Medium 또는 context로 둔다. 승인 topic은 contract에서도 High case가 많이 발생하므로 정상군 noise cap을 반드시 본다.

### 결산·기간귀속·입력시점

High 승격은 결산말/사후입력/cutoff 신호가 고액, 설명부족, 민감계정, 희소계정, 반복 수정과 결합될 때 가능하다.

`manual + closing + work_scope`만으로는 High를 만들지 않는다. 정상 결산조정과 구분되지 않기 때문이다.

### 계정분류·거래실질 불일치

계정분류 topic은 단독 fraud subtype보다 다른 조작 subtype의 보조 승격축이다. 민감계정, 희소 계정쌍, 프로세스-계정 불일치, 장기 미정리 가계정은 수익조작·결산조작·횡령은폐의 설명력을 높일 수 있다.

단독 High는 제한하고, 다른 topic의 강한 seed와 결합될 때 ranking 보강으로 쓴다.

### 중복·상계·자금유출

High 승격은 중복 지급, 중복 전표, 반제/상계, reversal, 자금성 계정이 승인통제 실패 또는 SoD 문제와 결합될 때 가능하다.

단순 reversal/offset 또는 work scope concentration은 정상 clearing에서도 많으므로 횡령은폐 floor로 쓰지 않는다.

### 관계사·내부거래·순환구조 (→ PHASE1-2 family로 이관됨)

이 topic은 PHASE1-1 룰 topic에서 삭제됐다. 순환거래·내부거래·관계사 구조는 한 전표로 안 보이는 구조 신호이므로 PHASE1-2 family(graph/relational) 탐지기의 정식 대상이다(SoT §7.3). counterparty chain, 동일 금액 왕복, 내부거래 제거 불일치 같은 graph/relational feature가 family의 책임이며, IC01~03·GR01/03의 PHASE1 점수경로는 제거됐다. L3-03만 PHASE1-1 account_logic booster(관계사 모집단 맥락)로 잔존한다. 근거: IFRS 10 §B86, K-IFRS 1110/1024, ISA 600/550, 감사기준서 550호 §23.

### 수익·금액·모집단 통계 이상

High 승격은 수익 이상 또는 고액 이상이 수기/조정 전표와 희소계정, 중복, cutoff, 계약·출고·세금계산서 불일치 같은 근거와 결합될 때 가능하다.

단순 고액, 단순 batch anomaly, 단순 Benford 이상은 High 근거가 아니다. contract noise에서 수익 High가 크게 발생하므로 customer 실재성, 거래 source, 증빙 연결 feature가 필요하다.

## 평가 기준

Ranking 변경은 다음 네 가지를 동시에 확인한다.

| 평가 항목        | 기준                                                                      |
| ---------------- | ------------------------------------------------------------------------- |
| 포착률           | manipulation truth가 score/rule/review 기준으로 포착되는가                |
| topic 진입       | 조작 subtype이 기대 topic에 들어오는가                                    |
| High/Top ranking | 기대 topic의 High, Top50, Top100에 들어오는가                             |
| noise cap        | contract/normal split에서 같은 floor가 false positive를 폭증시키지 않는가 |

단순히 manipulation Top100 truth만 올리는 변경은 통과 기준이 아니다. contract High case가 같이 늘면 fitting 위험으로 본다.

## 현재 anti-fitting 결과 요약

> **[역사 기록]** 아래 수치는 구 가중합 profile(2026-05-08) 기준 측정값으로, tier 전환 이후 baseline이 아니다. anti-fitting 원칙(정상 noise cap·약한 floor 제거)은 유효하나 구체 건수는 구 체계 산출이므로 역사적 맥락으로만 읽는다. tier 분포 재측정은 A안 코드 반영 단계에서 수행(`HIGH_COMBO_GROUNDING.md` §5b 과탐 가드).

2026-05-08 quality calibration profile 기준:

| 항목                     |  결과 |
| ------------------------ | ----: |
| manipulation truth       |   420 |
| score/rule/review 미포착 |     0 |
| 전체 case Top100 truth   |    39 |
| 전체 case Top1000 truth  |   162 |
| manipulation case count  | 4,218 |

약한 floor 제거 후 결과:

| topic                                    | manipulation High case | contract High case | 판단                                                            |
| ---------------------------------------- | ---------------------: | -----------------: | --------------------------------------------------------------- |
| 승인·권한·업무분장 통제                  |                    157 |                492 | 유지 가능하나 noise cap 필요                                    |
| 결산·기간귀속·입력시점                   |                      8 |                907 | rule floor 강화 금지                                            |
| 중복·상계·자금유출                       |                     56 |                439 | 자금성/중복/승인 근거 필요                                      |
| 관계사·내부거래·순환구조 (PHASE1-2 이관) |                      6 |                  7 | 역사적 수치. 이 topic은 이후 PHASE1-2 family로 이관됨(SoT §7.3) |
| 수익·금액·모집단 통계 이상               |                      5 |                700 | rule floor 강화 금지                                            |

quality calibration에서 제거한 weak medium floor:

| 제거한 floor reason                                                 | manipulation 감소 | contract 감소 | 의미                                          |
| ------------------------------------------------------------------- | ----------------: | ------------: | --------------------------------------------- |
| `period_end + manual_adjustment + weak_description`                 |                -1 |          -119 | 결산수정 조작 floor가 아니라 context로만 유지 |
| `reversal_or_offset + work_scope_concentration + manual_adjustment` |                -7 |          -112 | 횡령은폐 floor가 아니라 context로만 유지      |
| `approval_bypass + manual_adjustment`                               |               -20 |           -14 | 승인우회 floor 금지                           |
| `approval_bypass + non_business_day_timing`                         |                -2 |           -14 | 휴일 승인 단독 floor 금지                     |

해석:

- 미포착 문제는 현재 0건이다.
- 문제는 기대 topic의 High/Top ranking 승격이다.
- 약한 rule 조합을 다시 올리면 datasynth 성능은 좋아질 수 있지만 contract noise가 폭증한다.
- 이번 수정은 High/Top 지표를 바꾸지 않았지만, 정상 실무에서도 흔한 weak medium floor reason을 제거해 점수 근거 품질을 높였다.
- 다음 개선은 rule floor 강화가 아니라 비-rule feature와 graph/relational feature 추가로 한다.

## 구현 체크리스트

1. `topic_score_breakdown`에 floor reason과 combo reason을 계속 남긴다.
2. `fraud_scenario_tags`는 정렬 key로 쓰지 않는다.
3. `L3-12`, `L4-06`, Benford, D01, D02는 단독 High를 만들지 않는다.
4. High floor를 추가할 때는 `DETECTION_REFERENCE.md`의 감사기준·금감원 근거를 먼저 연결한다.
5. 새 floor를 추가하면 `datasynth_manipulation`과 `datasynth_contract`를 모두 재실행한다.
6. 결과 문서에는 manipulation truth 지표와 contract noise 지표를 같이 기록한다.
