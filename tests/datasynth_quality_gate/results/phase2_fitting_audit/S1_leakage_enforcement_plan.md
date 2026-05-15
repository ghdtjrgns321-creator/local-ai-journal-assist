# Stage 1 — Label Leakage Deny-list Enforcement Plan

- dataset: `data/journal/primary/datasynth_manipulation_v3/journal_entries.csv`
- 총 행수: **1,077,767**, 컬럼수 (Stage 0): **53**
- manipulated 행: **1,111** (0.10%)

## 정책

- 초기 deny: 사용자 명시 deny-list ∪ Stage 0 AUROC ≥ **0.95**
- 잔여 검증: X_clean 에서 단일 컬럼 AUROC ≥ **0.99** 인 컬럼은 deny 추가
- 반복 한도: **3 회**
- 타겟 라벨 컬럼 (피처 후보 자체에서 제외): `anomaly_type`, `fraud_type`, `is_anomaly`, `is_fraud`, `sod_conflict_type`, `sod_violation`

## 최종 deny-list (13 컬럼)

| column | s0_auroc | 분류 사유 |
|---|---:|---|
| `detection_surface_hints` | 1.0000 | explicit_user_denylist |
| `document_id` | 1.0000 | s0_auroc>=0.95 |
| `document_number` | 1.0000 | s0_auroc>=0.95 |
| `header_text` | 1.0000 | s0_auroc>=0.95 |
| `ip_address` | 0.9824 | s0_auroc>=0.95 |
| `mutation_base_event_type` | 0.6289 | explicit_user_denylist |
| `mutation_mutated_field` | 1.0000 | explicit_user_denylist |
| `mutation_mutated_value` | 1.0000 | explicit_user_denylist |
| `mutation_original_value` | 1.0000 | explicit_user_denylist |
| `mutation_reason` | 1.0000 | explicit_user_denylist |
| `mutation_type` | 1.0000 | explicit_user_denylist |
| `reference` | 0.9990 | s0_auroc>=0.95 |
| `semantic_scenario_id` | 0.6289 | explicit_user_denylist |

## 반복 audit

### Round 1 — deny size 13

- 잔여 컬럼 수: **38**
- AUROC ≥ 0.99 잔여: **0**

Top 5 잔여 AUROC:

| column | AUROC |
|---|---:|
| `source` | 0.9198 |
| `supply_amount` | 0.8936 |
| `invoice_amount` | 0.8932 |
| `created_by` | 0.8199 |
| `auxiliary_account_number` | 0.8093 |

## 최종 잔여 컬럼 Top AUROC

| column | AUROC |
|---|---:|
| `source` | 0.9198 |
| `supply_amount` | 0.8936 |
| `invoice_amount` | 0.8932 |
| `created_by` | 0.8199 |
| `auxiliary_account_number` | 0.8093 |
| `trading_partner` | 0.8021 |
| `counterparty_type` | 0.7972 |
| `auxiliary_account_label` | 0.7909 |
| `local_amount` | 0.7889 |
| `document_type` | 0.7401 |
| `approved_by` | 0.7401 |
| `line_text` | 0.7052 |
| `business_process` | 0.6937 |
| `gl_account` | 0.6823 |
| `profit_center` | 0.6316 |
| `line_number` | 0.6107 |
| `supporting_doc_type` | 0.5894 |
| `user_persona` | 0.5824 |
| `debit_amount` | 0.5519 |
| `credit_amount` | 0.5494 |
| `has_attachment` | 0.5474 |
| `fiscal_period` | 0.5338 |
| `fiscal_year` | 0.5305 |
| `posting_date` | 0.5302 |
| `document_date` | 0.5297 |

잔여 AUROC ≥ 0.99 컬럼 수: **0**

## Enforce 위치 제안 (src/preprocessing/)

현재 라벨 컬럼 deny 는 `src/preprocessing/constants.py:LABEL_COLUMNS` 에 정의되어 있고, `src/preprocessing/feature_quality.py::_drop_label_columns` 가 학습/추론 양측에서 호출한다. Stage 1 누수 컬럼은 라벨 컬럼과 분리된 *데이터 사이드카* 이므로 별도 상수로 관리하고 같은 drop 경로를 통해 일괄 제거한다.

