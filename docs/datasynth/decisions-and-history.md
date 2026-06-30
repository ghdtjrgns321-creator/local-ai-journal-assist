# DataSynth 의사결정 이력

## 현재 채택한 큰 결정

### 1. DataSynth를 메인 합성 전표 소스로 사용한다

초기 공개 데이터셋 검토 후 EY-ASU DataSynth 계열을 메인 데이터 소스로 채택했다.
이유는 회사·계정·전표·사용자·승인·텍스트·라벨을 동시에 생성할 수 있고, 감사 분석용 full-population testbed로 확장 가능하기 때문이다.
현행 프로젝트에서는 upstream DataSynth를 그대로 쓰지 않고, `tools/datasynth/` Rust profile을 프로젝트 요구에 맞춰 materialize한다.

### 2. NORMAL을 먼저 만들고 overlay를 얹는다

PHASE1/PHASE2 부정 데이터는 정상 모집단 위에 있어야 한다.
부정 overlay가 처음 등장하는 계정, 거래처, 증빙, reversal field, timestamp pattern을 만들면 model/detector가 부정 구조가 아니라 생성기 지문을 학습한다.
따라서 NORMAL base에 충분한 정상 배경을 먼저 만든다.

### 3. PHASE1 recall과 PHASE2 fraud overlay는 서로 다른 dataset이다

PHASE1 recall overlay는 규칙 기반 detector의 raw trigger 측정용이다.
PHASE2 fraud overlay는 비지도/구조 surface가 synthetic shortcut 없이 의미 있는 검토 후보를 만들 수 있는지 보는 데이터다.
PHASE1 recall dataset은 PHASE2 ML 학습 또는 full-column leak-free fraud dataset으로 재사용하지 않는다.

### 3-1. PHASE1-1 recall과 PHASE1 combo/tier overlay도 서로 다른 dataset이다

PHASE1-1 recall overlay는 최신 `DETECTION_RULES.md`의 개별 룰 26개가 raw trigger로 발화하는지 확인한다.
combo/tier overlay는 이미 켜진 룰들이 같은 case에서 HIGH/MEDIUM/LOW/CONTEXT tier로 조립되는지 확인한다.
따라서 r11 recall dataset이 accepted여도 combo/tier accepted를 의미하지 않으며, combo/tier는 별도의 actual case-builder gate를 통과해야 한다.

### 4. Detector 성능으로 데이터를 맞추지 않는다

DataSynth의 truth는 개발 검증 보조자료다.
정상성/부정성 판단은 다음 기준으로만 수정한다.

- 회계 실체.
- 정상 업무 배경.
- truth/provenance 추적 가능성.
- label shortcut 제거.
- 검증 도구가 발견한 생성 결함.

### 5. 검증 도구도 검증 대상이다

2026-06-14 full-column leak scan에서 1차 결과 19건 중 10건이 false positive로 판정됐다.
결측률 차이만으로 누출이라고 보지 않고 precision/lift/recall 식별력 기준을 추가했다.
이후 full-column scan은 좁은 shortcut gate를 대체하지 않고 보완하는 필수 gate가 됐다.

## 최신 accepted lineage

### NORMAL v46b

날짜: 2026-06-21.

결정:

- 프로젝트 범위를 단일법인 C001 GL-only로 고정했다.
- 단, 관계사 거래 흔적까지 제거하면 IC 계정과 PHASE1/PHASE2 IC 관련 검증이 빈 모집단이 된다.
- 따라서 C002/C003는 별도 회사 원장이 아니라 C001의 관계사 trading partner로만 존재하게 하고, 정상 IC GL row와 sidecar trace를 소량 생성한다.

검증:

- NORMAL realism verifier PASS 38 / MONITOR 1 / FAIL 0 / BLOCKED 0.
- `company_code=[C001]`.
- IC rows 432, IC docs 216, row share 0.001249.
- IC GL counts: 1150=108, 4500=108, 2050=72, 2700=36.
- company-node graph cycles 0.
- B15/B16/H04 IC checked docs 216, bad docs 0.
- O02 synthetic marker findings 0.
- IntercompanyMatcher smoke returned 432 score rows.

### NORMAL v43d

날짜: 2026-06-14.

결정:

- v42j는 도메인 7구역 감사 결함을 닫았지만, PHASE2 full-column scan에서 reversal link surface 누출이 발견됐다.
- NORMAL에 linked normal reversal background를 추가하는 base 수정이 승인됐다.
- v43d는 정상 역분개 배경, SoD marker 정책, document-number gate를 정리한 당시 accepted NORMAL이다.
- 현재 NORMAL 기준은 v46b이며, v43d는 PHASE2 r4m_h lineage의 base-history로 남긴다.

검증:

- `cargo fmt`, `cargo build -p datasynth-cli` PASS.
- NORMAL realism verifier PASS 33 / MONITOR 1 / FAIL 0.
- TB↔JE, BS equation, carry-forward, subledger PASS.

### PHASE1 recall v42j_r3

날짜: 2026-06-13~14.

결정:

- v42j_r2는 detector recall과 shortcut scan이 통과했지만 CoA coverage gate에서 실패했다.
- CoA 누락은 L1-03이 다른 rule injection의 신규계정 판별자가 되는 shortcut이므로 수락 불가로 판정했다.
- v42j_r3에서 recall-only normal accounts를 dataset/global CoA에 보강했고 `999998`만 L1-03 invalid-account standard 예외로 유지했다.

검증:

- base docs = output docs = 325,365.
- truth/provenance rows 2,160.
- standard 1,080 / 1,080 caught.
- boundary 0 / 1,080 caught.
- CoA coverage PASS.
- shortcut scan findings 0.

### PHASE1-1 recall r11

