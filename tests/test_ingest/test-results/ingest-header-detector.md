# Header Detector 테스트 결과

> 실행일: 2026-03-18 | Python 3.11.14 | pytest 9.0.2 | **12 passed** in 0.61s

## 요약

| 구분              | 테스트 수 | 결과          |
|:------------------|:---------:|:-------------:|
| 핵심 탐지 로직    |     8     | 8 passed      |
| 메시지 3단계 분기 |     3     | 3 passed      |
| 멀티시트 퍼사드   |     1     | 1 passed      |
| **합계**          |   **12**  | **12 passed** |

## 상세 테스트 케이스

### TestDetectHeaderRow — 핵심 탐지 로직

| #  | 테스트명                      | 시나리오                        | 검증 포인트                                             | 결과 |
|:---|:------------------------------|:-------------------------------|:-------------------------------------------------------|:----:|
| 1  | test_standard_header          | 표준 1행 헤더 (6개 키워드)      | row=0, confidence >= 0.8, matched >= 5, 자동패스 메시지  | PASS |
| 2  | test_erp_style_header         | ERP 제목2행 + 헤더3행          | row=2, confidence >= 0.3, matched >= 3                  | PASS |
| 3  | test_merged_header            | 병합셀 상위 + 실제 헤더 2행    | row=1, confidence >= 0.3, matched >= 4                  | PASS |
| 4  | test_empty_dataframe          | 빈 DataFrame                   | header_row=None, confidence=0.0, 수동입력 메시지         | PASS |
| 5  | test_no_keyword_match         | 비회계 데이터 (인사정보)        | header_row=None, confidence < 0.3, 수동입력 메시지       | PASS |
| 6  | test_dirty_columns_defense    | 유효 키워드 + 빈 컬럼 16개     | row=0, 0/0 방어 정상, matched >= 3                       | PASS |
| 7  | test_trick_data_interference  | 데이터 행에 키워드 간섭         | row=0 (진짜 헤더만 선택), confidence >= 0.8               | PASS |
| 8  | test_i18n_sap_keywords        | SAP 영문 (BELNR, BUDAT, HKONT) | row=0, belnr/budat/hkont 매칭 확인                       | PASS |

### TestMessageTiers — 신뢰도 3단계 메시지 분기

| #  | 테스트명                       | 신뢰도 구간 | 기대 메시지                            | 결과 |
|:---|:-------------------------------|:-----------|:--------------------------------------|:----:|
| 9  | test_high_confidence_auto_pass | >= 0.7     | "완벽히 인식" (자동 패스)              | PASS |
| 10 | test_mid_confidence_warning    | 0.3 ~ 0.7 | "확인해 주세요" (UI 경고)              | PASS |
| 11 | test_low_confidence_manual     | < 0.3      | "직접 헤더 행을 지정" (수동 입력 대기) | PASS |

### TestDetectHeaders — 멀티시트 퍼사드

| #  | 테스트명                | 시나리오                  | 검증 포인트                     | 결과 |
|:---|:------------------------|:-------------------------|:-------------------------------|:----:|
| 12 | test_multi_sheet_facade | ReadResult 전체 일괄 처리 | 시트 수 일치, 각 시트 결과 유효 | PASS |

## 소스 바로가기

| 구분           | 경로                                                         |
|:--------------|:------------------------------------------------------------|
| 테스트 코드    | [test_header_detector.py](../test_header_detector.py)       |
| 테스트 fixture | [conftest.py](../conftest.py)                               |
| 구현 코드      | [header_detector.py](../../../src/ingest/header_detector.py) |
| 모델           | [models.py](../../../src/ingest/models.py)                  |
| 설정           | [settings.py](../../../config/settings.py)                  |
| 키워드 사전    | [keywords.yaml](../../../config/keywords.yaml)              |

## 실행 명령어

```bash
uv run pytest tests/test_ingest/test_header_detector.py -v
uv run pytest tests/test_ingest/test_header_detector.py::TestMessageTiers -v
```
