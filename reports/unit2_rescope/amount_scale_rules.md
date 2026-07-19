# 금액 스케일 의존 룰 식별 — M11 재범위화 근거

측정일: 2026-07-15 · 대상: Unit 2 M11(손익 비율 현실성) 및 금액 현실성 일반

## 결론

**M11이 검사하는 "손익 비율"에는 제품 소비처가 없다. 실질 피해는 "금액 절대 스케일" 쪽이고, 거기 물린 룰은 L1-04·L2-01 2개뿐이다 (2/32).**

M11과 금액 스케일은 별개 문제이며, 섞어서 "손익 현실성"으로 다루면 안 된다.

## 모집단 (검색 전 등록)

| 대상                 |     수 | 출처                                                            |
| -------------------- | -----: | --------------------------------------------------------------- |
| PHASE1 룰            | **32** | `src/detection/rule_scoring.py` 의 `RULE_SCORING_REGISTRY` 실측 |
| `src/detection` 파일 |     49 |                                                                 |
| `src/feature` 파일   |      7 |                                                                 |

## 금액 의존 현황

| 구분                                                             |       M / N |
| ---------------------------------------------------------------- | ----------: |
| 금액 컬럼(`debit_amount`·`credit_amount`·`*amount*`)을 읽는 파일 |     26 / 56 |
| `used_columns` 선언 기준 금액 의존 룰                            | **18 / 32** |
| 그중 **절대 KRW 스케일**에 의존                                  |  **2 / 32** |

**금액 의존 18**: L1-01 · L1-04 · L1-06 · L1-07 · L2-01 · L2-02 · L2-03 · L2-04 · L3-02 · L3-04 · L3-09 · L4-01 · L4-02 · L4-03 · L4-04 · L4-06 · D01 · D02
**비의존 12**: L1-02 · L1-03 · L1-05 · L1-07-02 · L1-08 · L3-03 · L3-05 · L3-06 · L3-07 · L3-10 · L3-11 · L3-12
**`used_columns` 미선언 2 (판정 불가)**: L2-05 · L4-05 — `src/detection/constants.py:540-545`, `:666-669`

## 스케일 불변 근거 (룰별)

| 룰                    | 실제 입력                    | 절대 스케일 의존            | 근거                                                                                                                                                                                                                                |
| --------------------- | ---------------------------- | --------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **L4-03** 절대고액    | 회사×연도별 PM 임계          | **아니오 — 자기 스케일링**  | `anomaly_rules_simple.py:691` `c08_amount_outlier`, 임계산출 `:594-688`. 임계 = `income × pbt_pct × pm_ratio` 또는 `revenue × rev_pct × pm_ratio` — **데이터 자신의 매출/NI에서 파생**. 전 금액에 k를 곱하면 임계도 k배 → 발화 불변 |
| **L4-01** 매출 이상치 | `amount_zscore_log` (3σ)     | **아니오 — 스케일 불변**    | `fraud_rules_feature.py:16` `b01_revenue_manipulation`. log 후 z-score라 상수배는 log 평행이동으로 상쇄                                                                                                                             |
| **L4-02** Benford     | `first_digit` (1~9)          | **아니오 — 스케일 불변**    | `pattern_features.py:187` `add_first_digit` — `str.extract(r"([1-9])")`                                                                                                                                                             |
| **L1-05**             | `created_by` · `approved_by` | **아니오 — 금액을 안 읽음** | 아래 §정정 참조                                                                                                                                                                                                                     |

**L4-03의 유일한 실질 제약**: `income <= 0 && revenue <= 0` 이면 `threshold_basis="unset"` → **발화 0** (`:671-679`). 즉 절대 크기가 아니라 **양(+)의 매출/NI가 나오는 마감 구조**가 요구된다. prod_single 은 매출 775M > 0 이므로 이 조건은 충족한다.

## 진짜 절대 스케일 의존 — L1-04 / L2-01

`config/settings.py:81-88` — **절대 KRW 리터럴**

