# ripple-search 모집단·증거 — 1190 / 2190 / 9990

실행일: 2026-07-15
권위 출처: `config/audit_rules.yaml` (탐지 룰 L2-04 `suspense_account_codes`, L3-10 `high_risk_accounts`가 읽는 SoT)
계기: 계정결정 표 도입으로 부가세를 `1160`/`2110`으로 라우팅하면서, 1190/2190의 의미가 프로젝트 안에서 갈리는지 확인.

## 1. 모집단 등록 (검색 **전** 확정)

| 면     | 범위                                                              | 파일 수 N |
| ------ | ----------------------------------------------------------------- | --------- |
| Rust   | `tools/datasynth/crates/**/*.rs` (target 제외)                    | 867       |
| Python | `src/**`, `tools/scripts/**`, `tests/**` `*.py`                   | 809       |
| config | `config/**` `*.yaml` `*.yml` `*.csv`                              | 15        |
| 기타   | 위 3면 밖 `*.py` `*.yaml` `*.md` (target·.venv·data/journal 제외) | 1,369     |

히트 라인: Rust 37, Python 40, config 8 = **82**.

## 2. 음의공간 증명 (모집단 밖 영향원 0건)

계정코드를 정의·소비할 수 있는 나머지 확장자(`json` `toml` `sql` `sh` `ts` `tsx` `js`)를 전수 검색.

`reports/`·`data/`·`target/`·`.venv/`·`node_modules/`·`docs/` 제외 후 `json` 히트 **2건**:

- `tests/phase2_data_analysis/results/independent_profile.json`
- `tests/datasynth_quality_gate3/results/data_profile.json`

둘 다 **테스트 실행 결과 프로파일**이며 계정 정의·소비 소스가 아니다. `reports/*.json` 히트 20건은 전부 과거 게이트 실행 산출물이다.

→ **위 4개 면 밖에 1190/2190/9990을 계정으로 정의하거나 계정 선택을 구동하는 소스 0건.**

## 3. 히트 전수 3분류 (분모 = 히트 라인 82)

| 분류                     | 위치                                                                       | 히트 라인 | 조치                                                                                                                            |
| ------------------------ | -------------------------------------------------------------------------- | --------- | ------------------------------------------------------------------------------------------------------------------------------- |
| **[소스] 계정결정 경로** | `je_generator.rs` `account_numbers.choose` / `role_candidates.choose`      | **0**     | Unit 1에서 `determine_account()`로 대체 완료                                                                                    |
| [소스] fraud 경로        | `je_generator.rs` `SUSPENSE_GL_CODES`·적요 튜플                            | 18        | **유지**. `NORMAL_SUSPENSE_RATE=0.0`이라 NORMAL 무영향. 1190/2190이 가지급금/가수금으로 확정되어 이 경로의 의미는 이제 **맞다** |
| [소스] v42/overlay 덧칠  | `datasynth-cli/*.rs` (`normal_coa_v30`, `p3_2_overlay`, `manipulation_v7`) | 16        | **Unit 2 철거 대상**. `normal_coa_v30.rs:6478` `"1190" => "INPUT_TAX_RECEIVABLE"`이 CoA와 정면 모순                             |
| [config] 제품 설정       | `config/audit_rules.yaml`, `config/chart_of_accounts.csv`                  | 8         | `chart_of_accounts.csv` 1190→가지급금, 2190→가수금 **수정 완료**. `audit_rules.yaml`은 이미 맞아 유지                           |
| [소스] 제품 탐지 코드    | `src/**/*.py`                                                              | **0**     | 계정코드 하드코딩 없음 (config 경유) — 전역 룰 "GL 계정코드 코드상수 금지" 준수 확인                                            |
| [Python 덧칠]            | `tools/scripts/build_datasynth_v*.py`                                      | 11        | `v74:47` 치팅 플래그 제거 완료. 나머지 10건은 Unit 2 철거 대상                                                                  |
| [테스트]                 | `tests/**/*.py`                                                            | 29        | **재실행 대상** (내용 수정 아님)                                                                                                |

## 4. 5-way 정의 충돌 → 1-way 수렴

| 위치                                     | 종전 정의                                          | 조치                                                                                        |
| ---------------------------------------- | -------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| `config/audit_rules.yaml:134,349`        | 가지급금 / 가수금                                  | 유지 — **기준으로 채택**                                                                    |
| `je_generator.rs:1848,1889` 적요         | 가지급금 / 가수금                                  | 유지 — 기준과 일치                                                                          |
| `config/chart_of_accounts.csv:94,188`    | 기타유동자산 / 기타비유동부채                      | → **가지급금 / 가수금** 수정                                                                |
| datasynth CoA (`build_datasynth_v74:47`) | 기타유동자산 + `is_suspense_account=true` 하드코딩 | → 하드코딩 **제거**. `coa_generator`가 `Suspense Receivable`/`Suspense Payable`로 직접 생성 |
| `normal_coa_v30.rs:6478,6483`            | 부가세대급금 / 부가세예수금                        | v42 덧칠 — **Unit 2 철거 대상** (유일한 잔존 모순)                                          |

근거: 한국 실무 CoA에서 가지급금과 부가세대급금은 별개 계정이다. 부가세는 계정결정 표가 `1160 Input VAT` / `2110 VAT Payable`로 보내므로 1190/2190과 충돌하지 않는다.

`9990 통계계정`: 통계계정은 가계정이 아니고 원장 0행이므로 가계정 플래그 제거.

## 5. 잔존 (Unit 2 이월)

- `normal_coa_v30.rs:6478` — `fallback_subtype`이 CoA를 읽지 않고 `1190 => INPUT_TAX_RECEIVABLE` 상수 매핑.
- `append_v47_p2p_tax_doc`(`:886,895`) / `append_v47_o2c_tax_doc`(`:888`) — 세금 전표 계정을 1190/2190으로 하드코딩.
- `tools/scripts/build_datasynth_v42/v45/v61/v92*.py` — 1190/2190을 suspense prefix로 취급하는 Python 덧칠 10건.
