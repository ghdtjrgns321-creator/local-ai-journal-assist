# DataSynth 문서 인덱스

이 디렉터리는 `local-ai-assist`에서 사용하는 DataSynth 생성 기준, 생성 흐름, 검증 게이트, 의사결정 이력을 한곳에 모은 현재 기준 문서다.
오래된 v20~v134 실험 문서는 원인 추적용으로만 참조하고, 현행 설명은 2026-06-14 기준 accepted lineage를 기준으로 한다.

## 현재 기준

| 영역 | 현재 기준 | 역할 |
| --- | --- | --- |
| NORMAL base | `datasynth_semantic_v1_normal_20260614_v43d` | PHASE1/PHASE2 overlay가 올라가는 정상 원장 기준본 |
| PHASE1 recall overlay | `datasynth_semantic_v1_recall_20260613_v42j_r3` | PHASE1-1 룰 39개 detector-only recall 검증용 |
| PHASE2 fraud overlay | `datasynth_semantic_v1_phase2_fraud_20260614_v1_r4m_h` + `..._seed1` | PHASE2 비지도/구조 신호의 shortcut-free 부정 scheme 검증용 |
| PHASE2 scale reference | `datasynth_semantic_v1_phase2_fraud_20260613_v1_r4l_b` | r4m 이후 S13 규모 보존 비교용. full-column leak 때문에 최종 accepted overlay는 아님 |
| historical contract freeze | `datasynth` v126 freeze | 과거 PHASE1 contract truth/sidecar 기준. 현행 semantic NORMAL/overlay 생성 기준은 아님 |

## 읽는 순서

1. [생성 원칙](./generation-principles.md)
2. [생성 흐름](./generation-flow.md)
3. [시나리오와 데이터셋](./scenario-and-datasets.md)
4. [검증과 테스트](./verification-and-tests.md)
5. [의사결정 이력](./decisions-and-history.md)

## 범위

포함한다.

- DataSynth를 왜 채택했고 어떤 데이터 생성 원칙을 적용했는지.
- NORMAL 원장을 어떤 기준으로 만들고 검증했는지.
- PHASE1 rule-recall overlay와 PHASE2 fraud overlay를 어떻게 NORMAL 위에 얹는지.
- 어떤 테스트와 감사 스크립트를 실행했으며 어떤 결함을 찾아 수정했는지.
- 현재 accepted lineage와 legacy lineage의 차이.

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
- 도메인 감사: [18_DATASYNTH_DOMAIN_AUDIT.md](../guide/users/18_DATASYNTH_DOMAIN_AUDIT.md)
- 전 컬럼 누출 스캔: [19_DATASYNTH_FULL_COLUMN_LEAK_SCAN.md](../guide/users/19_DATASYNTH_FULL_COLUMN_LEAK_SCAN.md)
- 디버깅/수정 기록: [docs/debugging.md](../debugging.md)

