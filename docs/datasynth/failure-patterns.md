# DataSynth 반복 결함과 Gate 사전

이 문서는 DataSynth 작업 중 반복해서 발생한 REJECT 원인을 유형별로 정리한다.
새 결함이 발견되면 한 번 수정하고 끝내지 말고, 이 문서와 해당 verifier/gate에 regression 항목을 추가한다.

## 1. Hollow PASS

### 증상

- PASS라고 표시되지만 검사 대상 population이 비어 있다.
- metric이 `{}` 또는 count 없이 PASS다.
- sidecar나 financial statement가 실제 GL에서 파생되지 않는다.

### 재발 사례

- tax docs 0인데 tax ratio PASS.
- B15/B16/H04 metric이 비어 있는데 PASS.
- TB/subledger reconciliation이 실측 없이 0 difference.
- batch 전표가 3건뿐인데 batch coverage를 통과.

### Gate 원칙

- required field가 없으면 PASS가 아니라 BLOCKED다.
- checked count, bad count, residual을 반드시 출력한다.
- 빈 집합 통과 금지.

## 2. Truth/token leakage

### 증상

- journal/master에 정답 문구나 scenario marker가 남는다.
- 특정 header, reference, mutation field가 fraud 전용이다.
- truth/provenance가 sidecar가 아니라 detector input surface에 존재한다.

### 재발 사례

- `협력사 정산`, `임직원 비용 정산` header token.
- `mutation_reason`, `mutation_mutated_field` 정답 평문.
- `SUP-32xx`, `EMPLOYEE`류 식별 cluster.
- fraud-only reference range.

### Gate 원칙

- 특정 단어 grep만으로는 부족하다.
- 전 컬럼 oracle scan으로 단일 값, format, range, nullness, 2컬럼 조합을 검사한다.
- truth/provenance는 labels sidecar에만 둔다.

## 3. Normal background 부재

### 증상

- overlay가 사용하는 계정, 증빙, reversal link, delivery date, IC trace가 NORMAL에 없다.
- 정상 모집단이 너무 깨끗해서 overlay surface 자체가 분리자다.

### 재발 사례

- PHASE2 계정 14개가 NORMAL에 없어 계정 자체가 shortcut.
- NORMAL `delivery_date`가 전부 null이라 O2C fraud만 populated.
- NORMAL linked reversal이 부족해 `original_document_id` non-null이 fraud-only.
- 단일법인 전환 후 IC GL trace 0.

### Gate 원칙

- overlay가 쓰는 표면은 NORMAL twin이 있어야 한다.
- NORMAL v46b 기준 IC trace는 0이면 FAIL이다.
- PHASE2 base 동기화 시 normal twin 분포를 다시 측정한다.

## 4. 회계 실체 훼손

### 증상

- 차대변 균형은 맞지만 경제 효과가 없다.
- 회계적으로 맞지 않는 계정이 scheme에 끼어든다.
- 같은 계정을 같은 방향으로 쪼개 라인 수만 늘린다.

### 재발 사례

- 같은 GL에 차변/대변을 동시에 넣은 자기상쇄 분개.
- 가공매출/재고/IC scheme에 loans_receivable filler 삽입.
- same-side split으로 라인 수 gate 통과.
- 비용 금액이 매출과 무관하게 생성되어 SGA/interest/tax가 매출을 압도.

### Gate 원칙

- document balance만으로 수락하지 않는다.
- scheme-account whitelist를 둔다.
- economic direction floor를 둔다.
- P&L ratio gate로 COGS/SGA/interest/tax 현실성을 본다.

## 5. CoA 및 master mismatch

### 증상

- overlay가 쓰는 GL이 dataset CoA나 global config에 없다.
- L1-03 invalid account가 다른 룰의 shortcut으로 발화한다.
- master에 없는 user/vendor/counterparty를 쓰면서 다른 룰이 같이 켜진다.

### 재발 사례

