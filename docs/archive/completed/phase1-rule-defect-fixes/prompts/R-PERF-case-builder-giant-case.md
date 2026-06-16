# 작업: case_builder 거대 case 성능 최적화 — cProfile 규명 후 핫패스 선형화

> 한국어로 응답·보고할 것. 저장소: `C:\Users\ghdtj\workspace\portfolio\local-ai-assist`, 브랜치 `develop`.
> grep 없으면 rg 대체. **이 작업은 동작(점수·band·hit)을 바꾸지 않는 순수 성능 최적화다.**

## 1. 목표

- case_builder가 거대 case(단일 case에 hit 수천~수만)를 처리할 때 폭증하는 핫패스를 cProfile로
  규명하고, **동작을 한 비트도 바꾸지 않으면서** O(hit²) 또는 과다 상수를 O(hit)로 낮춘다.
- 성공 기준: §6에서 동일 입력의 case 산출물(band·priority_score·hit 수·topic_scores)이 최적화
  전후 **완전 동일**(회귀 0)하고, 거대 case 포함 빌드의 벽시계 시간이 유의하게 감소.

## 2. 컨텍스트

- 읽어야 할 파일:
  - `src/detection/phase1_case_builder.py` — case 루프(약 1512행 `for ordinal, ((theme_id,
    case_key), group) in enumerate(groups.items())`). 내부 호출: `_collect_case_hits`(1517),
    `compute_topic_scores(case_hits)`(1614), `_fraud_combo_rule_scope(case_hits)`(1628),
    `_case_secondary_topics`(1644), document/rule count(1703·1772 — `len({hit... for hit in case_hits})`
    반복 집합 생성).
  - `src/detection/topic_scoring.py` — `compute_topic_scores`(115~), topic마다 `views` 재순회
    (131·143·149·158행 — topic_views를 여러 번 순회). evidences가 거대하면 topic×hit×재순회.
- 배경 (모르면 잘못 판단할 사실):
  - 실측: r24는 case build 674s인데 v42j_r3는 **3,717s**(b2 가드 max 1,200s 위반). 거대 case가
    r24 24개 → v42j_r3 40개로 증가(approval_control 11 + closing_timing 10 + duplicate_outflow 13 등).
    최대 case 18,718 hit. 산출물: `artifacts/phase1_priority_truth_v42j_r3/`.
  - approval_control 거대 case(ALOPEZ058, 최대 15,917 hit)는 r24에도 있었으므로 이 최적화는
    fallback 억제(별도 작업)와 무관하게 **기존 거대 case에도 유효**하다.
  - **동작 불변이 절대 조건**이다. 점수·band·hit·topic 결과가 바뀌면 그건 최적화가 아니라 회귀다.
    캐싱·중복 집합 생성 제거·불필요 재순회 제거만 한다. 알고리즘 의미를 바꾸지 말 것.

## 3. 설계 (이대로 수행 — 임의 변경 금지)

1. **cProfile 규명 먼저**: 거대 case가 있는 입력으로 case_builder를 프로파일링해 누적 시간 상위
   함수를 찾는다(추정 금지, 측정으로 핫패스 확정). 후보: `compute_topic_scores`의 topic별 views
   재순회, case 루프 내 반복 `{... for hit in case_hits}` 집합 생성(rule/document count를 매번
   재계산), `_coerce_evidence` 반복 호출.
2. 확정된 핫패스만 최적화 — 허용되는 변경:
   - case_hits에서 한 번만 만들면 되는 파생값(distinct rule_ids, document_ids, evidence_types)을
     **1회 계산 후 재사용**(현재 1518·1703·1772 등에서 반복 생성하면 통합).
   - `compute_topic_scores`가 topic마다 전체 views를 재필터링하면, views→topic 인덱스를 1회
     구축해 재사용(동일 결과 보장).
   - `_coerce_evidence`가 동일 evidence에 반복 호출되면 1회 변환 후 재사용.
3. **금지되는 변경**: 점수 공식·floor·band 임계·콤보 로직·hit 수집 범위 변경. "근사"나 "샘플링"
   금지(거대 case의 hit를 잘라내면 동작이 바뀜).
