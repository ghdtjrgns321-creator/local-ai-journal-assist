# datasynth(Rust) 생성 핸드오프 — 통합 쓸모 벤치마크 부정 주입

대상: tools/datasynth Rust 생성 컨텍스트. 목표: 정상 합성 장부에 FSS in-scope 227 부정을 **기전 그대로** 심어, 3 surface 검출을 측정할 데이터셋을 만든다. 룰에 끼워맞추지 말고 데이터를 올바르게 생성한다(Python 덧대기 금지, Rust 근본 수정).

## 1. 입력 SoT (이미 동결됨 — 읽고 따른다)
- 설계 잠금: [DESIGN.md](DESIGN.md) (9개 결정, 46컬럼 빈칸 A/B/C/D).
- 모집단 대조표: [INJECTION_POPULATION.md](INJECTION_POPULATION.md) (in 227 / out 247 / N 474, weak 27, blind-spot).
- 6패턴 기전 spec: [pattern_specs/](pattern_specs/) (각 A 고정·C 범위·D 상태·spec선언위반).
- 엔진 현황: [ENGINE_AUDIT.md](ENGINE_AUDIT.md), 경로: [GENERATOR_PATH.md](GENERATOR_PATH.md).
- 판정 정책: docs/spec/CONSTRAINTS.md §통합 쓸모 벤치마크.

## 2. 엔진 재사용 vs 신축 (ENGINE_AUDIT 결론)
- **재사용**: 주입 배선(injector.process_entries→serialize) · provenance→header + 자가검증(위반필수) · firewall(라벨 누수 차단) · 1층 SemanticValidator.
- **신축**: 기전 생성(6패턴) · 상태 인지(D값) · 2·3층 정합 오라클 · schemes/ dead code 폐기 또는 배선 신설.

## 3. 단계 순서 (상태 의존도 기준)
- **Phase 1 먼저 (상태 경량, 새 분개 생성)**: pattern_specs 01 가공전표 · 02 비용자산화 · 03 계정분류. 기존 잔액 참조 의존 낮음 → 2·3층 오라클 없이 1층 + 약한 상태로 착수 가능.
- **Phase 2 후 (상태 중량, 기존 잔액·관계 참조)**: 04 횡령 · 05 승인SoD · 06 순환거래. 2·3층 오라클(§7) 선행 필요.

## 4. 6패턴 컬럼 생성지침 (1:1)
각 패턴은 해당 spec의 A(고정)/C(범위)/D(상태)/spec선언위반을 그대로 따른다. A=엔진 고정, C=범위 추출, D=실재 객체 참조(지어내기 금지), 위반=truth.

| #   | 패턴       | spec                                                | Phase    | 핵심 A 고정                                      | 핵심 D 상태                                                 |
| --- | ---------- | --------------------------------------------------- | -------- | ------------------------------------------------ | ----------------------------------------------------------- |
| 1   | 가공전표   | [01](pattern_specs/01-fabricated-revenue.md)        | 1        | gl=매출/매출채권, source=Manual                  | 약함(새 매출)                                               |
| 2   | 비용자산화 | [02](pattern_specs/02-expense-capitalization.md)    | 1        | gl=자산(차)/비용(대), SA수기                     | 약함(CIP 대체만 참조)                                       |
| 3   | 계정분류   | [03](pattern_specs/03-account-misclassification.md) | 1        | 오분류 계정, SA수기                              | 부실대체형=기존 부실잔액 참조                               |
| 4   | 횡령은폐   | [04](pattern_specs/04-embezzlement-concealment.md)  | 2        | gl=선급/대여/가수금, approved_by=created_by      | **강**: 열린 AR 참조(돌려막기)·유출↔재입금 쌍·가수금 미해소 |
| 5   | 승인SoD    | [05](pattern_specs/05-approval-sod.md)              | 2        | approved_by=created_by, sod_violation=true       | **강**: 이사회결의·계약서 부재                              |
| 6   | 순환거래   | [06](pattern_specs/06-circular-transaction.md)      | PHASE1-2 | counterparty=paper/3자, trading_partner=순환노드 | **강**: A→B→C→A 폐곡선·노드 거래쌍                          |

