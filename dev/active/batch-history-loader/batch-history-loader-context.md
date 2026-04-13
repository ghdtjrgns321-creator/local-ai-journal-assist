# Batch History Loader - Context & Decisions

## Status

- Phase: 구현 완료
- Progress: 10 / 10 tasks complete
- Last Updated: 2026-04-08

## Key Files

**Modified**:
- `src/db/schema.py` — upload_batches DDL + UPLOAD_BATCHES_COLUMNS 추가
- `src/db/loader.py` — load_all()에 file_name 파라미터 + upload_batches INSERT
- `src/db/queries.py` — list_batches, batch_meta 프리셋 쿼리 2종 추가
- `src/pipeline.py` — AuditPipeline에 file_name 전달 경로 추가
- `dashboard/app.py` — result=None 분기에 batch_selector 통합
- `dashboard/_state.py` — KEY_LOADED_FROM_DB 키 추가
- `dashboard/components/data_uploader.py` — _run_pipeline_from_mapped()에서 file_name 전달

**New**:
- `src/db/batch_reader.py` — list_batches() + load_batch() (DB → PipelineResult 복원)
- `dashboard/components/batch_selector.py` — 배치 목록 카드 UI
- `tests/modules/db/test_batch_meta.py` — 메타 적재 테스트
- `tests/modules/db/test_batch_reader.py` — 배치 로드 테스트

## Key Decisions

1. **upload_batches 테이블 신설 (2026-04-08)**
   - Rationale: general_ledger에서 DISTINCT upload_batch_id로 배치 목록을 추출할 수 있지만, 파일명/행수/업로드 시간 등 메타데이터를 함께 저장하려면 별도 테이블이 필요
   - Alternatives: (A) general_ledger에 file_name 컬럼 추가 → 행마다 중복 저장, 비정규화. (B) JSON 파일로 메타 관리 → DB 트랜잭션과 분리되어 정합성 위험
   - Trade-offs: 테이블 1개 추가되지만, 쿼리 한 번으로 전체 배치 이력 조회 가능

2. **DetectionResult 리스트를 anomaly_flags에서 역산하여 Pseudo 복원 (2026-04-08, 리뷰 피드백 #1 반영)**
   - Rationale: 빈 리스트로 두면 대시보드의 룰별 위반 건수 차트, 위험 등급별 분포 차트가 깨짐. anomaly_flags 테이블을 rule_code별 GROUP BY로 집계하여 DetectionResult 껍데기 객체를 생성하면 대시보드 차트가 정상 작동함
   - Alternatives: (A) DetectionResult를 pickle/JSON으로 별도 저장 → 복잡도 증가 (B) 빈 리스트 → 차트 깨짐 (C) anomaly_flags 역산 → 구조 완전 복원은 아니지만 대시보드 표시에 충분
   - Trade-offs: details DataFrame의 컬럼별 점수 세부 정보는 부분 복원. "재탐지" 기능은 DB 로드 시 비활성화 (featured_data=None)

3. **대시보드 진입점: engagement 선택 후 배치 목록 + 업로드를 동시 표시 (2026-04-08)**
   - Rationale: 별도 "로드" 탭을 만들면 2탭 전환 필요. 한 화면에서 기존 결과와 새 업로드를 모두 접근 가능하게 함
   - Alternatives: engagement_selector에 배치 목록을 통합 → engagement_selector의 책임 초과
   - Trade-offs: data_uploader 화면이 길어질 수 있지만, 배치가 없으면 batch_selector가 아무것도 렌더링하지 않으므로 기존 UX와 동일

## Review Feedback Log (2026-04-08)

| # | 심각도 | 피드백 | 반영 |
|---|--------|--------|------|
| 1 | 치명적 | results=[] 시 대시보드 차트 깨짐 | anomaly_flags에서 Pseudo DetectionResult 역산 (Task 2-1) |
| 2 | UX/UI | 읽기 전용 모드 명시 필요 | st.info 배지 + 탐지 설정 비활성화 (Task 3-1) |
| 3 | 데이터흐름 | file_name 시그니처 연쇄 오염 | PipelineResult.file_name 필드 방식 (Task 1-2, 1-4) |

## Known Issues

- 기존에 이미 적재된 배치(upload_batches 테이블 생성 전)는 배치 목록에 나타나지 않음. 마이그레이션 스크립트로 기존 general_ledger에서 DISTINCT batch_id를 추출하여 upload_batches에 백필할 수 있지만, 파일명 등 메타 정보는 복구 불가. 우선순위 낮음.
- DB 로드 결과에서 "재탐지" 버튼이 비활성화됨. Phase 2(ML) 이후 별도 대응 가능.
