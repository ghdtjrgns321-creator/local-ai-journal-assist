# DataSynth Update Checklist

Current production baseline: `data/journal/primary/datasynth/` freeze `v45` as of 2026-04-25. Latest freeze note: `data/journal/primary/datasynth/FREEZE_V45.md`.

DataSynth를 재생성하거나 핫픽스할 때, 같이 확인하거나 업데이트해야 하는 파일 목록이다.

목적:
- `data/journal/primary/datasynth/` 실사용 기준본과 문서가 어긋나지 않게 유지
- 후보본(`datasynth_vXX_candidate`)과 운영본을 혼동하지 않게 관리
- 라벨 의미 변경, sidecar 추가, 품질 수치 변경이 있을 때 누락 없이 반영

## 1. 운영 기준본 승격 시

실사용 기준본을 새 버전으로 올릴 때 반드시 확인:

- 데이터 본문
  - `data/journal/primary/datasynth/journal_entries.csv`
  - `data/journal/primary/datasynth/journal_entries_2022.csv`
  - `data/journal/primary/datasynth/journal_entries_2023.csv`
  - `data/journal/primary/datasynth/journal_entries_2024.csv`
- 라벨/sidecar
  - `data/journal/primary/datasynth/labels/anomaly_labels.csv`
  - `data/journal/primary/datasynth/labels/anomaly_labels.json`
  - `data/journal/primary/datasynth/labels/anomaly_labels.jsonl`
  - `data/journal/primary/datasynth/labels/anomaly_labels_summary.json`
  - `data/journal/primary/datasynth/labels/document_labels_2022.csv`
  - `data/journal/primary/datasynth/labels/document_labels_2023.csv`
  - `data/journal/primary/datasynth/labels/document_labels_2024.csv`
- 메타/검증
  - `data/journal/primary/datasynth/generation_statistics.json`
  - `data/journal/primary/datasynth/data_quality_stats.json`
  - `data/journal/primary/datasynth/validated_metadata_2022.json`
  - `data/journal/primary/datasynth/validated_metadata_2023.json`
  - `data/journal/primary/datasynth/validated_metadata_2024.json`
  - `data/journal/primary/datasynth/run_manifest.json`
  - `data/journal/primary/datasynth/balance_validation.json`
- 기준 문서
  - `data/journal/primary/datasynth/FREEZE_VXX.md`
  - `data/journal/primary/datasynth/PREVIEW.md`
  - `data/journal/OVERVIEW.md`
- 프로젝트 문서
  - `docs/DECISION.md`
  - `docs/PROJECT_OVERVIEW.md`
  - `docs/TASKS.md`
  - `docs/핵심기능.MD`

## 2. 후보본만 만들었을 때

운영본 승격 없이 `datasynth_v21_candidate`, `datasynth_v22_candidate` 같은 실험본만 만들었을 때:

- 후보본 문서
  - `data/journal/primary/datasynth_vXX_candidate/FREEZE_VXX_CANDIDATE.md`
  - `data/journal/primary/datasynth_vXX_candidate/PREVIEW.md`
- 현재 운영본과의 관계 명시
  - `current production baseline = data/journal/primary/datasynth/ freeze vXX`
- 운영본 문서는 바꾸지 않음
  - `data/journal/primary/datasynth/FREEZE_V*.md`
  - `data/journal/primary/datasynth/PREVIEW.md`

## 3. 라벨 의미가 바뀌었을 때

예:
- `ExceededApprovalLimit := approved_by.approval_limit`
- `JustBelowThreshold := approved_by.approval_limit * ratio <= document_amount < approved_by.approval_limit`
- `DuplicatePayment := P2P + KZ duplicate payment pair`

반드시 같이 수정:

- 데이터/라벨
  - `data/journal/primary/datasynth/labels/*`
- 검증 코드
  - `tools/audit_labels.py`
  - `tools/audit_fullcheck.py`
  - `tests/datasynth_quality_gate/checks/tier3_crossref.py`
  - `tests/phase1_rulebase/test_e2e_label_validation.py`