- 15110, 25110, 7600, 8010, 999998 CoA 누락.
- L3-09 가수금 계정이 CoA에 없어 L1-03과 같이 발화.
- approval user가 employees.json에 없어 승인 룰 미발화 또는 unknown-approver로 오염.

### Gate 원칙

- L1-03 standard의 invalid account만 CoA outside를 허용한다.
- 그 외 모든 rule/overlay GL은 dataset CoA와 config CoA에 있어야 한다.
- approval 관련 룰은 employee master와 실제 approval limit을 연결한다.

## 6. Derived flag override

### 증상

- `is_period_end`, `is_weekend`, `is_after_hours`, `exceeds_threshold` 같은 파생 플래그를 직접 박는다.
- feature pipeline이 raw에서 다시 계산하면 주입이 사라진다.

### 재발 사례

- L3-04 period-end flag override.
- L3-05 공휴일/주말을 flag로만 주입하고 실제 날짜는 평일.
- L1-04 한도초과를 1원 차이 flag로만 표현.
- L1-06 SoD를 marker로만 주입하고 실제 created_by/approved_by 관계가 없음.

### Gate 원칙

- raw-only injection.
- feature 재계산 후에도 발화해야 한다.
- PHASE1 recall audit은 trigger-present와 fired를 전수 대조한다.

## 7. Case assembly 실패

### 증상

- 개별 룰은 켜지지만 같은 case에 묶이지 않는다.
- static truth gate는 PASS인데 actual case-builder gate가 FAIL이다.

### 재발 사례

- PHASE1 combo r1i: member legs가 독립 문서로 흩어짐.
- PHASE1 combo r1l: flow-based `L2-05`가 companion rule과 같은 observed case에 노출되지 않음.
- LOW/CONTEXT가 broad normal signal과 결합해 HIGH로 승격.

### Gate 원칙

- combo/tier는 actual case-builder gate가 authoritative다.
- member docs는 같은 `(theme_id, case_key)` 또는 flow group에서 보인다.
- final `priority_band` 단독 일치가 아니라 expected topic score cut을 본다.

## 8. Metadata 조합 shortcut

### 증상

- source, user persona, document type, counterparty type을 각각 정상 marginal에서 샘플링했지만 조합은 정상에 없다.
- 단일 컬럼 gate는 PASS인데 2컬럼 조합이 fraud-only다.

### 재발 사례

- `source × user_persona` fraud-only cells.
- `source × document_type` fraud-only cells.
- H2R payroll에 정상에 없는 tax invoice support type.

### Gate 원칙

- 독립 샘플링 금지.
- 정상 donor document에서 metadata 묶음을 통째 상속한다.
- full-column leak scan의 2컬럼 조합을 필수로 본다.

## 9. Seed rotation hollow PASS

### 증상

- seed마다 document id나 회사 배정만 바뀌고 fraud content는 같다.
- per-seed gate는 PASS지만 다양성이 없다.

### 재발 사례

- r4i seed1~5에서 fraud-content difference 0.

### Gate 원칙

- seed diversity는 `(scheme_id, component_role, local_amount, posting_date, gl_account)` content difference를 본다.
- assignment vector만 주기적으로 회전하면 FAIL이다.
- representative와 seed1 이상에서 full-column leak scan을 실행한다.

## 10. Source identity / measurement input hollow PASS

### 증상

- automated/recurring 전표에 `batch_id` 또는 `job_id` 중 하나만 있어도 단순 채움률은 좋아 보인다.
- 그러나 `source_trust.py`는 batch/job 둘 중 하나가 비면 weak identity로 보고 자동 source를 신뢰하지 않는다.
- raw CSV에는 `original_document_id`/`reversal_document_id`가 있는데, PHASE1 measurement harness가
  해당 컬럼을 읽지 않아 L2-05 combo가 missing으로 false reject된다.

### 재발 사례

