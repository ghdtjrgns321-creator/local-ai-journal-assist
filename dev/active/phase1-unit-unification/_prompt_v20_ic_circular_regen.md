[작업] 정상(NORMAL) DataSynth 재생성 = 내부거래·순환 구조를 정상 배경으로 추가한다(v19→v20).
PHASE1 IntercompanyMatcher/GraphDetector가 의미 있게 돌 수 있게 한다. fraud/anomaly 주입 없음.
Local AI Audit Assistant. Rust 생성기 근본 수정(Python 덧대기 금지).

[배경]
v19 정상 데이터에 회사 간 거래·관계사·IC 대사쌍·회사 그래프 재료가 사실상 0이라 IC 흐름 0, 순환 탐지
skip 상태다(조사 완료). 정상 IC/순환 배경을 추가해야 PHASE1 IC/GR이 동작하고, 이후 부정(P3-3)이 숨을
현실적 모집단이 생긴다. 이번은 정상 배경만 깐다.

[먼저 읽기]
- dev/active/datasynth-journal-realism-rebuild/normal-data-realism-test-catalog.md K01~K07 (관계사·내부거래·그래프 현실성 기준)
- config/audit_rules.yaml (IC prefix: 1150<->2050, 4500<->2700)
- src/detection/intercompany_matcher.py, src/detection/graph_rules.py (요구 입력 컬럼/구조)
- tools/datasynth/ (Rust 생성기: generators/runtime/output_writer 등)

[추가할 정상 구조]
1. 회사 간 정상 거래: 일부 거래의 상대가 그룹 회사(C001/C002/C003)가 되도록.
   - counterparty_type에 관계사 계열(RELATED_PARTY / IntercompanyAffiliate 등) 추가
   - trading_partner가 상대 회사코드를 가리키게
2. IC 대사쌍(정상): 한 회사 채권(1150/4500 계열) ↔ 상대 회사 채무(2050/2700 계열) 양방향,
   shared reference, 허용오차 내 금액·일자로 정상 대사되게(정상이라 잘 맞아떨어진다).
3. 정상 순환 배경(소량): 업무상 설명 가능한 A→B→C→A (물류·정산 흐름 등). 부정 아님.
4. is_intercompany 컬럼을 생성기가 직접 출력(생성기가 IC 여부를 아는 게 authoritative).
   GR/IC 탐지기가 요구하는 컬럼이 채워지게.

[볼륨]
정상 배경다운 현실적 규모로(법인×기간 분산). 정확한 건수는 batch 때처럼 네가 제안하고 보고한다. 토큰 샘플 금지.

[검증 — 숫자로]
- 기존 gate 무회귀: balance·semantic coherence·tax·noise·batch 등 v19 통과 항목 그대로 PASS.
- 신규 K01~K07: IC counterparty/계정쌍/대사 일치/순환 설명가능성 등 통과.
- PHASE1 IC/GR smoke:
  · IntercompanyMatcher가 reciprocal/candidate 대사쌍을 실제로 만들어내는지(0이 아니어야 함)
  · GraphDetector 순환이 vendor/bank 체인이 아니라 회사 노드 기반인지 (조사에서 partner 노드 형식
    미강제 문제가 보였으니, 정상 순환이 회사 간으로 잡히는지 확인하고 결과 보고. 룰 보정이 필요하면 별도 표시만)
- 실제 수치 보고: 회사 간 거래 수, IC 대사쌍 수와 매칭률, 정상 순환 수, GR/IC 탐지기 결과 건수.
  "정상 데이터에서 이만큼이 말이 되나"를 같이 적는다.

[하지 말 것]
- fraud/anomaly 주입 없음(P3-3). 정상 IC/순환만.
- PHASE1 탐지기 룰 로직을 이번에 바꾸지 않는다(필요하면 보고만). flow builder(P2-3) 코드 안 건드림.

[안전]
- Rust 루트 수정, Python 덧대기 금지. 한국어 인코딩(거래처명·적요) UTF-8 확인. 커밋 안 함.
  브랜치 develop 확인, main 금지. docs/debugging.md에 v20 재생성·검증 기록.

[보고 후 멈춤]
추가 구조·볼륨·기존 gate 무회귀·K01~K07·IC/GR smoke 수치를 보고하고 멈춘다.

모든 응답은 한국어로.