```python
approval_thresholds: list[int] = [
    10_000_000, 100_000_000, 1_000_000_000,
    5_000_000_000, 10_000_000_000, 50_000_000_000,
]   # 자동승인(10M) → 담당자(100M) → 팀장(1B) → 본부장(5B) → CFO(10B) → 이사회(50B)
```

소비: `src/feature/amount_features.py:621-624` → `add_is_near_threshold`(L2-01) · `add_exceeds_threshold`(L1-04).
두 룰은 `master_data/employees.json` 의 `approval_limit`(절대 KRW)도 읽는다(`amount_features.py:111-123`).

**원장 금액 ↔ `settings.py` 승인한도 ↔ `employees.json.approval_limit` 삼각 정합이 요구되는 유일한 지점.**

## 실측 — 승인한도 대비 원장 금액 분포

분모: 금액>0 행 (prod_single 992,808 / r6 376,727)

|                                  | prod_single (순수 생성기) |           r6 (v42 덧칠) |
| -------------------------------- | ------------------------: | ----------------------: |
| 중앙값                           |              **1,000 원** |              299,700 원 |
| 평균                             |                 33,903 원 |           20,918,701 원 |
| 최대                             |          1,895,748,347 원 |      235,668,747,760 원 |
| **≥ 10,000,000 (최저 승인한도)** |       **274 건 (0.028%)** | **47,058 건 (12.491%)** |
| ≥ 100,000,000                    |            25 건 (0.003%) |       7,203 건 (1.912%) |
| ≥ 1,000,000,000                  |             3 건 (0.000%) |         779 건 (0.207%) |
| ≥ 5,000,000,000                  |                      0 건 |         131 건 (0.035%) |
| ≥ 10,000,000,000                 |                      0 건 |          64 건 (0.017%) |
| ≥ 50,000,000,000                 |                      0 건 |          17 건 (0.005%) |

**전표 중앙값이 1,000원인데 최저 승인한도가 1천만원이다.**
→ L1-04(승인한도 초과)·L2-01(임계 근처)의 모집단이 **274건 vs 47,058건 = 172배** 차이.
→ 상위 3개 한도(5B·10B·50B)는 **발화 자체가 불가능**(초과 행 0건).

**이것이 금액 비현실성의 유일한 구체적 제품 피해다.**

## PHASE2 VAE — 금액 현실성의 기대 효익 0

`src/preprocessing/constants.py:63-118`

```python
# These columns encode synthetic manipulation mechanics or deterministic
# enrichment tails. They are denied for PHASE2 training until a later generator
# version proves each column has non-shortcut real-data-like overlap.
LEAKAGE_DENY_COLUMNS_V6_BASELINE = frozenset({
    "amount_magnitude", "amount_zscore", "credit_amount", "debit_amount",
    "document_approval_amount", "invoice_amount", "local_amount",
    "near_threshold_amount", "supply_amount", "tax_amount",
    "first_digit", "is_round_number", ...
})
```

`:106-118` `LEAKAGE_DENY_COLUMNS_V7_DERIVED` 가 `amount_zscore_log`·`approver_limit_amount`·`near_threshold_*` 추가 차단. `:120-122` 합집합 → `LEAKAGE_DENY_COLUMNS`.

**VAE 학습에서 금액 컬럼이 전량 배제된다.** 차단 사유가 "합성 조작 시나리오가 너무 깨끗하게 분리된다" — 금액 비현실성은 이미 leakage 로 진단돼 컬럼째 격리된 상태다.

VAE 피처는 고정 목록이 아니라 런타임 자동분류(`src/services/phase2_training_service.py:423` → `src/preprocessing/feature_groups.py:46`)이며, deny-list 가 그 앞단에서 금액을 걷어낸다.

> **함의**: "PHASE2 VAE 가 정상 분포를 학습하므로 금액 현실성이 필수" 라는 논거는 현행 코드에서 성립하지 않는다. 금액을 고쳐도 VAE 는 그걸 안 본다. 금액을 deny-list 에서 풀 계획이 없다면 M11 작업의 VAE 효익은 0이다.

