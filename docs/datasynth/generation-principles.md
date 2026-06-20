# DataSynth 생성 원칙

## 목적

DataSynth는 이 프로젝트의 감사 분석 surface를 검증하기 위한 합성 전표 모집단을 만든다.
목표는 detector score를 잘 나오게 만드는 것이 아니라, 회계적으로 가능한 정상 모집단과 추적 가능한 위반/부정 후보를 생성하는 것이다.
PHASE1/PHASE2에서 쓰는 `is_fraud`, `is_anomaly`, precision, recall은 개발 검증 보조 지표이며 운영상 부정 확정 근거가 아니다.

## 비협상 원칙

- 정상 데이터는 정상 원장이어야 한다. 차대변 균형, 기간·회사·계정 정합, master 참조, 세금·통화·결산 산출물 정합을 충족해야 한다.
- 정상 데이터에는 `is_fraud=true`, `is_anomaly=true`, `fraud_type`, `anomaly_type`, `mutation_*`, truth/provenance 정답 표면이 남으면 안 된다.
- 비정상 데이터는 의도적 이상 패턴이다. fraud, error, process issue, policy violation을 truth/provenance sidecar로 추적할 수 있어야 한다.
- 데이터 품질 noise는 정상/비정상 모두에 존재해야 한다. MCAR 결측, typo, format variance가 라벨 지름길이 되면 안 된다.
- detector hit count 또는 모델 점수를 맞추기 위해 데이터를 조정하지 않는다. 수정 이유는 회계 실체, 정상 현실성, 누출 제거, 산출물 정합 중 하나여야 한다.
- Python 후처리로 생성 결함을 덧대지 않는다. 현재 materialized profile은 Rust `tools/datasynth/`의 CLI profile을 기준으로 고친다.
- 새로 발견된 결함은 관련 검증 카탈로그에 regression gate로 승격한다. 콘솔에서 한 번 확인한 기록만으로 완료 처리하지 않는다.
- PHASE1/PHASE2 surface는 분리한다. DataSynth truth는 surface별 검증 보조자료이며 단일 fraud score를 만들기 위한 통합 정답이 아니다.

## NORMAL 우선 원칙

현행 구조는 먼저 fraud/anomaly가 없는 NORMAL base를 만들고, 그 위에 PHASE1/PHASE2 목적별 overlay를 얹는다.
NORMAL base는 부정 케이스의 배경이 되므로 충분히 다양한 정상 구조를 가져야 한다.

필수 정상 배경은 다음과 같다.

- 일반 R2R/O2C/P2P/H2R/A2R/TREASURY/MFG 전표.
- 정상 내부거래와 양방향 대사쌍.
- 정상 3-hop 이상 회사 노드 cycle 배경.
- 정상 batch 전표, payroll run, 감가상각 run, vendor payment.
- 정상 역분개. PHASE2 overlay가 `original_document_id`/`reversal_document_id`를 사용하므로 NORMAL v43d부터 linked normal reversal background가 필수다.
- PHASE2 악용 가능 계정군의 정상 활동. 계정이 부정 overlay에서 처음 등장하면 계정 자체가 라벨 shortcut이 된다.

## 라벨과 provenance 정책

라벨은 운영 판단이 아니라 synthetic truth다.

- journal CSV는 detector 입력 surface다. 여기에 정답 문구, component role, mutation provenance, truth token이 새면 실패다.
- truth/provenance는 sidecar에 둔다. PHASE1 recall은 `labels/p3_2_rule_truth.csv` 호환 구조를 쓰되 `truth_layer=phase1_rule_recall_overlay`로 구분한다.
- PHASE2 fraud overlay는 `labels/phase2_scheme_truth.csv`, `labels/phase2_scheme_provenance.csv`, scheme acceptance report를 통해 부정 구조를 추적한다.
- `is_synthetic`과 `is_mutated` 같은 관리용 컬럼은 PHASE2 feature 입력에서 차단하며, 데이터 표면에서도 정상/부정 간 null marker가 되지 않게 채운다.

## Anti-Fitting 기준

허용되는 피드백:

- 회계 정합 실패를 고친다.
- 정상 모집단에 현실적 배경이 없어 overlay가 들키는 문제를 고친다.
- 단일 컬럼, 결측률, 값 조합, seed 표면이 truth를 노출하는 문제를 고친다.
- detector가 아니라 데이터 검증 게이트가 발견한 결함을 고친다.

금지되는 피드백:

- PHASE1 expected-topic 진입률을 올리기 위해 특정 timestamp, source, amount, account를 맞춘다.
- PHASE2 모델 성능을 낮추거나 높이기 위해 분포를 튜닝한다.
- 정상 데이터에 unlabeled confirmed violation을 넣는다.
- period mismatch, stale fiscal period, invalid CoA 같은 회계 불일치를 detector 성능 때문에 일부러 재현한다.
- seed rotation을 document id, company label, density만 바꾸는 표면 회전으로 처리한다.

## 도너 상속 원칙

PHASE2 fraud overlay는 정상 donor document에서 부수 필드를 상속한다.
부정의 본질 필드만 바꾸고, invoice/supporting metadata, user/persona/source, auxiliary field, counterparty surface, document format은 정상 donor의 규칙을 따른다.

이 원칙은 2026-06-14 full-column leak scan에서 확인된 L5 계열 누출의 공통 처방이다.
부정 overlay가 부수 필드를 정상 생성기와 다른 규칙으로 채우거나 비우면 ML이 부정 구조가 아니라 생성기 표면을 학습한다.

## 정상 범위 임계값 원칙

검증 임계값은 detector 성능에서 역산하지 않는다.
우선순위는 다음과 같다.

1. 회계·ERP hard invariant: 차대변 균형, CoA 존재, master 참조, VAT/환율, TB↔JE, carry-forward, subledger reconciliation.
2. 감사·업무 도메인 분포: 결산월, 주말/심야, 승인 지연, batch, IC, reversal, 신규계정 자연화.
3. synthetic marker 방지: 단일 값 purity, 결측률 차, 조합 셀, seed 다양성.
4. diagnostic: 전문가/LLM 샘플 리뷰, 경제성/잔액 방향 모니터링.

