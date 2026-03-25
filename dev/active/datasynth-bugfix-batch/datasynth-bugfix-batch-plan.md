# DataSynth 잔여 버그 일괄 수정 - Strategic Plan

## Executive Summary

DataSynth JE generator의 승인/SOD 관련 버그 4건을 체계적으로 진단하고 수정한다.
코드 분석 결과 parallel clone은 정상 동작하며, 핵심 문제는 auto-approve 경로의 설계 결함과 DEBUG 잔여물이다.

## 진단 결과

### Bug 1: 자기승인 64% (기대: ~10%)

**원인**: parallel clone 문제가 **아님**. `split()` (L2268-2269)에서 `approval_threshold`는 올바르게 clone되고 있다.

실제 원인은 `populate_approval_fields()` (L1958-1964)의 auto-approve 경로:

```
amount <= threshold(2000) 일 때:
  → ApprovalWorkflow::auto_approved(preparer_id=created_by, ...)
  → populate_approval_fields()에서 last_approver = None
  → approved_by = workflow.preparer_id = created_by
  → 자기승인
```

log-normal(mu=7.0, sigma=2.5)에서 중심값 ≈ $1,096. threshold=$2,000 이하 비중이 약 60~65%.
여기에 threshold 초과 전표 중 `sod_violation_rate=0.10` 주입분이 추가되어 총 ~64%.

**수정 방향**: auto-approve된 전표의 `approved_by`에 creator가 아닌 **Senior 이상 approver**를 배정해야 한다. generation_principles.md 4.3절: "JuniorAccountant는 전결 권한이 없다. Maker/Checker 분리 필수."

### Bug 2: anomalous 1명/110명 (0.9%, 기대: ~3.5명/50명 = 7%)

**원인**: 코드 로직은 올바르다 (L377-388). anomalous_pairs.choose()는 정상 호출.

문제는 **대상 모수**: anomalous 분기는 `persona != Junior && persona != AutomatedSystem` 조건에서만 도달. Senior 이상 50명 중 7% = 3.5명. seed=2024에서 RNG 결과로 1명만 걸린 것.

이것은 **seed 의존 분산 문제**이지 코드 버그가 아닌 가능성이 높다. 다만, seed를 바꿔도 일관되게 낮다면 RNG 경로에 문제가 있을 수 있다.

**검증 방법**: 다른 seed로 3회 실행하여 anomalous 수 분포 확인. 일관되게 1-2명이면 RNG 편향 조사.

### Bug 3: SystemAccessConflict 0건

**원인**: Bug 2와 연쇄. anomalous user가 1명이면 그 1명의 전표에만 라벨이 부여된다.
코드 (L1086-1088, L1392-1394)는 정상: `anomalous_process_users.contains(&header.created_by)` 체크.

그런데 0건이라면, 그 1명이 전표를 생성하지 않았거나, 라벨 부여 후 `populate_approval_fields`의 SOD 주입에서 덮어쓰기되었을 가능성.

L1968-1976:
```rust
if !entry.header.sod_violation && self.rng.random::<f64>() < self.sod_violation_rate {
    entry.header.sod_violation = true;
    entry.header.sod_conflict_type = Some(SodConflictType::PreparerApprover);
}
```

이 코드는 `!sod_violation`일 때만 실행하므로, 이미 SystemAccessConflict가 설정된 전표는 건너뛴다. 따라서 **덮어쓰기 문제는 아니다**.

0건의 원인: anomalous user 1명의 전표 수가 적거나, CSV 출력 시 sod_conflict_type 필드 누락 가능.
output_writer.rs에서 sod_conflict_type 출력 확인 필요.

### Bug 4: DEBUG 로그 제거

L1774-1782: `APPROVAL_DEBUG` static counter 및 tracing::info 제거.

## Implementation Phases

### Phase 1: 진단 확인 (0.5일)

**Goal**: 각 버그의 실제 원인을 데이터로 확인

- [ ] Task 1.1 - Python 검증 스크립트 작성 - Size: M
  - 소규모(seed=2024, 1000건) 생성 후 아래 지표 일괄 확인:
    - 자기승인 비율 (approved_by == created_by)
    - anomalous user 수 (sod_conflict_type == "SystemAccessConflict")
    - auto-approve 비율 (amount <= 2000인 건의 %)
    - sod_violation 유형별 건수
  - File: `tools/datasynth/scripts/verify_bugs.py` (신규)

- [ ] Task 1.2 - output_writer.rs에서 sod_conflict_type 출력 확인 - Size: S
  - File: `tools/datasynth/crates/datasynth-cli/src/output_writer.rs`
  - `sod_conflict_type` 필드가 CSV 39컬럼에 포함되는지 확인

