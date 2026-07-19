# Relational Family: Circular Transaction 메인 책임 이관 및 구현

작성: 2026-06-02

## 임무

`circular_related_party_transaction`(관계사 순환거래)은 이제 **relational family
(graph/entity anomaly family)의 메인(primary) 책임**이다. 현재 relational 로직이 순환을
제대로 잡는지 점검하고, 메인으로 잡도록 구현/수정하라. **circular = 네 담당이다.**

> 현재 로직이 잘못돼 있는지는 확정되지 않았다. 먼저 점검하고, 진짜 순환 데이터가
> 들어왔을 때 메인으로 잡을 수 있게 만드는 것이 목표다.

## 배경 (측정으로 확인된 사실)

- circular 34건은 그동안 **intercompany primary 로 잘못 라벨**돼 있었다. IC 는 양측 잔액
  대사(reconciliation, ISA 600), 순환은 그래프 위상(ISA 550 관계자 거래 합리성)이며
  graph/entity anomaly = **relational 영역**이다.
  근거: `docs/spec/phase2_reorgani.md:147` active family 5개(unsupervised/timeseries/duplicate/
  **relational**/intercompany) 에 graph 독립 family 가 없고, line 42·154·360 에서 relational
  을 "graph/entity anomaly family" 로 정의. graph(GR01)는 PHASE1 corroboration detector 일 뿐
  독립 PHASE2 family 가 아니다.

- 측정 결과 **누구도 circular 을 제대로 못 잡는다**:
  | detector | circular truth 34 recall | 성격 |
  |---|---|---|
  | GR01 (Johnson 순환, graph_detector) | 0/34 | 진짜 순환이 없어 0 |
  | IC 대사 (IC01/02/03) | 0/34 | self-balanced 라 대사 맞음 |
  | IC reciprocal_flow | 22/34 | 단일전표 self-balanced **컨닝** (정상도 19.7% 오탐) |
  | relational R06 | 18/34 | R06 은 user-account degree 룰, **우연히** 겹침 |

- 현재 DataSynth 의 circular 데이터는 **진짜 순환이 아니다**: 회사 C001~C003 3개뿐,
  C001↔C002 2-cycle 만, A→B→C→A 3-hop+ 순환 0개, 각 전표가 단일 doc self-balanced.

- **DataSynth 가 진짜 순환 구조로 재생성 중**이다(회사 수 확대, 3-hop+ 순환 엣지,
  1천만원+ 금액). 즉 데이터가 곧 바뀐다.

## 목표

1. relational family 에 **순환 탐지를 메인 신호로** 구현한다. 재생성된 circular truth 를
   relational primary 로 잡아야 한다.
2. GR01 의 Johnson N-hop cycle 로직(`src/detection/graph_rules.py:175`
   `gr01_circular_transaction`, `networkx.simple_cycles(length_bound=...)`)을 relational 로
   **편입**하거나 relational 에 **신규 순환 룰(예: R08 circular_related_party)** 을 추가한다.
   중복 구현보다 기존 GR01 로직 재사용을 우선 검토.
3. 먼저 **현재 relational 순환 관련 로직을 점검**하라: 순환 전용 룰 부재 여부, R06 이
   우연히 잡는 구조, relational primary owner metadata 에 circular 이 반영되는지.

## 제약 / 주의

- DataSynth 재생성 데이터가 나오기 전엔 현재 데이터(순환 아님)로 0 에 가까운 게 정상이다.
  로직 점검은 **"진짜 3-hop+ 순환이 들어오면 잡는가"** 를 기준으로.
- 순환 파라미터(`graph_gr01_max_cycle_length`, `graph_gr01_min_amount`=1천만,
  `graph_gr01_max_edges` 등)가 재생성 데이터의 순환 길이·금액과 맞는지 확인.
- 대용량 그래프 OOM 방어: networkx `add_edge` 루프 금지, `from_pandas_edgelist` +
  사전필터 + `max_edges` 3중 가드 (메모리: feedback_networkx_oom).
