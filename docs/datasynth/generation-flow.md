# DataSynth 생성 흐름

## 전체 구조

현재 생성 흐름은 3단계다.

```text
Rust base generator / materialized profile
  -> NORMAL semantic base
  -> PHASE1 recall overlay 또는 PHASE2 fraud overlay
  -> verifier / shortcut / regression / leak scan
```

핵심 엔트리포인트는 `tools/datasynth/crates/datasynth-cli/src/main.rs`의 `generate --profile` materialization 경로다.
현재 지원되는 관련 profile은 다음과 같다.

| profile | Rust 함수 | 용도 |
| --- | --- | --- |
| `normal-coa-v42` | `normal_coa_v30::materialize_normal_coa_v42` | v42/v43 계열 NORMAL base materialization |
| `phase1-recall-overlay` | `p3_2_overlay::materialize_phase1_recall_overlay` | PHASE1 룰별 standard/boundary recall dataset |
| `phase1-combo-tier-overlay` | `p3_2_overlay::materialize_phase1_combo_tier_overlay` | PHASE1 combo/tier case assembly dataset |
| `p3-2-overlay` | `p3_2_overlay::materialize_p3_2_overlay` | 초기 PHASE1 rule violation overlay |
| `phase2-fraud-r1` | `phase2_scheme_overlay::materialize_phase2_scheme_overlay` | PHASE2 real fraud scheme overlay r4 계열 |
| `phase2-real-schemes` | `phase2_scheme_overlay::materialize_phase2_scheme_overlay` | PHASE2 scheme overlay 호환 profile |
| `manipulation-v7` | `manipulation_v7::materialize_manipulation_v7` | 과거 manipulation v7 계열. 현재 PHASE2 accepted lineage는 semantic v43/r4m 계열 |

## NORMAL 생성

NORMAL 생성은 fraud/anomaly 없는 base를 만든다.
v46b accepted base는 v42 계열 profile에서 다음 결함을 닫은 산출물이다.

- taxable 10% VAT 계산 오류.
- KRW 거래의 `exchange_rate != 1` marker.
- master reference mismatch, vendor orphan, cost center 체계 불일치.
- direct SoD marker 오염.
- 연도별 clone marker와 timestamp 집중.
- TB가 JE에서 파생되지 않는 hollow pass.
- opening balance carry-forward 더미.
- subledger reconciliation의 실측 없는 0 기록.
- PHASE2 overlay에서만 reversal link가 생기는 L6 누출.
- 단일법인 전환 이후 IC GL trace가 0이 되는 회귀.

v46b의 scope는 C001 단일 `company_code`다. C002/C003는 별도 회사 원장이 아니라 관계사 거래처로만
사용하며, 정상 IC GL row와 sidecar trace를 소량 생성한다.

NORMAL 산출물은 다음 파일군을 포함한다.

- `journal_entries.csv`, `journal_entries_YYYY.csv`
- `journal_entries.json`
- `chart_of_accounts.json`
- `master_data/**`
- `document_flows/**`
- `intercompany/**`
- `period_close/trial_balances.json`
- `balance/opening_balances.json`
- `balance/subledger_reconciliation.json`
- `run_manifest.json`, `prov.json`, `generation_statistics.json`

## PHASE1 recall overlay 생성

PHASE1 recall overlay는 NORMAL 문서 수를 유지하면서 일부 정상 문서를 standard violation 또는 boundary control로 대체한다.
목표는 PHASE1-1 룰이 raw trigger를 제대로 잡는지 보는 detector-only 검증이다.

불변식:

- output distinct document count는 base와 같아야 한다.
- 최신 `docs/spec/DETECTION_RULES.md` 기준 26개 PHASE1-1 룰 모두 truth에 있어야 한다.
- standard와 boundary control은 각각 같은 수로 생성한다.
- boundary control은 정상으로 라벨링되고 expected no-fire여야 한다.
- derived answer column을 주입하지 않는다.
- journal/master에는 truth/provenance text가 없어야 한다.
- journal `gl_account`는 dataset CoA와 global CoA에 있어야 한다. L1-03 invalid-account standard 문서의 `999998`만 예외다.

현재 accepted PHASE1-1 recall lineage는 `datasynth_semantic_v1_recall_20260622_v46b_phase1_1_r11`이다.
r11은 최신 firing matrix 기준으로 standard 750/750 caught, boundary 0/750 caught, shortcut findings 0을 달성했다.

