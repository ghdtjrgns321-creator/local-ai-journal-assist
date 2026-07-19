# Ingest Pipeline 스트레스 테스트 결과

실행일: 2026-03-28
대상: `tests/phase1_ingest/` (28개 테스트 파일 × 64개 테스트 케이스)
결과: **64 passed, 0 failed** (기존 `tests/test_ingest/` 240개도 회귀 없음)

## 1. 테스트 파일별 결과 요약

```
파일                 시나리오                    테스트 수  결과
────────────────────────────────────────────────────────────────
stress_01            K-기업 멀티시트 Excel        5        5 PASS
stress_02            CP949 + 파이프 구분자        3        3 PASS
stress_03            혼합 날짜/금액 포맷          3        3 PASS
stress_04            필수 누락 + 중복 컬럼        3        3 PASS
stress_05a           확장자 위조 Excel            2        2 PASS
stress_05b           빈 파일 (0 bytes)            1        1 PASS
stress_06            Excel 재저장 오염            3        3 PASS ← 수정됨
stress_07            줄바꿈 적요 필드             2        2 PASS
stress_08            다국가 날짜 포맷 혼재        2        2 PASS
stress_09            BOM + Zero-Width Space       4        4 PASS ← 수정됨
stress_10            trailing delimiter           2        2 PASS
sys_01               정상 CSV (baseline)          3        3 PASS
sys_02               세미콜론 구분                2        2 PASS
sys_03               지연 헤더 (5행)              3        3 PASS ← 수정됨
sys_04               파이프 + 헤더 없음           2        2 PASS
sys_05               혼합 구분자                  2        2 PASS
sys_06               고 결측률                    3        3 PASS
sys_07               손상된 따옴표                2        2 PASS
sys_08               빈 컬럼 + 빈 행              2        2 PASS
sys_09               Latin-1 인코딩               2        2 PASS
sys_10               TSV + 지연 헤더              2        2 PASS ← 수정됨
sys_11               열 수 불안정 TXT             1        1 PASS
sys_12               스파스 DAT                   2        2 PASS
sys_13               Parquet fast path            3        3 PASS
sys_14               잘못된 시트 우선             2        2 PASS
sys_15               빈 행 + 병합셀               3        3 PASS
```

## 2. 모듈별 검증 현황

```
모듈                  테스트 수  PASS  검증 항목
──────────────────────────────────────────────────────────────────────
file_validator         5        5     빈 파일, 위조 Excel, 정상 통과
integrity_checkers     3        3     CP949 경고, 위조 Excel 거부
text_reader           15       15     인코딩/구분자 감지, 줄바꿈, 잘린 행, 지연 헤더
excel_reader           5        5     멀티시트, 병합셀, 시트 스코어링
parquet_reader         3        3     타입 보존, 정상 읽기
header_detector       10       10     지연 헤더, 메타데이터 스킵, 키워드 매칭
column_mapper          8        8     fuzzy match, 중복 dedup, 필수 누락
type_caster           13       13     금액/날짜/빈컬럼/ZWSP 캐스팅
sheet_scorer           3        3     데이터 시트 추천
```

## 3. 수정된 버그 (3건)

### FIX-01: text_reader — EOF inside unclosed quote 폴백

| 항목   | 내용                                                                     |
|--------|--------------------------------------------------------------------------|
| 파일   | `stress_06_excel_curse.csv`                                              |
| 모듈   | `src/ingest/text_reader.py` (`read_text`)                                |
| 증상   | 마지막 행의 큰따옴표가 닫히지 않으면 `ParserError` 발생                  |
| 원인   | C 파서의 `on_bad_lines="warn"`은 토큰화 에러(EOF inside string)에 무력   |
| 수정   | `try/except ParserError` → `engine="python"` 폴백 추가                   |

### FIX-02: text_reader — Sniffer 구분자 오판 방지

| 항목   | 내용                                                                     |
|--------|--------------------------------------------------------------------------|
| 파일   | `sys_03_csv_header_late.csv`, `sys_10_tsv_header_row5.tsv`               |
| 모듈   | `src/ingest/text_reader.py` (`_detect_separator`, `_prescan_max_columns`)|
| 증상   | 메타데이터 행 때문에 `\r`을 구분자로 오인 → 전체 파일이 1컬럼            |
| 원인   | (1) Sniffer가 `\r`을 구분자로 감지 (2) 첫 행 기준 컬럼 수 고정          |
| 수정   | (1) 줄바꿈 문자 구분자 거부 (2) 폴백 비교 (최대 컬럼 수 기준)           |
|        | (3) `_prescan_max_columns`로 최대 컬럼 수 파악 → `names` 파라미터 전달  |

### FIX-03: type_caster — ZWSP(Zero-Width Space) 제거

| 항목   | 내용                                                                     |
|--------|--------------------------------------------------------------------------|
| 파일   | `stress_09_invisible_assassin.csv`                                       |
| 모듈   | `src/ingest/type_caster.py` (`cast_amount`)                              |
| 증상   | "350\u200B000" → `to_numeric` 실패 → NaN                                |
| 원인   | ZWSP(U+200B 등)가 숫자 사이에 삽입되어 변환 차단                         |
| 수정   | `_ZERO_WIDTH_RE` 정규식으로 7종 제로 폭 문자 사전 제거                   |

## 4. 주의 사항 (수정 불필요)

| 항목              | 상태       | 설명                                                    |
|-------------------|------------|---------------------------------------------------------|
| DD.MM.YYYY 경고   | 정상 동작  | `casting_date_dayfirst` 설정으로 제어 가능. 5차 폴백 작동 |
| 혼합 구분자       | 한계 인정  | 행마다 구분자가 다른 파일은 어떤 파서도 처리 불가         |
| 닫히지 않은 따옴표 | 부분 손실  | python 엔진이 처리하나, 흡수된 행은 복구 불가             |

## 5. 변경 파일

| 파일                          | 변경 내용                                |
|-------------------------------|------------------------------------------|
| `src/ingest/text_reader.py`   | Sniffer 검증, prescan, python 엔진 폴백  |
| `src/ingest/type_caster.py`   | ZWSP 제거 정규식 추가                    |

## 6. 테스트 구조

```
tests/phase1_ingest/
├── conftest.py          # 28개 파일 경로 fixture
├── test_stress.py       # Stress Test 01~10 (30개 테스트)
├── test_systematic.py   # Systematic Test 01~15 (34개 테스트)
└── test-results/
    └── ingest-stress-test-summary.md  # 이 문서
```