## 5. B/C 조건부 추출 (독립 랜덤 금지)
DESIGN §2 빈칸표의 B(정상풀)·C(범위)는 **고정된 A값에 맞는 것끼리** 공동출현으로 뽑는다(가수금↔그 계정과 같이 쓰는 거래처·승인자·적요). 독립 난수로 채우면 논리 모순 분개가 나온다(예: 없는 매출채권 갚기). 정상 base에서 공동출현 풀을 만들어 조건부 추출.

## 6. truth sidecar (라벨 = "왜 부정인가"의 정답)
- 행 라벨: is_fraud=true, fraud_type=패턴명, is_anomaly, anomaly_type, sod_violation/sod_conflict_type(해당 시).
- **spec 선언위반 목록**을 transaction별로 기록(이 전표가 일부러 깬 정합규칙) = truth 정의 + 채점 근거.
- 5벌 시드: in-scope 사건 전수를 **위치만** 바꿔 5벌(금액·은닉·범위는 충실 복원 동결, B/C만 재추출).

## 7. 정합 3층 오라클 (생성 후 게이트 — 사고 위반 0)
부정 전표는 **자기 spec이 선언한 위반만 깨고 나머지 정합은 전부 지켜야** 정상이다.
- 1층(한 줄): 차대균형·계정짝·거래처-계정 — 기존 SemanticValidator 재사용.
- 2층(줄 사이): 갚을 invoice·되돌릴 원전표 실존 — 신축.
- 3층(장부상태): 없는 AR 갚기·불가능 잔액·시점 역전 — 신축. 1차 방어 = 상태 인지 생성(존재하는 것만 건드림).
- **오라클 구현 완료(내가 냄)**: `tools/scripts/verify_injection_coherence.py`(spec: COHERENCE_ORACLE_SPEC.md). 7 HARD 불변식(차대·금액·역분개/원전표 실존·시점순서·clearing정합·없는AR). `--self-test` 내장(7/7 발화 검증). **매 재생성 후 이 스크립트로 fraud 문서 사고 0 확인**.
- 통과 기준: spec 밖(사고) 위반 0건. LLM은 게이트 아님(표본 의미점검 보완만).

## 8. firewall + 수용 게이트
- **firewall(재사용+보강)**: truth 라벨(is_fraud 등)·mutation·detection_surface_hints가 detection/feature 입력으로 **새지 않게**. 기존 3중 방어 유지 + **truth 라벨 AST 가드 신설**(ENGINE_AUDIT §6 비대칭 부채).
- **rule-blind**: 생성은 surface 모르고 한다. "어느 surface가 잡아야 한다"는 사전등록 예측으로만 별도 기록(생성 지시 아님).
- **수용 게이트**: (a) 6패턴 각 ≥1 생성, (b) 3층 오라클 사고위반 0, (c) 라벨/힌트 누수 0(detection grep read 0), (d) **분포 누수 스캔 — 전 범주형 컬럼에서 fraud 최빈값 비중>85% & 동일값 normal<20%인 컬럼 0개**(exact-value 오라클로는 못 잡음; source/batch_id 등이 fraud 단독 tell 되면 안 됨), (e) 5벌 모두 (a)~(d) 통과. 미달 시 결함 적시(은폐 금지).
- **수용 게이트 (f) 정합 오라클**: `verify_injection_coherence.py <dataset>` 사고 0.
- **분포 누수 주의(Phase1 v1e 실측 결함)**: source=manual가 fraud 100%/normal 10%, batch_id='' fraud 100%/normal 12%로 잡혔다. 재생성 시 source는 수기조작 subtype만 manual(정상 흐름 편승형은 base source 유지), batch_id는 base batch 소속 상속. 게이트 (d)로 회귀 방지. (v1f_c에서 이 둘은 해결됨.)
- **관계형 누수 주의(v1f_c 잔존 결함, 내 오라클이 잡음)**: approval_date < document_date가 fraud 542/595(92.7%) vs normal 1.7%. 시점 역전(코히런스 사고)이자 2컬럼 관계형 tell — 단일컬럼 (d) 스캔이 못 본다. 오버레이가 document/posting_date를 부정 시점으로 옮길 때 approval_date도 함께 옮겨 **approval ≥ document** 유지. 게이트 (f)로 회귀 방지.

## 9. 끝나고 보고
생성 후 `docs/debugging.md` 갱신(프로젝트 규칙). 채점 harness(T7)·합격판정(T8)은 이 데이터셋을 입력으로 별도 진행.