- [ ] Task 1.3 - 다른 seed (42, 12345)로 anomalous user 수 비교 - Size: S
  - seed 3개로 각각 생성하여 anomalous user 수 비교
  - 일관되게 0-1명이면 코드 문제, 분산이 있으면 seed 의존

### Phase 2: 버그 수정 (1일)

**Goal**: 4개 버그 수정

- [ ] Task 2.1 - auto-approve 경로의 approved_by 수정 - Size: L
  - File: `tools/datasynth/crates/datasynth-generators/src/je_generator.rs`
  - L1785-1794: amount <= threshold일 때 `auto_approved` 생성 후,
    `populate_approval_fields`에서 approved_by를 Senior/Manager 중 랜덤 선택하도록 변경.
  - 핵심: auto_approved 워크플로우에도 `Approve` 액션을 추가하여 approver != creator 보장.
  - 단, `sod_violation_rate=0.10` 주입분은 유지 (의도적 자기승인 = B06 탐지 대상).
  - 예상 결과: 자기승인 ~10% (SOD 주입분만 남음)
  - Acceptance: 자기승인 비율 8~15% 범위

- [ ] Task 2.2 - anomalous user 수 안정화 (필요시) - Size: M
  - Phase 1.3 결과에 따라 수행 여부 결정
  - 방안 A: anomalous_assignment_rate를 0.10으로 상향 (config 변경만)
  - 방안 B: anomalous 분기에서 Junior도 대상에 포함 (원칙 위반이므로 비권장)
  - 방안 C: Senior 이상 중 최소 N명 보장하는 floor 로직 추가
  - File: `je_generator.rs` L377 또는 `config/datasynth.yaml` L108
  - Acceptance: anomalous user >= 3명

- [ ] Task 2.3 - SystemAccessConflict 0건 해결 - Size: S
  - Bug 2 해결 시 자동 해결될 가능성 높음 (anomalous user 증가 → 라벨 전표 증가)
  - output_writer.rs에서 sod_conflict_type 출력 누락 시 추가
  - Acceptance: SystemAccessConflict > 0건, anomalous user의 전표 전수에 라벨 존재

- [ ] Task 2.4 - DEBUG 로그 제거 - Size: S
  - File: `tools/datasynth/crates/datasynth-generators/src/je_generator.rs`
  - L1774-1782: `APPROVAL_DEBUG` static counter 및 tracing::info! 6줄 삭제
  - Acceptance: `APPROVAL_DEBUG` grep 결과 0건

### Phase 3: 검증 및 재생성 (0.5일)

**Goal**: 수정 후 전체 데이터 재생성 및 최종 검증

- [ ] Task 3.1 - 소규모 빌드+테스트 - Size: S
  - `cargo test -p datasynth-generators`
  - `cargo clippy`

- [ ] Task 3.2 - 소규모 생성 + 검증 스크립트 - Size: M
  - seed=2024, 1000건으로 생성
  - verify_bugs.py 실행하여 모든 지표 정상 확인

- [ ] Task 3.3 - 전체 재생성 (100K건) - Size: M
  - `cargo build --release`
  - `./target/release/datasynth-data generate -c ../../config/datasynth.yaml -o ../../data/journal/primary/datasynth --seed 2024 --verbose`
  - verify_bugs.py로 최종 검증

- [ ] Task 3.4 - 기존 Python 테스트 실행 - Size: S
  - `uv run pytest tests/test_ingest/ tests/test_feature/ -v`
  - 재생성된 데이터로 ingest/feature 테스트 통과 확인

## Risk Assessment

- **Medium Risk**: Task 2.1에서 auto-approve 경로 변경 시, 기존 approval workflow 구조와 충돌 가능
  - Mitigation: `ApprovalWorkflow::auto_approved`의 구조를 유지하면서 `Approve` 액션만 추가
- **Low Risk**: anomalous user 수가 seed 의존이라 config 변경으로 불충분할 수 있음
  - Mitigation: floor 로직(최소 3명 보장)을 코드에 추가하는 방안 C를 대비

## Success Metrics

| 지표                  | 현재     | 목표        |
|-----------------------|----------|-------------|
| 자기승인 비율         | 64%      | 8~15%       |
| anomalous user 수     | 1/110    | >= 3/110    |
| SystemAccessConflict  | 0건      | > 0건       |
| APPROVAL_DEBUG 로그   | 존재     | 0건         |
| 기존 테스트           | -        | 전수 통과   |

## Dependencies

- Code: Bug 2 → Bug 3 (연쇄 관계, Bug 2 해결이 선행)
- Build: `cargo build --release` (약 2분)
- Data: 재생성 후 Python 테스트 재실행 필요
