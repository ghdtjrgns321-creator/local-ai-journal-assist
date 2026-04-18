# Performance Evaluation Report - Context & Decisions

## Status

- Phase: 계획 수립
- Progress: 0 / 15 tasks complete
- Last Updated: 2026-04-16

## Key Files

**Modified**:
- 없음

**Planned**:
- `src/db/schema.py` - 평가 요약/룰별 지표 테이블 DDL
- `src/db/queries.py` - 평가 조회 프리셋
- `src/pipeline.py` - 평가 입력 연결 지점
- `dashboard/tab_phase2.py` - 성능 평가 섹션
- `tests/phase1_rulebase/test_e2e_label_validation.py` - evaluator 재사용

**New**:
- `src/metrics/models.py`
- `src/metrics/rule_mapping.py`
- `src/metrics/ground_truth_evaluator.py`
- `src/metrics/operational_evaluator.py`
- `src/metrics/report_builder.py`
- `src/db/performance_store.py`
- `tests/modules/test_metrics/test_ground_truth_evaluator.py`
- `tests/modules/test_metrics/test_operational_evaluator.py`
- `docs/metrics.md`

## Key Decisions

1. **정답 지표와 운영 지표를 분리한다 (2026-04-16)**
   - Rationale: DataSynth label 기반 precision/recall은 정답 지표이고, whitelist/high-risk 추세는 운영 proxy 지표다. 둘을 한 표로 섞으면 precision의 의미가 훼손된다.
   - Alternatives: 하나의 점수판으로 합치기. 하지만 ground truth 유무에 따라 계산 불가능한 컬럼이 많아지고 해석이 흐려진다.
   - Trade-offs: UI와 DB 스키마가 약간 늘어나지만, 지표 의미가 명확해진다.

2. **기존 테스트 스크립트의 평가 로직을 서비스 모듈로 승격한다 (2026-04-16)**
   - Rationale: `tests/phase1_rulebase/test_e2e_label_validation.py`에는 이미 룰별 precision/recall 계산이 있다. 이것을 재사용 가능한 서비스로 올리는 것이 가장 빠르고 정확하다.
   - Alternatives: 새 evaluator를 처음부터 다시 작성. 하지만 룰-라벨 매핑과 보고 포맷이 다시 분기될 가능성이 높다.
   - Trade-offs: 테스트 파일 구조를 손봐야 하지만 장기적으로 중복이 줄어든다.

3. **Phase 1 vs Phase 2 비교는 detector track scope 기준으로 산출한다 (2026-04-16)**
   - Rationale: 현재 코드베이스에는 `maturity`, `default_enabled`, `run_status`가 있다. 하지만 성능 비교는 성숙도보다 실제 실행된 track 집합이 중요하다.
   - Alternatives: `maturity=production/beta/experimental` 기준 비교. 하지만 이것은 운영 상태 분류이지 성능 비교 스코프가 아니다.
   - Trade-offs: track grouping 정의를 별도 모듈로 관리해야 하지만, 계산 기준이 명확하다.

4. **historical batch는 partial confidence를 허용한다 (2026-04-16)**
   - Rationale: 현재 과거 배치는 detector runtime snapshot을 완전 저장하지 않는다. 따라서 일부 비교 지표는 정확도 한계가 있다.
   - Alternatives: 과거 배치 전체 미지원. 하지만 운영상 유용성이 크게 떨어진다.
   - Trade-offs: 결과에 `partial` 표식이 필요하지만 사용자 기대를 올바르게 조정할 수 있다.

## Known Issues

- `dev/README.md`는 현재 repo에 없다. 이번 계획은 `CLAUDE.md`와 기존 `dev/active/*` 문서 형식 기준으로 작성했다.
- 과거 배치에는 `detector_statuses` 영속 스냅샷이 없어 일부 Phase 비교가 불완전할 수 있다.
- DataSynth 라벨은 synthetic rule proximity가 있어 precision/recall이 실무보다 높게 보일 수 있다. 이 제한은 리포트 상단에 명시해야 한다.
- 현재 whitelist는 “사람이 FP로 본 사례”를 쌓는 구조라 precision의 대체재가 아니라 운영 보조 지표다.

## Open Questions

1. 성능 리포트를 모든 배치 자동 생성으로 둘지, `Generate Report` 액션 기반 반자동으로 둘지 결정이 필요하다.
2. `performance_reports`를 engagement DB에 영속 저장할지, Markdown 파일 산출만 할지 범위를 고정해야 한다.
3. historical batch에도 보고서를 역산 생성할지, 신규 배치부터만 지원할지 운영 정책이 필요하다.
