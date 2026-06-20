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

### NORMAL v43d

날짜: 2026-06-14.

결정:

- v42j는 도메인 7구역 감사 결함을 닫았지만, PHASE2 full-column scan에서 reversal link surface 누출이 발견됐다.
- NORMAL에 linked normal reversal background를 추가하는 base 수정이 승인됐다.
- v43d는 정상 역분개 배경, SoD marker 정책, document-number gate를 정리한 accepted NORMAL이다.

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
| v20~v31 NORMAL 기록 | 생성 원칙 진화와 regression 설계 근거. 현재 accepted 기준은 v43d |
| v42j NORMAL | PHASE1 recall base로는 사용됐지만 PHASE2 current normal은 v43d |
| r4f~r4l non-b | 실패 또는 중간 산출. 삭제 가능/legacy |
| r4l_b | S13 scale reference로 유지. full-column leak 때문에 accepted overlay 아님 |
| v126 freeze | historical contract truth/sidecar 기준. 현행 semantic NORMAL/PHASE2 기준 아님 |
| manipulation v2~v7/fixed 계열 | 과거 anti-fitting/shortcut 수리 이력. 현행 PHASE2 accepted lineage는 semantic v43/r4m |
| Python `build_datasynth_v*.py` patch series | 과거 patch history. 현행 생성 원인은 Rust profile에 반영해야 함 |

## 문서와 코드 근거

현행 기준을 확인할 때 우선순위는 다음과 같다.

1. `docs/debugging.md`의 2026-06-13~2026-06-14 DataSynth accepted lineage 기록.
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

