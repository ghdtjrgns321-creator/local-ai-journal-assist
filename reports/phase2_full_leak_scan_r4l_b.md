# PHASE2 전 컬럼 전수 누출 스캔 — r4l_b/seed1 (2026-06-14)

도구: tools/scripts/audit_full_leak_scan.py (71컬럼 화이트리스트 없이 자동)
대상: r4l_b 대표본 + r4l_b_seed1 (2벌 교차검증, 단일대상 단정 금지)

## 도구 자체 검증 (검증도구도 검증대상)
1차 19건 → precision/lift 가드 부재로 거짓양성 다수.
  결측률차 단독 flag 금지. precision≥25% OR (recall≥25% AND lift≥5) 가드 추가.
  걸러진 노이즈: approved_by/approval_date/delivery_date/profit_center/tax_code/
    tax_amount/reversal_*(정상에도 396건) — 전부 lift<5 (ML 식별 불가).
2차 9건(대표본)/6건(seed1) — 구조적 5종 양쪽 재현.

## 진짜 누출 (2벌 재현)
| ID  | 누출 | 식별력 | 뿌리 |
|-----|------|--------|------|
| L4  | trading_partner V-000001 집중 | precision 48~54% (부정 14~17%) | vendor/IC scheme 거래처 미분산 |
| L5a | invoice_amount·supply_amount 전부 NULL | lift 57, recall 100% | 부수필드 정상규칙 미상속 |
| L5b | auxiliary_account_number 전부 NULL | lift 6, recall 100% | 부수필드 정상규칙 미상속 |
| L5c | event_type×supporting_doc_type 부정전용조합 | 조합당 5~17건 | 정상 쌍둥이 없는 분개유형 |
| L6  | original_document_id 채워짐 | precision 35%, lift 531 | 정상 base에 역분개 거의 없음 |
| L7  | 라운드금액 25M/40M/2.49M 부정전용 | 대표본만 3~6건(seed 없음) | 자연단수 미부여 (약함, 기존 L3) |

## 공통 뿌리
L1/L2(sub_type)·L5 = 동일 병: overlay가 부수필드를 정상 생성기와 다르게 채움/비움.
처방: 부정 분개를 정상 분개(도너)에서 출발 → 금액·계정만 변형, 나머지 부수필드 도너 상속.
L6만 별개: 정상 base(v42j)에 역분개 부재 → v43에 정상 역분개 소량 주입(사용자 승인 2026-06-14).

## 교훈
게이트는 "내가 의심한 컬럼"만 본다(S2_COLS 화이트리스트). 전 컬럼 전수 스캔을
r4m 완료조건(audit_full_leak_scan.py exit 0)으로 상시화해야 미지 누출을 잡는다.
