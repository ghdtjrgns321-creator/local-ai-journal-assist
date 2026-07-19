# 사이드카 소비처 전수 조사 — U2-1 폐기 근거

측정일: 2026-07-15 · 대상: Unit 2 U2-1 "재무제표 사이드카 9개"

## 결론

**DataSynth 재무 사이드카 4종을 제품 런타임이 읽는 곳은 0곳 / 299 파일.**

U2-1은 아무도 읽지 않는 파일을 만드는 작업이다. 폐기를 권고한다.

## 모집단 (검색 전 등록)

| 대상                 | 파일 수 | 역할        |
| -------------------- | ------: | ----------- |
| `src/**/*.py`        |     228 | 제품 런타임 |
| `dashboard/**/*.py`  |      71 | 제품 런타임 |
| **제품 런타임 소계** | **299** | ← 분모      |
| `tests/**/*.py`      |     356 | 검증        |
| `tools/**/*.py`      |     254 | 도구        |
| `config/**`          |      17 | 설정        |

검색 대상 파일명: `opening_balances` · `trial_balances` · `financial_statements` · `subledger_reconciliation` · `balance/` · `period_close/` · `financial_reporting/`

## 3분류 결과

| 분류                                                |  히트 |    분모 |
| --------------------------------------------------- | ----: | ------: |
| **(a) 제품 런타임(`src/**`·`dashboard/**`)이 읽음** | **0** | **299** |
| (b) 검증기·테스트·도구만 읽음                       |    12 |     610 |
| (c) 문서·주석·리포트 산출물뿐                       |    62 |       — |

`config/**` 히트 0건.

(b) 12건 전량: `tests/datasynth_quality_gate/checks/tier3_crossref.py` · `tools/datasynth/python/datasynth_py/dataframes.py` · `tools/scripts/audit_balance_integrity.py` · `tools/scripts/normal_data_realism_verifier_20260603.py` · `tools/scripts/verify_phase2_quality.py` · `tools/scripts/_tmp_*.py` 7개

## 근거 1 — 제품의 사이드카 로더 레지스트리

`src/db/loader_supplementary.py:647-670` 의 `_LOADERS` 가 제품이 읽는 사이드카 **전량 18개**다.

`document_flows/` 7 · `master_data/` 5 · `labels/` 2 · `subledger/ap_invoices.json` · `subledger/ar_invoices.json` · `intercompany/ic_matched_pairs.json` · `change_log.csv`

**`balance/` · `period_close/` · `financial_reporting/` 는 한 줄도 없다.**

레지스트리 밖 추가 소비처는 `src/feature/amount_features.py:89-108` 의 `master_data/employees.json` 하나뿐이다.

## 근거 2 — 제품은 TB를 사이드카에서 안 읽고 원장에서 재생성한다

`src/validation/tb_reconciliation.py:27-62`

```python
def build_trial_balance(df: pd.DataFrame) -> pd.DataFrame:
    grouped["opening_balance"] = 0.0          # :58 — 하드코딩
    grouped["closing_balance"] = (
        grouped["opening_balance"] + grouped["debit_total"] - grouped["credit_total"]
    ).round(2)
```

같은 파일 docstring(`:7-10`): *"현재 GL 원본에 이월 기초전표(Opening Entry)가 없으므로 TB의 opening_balance는 항상 0이고, closing_balance는 엄밀히 '당기 순증감액(Net Change)'이다"*

`period_close/trial_balances.json` 과 `balance/opening_balances.json` 이 데이터셋 안에 **존재하는데도** 제품은 그걸 무시하고 원장에서 자체 집계하며 기초잔액을 0으로 못박는다.

## 근거 3 — 게이트 자체가 절반은 항등식

| test                      | 성격                                                                      | 근거                                                                                                               |
| ------------------------- | ------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| M01                       | v42 공식 ↔ 검증기 공식 대조. 두 구현이 같은 알고리즘                      | 검증기 `:1841-1861` ↔ `normal_coa_v30.rs:6798-6840` — BS/PL 기간규칙·`net = od-oc+debit-credit`·부호분해 전부 동일 |
| M03                       | `closing` 을 정의한 식을 그대로 재계산해 비교 → 항상 0                    | 검증기 `:1951` 정의, `:1954-1966` 검사                                                                             |
| M04                       | `opening_value` 를 `prior_closing[key]` 에서 꺼낸 뒤 같은지 검사 → 항상 0 | 검증기 `:1941-1943` ↔ `:1969-1972`                                                                                 |
| M07                       | `difference: 0` 이 계산이 아니라 리터럴                                   | `normal_coa_v30.rs:4617-4619` — `subledger_balance` 와 `gl_balance` 에 같은 변수 대입                              |
| M02 (FS 파일 **있을 때**) | v44가 `equity = assets - liabilities` 로 정의 후 `L+E=A` 확인             | `normal_coa_v30.rs:4673`, `:4690`                                                                                  |
| M02 (FS 파일 **없을 때**) | 원장으로 회계등식 실검사 — **실질**                                       | 검증기 `:2052-2066`                                                                                                |