### Patch 1 — `src/preprocessing/constants.py`

- LABEL_COLUMNS 는 그대로 유지하고, Stage 1 검증된 deny-list 를 신규 상수로 추가.

```diff
--- a/src/preprocessing/constants.py
+++ b/src/preprocessing/constants.py
@@
 LABEL_COLUMNS = frozenset({
     "is_fraud",
     "fraud_type",
     "is_anomaly",
     "anomaly_type",
     "sod_violation",
     "sod_conflict_type",
     "label",
     "target",
 })
+
+# Stage 1 누수 컬럼 deny-list — DataSynth truth sidecar / 식별자 단독 누수 컬럼.
+# Why: Stage 0 AUROC ≥ 0.95 + 명시 mutation_* 메타 + 반복 잔여 audit (AUROC ≥ 0.99)
+# 으로 확정. 학습/추론 양 경로에서 일괄 제거하여 라벨 누수를 차단한다.
+LEAKAGE_DENY_COLUMNS = frozenset({
+    "detection_surface_hints",
+    "document_id",
+    "document_number",
+    "header_text",
+    "ip_address",
+    "mutation_base_event_type",
+    "mutation_mutated_field",
+    "mutation_mutated_value",
+    "mutation_original_value",
+    "mutation_reason",
+    "mutation_type",
+    "reference",
+    "semantic_scenario_id",
+})
```

### Patch 2 — `src/preprocessing/feature_quality.py`

- `_drop_label_columns` 는 LABEL_COLUMNS 만 처리한다. LEAKAGE_DENY_COLUMNS 도 동일 함수에서 일괄 제거하도록 확장.
- `apply_feature_quality_policy` 진입점은 `pipeline_builder.drop_label_columns`, `prepare_training_features` 양측에서 호출되므로 enforce 가 자동 전파됨.

```diff
--- a/src/preprocessing/feature_quality.py
+++ b/src/preprocessing/feature_quality.py
@@
-from src.preprocessing.constants import LABEL_COLUMNS
+from src.preprocessing.constants import LABEL_COLUMNS, LEAKAGE_DENY_COLUMNS
@@
 def _drop_label_columns(df: pd.DataFrame) -> pd.DataFrame:
-    cols_to_drop = [col for col in df.columns if col.lower() in LABEL_COLUMNS]
+    deny = LABEL_COLUMNS | LEAKAGE_DENY_COLUMNS
+    cols_to_drop = [col for col in df.columns if col.lower() in deny]
     if not cols_to_drop:
         return df
     return df.drop(columns=cols_to_drop, errors="ignore")
```

### Patch 3 — `src/preprocessing/feature_groups.py` (방어층)

- `classify_features` 의 `_EXCLUDE_NAMES` 는 식별자만 다룬다. 누수 deny-list 도 자동 제외.

```diff
--- a/src/preprocessing/feature_groups.py
+++ b/src/preprocessing/feature_groups.py
@@
-from src.preprocessing.constants import LABEL_COLUMNS
+from src.preprocessing.constants import LABEL_COLUMNS, LEAKAGE_DENY_COLUMNS
@@
-        if col_name.lower() in _EXCLUDE_NAMES | LABEL_COLUMNS:
+        if col_name.lower() in _EXCLUDE_NAMES | LABEL_COLUMNS | LEAKAGE_DENY_COLUMNS:
             _assign_to_group(groups, col_name, "excluded")
             continue
```

### Patch 4 — 회귀 테스트

- `tests/preprocessing/test_feature_quality.py` (또는 동등 위치) 에 deny-list enforce 검증 케이스를 추가: deny 컬럼이 포함된 df → `apply_feature_quality_policy` 후 모두 제거되는지 확인.

```python
def test_leakage_deny_columns_dropped() -> None:
    from src.preprocessing.constants import LEAKAGE_DENY_COLUMNS
    from src.preprocessing.feature_quality import apply_feature_quality_policy

    df = pd.DataFrame({col: [1] for col in LEAKAGE_DENY_COLUMNS})
    df['debit_amount'] = [100]
    cleaned, _, _ = apply_feature_quality_policy(df, None, for_training=False)
    assert set(cleaned.columns).isdisjoint(LEAKAGE_DENY_COLUMNS)
    assert 'debit_amount' in cleaned.columns
```
