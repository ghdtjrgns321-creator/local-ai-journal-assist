# DataSynth 잔여 버그 일괄 수정 - Task Checklist

## Progress Summary

0 / 10 tasks complete (0%)

## Phase 1: 진단 확인 (0.5일)

- [ ] 1.1 Python 검증 스크립트 작성
  - File: `tools/datasynth/scripts/verify_bugs.py` (신규)
  - Details: 소규모(1000건) CSV 읽어서 아래 지표 출력
    - 자기승인 비율: `approved_by == created_by` 건수/전체
    - auto-approve 비율: `amount <= 2000` 건수/전체
    - anomalous user 수: `sod_conflict_type == "SystemAccessConflict"` unique user 수
    - sod_violation 유형별 건수: `sod_conflict_type` value_counts
    - user별 전표 수 분포: `created_by` value_counts 상위 20명
  - Acceptance: 스크립트가 1회 실행으로 전체 현황 파악 가능
  - Size: M

- [ ] 1.2 output_writer.rs에서 sod_conflict_type 출력 확인
  - File: `tools/datasynth/crates/datasynth-cli/src/output_writer.rs`
  - Details: CSV 39컬럼 중 `sod_conflict_type` 필드 존재 여부 확인.
    없으면 Bug 3의 원인이 여기에 있음.
  - Acceptance: 필드 존재 확인 또는 누락 발견
  - Size: S

- [ ] 1.3 다른 seed로 anomalous user 수 비교
  - Details: seed={2024, 42, 12345}로 3회 생성하여 anomalous user 수 비교
  - Acceptance: seed 의존 vs 코드 버그 판별 완료
  - Size: S

## Phase 2: 버그 수정 (1일)

- [ ] 2.1 auto-approve 경로의 approved_by 수정 (Bug 1)
  - File: `tools/datasynth/crates/datasynth-generators/src/je_generator.rs`
  - Details:
    - L1785-1794: `maybe_apply_approval_workflow`의 auto-approve 분기 수정
    - amount <= threshold 전표에도 Approve 액션 추가 (approver = Senior/Manager 랜덤)
    - 방법: `auto_approved` 대신 level=1 워크플로우 생성 후 `select_approver(1, &created_by)` 호출
    - sod_violation_rate=0.10 주입은 `populate_approval_fields`에서 유지 (B06 탐지용)
  - Acceptance: 자기승인 비율 8~15%
  - Size: L

- [ ] 2.2 anomalous user 수 안정화 (Bug 2, 조건부)
  - File: `je_generator.rs` L311~411 또는 `config/datasynth.yaml`
  - Details: Phase 1.3 결과에 따라 수행
    - 방안 A (config): anomalous_assignment_rate 0.07 → 0.10
    - 방안 C (code): Senior 이상 순회 후 anomalous user < 3명이면 강제 추가 배정
  - Acceptance: anomalous user >= 3명
  - Size: M

- [ ] 2.3 SystemAccessConflict 0건 해결 (Bug 3)
  - File: `output_writer.rs` (필드 누락 시) 또는 자동 해결 (Bug 2 연쇄)
  - Details:
    - Bug 2 해결 시 anomalous user 증가 → 라벨 전표 자동 증가
    - output_writer.rs에서 sod_conflict_type 출력 누락 시 필드 추가
  - Acceptance: CSV에서 SystemAccessConflict 건수 > 0
  - Size: S

- [ ] 2.4 DEBUG 로그 제거 (Bug 4)
  - File: `tools/datasynth/crates/datasynth-generators/src/je_generator.rs`
  - Details: L1774-1782의 6줄 삭제
    ```rust
    // DELETE: L1774-1782
    static COUNTER: std::sync::atomic::AtomicU64 = ...
    let n = COUNTER.fetch_add(...)
    if n < 5 {
        tracing::info!("APPROVAL_DEBUG: ...")
    }
    ```
  - Acceptance: `grep -r "APPROVAL_DEBUG" .` 결과 0건
  - Size: S

## Phase 3: 검증 및 재생성 (0.5일)

- [ ] 3.1 빌드 + 단위 테스트
  - Details: `cargo test -p datasynth-generators && cargo clippy`
  - Acceptance: 테스트 전수 통과, clippy warning 0건
  - Size: S

- [ ] 3.2 소규모 생성 + 검증
  - Details: seed=2024, 1000건 생성 → verify_bugs.py 실행
  - Acceptance: 모든 지표 목표 범위 내
  - Size: M

- [ ] 3.3 전체 재생성 (100K건) + 최종 검증
  - Details:
    ```bash
    cd tools/datasynth
    ./target/release/datasynth-data generate \
      -c ../../config/datasynth.yaml \
      -o ../../data/journal/primary/datasynth \
      --seed 2024 --verbose
    ```
    verify_bugs.py로 최종 검증
  - Acceptance: 자기승인 8~15%, anomalous >= 3명, SystemAccessConflict > 0, DEBUG 0건
  - Size: M

- [ ] 3.4 Python 테스트 실행
  - Details: `uv run pytest tests/test_ingest/ tests/test_feature/ -v`
  - Acceptance: 전수 통과
  - Size: S

## Deployment Checklist

- [ ] cargo test 통과
- [ ] cargo clippy 통과
- [ ] verify_bugs.py 전 지표 정상
- [ ] 전체 데이터 재생성 완료
- [ ] Python 테스트 통과
- [ ] docs/debugging.md에 진단/수정 이력 기록
- [ ] APPROVAL_DEBUG grep 0건 확인