**FS 파일을 쓰면 M02가 실검사 → 항등식으로 강등된다.** 사이드카를 만드는 것이 게이트를 약화시킨다.

## 근거 4 — r6의 M01~M07 PASS는 현실성 근거가 아니다

r6 기초잔액 총자산 = 1000(3.0B) + 1100(1.1B) + 1200(0.9B) + 15110(1.7B) = **67억원**
r6 매출 = 947,974,799,718 / 3년 = **연 3,160억원**
→ **자산회전율 47.2배** (실제 제조업 1~1.5배)

이 상태로 M01~M07 PASS. 게이트가 항등식이라 안 걸린다.

## U2-1 전제의 오류

계약서(820fd827) U2-1 원문:

> base 출력에 `balance/opening_balances.json` 부재로 M01이 BLOCKED. v42의 `write_v42_opening_balances`·`refresh_trial_balances_from_journal`·`write_v44_financial_statements`·`write_v42_subledger_reconciliation` 가 만들던 것을 **생성기가 네이티브로 내야 한다**.

**틀렸다. 생성기는 이미 네이티브로 낸다. 설정이 꺼져 있었을 뿐이다.**

| 사실                                                       | 근거                                                                         |
| ---------------------------------------------------------- | ---------------------------------------------------------------------------- |
| `BalanceConfig.generate_opening_balances` 기본값 = `false` | `datasynth-config/src/schema.rs:4281`                                        |
| `generate_trial_balances` 기본값 = `true`                  | `schema.rs:4282` — 그래서 `trial_balances.json` 만 나왔다                    |
| 설정 off → `phase_opening_balances` 가 빈 Vec 반환         | `enhanced_orchestrator.rs:6364-6367`                                         |
| 빈 컬렉션이면 파일 자체를 안 만듦                          | `output_writer.rs:42-44` `if data.is_empty() { return Ok(()); }`             |
| preset 경로는 이미 켜고 있음                               | `presets.rs:373-375`                                                         |
| `prod_normal.yaml` 에 `balance:` 섹션 없음                 | 최상위 섹션 5개(`global`·`companies`·`chart_of_accounts`·`fraud`·`output`)뿐 |

**실증**: `prod_normal.yaml` 에 `balance: {generate_opening_balances: true}` 3줄만 추가하고 재생성(992,832행, Rust 변경 0줄) →
`Opening balances written: 1 records -> ./output\balance\opening_balances.json`

## 다만 파일 내용은 여전히 틀렸다 (그래도 아무도 안 읽는다)

네이티브 산출 `opening_balances.json` 실측:

| 항목                | 값                                       |
| ------------------- | ---------------------------------------- |
| `total_assets`      | **10,000,000** (총자산 1천만원 — 제조업) |
| `total_liabilities` | 4,000,000                                |
| `total_equity`      | 6,000,000                                |
| `is_balanced`       | `true`                                   |
| `balances`          | 16계정, **전부 양수**                    |

**결함 1 — contra 계정 부호 손실**: 접두1 계정 단순합 13,091,609 vs 선언된 `total_assets` 10,000,000. 차액 3,091,609 = `1510`(1,545,804) × 2 **정확히 일치**. `1510` 은 `sub_type: accumulated_depreciation` (감가상각누계액). 1510을 음수로 두면 자산 = 10,000,000 으로 정확히 맞는다. 코드가 이 한계를 스스로 기록해 뒀다 — `enhanced_orchestrator.rs:1693-1699`: *"GeneratedOpeningBalance.balances loses AccountType, making contra-asset accounts like Accumulated Depreciation indistinguishable from regular assets by code prefix"*.

**결함 2 — v42와 부호 규약이 반대**: 네이티브는 부채를 양수(2000: +695,864), v42는 음수(2000: -900,000,000)로 저장. 검증기 M01(`:1843-1844`)은 `(amount, 0) if amount >= 0 else (0, -amount)` 로 **부호만 보고 차대를 정하므로 v42 규약을 가정**한다. 네이티브 파일을 그대로 쓰면 부채가 차변잔액으로 읽힌다.

**결함 3 — 스케일**: 총자산 1천만원. v42의 67억보다도 나쁘다.

→ 셋 다 고칠 값어치가 없다. **제품 소비처가 0곳이기 때문이다.**

## 권고

| 항목                        | 조치                                                                                                                                                      |
| --------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| U2-1 (사이드카 writer 구현) | **폐기** — 제품 소비처 0/299                                                                                                                              |
| M01·M03·M04·M07             | **게이트 목록에서 제외** — 항등식/자기검사                                                                                                                |
| M02                         | **FS 파일을 쓰지 않는 쪽 유지** — 그래야 원장 회계등식 실검사가 산다                                                                                      |
| M05·M13·M14                 | 원장만 읽음. 공통 게이트(`:1780-1802`)가 파일 부재로 싸잡아 BLOCK 하는 것이 문제 → **게이트 구조를 고쳐 파일 의존을 끊는 편이 파일을 만드는 것보다 싸다** |
| M11                         | 별건. `amount_scale_rules.md` 참조                                                                                                                        |