## 정정 2건 (기존 문서·메모리의 오류)

**1. "L1-05 = 중요성(materiality)" → 틀림.**
L1-05 는 `src/detection/constants.py:99` 기준 **"Self Approval"** 이다. `src/detection/fraud_rules_access.py:954` `b06_self_approval` 의 `required = {"created_by", "approved_by"}`, 발화식은 `flagged = same_person & ~allowed` 뿐. `high_amount = pd.Series(False, index=df.index)` 로 **고정 False** 이며 요약용으로만 전달(`:1012-1021`) — 발화에 무영향. 코드 주석도 *"L1-05 is binary"*.
중요성(PM)은 **L4-03** 소관이다.
`config/audit_rules.yaml:126` 의 `materiality_amount: 1000000000` 은 `self_approval_immediate_override` 블록에 있으나 전 프로젝트 유일 소비처가 `dashboard/components/pre_analysis_settings.py:142` `_default_materiality_amount()` — **UI 입력창 기본 제안값**이다. 탐지 로직은 이 값을 안 읽는다. YAML 주석: *"Performance materiality placeholder. 1,000,000,000 KRW is not a universal 'correct' threshold."*

**2. `docs/spec/PHASE2_INTERFACE_DESIGN.md` 는 존재하지 않는다.**
실재 위치는 `docs/archive/completed/PHASE2_INTERFACE_DESIGN.md`. 그 문서 §2.2 는 금액을 `SignedLogTransformer` 로 **ML 입력 허용**한다고 적었으나 `constants.py:63-118` 이 전량 deny 하므로 **현행 코드에 의해 무효화**됐다. archive/completed 에 있는 것과 정합. 프로젝트 CLAUDE.md 문서 인덱스가 이 경로를 `docs/spec/` 으로 가리키고 있어 수정이 필요하다.

## `config/**` 금액 임계 리터럴 전수

| 파일:라인                         | 값                                                    | 성격                                      |
| --------------------------------- | ----------------------------------------------------- | ----------------------------------------- |
| `config/settings.py:81-88`        | `[10_000_000 … 50_000_000_000]`                       | **절대 — L1-04/L2-01 실사용**             |
| `config/settings.py:220`          | `graph_gr01_min_amount = 10_000_000.0`                | 절대 — GR01 엣지 최소금액                 |
| `config/settings.py:102`          | `zscore_threshold = 3.0`                              | 상대 — L4-01                              |
| `config/audit_rules.yaml:126`     | `materiality_amount: 1000000000`                      | 절대이나 **detection 미사용** (UI 기본값) |
| `config/audit_rules.yaml:390-392` | `pbt_pct: 0.05` · `rev_pct: 0.005` · `pm_ratio: 0.75` | 비율 — L4-03                              |
| `config/audit_rules.yaml:393`     | `materiality_amount: 0`                               | L4-03 override **OFF**                    |

## 권고

| 항목                                | 조치                                        | 근거                                                                                                           |
| ----------------------------------- | ------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| **금액 절대 스케일**                | **수정 대상**                               | L1-04/L2-01 모집단 274 vs 47,058. 상위 3개 한도 발화 불가                                                      |
| M11 손익 비율(cogs/sga/margin)      | **제품 근거로는 수정 불필요**               | 스케일 불변 룰뿐 · VAE 금액 deny · L4-03은 자기 스케일링                                                       |
| M11 손익 비율                       | **포트폴리오 근거로는 수정 필요할 수 있음** | 감사인이 데모에서 영업이익률 -386% 를 본다. 제품 로직이 아니라 신뢰성 문제 — 사용자 판단 필요                  |
| `target_gross_margin` 등 5개 손잡이 | **죽은 설정 — 제거하거나 배선**             | `validation.rs:551` 이 0~1 범위만 검사하고 버림. je_generator 는 안 읽음. `config.balance.` 전수 검색으로 확인 |