날짜: 2026-06-22.

결정:

- 최신 `DETECTION_RULES.md` 기준 PHASE1-1 개별 룰은 26개다.
- 구버전 r9/r10/r42j_r3의 39룰/legacy metadata 기준은 최신 rule firing 검증에 쓰지 않는다.
- r11은 `phase1-rule-firing-matrix.md`의 설명 문장, detector predicate, datasynth variant, boundary control 대조에 맞춰 재생성했다.

검증:

- Dataset: `datasynth_semantic_v1_recall_20260622_v46b_phase1_1_r11`.
- Base: `datasynth_semantic_v1_normal_20260621_v46b`.
- active rules 26 / 26.
- truth units 1,500 = standard 750 + boundary control 750.
- standard 750 / 750 caught.
- boundary control 0 / 750 caught.
- shortcut scan findings 0.
- CoA coverage PASS.

### PHASE1 combo/tier r1z

날짜: 2026-06-22.

결정:

- `phase1-combo-tier-firing-matrix.md` 기준 buildable combo 13개와 LOW/CONTEXT controls를 별도 overlay로 만든다.
- static truth gate와 shortcut scan만으로는 수락하지 않는다. 실제 case-builder가 expected topic score cut을 만족해야 한다.
- 최종 case `priority_band`는 broad normal signal 때문에 기대 tier보다 높아질 수 있으므로, combo/tier 수락의 단독 기준으로 쓰지 않는다.

검증:

- Dataset: `datasynth_semantic_v1_combo_tier_20260622_v46b_r1z`.
- Base: `datasynth_semantic_v1_normal_20260621_v46b`.
- truth rows 15 = buildable combo 13 + LOW 1 + CONTEXT 1.
- static gate PASS.
- shortcut scan findings 0.
- actual case-builder gate PASS: passed rows 15 / 15, failed rows 0 / 15.

### PHASE2 r4m_h

날짜: 2026-06-14.

결정:

- r4l_b는 15개 shortcut gate, regression, seed diversity, surface shortcut scan을 통과했지만 full-column leak scan에서 L4~L7 누출이 재현됐다.
- r4l_b는 scale reference로만 남기고 accepted overlay는 r4m 이후로 미뤘다.
- r4m_h에서 trading partner 분산, donor inheritance, normal reversal background, round amount naturalization을 적용했다.

검증:

- `phase2_shortcut_gate.py`: representative와 seed1 모두 17/17 PASS.
- `verify_phase2_regression.py`: base unchanged 0, label consistency 0/0/0, 14 schemes, self-cancel 0, fraud imbalance 0.
- `scan_overlay_shortcuts.py`: findings 0.
- `audit_full_leak_scan.py`: NEW leak candidates 0.
- seed1도 동일 검증 PASS.

## 폐기 또는 legacy로 보는 기준

| 항목 | 현재 판단 |
| --- | --- |
| v20~v31 NORMAL 기록 | 생성 원칙 진화와 regression 설계 근거. 현재 accepted NORMAL 기준은 v46b |
| v42j/v43d NORMAL | 각각 PHASE1/PHASE2 과거 accepted lineage의 base-history. 현재 NORMAL 기준은 v46b |
| PHASE1 recall v42j_r3/r9/r10 | 구버전 DETECTION_RULES 기준. 최신 26룰 개별 발화 검증은 r11 |
| PHASE1 combo r1i/r1l | static/shortcut 일부 PASS였지만 actual case-builder gate FAIL. accepted 아님 |
| r4f~r4l non-b | 실패 또는 중간 산출. 삭제 가능/legacy |
| r4l_b | S13 scale reference로 유지. full-column leak 때문에 accepted overlay 아님 |
| v126 freeze | historical contract truth/sidecar 기준. 현행 semantic NORMAL/PHASE2 기준 아님 |
| manipulation v2~v7/fixed 계열 | 과거 anti-fitting/shortcut 수리 이력. 현행 PHASE2 accepted lineage는 semantic v43/r4m, 현행 NORMAL은 v46b |
| Python `build_datasynth_v*.py` patch series | 과거 patch history. 현행 생성 원인은 Rust profile에 반영해야 함 |

## 문서와 코드 근거

현행 기준을 확인할 때 우선순위는 다음과 같다.

1. `docs/debugging.md`의 2026-06-21~2026-06-22 DataSynth accepted lineage 기록.
2. `dev/active/datasynth-journal-realism-rebuild/*`의 최신 원칙/검증 카탈로그.
3. `tools/datasynth/crates/datasynth-cli/src/*.rs`의 materialization profile.
4. `tools/scripts/*` 검증 스크립트.
5. `docs/guide/users/18_DATASYNTH_DOMAIN_AUDIT.md`, `19_DATASYNTH_FULL_COLUMN_LEAK_SCAN.md`.
6. `docs/archive/completed/**`와 `tests/datasynth_quality_gate*/results/**` historical evidence.

## 다음 문서 정리 방향

이 디렉터리가 DataSynth의 현재 source of truth가 되려면 다음 후속 정리가 필요하다.

- `dev/active/datasynth-journal-realism-rebuild`의 완료된 원칙/검증 문서를 이 디렉터리로 이관하거나 canonical 링크를 명확히 한다.
- `docs/guide/users/18`, `19`는 사용자 설명용으로 유지하되, 현재 기준은 이 디렉터리에서 요약한다.
- `docs/archive/completed/datasynth*.md`는 historical로 남기고 최신 accepted lineage와 혼동되지 않게 인덱스에서 구분한다.
- 새 DataSynth accepted run이 생기면 `README.md`의 current 기준, `verification-and-tests.md`의 acceptance snapshot, `decisions-and-history.md`의 lineage 표를 함께 갱신한다.