- 핫패스가 알고리즘 의미상 O(hit²)라 동작 보존하며 못 낮추면: 임의 변경하지 말고 STATUS:
  NEEDS_CONTEXT로 프로파일 결과와 함께 멈춰라(설계자가 알고리즘 재설계 판단).

## 4. 단계 체크리스트 (순서 고정 — 건너뛰기·합치기 금지)

- [ ] Step 1 (프로파일): 거대 case 포함 입력으로 cProfile 실행, 누적 시간 상위 15개 함수 확보.
      입력은 작은 합성 케이스로 거대 case를 모사하거나(예: 동일 (theme,key)에 hit 1만개 생성),
      기존 산출물 `artifacts/phase1_priority_truth_v42j_r3` 재현 불가하면 단위 벤치 작성
      증거: cProfile 상위 15 함수 출력 원문 (핫패스 확정)
- [ ] Step 2 (회귀 기준선 고정): 최적화 전, 대표 입력(거대 case 포함)의 case 산출물
      (case_id별 priority_score·band·rule hit 수·topic_scores)을 JSON으로 덤프 — 최적화 후 대조용
      증거: 덤프 생성 명령 + 행 수
- [ ] Step 3 (최적화): §3의 허용 변경만 적용 → 산출물: phase1_case_builder.py(+topic_scoring.py) diff
      증거: 변경 요약 + 동작 영향 없음 근거(어떤 값도 안 바뀜)
- [ ] Step 4 (동작 불변 검증): Step 2 덤프를 최적화 후 재생성해 **완전 일치** 확인(diff 0)
      증거: 전후 덤프 diff 결과(0 라인) + 벽시계 시간 전/후 비교
- [ ] Step 5(항상 마지막): 전체 검증(§6)
※ 증거 없는 단계는 미수행 간주. Step 4의 "동작 완전 일치"가 이 작업의 핵심 게이트다.

## 5. 금지 사항 (1건이라도 위반 시 작업 전체 실패)

- **동작 변경 금지**: 점수·band·hit·topic 결과가 바뀌면 실패. Step 4 덤프 불일치 = 실패.
- 근사·샘플링·hit 잘라내기 금지(거대 case의 모든 hit를 그대로 처리하되 빠르게).
- 점수 공식·floor·콤보·case grouping 키 변경 금지.
- 테스트 약화 금지.
- 범위 밖 수정 금지: 수정 가능 = `src/detection/phase1_case_builder.py`,
  `src/detection/topic_scoring.py`(핫패스인 경우만), `tests/` 하위 신규 벤치/회귀 테스트.
  config·detector 본체·rule_scoring registry 변경 금지.
- 체크리스트 생략·순서 변경 금지.

## 6. 최종 검증 (완료 선언 전 필수 실행)

- 동작 불변: Step 2 vs Step 4 덤프 diff = 0 (원문 첨부)
- `uv run pytest tests/modules/test_detection/ -q` → 신규 실패 0 (사전 베이스라인 전/후 비교)
- `uv run ruff check src/detection/phase1_case_builder.py` (+topic_scoring.py 수정 시) → All checks passed
- 벽시계: 거대 case 포함 벤치의 최적화 전/후 시간 (감소 확인)
※ 동작 불변이 안 지켜지면 DONE 금지 — 회귀다.

## 7. 완료 보고 양식 (이 양식 그대로, 항목 생략 금지)

STATUS: DONE | DONE_WITH_CONCERNS | NEEDS_CONTEXT | BLOCKED
체크리스트: 항목별 [x]/[ ] + 증거(명령 + 출력 원문)
cProfile 핫패스: <상위 함수 + 최적화한 것>
동작 불변 증거: <Step2/Step4 덤프 diff = 0>
벽시계 개선: <전 → 후 초>
변경 파일: <경로 목록>
미완·우회·우려 사항: <정직하게 전부. 없으면 "없음">

신뢰 규칙: 정직한 부분 실패 보고는 정상 경로다. 동작이 바뀐 거짓 DONE은 재측정에서 드러난다.
