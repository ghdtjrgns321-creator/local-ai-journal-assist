# accounting_validator L2 회계 검증 테스트 결과

## 요약

```
테스트 실행일: 2026-03-21
모듈:         src/validation/accounting_validator.py
테스트 수:    20개
결과:         20 passed, 0 failed (0.34s)
회귀:         전체 492 tests passed
```

## 검증 범위

| 서브함수               | 테스트 수 | 커버리지                                              |
|:-----------------------|:---------:|:------------------------------------------------------|
| check_balance          |         7 | 정상일치, 불일치, 허용오차 내/초과, NaN, docid 부재, 빈df |
| check_date_continuity  |         5 | 연속, 1일누락, 전부NaT, 단일날짜, 컬럼부재            |
| check_duplicates       |         4 | 중복없음, 2쌍중복, 피처컬럼제외, 빈df                 |
| validate_accounting    |         4 | 정상, 복합이슈, 반환타입, graceful degradation         |

## 핵심 검증 포인트

1. **대차일치 성능 최적화**: `diff_series = debit - credit` 단일 차액 컬럼 → groupby 1회 처리
2. **피처 컬럼 제외**: `get_schema()` 기반 원본 컬럼만으로 중복 판정 — is_weekend 등 제외 확인
3. **Graceful Degradation**: 필수 컬럼(debit/credit/posting_date) 부재 시 crash 대신 기본값 반환
4. **반환 타입**: 모든 필드가 Python 네이티브 타입 (JSON 직렬화 보장)

## 남은 과제

- L3 통계 검증(statistical_validator): Phase 2 예정
- 한국 공휴일 지원: Phase 2에서 `custom_holidays` 연동
- 업종별 영업일 차이 대응: Phase 1c 대시보드 UI에서 고려
