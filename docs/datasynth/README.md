# DataSynth 문서 인덱스

이 디렉터리는 `local-ai-assist`에서 사용하는 DataSynth 생성 기준, 생성 흐름, 검증 게이트, 의사결정 이력을 한곳에 모은 현재 기준 문서다.
오래된 v20~v134 실험 문서는 원인 추적용으로만 참조하고, 현행 설명은 2026-06-30 기준 accepted lineage를 기준으로 한다.

## 현재 기준

| 영역 | 현재 기준 | 역할 |
| --- | --- | --- |
| NORMAL base | `datasynth_semantic_v1_normal_20260701_v48_rbac_r1` | v47 batch/job successor 위 RBAC/SoD persona-process 현실성 보정. 단일법인 C001 정상 원장 + 관계사 IC trace + automated/recurring batch_id·job_id 동시 부여 기준본 |
| PHASE1-1 recall overlay | `datasynth_semantic_v1_recall_20260630_v47_batchid_phase1_1_r1` | v47 normal 위 최신 `DETECTION_RULES.md` 기준 26개 개별 룰 detector-only recall 검증용 |
| PHASE1 combo/tier overlay | `datasynth_semantic_v1_combo_tier_20260630_v47_batchid_r1j` | v47 normal 위 HIGH/MEDIUM/LOW/CONTEXT case assembly 검증용 |
| PHASE2 fraud overlay | `datasynth_semantic_v1_phase2_fraud_20260614_v1_r4m_h` + `..._seed1` | PHASE2 비지도/구조 신호의 shortcut-free 부정 scheme 검증용 |
| PHASE2 scale reference | `datasynth_semantic_v1_phase2_fraud_20260613_v1_r4l_b` | r4m 이후 S13 규모 보존 비교용. full-column leak 때문에 최종 accepted overlay는 아님 |
| Integrated usefulness Phase1 overlay | `datasynth_integrated_usefulness_phase1_20260701_v1g` | 통합 쓸모 벤치마크 Phase1 3패턴 5벌 seed, label firewall, 분포/날짜 coherence 검증용 |
| historical contract freeze | `datasynth` v126 freeze | 과거 PHASE1 contract truth/sidecar 기준. 현행 semantic NORMAL/overlay 생성 기준은 아님 |

주의: PHASE2 r4m_h는 2026-06-14 accepted fraud overlay lineage다. 이후 NORMAL은 단일법인+관계사 흔적 기준과 v47 batch/job identity 기준으로 갱신되었으므로, PHASE2 overlay를 새 NORMAL 위에서 다시 만들 때는 r4m_h의 gate를 그대로 재사용하되 base 경로와 normal-twin 분포를 다시 검증해야 한다.

## 읽는 순서

1. [생성 원칙](./generation-principles.md)
2. [A-to-Z 이력](./end-to-end-history.md)
3. [생성 흐름](./generation-flow.md)
4. [에이전트 실행 Runbook](./agent-runbook.md)
5. [시나리오와 데이터셋](./scenario-and-datasets.md)
6. [검증과 테스트](./verification-and-tests.md)
7. [Fraud Overlay Realism Gate](./fraud-overlay-realism-gate.md)
8. [반복 결함과 Gate 사전](./failure-patterns.md)
9. [현재 기준과 남은 Gap](./current-lineage-and-gaps.md)
10. [의사결정 이력](./decisions-and-history.md)

## 범위

포함한다.

- DataSynth를 왜 채택했고 어떤 데이터 생성 원칙을 적용했는지.
- DataSynth 채택 이후 contract/manipulation/semantic rebuild로 이어진 전체 계보.
- NORMAL 원장을 어떤 기준으로 만들고 검증했는지.
- PHASE1 rule-recall overlay와 PHASE2 fraud overlay를 어떻게 NORMAL 위에 얹는지.
- PHASE1 combo/tier overlay가 개별 룰 recall과 왜 다른지.
- fraud/abnormal overlay가 어떤 realism gate와 shortcut/leak/coherence gate를 통과해야 하는지.
- 어떤 테스트와 감사 스크립트를 실행했으며 어떤 결함을 찾아 수정했는지.
- REJECT가 났을 때 어디를 보고 어떻게 다음 suffix로 반복해야 하는지.
- 현재 accepted lineage와 legacy lineage의 차이.
- v43d 이후 추가된 단일법인 전환, 관계사 IC 흔적 복구, PHASE1-1 r11, combo/tier r1z, v47 batch/job identity successor의 수락 기준.

포함하지 않는다.

- PHASE1-1/PHASE1-2/PHASE2 detector 자체의 scoring 상세.
- v20 이전 또는 v126~v134 patch의 모든 세부 diff. 현행에 남은 원칙과 regression gate만 요약한다.
- 원천 감사 데이터 내용. 이 문서는 synthetic/generated dataset 기준만 대상으로 한다.

## 핵심 근거 문서

- NORMAL 원칙: [datasynth-normal-generation-principles.md](../../dev/active/datasynth-journal-realism-rebuild/datasynth-normal-generation-principles.md)
- NORMAL 검증 설계: [normal-data-realism-verifier-design.md](../../dev/active/datasynth-journal-realism-rebuild/normal-data-realism-verifier-design.md)
- NORMAL 검증 카탈로그: [normal-data-realism-test-catalog.md](../../dev/active/datasynth-journal-realism-rebuild/normal-data-realism-test-catalog.md)
- PHASE1 recall 검증: [phase1-rule-recall-overlay-verification.md](../../dev/active/datasynth-journal-realism-rebuild/phase1-rule-recall-overlay-verification.md)
- PHASE2 overlay 검증: [phase2-overlay-verification-catalog.md](../../dev/active/datasynth-journal-realism-rebuild/phase2-overlay-verification-catalog.md)
- Fraud overlay 운영 gate: [fraud-overlay-realism-gate.md](./fraud-overlay-realism-gate.md)
- Integrated usefulness coherence oracle: [COHERENCE_ORACLE_SPEC.md](../../dev/active/integrated-usefulness-benchmark/COHERENCE_ORACLE_SPEC.md)
- PHASE1-1 firing matrix: [phase1-rule-firing-matrix.md](../../dev/active/phase1-rule-basis-audit/phase1-rule-firing-matrix.md)
- PHASE1 combo/tier matrix: [phase1-combo-tier-firing-matrix.md](../../dev/active/phase1-rule-basis-audit/phase1-combo-tier-firing-matrix.md)
- PHASE1 r11 3-way verification: [r11-rule-3way-verification.md](../../dev/active/datasynth-journal-realism-rebuild/r11-rule-3way-verification.md)
- 도메인 감사: [18_DATASYNTH_DOMAIN_AUDIT.md](../guide/users/18_DATASYNTH_DOMAIN_AUDIT.md)
- 전 컬럼 누출 스캔: [19_DATASYNTH_FULL_COLUMN_LEAK_SCAN.md](../guide/users/19_DATASYNTH_FULL_COLUMN_LEAK_SCAN.md)
- 디버깅/수정 기록: [docs/debugging.md](../debugging.md)