- 룰 문서
  - `docs/DETECTION_RULES.md`
  - `docs/completed/DATASYNTH_INJECTION_SPEC.md`
- 필요 시 탐지 코드
  - `src/detection/fraud_rules_groupby.py`

## 4. sidecar가 추가되거나 구조가 바뀌었을 때

예:
- `labels/duplicate_payment_pairs.json`
- `labels/duplicate_payment_negative_controls.json`
- `labels/duplicate_entry_pairs.json`

반드시 같이 수정:

- `data/journal/primary/datasynth/PREVIEW.md`
- `data/journal/OVERVIEW.md`
- `docs/DETECTION_RULES.md`
- `docs/핵심기능.MD`
- sidecar를 실제로 읽는 검증/분석 스크립트
  - `tools/analyze_datasynth.py`
  - `tools/scripts/verify_data.py`
  - 해당 후보/승격 빌드 스크립트

## 5. 소규모 핫픽스만 했을 때

예:
- `MisclassifiedAccount` invalid CoA 치환
- JE user master 조인 복구
- `ExceededApprovalLimit` 라벨 재판정

반드시 같이 수정:

- 핫픽스 기록 파일 생성
  - 예: `V20_1_*.json`, `V20_2_*.json`, `V20_4_*.json`
- `data/journal/primary/datasynth/FREEZE_VXX.md`
  - 어떤 핫픽스가 누적되었는지
- `data/journal/primary/datasynth/PREVIEW.md`
  - 최신 수치 반영
- 의미가 바뀐 경우 3번 항목도 같이 수행

## 6. 품질 수치가 바뀌었을 때

예:
- rows/documents 수
- anomaly label 수
- `DuplicatePayment` 개수
- `accounts_count`, `employee_count`

반드시 같이 수정:

- `data/journal/primary/datasynth/FREEZE_VXX.md`
- `data/journal/primary/datasynth/PREVIEW.md`
- `data/journal/OVERVIEW.md`
- `docs/DECISION.md`
- `docs/PROJECT_OVERVIEW.md`
- `docs/핵심기능.MD`

## 7. 역사 문서 처리 원칙

아래는 과거 결과 기록이다. 현재값으로 본문 전체를 갈아엎지 않는다.
대신 상단에 현재 운영 기준본만 주석으로 적는다.

- `docs/debugging.md`
- `tests/datasynth_quality_gate/results/fullcheck_report.md`
- `tests/modules/test_feature/test-results/e2e-datasynth.md`
- `tests/modules/test_feature/test-results/dual-audit-datasynth.md`
- 기타 과거 `test-results/*.md`

권장 주석 형식:

`Historical report. Current production DataSynth baseline is data/journal/primary/datasynth/ freeze vXX as of YYYY-MM-DD.`

## 8. 승격 전 최소 확인

운영본 승격 전 최소 체크:

1. 핵심 룰 회귀 테스트 통과
2. `anomaly_labels.csv`와 sidecar 정합성 확인
3. `validated_metadata_2022/2023/2024.json` 재생성
4. `PREVIEW.md`, `FREEZE_VXX.md`, `OVERVIEW.md` 수치 반영
5. `DECISION.md`에 승격 결정 기록
6. 백업 디렉터리 생성

## 9. 이번 기준에서 특히 자주 놓친 파일

우선순위 높음:

- `data/journal/primary/datasynth/PREVIEW.md`
- `data/journal/primary/datasynth/FREEZE_VXX.md`
- `data/journal/OVERVIEW.md`
- `docs/DECISION.md`
- `docs/DETECTION_RULES.md`
- `docs/completed/DATASYNTH_INJECTION_SPEC.md`
- `tests/phase1_rulebase/test_e2e_label_validation.py`
- `tools/audit_labels.py`
- `tools/audit_fullcheck.py`

## 10. 권장 운영 방식

- 메인 운영본은 항상 `data/journal/primary/datasynth/`
- 실험은 항상 `data/journal/primary/datasynth_vXX_candidate/`
- 승격 전에는 메인 문서 건드리지 말고 후보본 문서만 수정
- 승격 시에만 메인 문서와 결정 로그를 함께 갱신