- v47 작업 중 combo/tier `L2-05|L3-03`은 raw detector에서 발화했지만,
  `profile_phase1_v126.PHASE1_USECOLS`가 reversal structural columns를 버려 full combo gate에서 false reject됐다.
- 기존 PHASE1-1 recall 산출물은 automated source의 batch/job 동시 채움률이 65.4%라 새 E13 gate에서
  FAIL한다. 다음 recall 재생성은 generator-level batch/job identity fix를 포함해야 한다.

### Gate 원칙

- NORMAL E13: automated-family rows는 `batch_id`와 `job_id`가 둘 다 있어야 하고, human source rows는 둘 다 비어 있어야 하며, `trusted_automated_mask` rate >= 0.90이어야 한다.
- PHASE1 combo/tier preflight: L2-05 structural-reference columns가 measurement usecols와 journal schema 양쪽에 있어야 한다.
- full PHASE1 measurement는 이 fast gate가 통과한 뒤 마지막 1회만 돌린다.

## 11. Categorical distribution leak

### 증상

- exact-value oracle은 통과하지만 fraud의 최빈 범주값이 한 컬럼에 과도하게 몰린다.
- 해당 값이 normal에서는 낮은 비율이라, 값 자체가 정답 토큰이 아니어도 분포만으로 fraud를 분리한다.

### 재발 사례

- Integrated usefulness Phase1 v1e:
  - fraud `source=manual` 100%, normal 약 10%.
  - fraud `batch_id/job_id` blank 100%, normal blank 약 12%.
- v1f_b:
  - O2C weak만 donor 상속하고 R2R weak는 manual로 남아 weak signal 표면이 분리됐다.

### Gate 원칙

- journal 범주형 컬럼마다 fraud 최빈값 비중 > 85%이고 해당 값의 normal 비중 < 20%이면 FAIL.
- `weak_signal=true` 행은 manual/blank batch artifact를 만들지 않는다.
- 정상 흐름 편승형은 base/donor의 `source`, `batch_id`, `job_id`, `batch_type` 조합을 상속한다.

## 12. Temporal relationship leak

### 증상

- 단일 날짜값은 정상처럼 보이지만 날짜 관계가 불가능하다.
- 예: `approval_date < document_date`, `posting_date < document_date`, `settlement_date < posting_date`.
- 2컬럼 관계만으로 fraud와 normal을 분리할 수 있다.

### 재발 사례

- Integrated usefulness Phase1 v1f_c:
  - overlay가 새 결산기 `document_date/posting_date`로 옮겼지만 donor의 더 이른 `approval_date`를 그대로
    둬 `INV-TEMPORAL` 1,874건이 발생했다.

### Gate 원칙

- overlay가 날짜를 이동하면 관련 날짜 필드를 함께 이동한다.
- `verify_integrated_usefulness_phase1.py`는 temporal coherence counts/findings를 포함한다.
- `verify_injection_coherence.py --self-test`가 PASS한 뒤 dataset coherence oracle을 실행한다.

## 13. REJECT 처리 규칙

REJECT는 중단 사유가 아니다.
다음 순서로 처리한다.

1. 실패 gate를 확인한다.
2. 원인을 다음 중 하나로 분류한다.
   - generator defect.
   - gate가 잘못된 acceptance target을 본 경우.
   - detector/code bug.
   - scope 밖 또는 synthetic 불가능.
3. generator defect이면 Rust profile을 수정하고 다음 suffix로 재생성한다.
4. gate가 잘못된 target을 본 경우에는 gate 기준을 문서와 코드에서 정정한다. 임계 완화는 사용자 승인 없이는 하지 않는다.
5. detector/code bug이면 DataSynth 작업에서 고치지 않고 별도 detection 작업으로 분리한다.
6. scope 밖이면 truth에서 제외하고 out-of-scope 사유를 문서화한다.

완료 선언은 관련 gate가 exit 0이고, 실패 lineage와 수정 lineage가 문서에 기록된 뒤에만 한다.
