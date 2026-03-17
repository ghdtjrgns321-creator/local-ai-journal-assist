# Audit Domain Reference

감사 도메인 지식. 코드 변수명·룰 ID 일관성 유지용.

## 감사 기준

- **PCAOB AS 2401**: 부정 감사 기준 (미국)
- **ISA 240**: 부정 관련 감사인 책임 (국제)
- **ISA 520**: 분석적 절차 (Benford 근거)

## 감사 룰 (R001~R008)

| ID | 룰명 | 로직 | 코드 변수 |
|----|------|------|----------|
| R001 | 승인한도 직하 | 금액이 threshold 바로 아래 (예: 5천만원 한도 → 4,900만원대) | `is_near_threshold` |
| R002 | 주말 거래 | 토/일 전기 | `is_weekend` |
| R003 | 심야 거래 | 22:00~06:00 전기 | `is_midnight` |
| R004 | 기말 대규모 | 결산월 마지막 5영업일 + 대규모 매출 | `is_period_end` |
| R005 | 역분개 | 동일금액 반대분개 쌍 | `is_reversal` |
| R006 | 수기 전표 | 자동전표가 아닌 수동 입력 | `is_manual_je` |
| R007 | 위험 적요 | '상품권', '가계정', '대여금' 등 키워드 | `has_risk_keyword` |
| R008 | 관계사 거래 | 특수관계자 간 거래 | `is_intercompany` |

## Benford's Law 판정 기준

| 지표 | 적합 | 의심 | 부적합 |
|------|------|------|--------|
| MAD | < 0.006 | 0.006~0.012 | > 0.012 |
| KS p-value | > 0.05 | 0.01~0.05 | < 0.01 |

추가 검정: Runs test (무작위성), Chi-square

## 표준 컬럼 스키마 (매핑 타겟)

> 상세: [01-project-setup.md](pre-plan/01-project-setup.md)의 `schema.yaml` 섹션

| 컬럼명 | 타입 | 필수 | 설명 |
|--------|------|------|------|
| `journal_id` | str | Y | 전표 번호 |
| `entry_date` | datetime | Y | 전기 일자+시각 |
| `account_code` | str | Y | 계정 코드 |
| `account_name` | str | Y | 계정명 |
| `debit_amount` | float | Y | 차변 금액 |
| `credit_amount` | float | Y | 대변 금액 |
| `description` | str | N | 적요 |
| `department` | str | N | 부서 |
| `created_by` | str | N | 전기자/작성자 |
| `source_type` | str | N | 전표 유형 (자동/수동) |
| `counterparty` | str | N | 거래처 |

## 도메인 용어 ↔ 코드 매핑

| 감사 용어 | 영문 | 코드 변수 |
|-----------|------|----------|
| 전표 | Journal Entry | `journal_entry`, `je` |
| 전기 | Posting | `entry_date`, `entry_time` |
| 적요 | Description | `description` |
| 차변/대변 | Debit/Credit | `debit_amount`, `credit_amount` |
| 역분개 | Reversal | `reversal` |
| 수기전표 | Manual JE | `manual_je` |
| 관계사 | Intercompany | `intercompany` |
| 총계정원장 | General Ledger | `gl`, `general_ledger` |
| 이상징후 | Anomaly | `anomaly` |
| 감사증거 | Audit Evidence | `audit_evidence` |
