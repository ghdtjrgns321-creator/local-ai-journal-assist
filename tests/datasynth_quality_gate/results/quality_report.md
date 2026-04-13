# DataSynth 전수 품질검사 리포트
> 실행일: 2026-04-07 23:04 | 소요: 12.3s | 판정: **FAIL**

## 요약
| Tier | 이름 | Pass | Fail | Warning | Skip | 판정 |
|------|------|------|------|---------|------|------|
| T1 | 구조적 무결성 | 15 | 1 | 0 | 0 | FAIL |

## Tier 1: 구조적 무결성
| ID    | 체크 | 상태 | 기대 | 실측 |
|-------|------|------|------|------|
| T1-01 | 행수/컬럼수 | PASS | rows>0; cols∈{39,46} | rows=1,191,815; cols=46 |
| T1-02 | 필수컬럼 존재+dtype | PASS | 필수 10컬럼 존재 + 올바른 dtype | OK |
| T1-03 | 보호필드 NOT NULL | PASS | document_id/company_code/posting_date NULL=0 | null_doc=0, null_cc=0, null_pd=0 |
| T1-04 | 금액 음수 | PASS | 음수 금액=0 (ReversedAmount 등 제외) | neg_count=0 |
| T1-05 | 전표 대차일치 | PASS | 대차불일치 전표=0 (금액변형 anomaly 제외) | unbalanced_docs=0 |
| T1-06 | company_code 도메인 | PASS | company_code IN (C001,C002,C003) | out_of_domain=0 |
| T1-07 | 기간 범위 | PASS | fiscal_year∈[2022, 2023, 2024], period=1~12, posti... | bad_fy=0, bad_fp=0, date_out_of_range=0 |
| T1-08 | 라벨 orphan | PASS | orphan labels=0 | orphan_count=0 |
| T1-09 | 단일행 전표 | PASS | 단일행 전표=0 (UnbalancedEntry+MissingField 제외) | single_line_docs=0 |
| T1-10 | KRW 소수점 | PASS | 소수점 금액=0 (KRW) | fractional_count=0 |
| T1-11 | 문서 내 일관성 | PASS | 문서 내 company_code/posting_date 불일치=0 | inconsistent_docs=0 |
| T1-12 | gl_account 형식 | PASS | gl_account 형식 불일치=0 (InvalidAccount+DormantAccount... | bad_format=0 |
| T1-13 | document_type MCAR 비율 | FAIL | MCAR 빈값 비율 0.5~4% (전역 2% 적용) | null_or_empty=0 (0.00%) |
| T1-14 | gl_account MCAR 비율 | PASS | MCAR 빈값 비율 0.5~4% (전역 2% 적용) | null_or_empty=23,889 (2.00%) |
| T1-15 | change_log 구조 | PASS | 필수 6컬럼 존재 | OK (6컬럼) |
| T1-16 | change_log NOT NULL | PASS | 보호필드 NULL=0 | null_rows=0 |

## 실패/경고 항목 상세
### T1-13 document_type MCAR 비율 [FAIL]
- 기대: MCAR 빈값 비율 0.5~4% (전역 2% 적용)
- 실측: null_or_empty=0 (0.00%)