## PHASE1 combo/tier overlay 생성

PHASE1 combo/tier overlay는 개별 룰 발화가 아니라 같은 case 안의 rule 조합이 HIGH/MEDIUM/LOW/CONTEXT
tier로 조립되는지 검증한다. `phase1-recall-overlay`와 다른 산출물이다.

불변식:

- truth rows는 buildable combo 13개 + LOW + CONTEXT = 15개다.
- out-of-scope combo 4개는 truth에 없어야 한다.
- member 문서는 실제 flow/case builder가 같은 case로 묶을 수 있어야 한다.
- 수락 기준은 final case `priority_band` 단순 일치가 아니라 expected topic의 actual topic score cut이다.
  같은 case에 독립 broad signal이 섞이면 final band가 더 높아질 수 있기 때문이다.

현재 accepted lineage는 `datasynth_semantic_v1_combo_tier_20260622_v46b_r1z`이다.

## PHASE2 fraud overlay 생성

PHASE2 fraud overlay는 NORMAL base 위에 14개 fraud scheme을 얹는다.
이 dataset은 모델 성능을 맞추기 위한 라벨셋이 아니라, 정상에 섞인 구조적 부정 후보가 단순 표면으로 들키지 않는지 검증하는 입력이다.

핵심 규칙:

- FS01~FS14 scheme coverage가 모두 있어야 한다.
- overlay 문서는 차대변 균형을 유지한다.
- base normal document는 변경하지 않는다.
- overlay가 쓰는 계정, 문서유형, metadata, reversal link, supporting document 조합은 정상 twin 또는 정상 donor 규칙을 가져야 한다.
- seed rotation은 실제 fraud content와 assignment vector를 바꿔야 한다.
- full-column leak scan은 representative와 최소 1개 seed에서 통과해야 한다.

현재 accepted PHASE2 lineage는 `datasynth_semantic_v1_phase2_fraud_20260614_v1_r4m_h`와 `..._r4m_h_seed1`이다.
r4l_b는 15개 shortcut gate와 regression은 통과했지만 2026-06-14 전 컬럼 누출 스캔에서 L4~L7 계열 누출이 재현되어 scale reference로만 남는다.
PHASE2 r4m_h는 v46b NORMAL 위에서 다시 materialize된 최신 산출물은 아니므로, 다음 PHASE2 재생성 시 base 동기화 검증이 필요하다.

## 출력 작성

`tools/datasynth/crates/datasynth-cli/src/output_writer.rs`는 생성 결과를 표준 파일 구조로 쓴다.
주요 동작은 다음과 같다.

- `journal_entries.csv`와 연도별 CSV를 작성한다.
- JSON 산출물, master data, flow, intercompany, tax, balance, quality gate 결과를 안전하게 쓴다.
- `run_manifest.json`에 output file, checksum, seed, config 정보를 남긴다.
- document id/company scope와 same-role reference를 정규화한다.
- profile에 따라 일부 legacy/contract/manipulation truth 컬럼을 drop할 수 있다.

## 기본 명령 패턴

```powershell
cd tools/datasynth
cargo build -p datasynth-cli
```

```powershell
cargo run -p datasynth-cli --bin datasynth-data -- generate `
  --profile normal-coa-v42 `
  --manipulation-source <SOURCE_NORMAL_OR_BASE> `
  --output <NORMAL_OUTPUT>
```

```powershell
cargo run -p datasynth-cli --bin datasynth-data -- generate `
  --profile phase1-recall-overlay `
  --manipulation-source <NORMAL_BASE> `
  --output <PHASE1_RECALL_OUTPUT>
```

```powershell
cargo run -p datasynth-cli --bin datasynth-data -- generate `
  --profile phase1-combo-tier-overlay `
  --manipulation-source <NORMAL_BASE> `
  --output <PHASE1_COMBO_TIER_OUTPUT>
```

```powershell
cargo run -p datasynth-cli --bin datasynth-data -- generate `
  --profile phase2-fraud-r1 `
  --manipulation-source <NORMAL_BASE> `
  --output <PHASE2_OUTPUT>
```

실제 accepted run의 정확한 명령과 산출 경로는 [docs/debugging.md](../debugging.md)의 2026-06-21~2026-06-22 DataSynth 항목을 우선 확인한다.
