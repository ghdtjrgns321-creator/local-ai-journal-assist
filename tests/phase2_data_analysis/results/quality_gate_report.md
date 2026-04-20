# Data Quality Gate Report

**Overall**: ✅ PASS
- 총 21개 체크 / 통과 21 / 실패 0
- Critical 실패: 0

## COMMON (7/7)

- ✅ **full_duplicate_rows**
  - 목표: 중복 행 = 0
  - 실제: 0
- ✅ **line_number_gap**
  - 목표: line_number gap = 0
  - 실제: 0
- ✅ **null_rate_created_by**
  - 목표: created_by null < 1%
  - 실제: 0.00%
- ✅ **null_rate_document_id**
  - 목표: document_id null < 1%
  - 실제: 0.00%
- ✅ **null_rate_debit_amount**
  - 목표: debit_amount null < 1%
  - 실제: 0.00%
- ✅ **null_rate_credit_amount**
  - 목표: credit_amount null < 1%
  - 실제: 0.00%
- ✅ **null_rate_posting_date**
  - 목표: posting_date null < 1%
  - 실제: 0.00%

## P1 (5/5)

- ✅ **benford_mad**
  - 목표: MAD < 0.015 (Nigrini 적합)
  - 실제: 0.00162
- ✅ **december_dominance**
  - 목표: 12월 1순위 fraud_type ≤ 60% (현실적 분산)
  - 실제: 56% (5/9)
- ✅ **after_hours_real_users**
  - 목표: 실사용자 심야 전표 ≥ 200건 (L3-06/L4-05 탐지 타겟)
  - 실제: 849건
- ✅ **exceeded_approval_realistic**
  - 목표: ExceededApprovalLimit 중앙값 ≤ 3,000,000,000 (30억, 중견기업 상한)
  - 실제: 330,000,000원
- ✅ **round_dollar_realistic**
  - 목표: RoundDollarManipulation 중앙값 ≥ 100,000 (10만원)
  - 실제: 1,289,500원

## P2 (6/6)

- ✅ **total_users**
  - 목표: 사용자 수 ≥ 1,000 (대규모 시나리오)
  - 실제: 1,365명
- ✅ **fraud_user_concentration**
  - 목표: Fraud 보유 사용자 비율 ≤ 20% (횡령범 집중형)
  - 실제: 2.4%
- ✅ **clean_user_ratio**
  - 목표: Clean/low 사용자 ≥ 70% (정상 사용자 다수)
  - 실제: 91.0%
- ✅ **yearly_fraud_stability**
  - 목표: 연간 fraud_rate 변동 ≤ 0.5%p (PSI stable)
  - 실제: ±0.01%p
- ✅ **user_docs_p25**
  - 목표: 사용자 P25 전표 수 ≥ 16 (BiLSTM seq_len 충족)
  - 실제: 116건
- ✅ **positive_negative_amount_ratio**
  - 목표: 양성/음성 금액 비율 ∈ [1.3, 5.0] (ML 분리가능)
  - 실제: 3.30x

## P3 (3/3)

- ✅ **top3_approver_share**
  - 목표: Top 3 승인자 비중 ∈ [20%, 50%] (실무 승인 체계)
  - 실제: 38.0%
- ✅ **fraud_type_diversity**
  - 목표: Fraud 타입 ≥ 8종
  - 실제: 9종
- ✅ **automated_system_share**
  - 목표: automated_system 평균 전표 비중 ≤ 50%
  - 실제: 47.8%
