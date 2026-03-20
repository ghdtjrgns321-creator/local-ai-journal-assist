# Header Detector 테스트 결과

> 실행일: 2026-03-20 | **20 passed** in 0.35s

## 1. 테스트 요약

| 구분                   | 테스트 수 | 결과     |
|:-----------------------|:---------:|:--------:|
| 핵심 탐지 로직         |     8     | 8 passed |
| 메시지 분기            |     3     | 3 passed |
| 구조적 스코어링 (v2)   |     8     | 8 passed |
| 멀티시트 퍼사드        |     1     | 1 passed |
| **합계**               |  **20**   | **20 passed** |

---

## 2. v1 문제점

**키워드 의존도 80%** → keywords.yaml에 미등록된 컬럼명(Amount, Date, EntryNo)이면 무조건 탐지 실패.

- financial-anomaly: conf=0.20 (키워드 0개) → 탐지 실패
- general-ledger: conf=0.20 (키워드 0개) → 탐지 실패
- 비회계 파일(이름/부서/직급)도 헤더인데 실패로 처리

---

## 3. 개선방안

키워드를 대량 추가하는 대신, **데이터 구조 자체의 신호**로 헤더를 판별:

```
v1: Confidence = KeywordScore × 0.80 + StringRatio × 0.20
v2: Confidence = TypeDiversity × 0.35 + Uniqueness × 0.25 + NullDensity × 0.15
                + KeywordScore × 0.15 + StringRatio × 0.10
```

| 신호          | 원리                                          | 가중치 |
|:--------------|:----------------------------------------------|:------:|
| TypeDiversity | 헤더=100% 문자열, 데이터=숫자/날짜 혼재       | 0.35   |
| Uniqueness    | 헤더=각 셀 고유, 데이터=반복값 존재            | 0.25   |
| NullDensity   | 헤더=NaN 거의 없음                             | 0.15   |
| KeywordScore  | 보조 신호로 격하 (0.80→0.15)                   | 0.15   |
| StringRatio   | 문자열 비율                                    | 0.10   |

---

## 4. v2 개선 결과

| 데이터셋          | v1 conf | v2 conf | 개선                    |
|:------------------|:-------:|:-------:|:------------------------|
| financial-anomaly | 0.20    | **0.85** | 구조 기반 탐지 성공     |
| general-ledger    | 0.20    | **0.77** | 구조 기반 탐지 성공     |
| 비회계 파일       | 실패    | **성공** | 올바른 동작 (mapper에서 차단) |

**테스트 조정 2건:**
- `test_no_keyword_match`: 탐지 실패 → **탐지 성공** (비회계여도 헤더는 맞으니까)
- `test_mid_confidence`: fixture를 숫자+문자열 혼합 패턴으로 변경

---

## 5. 남은 문제점

없음 — 헤더 탐지 단독으로는 모든 케이스 해결. 비회계 파일 필터링은 column_mapper 책임.

---

## 6. 세부 테스트 케이스

### TestDetectHeaderRow (8)

| #  | 테스트명                      | 시나리오                     | 검증 포인트                                          |
|:---|:------------------------------|:----------------------------|:----------------------------------------------------|
| 1  | test_standard_header          | 표준 1행 헤더 (6 키워드)     | row=0, conf >= 0.8, matched >= 5                     |
| 2  | test_erp_style_header         | ERP 제목2행 + 헤더3행       | row=2, conf >= 0.3, matched >= 3                     |
| 3  | test_merged_header            | 병합셀 + 실제 헤더 2행      | row=1, conf >= 0.3, matched >= 4                     |
| 4  | test_empty_dataframe          | 빈 DataFrame                | header_row=None, conf=0.0                            |
| 5  | test_no_keyword_match         | 비회계 (인사정보)            | row=0 **(v2)**, matched=0, 구조 기반 메시지          |
| 6  | test_dirty_columns_defense    | 키워드 + 빈 컬럼 16개       | row=0, 0/0 방어                                      |
| 7  | test_trick_data_interference  | 데이터에 키워드 간섭         | row=0 (진짜 헤더만 선택)                             |
| 8  | test_i18n_sap_keywords        | SAP (BELNR, BUDAT, HKONT)   | belnr/budat/hkont 매칭                               |

### TestMessageTiers (3)

| #  | 신뢰도 구간 | 기대 메시지            |
|:---|:-----------|:-----------------------|
| 9  | >= 0.7     | "완벽히 인식"          |
| 10 | 0.3 ~ 0.7 | "확인해 주세요"        |
| 11 | < 0.3      | "직접 헤더 행을 지정"  |

### TestStructuralScoring (8)

| #  | 테스트명                       | 검증 포인트                 |
|:---|:-------------------------------|:---------------------------|
| 12 | test_type_diversity_string_row | 순수 문자열 → 1.0          |
| 13 | test_type_diversity_mixed_row  | 숫자 혼합 → < 0.5          |
| 14 | test_uniqueness_unique_row     | 고유값 → 1.0               |
| 15 | test_uniqueness_repeated_row   | 반복값 → 0.25              |
| 16 | test_null_density_full_row     | NaN 없음 → 1.0             |
| 17 | test_null_density_sparse_row   | 3/4 NaN → 0.25             |
| 18 | test_structural_no_keywords    | 키워드 0개 → 탐지 성공     |
| 19 | test_message_structural        | "구조" 메시지 포함          |

### TestDetectHeaders (1)

| 20 | test_multi_sheet_facade | ReadResult 일괄 처리, 시트 수 일치 |

---

## 7. 소스 바로가기

| 구현 코드    | [header_detector.py](../../../src/ingest/header_detector.py), [_header_scoring.py](../../../src/ingest/_header_scoring.py) |
|:------------|:------------|
| 테스트 코드  | [test_header_detector.py](../test_header_detector.py) |

```bash
uv run pytest tests/test_ingest/test_header_detector.py -v
```