- truth/scenario 라벨을 detector **입력**으로 쓰지 않는다(평가 전용, 사후 join).
- 한국어 적요 컬럼 인코딩 가드(round-trip 금지).
- IC reciprocal_flow 가 circular 을 잡던 self-balanced 경로는 **컨닝**이므로 그쪽 신호를
  relational 로 복제하지 말 것. 순환은 회사 간 흐름 위상으로 잡는다.

## 검증 기준 (recall 단독 금지)

- 재생성된 진짜 순환 데이터에서 relational circular recall ≥ 목표(예: 0.7+)
- 정상 거래 FP / `lift`(=truth_rate/normal_rate) 동반 측정 — IC 100% 가 컨닝이었던 교훈
- circular 이 relational primary 책임으로 family responsibility 측정에 반영
- 측정 도구 재사용:
  - `tools/scripts/circular_ownership_probe_20260602.py` (graph/relational circular recall)
  - `tools/scripts/ic_signal_discrimination_probe_20260602.py` (신호별 lift 템플릿)

## 참고 자산

- `src/detection/graph_rules.py` : `gr01_circular_transaction` (Johnson 순환, 재사용 후보)
- `src/detection/graph_detector.py` : GraphDetector (GR01/GR03, 독립 트랙 WU-22)
- `src/detection/relational_detector.py` / `relational_rules.py` : R01~R07 현황
- `docs/spec/phase2_reorgani.md` §4 relational = graph/entity anomaly family
- `docs/spec/DETECTION_REFERENCE.md` : ISA 550 관계자 거래 위상/합리성 근거
- `dev/active/manipulation-truth-signal-audit-20260602/PROMPT.md` : circular=NOSIGNAL 판정 상세
- `docs/spec/PHASE2_FITTING_AUDIT.md` §9 : IC structural tier separability(컨닝) 사례

## 추가 제약 (inspector 보완 2026-06-02)

- **룰 ID 충돌 금지**: employee_vendor master-join = **R08**, circular = **R09** 로 분리한다.
  (employee-vendor 작업에서 R08 을 이미 선점했으므로 circular 은 R09. R08 중복 금지.)
- **순환 = topology 단독 금지**: cycle 위상만으로 flag 하면 IC reciprocal 의 19.7% 오탐과
  동일한 실패를 반복한다. 정상 그룹 순환(cash pooling·intercompany netting·위탁·라운드트립
  자금)이 합법적으로 존재하기 때문이다. cycle 위상 + 보강 이상신호(off-market/라운드 금액,
  문서체인·물류 부재, 비정상 timing, 순환 내 신규/휴면 거래처)를 결합하고, 정상 순환 FP 를
  lift 로 반드시 측정한다.
- **owner-metadata 재배치 정합**: circular 34 는 현재 IC primary
  (`injected_intercompany_primary`)로 라벨돼 있다. 이를 relational primary 서브타깃으로
  이관하고, `tools/scripts/measure_phase2_family_responsibility_recall_*` 의 `_owner_masks`
  와 IC primary 정의(대사 증거로 재서술)를 **동시** 갱신한다. 이중계상 금지.
- **relational 2-primary surface**: relational 은 이제 master-join(employee-vendor) +
  cycle(circular) 두 primary 메커니즘을 갖는다. review surface 재설계 시 두 lane 을 함께
  수용하고, 제거한 token profile lane 은 영구 삭제 상태를 유지한다.
- **DataSynth circular 재생성 규율(필수)**: circular 데이터는 scenario 토큰이나
  self-balanced reciprocal 컨닝이 아니라 **오직 그래프 위상으로만** 탐지 가능해야 한다.
  재생성 데이터는 employee-vendor 와 동일한 **전 컬럼 오라클 스캔**(어떤 단일 journal 컬럼
  값도 truth 를 N>=5 & normal==0 으로 분리 불가)을 통과해야 한다. (employee-vendor 에서
  토큰이 협력사→임직원→mutation_* 로 두 번 누출된 전력이 있으므로 circular 도 동일 검사.)
