# DataSynth 잔여 버그 일괄 수정 - Context & Decisions

## Status

- Phase: Phase 1 (진단 확인) 시작 전
- Progress: 0 / 10 tasks complete
- Last Updated: 2026-03-24

## Key Files

**Modified (수정 대상)**:
- `tools/datasynth/crates/datasynth-generators/src/je_generator.rs` - 승인 로직, anomalous 배정, DEBUG 로그
- `config/datasynth.yaml` - anomalous_assignment_rate 조정 (필요시)

**Read-only (참조)**:
- `tools/datasynth/crates/datasynth-cli/src/output_writer.rs` - CSV 출력 필드 확인
- `tools/datasynth/crates/datasynth-core/src/models/department.rs` - ProcessAssignmentPolicy, anomalous_pairs
- `tools/datasynth/crates/datasynth-core/src/distributions/amount.rs` - 금액 분포 (log-normal mu=7.0)
- `tools/datasynth/crates/datasynth-config/src/schema.rs` - anomalous_assignment_rate 기본값 0.07
- `data/journal/primary/datasynth/generation_principles.md` - 생성 원칙 (승인 한도, SOD, 프로세스 배정)

**New (신규)**:
- `tools/datasynth/scripts/verify_bugs.py` - 검증 스크립트

## Key Decisions

1. **parallel clone은 정상** (2026-03-24)
   - Rationale: `split()` L2268-2269에서 `approval_enabled`, `approval_threshold`, `anomalous_process_users` 모두 clone됨
   - 근거: 코드 직접 확인. L2266-2272에서 fraud_config, persona_errors_enabled, approval_enabled, approval_threshold, sod_violation_rate, user_process_map, anomalous_process_users 7개 필드 전부 clone
   - 결론: parallel이 원인이 아님

2. **자기승인 64%의 근본 원인 = auto-approve 경로 설계** (2026-03-24)
   - Rationale: amount <= threshold(2000)인 전표는 `auto_approved` → `populate_approval_fields`에서 approved_by = preparer_id = created_by
   - log-normal(mu=7.0, sigma=2.5)에서 threshold=2000 이하 비중 ≈ 60~65%
   - 여기에 threshold 초과 전표 중 sod_violation_rate=0.10 주입분 추가 → 총 ~64%
   - Trade-offs: threshold를 올리면 자기승인 감소하지만, B06 탐지 시나리오가 약해짐. auto-approve에 approver 배정이 정석.

3. **anomalous 1명은 seed 의존 분산 가능성** (2026-03-24)
   - Rationale: Senior 이상 50명 × 7% = 기대값 3.5명이지만, Binomial(50, 0.07)에서 P(X<=1) ≈ 12.5%
   - 통계적으로 불가능하진 않으나, 다른 seed로 재현 확인 필요
   - Alternatives: rate 상향(0.10), floor 로직(최소 3명), Junior 포함(원칙 위반)

## Known Issues

- generation_principles.md 4.3절의 승인 한도(KRW)와 je_generator.rs의 threshold(USD $2,000)은 스케일이 다름.
  KRW 1천만원 ≈ USD ~$7,500이므로 현재 $2,000은 상대적으로 낮은 편.
  Phase 2에서 통화별 threshold 분기가 필요할 수 있음.
- `ApprovalWorkflow::auto_approved` 팩토리 메서드의 구조를 확인하여 Approve 액션 추가 가능 여부 확인 필요.
