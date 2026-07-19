# Streamlit UX 수동 테스트 체크리스트

실행: `uv run streamlit run dashboard/app.py`
테스트 데이터: `data/test/ingest/`

---

## 사전 준비

- [ ] Streamlit 정상 기동 확인
- [ ] Dev mode 토글 위치 확인 (사이드바)
- [ ] Dev mode ON 상태에서 테스트 시작

---

## Part 1: Stress Test 파일 (10개 시나리오)

### stress_01_k_corp.xlsx — 멀티시트 + 병합셀 + 특수문자 헤더

예상 경로: UPLOAD → REVIEW → PIPELINE

```
[ ] 업로드 성공 (에러 없음)
[ ] 시트 선택 UI 표시됨 (UI-2 시트 테이블)
[ ] "표지" 시트가 아닌 "본 데이터" 시트가 추천됨
[ ] 시트 테이블에 행 수, 열 수, 헤더 confidence, 점수 표시
[ ] 다른 시트 선택 시 매핑 결과가 변경됨
[ ] 매핑 테이블 3-tier 표시 (Green/Yellow/Red)
[ ] "[필수] 전표번호" → document_id 매핑됨 (fuzzy)
[ ] "매핑 확인" 클릭 → PIPELINE 실행
[ ] 결과 탭(EDA/Summary/Benford/Explorer) 정상 표시
[ ] 경과 시간 표시됨
```

### stress_02_alien_encoding.dat — CP949 + 파이프 구분자

예상 경로: UPLOAD → REVIEW 또는 PIPELINE

```
[ ] 업로드 성공
[ ] 인코딩 경고 표시 여부 확인 (confidence < 70%이면 UI-1 인코딩 셀렉터)
[ ] 인코딩 셀렉터 표시 시: 다른 인코딩 선택 → "이 인코딩으로 다시 읽기" 작동
[ ] 파이프 구분자 감지되어 다중 컬럼으로 파싱됨
[ ] 한글 데이터(확장 완성형 포함) 깨짐 없이 표시
[ ] 매핑 → 파이프라인 정상 완료
```

### stress_03_type_hell.csv — 혼합 날짜/금액 + BOM + 유령 컬럼

예상 경로: UPLOAD → REVIEW 또는 PIPELINE

```
[ ] 업로드 성공 (BOM이 있어도 에러 없음)
[ ] 매핑 결과에서 "세금코드" 컬럼이 unmapped 또는 경고
[ ] PIPELINE 실행 후 캐스팅 경고 표시 (혼합 금액/날짜)
[ ] 경고 expander 열면 상세 내용 확인 가능
[ ] 결과 탭 정상 표시
```

### stress_04_mapping_breaker.csv — 필수 누락 + 중복 컬럼

예상 경로: UPLOAD → REVIEW (필수 컬럼 에러로 block)

```
[ ] REVIEW 단계 진입
[ ] "금액" 중복 → "금액", "금액_2"로 dedup 표시
[ ] 차변/대변 분리 퀵픽스(UI-4) 표시 여부 확인
[ ] 퀵픽스 버튼 클릭 시 매핑 반영 확인
[ ] posting_date 미매핑 → st.error() 에러 메시지 표시
[ ] 에러 메시지에 "주말/심야/백데이팅 비활성" 등 영향 설명 포함
[ ] "매핑 확인" 버튼이 비활성(disabled) 상태
[ ] "항목코드_V2" → Yellow 구간 매핑 드롭다운 표시
[ ] 드롭다운으로 gl_account 선택 가능
```

### stress_05a_fake_excel.xlsx — 확장자 위조

예상 경로: UPLOAD (에러로 중단)

```
[ ] 업로드 시 st.error() 표시
[ ] 에러 메시지에 "손상" 또는 "무결성" 관련 문구
[ ] Dev mode ON: st.exception()으로 상세 트레이스백 표시
[ ] 파이프라인이 진행되지 않음 (REVIEW/PIPELINE 미진입)
```

### stress_05b_empty.csv — 빈 파일 (0 bytes)

예상 경로: UPLOAD (에러로 중단)

```
[ ] 업로드 시 st.error() 표시
[ ] 에러 메시지에 "빈 파일" 또는 "0 bytes" 문구
[ ] 파이프라인이 진행되지 않음
```

### stress_06_excel_curse.csv — 지수 표기법 + 잘린 행

예상 경로: UPLOAD → PIPELINE (python 엔진 폴백)

```
[ ] 업로드 성공 (ParserError 없이 python 폴백)
[ ] 경고 메시지 확인 ("Skipping line" 또는 잘린 행 관련)
[ ] 지수 표기법 금액이 정상 값으로 표시 (15000000 등)
[ ] 결과 탭 정상 표시
```

### stress_07_memo_rebellion.csv — 줄바꿈 적요

예상 경로: UPLOAD → REVIEW 또는 PIPELINE

```
[ ] 업로드 성공 (줄바꿈으로 인한 크래시 없음)
[ ] 멀티라인 적요가 하나의 셀로 표시 (EDA 탭 등에서 확인)
[ ] 행 수가 예상보다 적을 수 있음 (일부 행 흡수) — 크래시만 아니면 OK
```

### stress_08_frankenstein_date.csv — 다국가 날짜 혼재

예상 경로: UPLOAD → PIPELINE

```
[ ] 업로드 성공
[ ] 캐스팅 경고 확인 (DD.MM.YYYY dayfirst 경고 등)
[ ] ISO/한국어/8자리/슬래시 날짜가 datetime으로 변환됨
[ ] NaT(변환 실패)가 일부 존재해도 파이프라인 정상 완료
```

### stress_09_invisible_assassin.csv — BOM + ZWSP

예상 경로: UPLOAD → PIPELINE

```
[ ] BOM 있어도 업로드 성공
[ ] "전표번호" 컬럼이 document_id로 정상 매핑 (BOM 영향 없음)
[ ] ZWSP가 포함된 금액이 정상 숫자로 변환 (350000 등)
[ ] ZWSP가 포함된 문자열(작성자명 등)은 그대로 보존
```

### stress_10_ghost_pipeline.csv — trailing delimiter

예상 경로: UPLOAD → PIPELINE

```
[ ] 업로드 성공
[ ] trailing delimiter의 유령 컬럼이 보이지 않거나 무시됨
[ ] 11개 유효 컬럼만 매핑/표시
[ ] 결과 탭 정상 표시
```

---

## Part 2: Systematic Test 파일 (15개)

### sys_01_csv_utf8_clean.csv — 정상 기준선

예상 경로: UPLOAD → PIPELINE (fast path)

```
[ ] REVIEW 단계 없이 바로 PIPELINE 진입
[ ] 10행 11열 데이터 정상 표시
[ ] needs_review=False 확인 (REVIEW UI 표시 안 됨)
[ ] 4개 탭 모두 정상 렌더링
[ ] 위험 요약(risk_summary) 표시
```

### sys_02_csv_semicolon.csv — 세미콜론 구분

```
[ ] 세미콜론이 자동 감지되어 다중 컬럼 파싱
[ ] 매핑/파이프라인 정상 완료
```

### sys_03_csv_header_late.csv — 지연 헤더 (메타데이터 4행)

```
[ ] Sniffer 폴백으로 쉼표 감지 성공
[ ] 메타데이터 행이 데이터 행과 분리됨
[ ] 헤더 행("전표번호" 등)이 정상 탐지
[ ] 10행 데이터 정상 표시
```

### sys_04_csv_pipe_noheader.csv — 파이프 + 헤더 없음

```
[ ] 파이프 구분자 감지
[ ] 헤더 없음 → REVIEW 단계 진입 (모든 컬럼 Red)
[ ] 수동 매핑 드롭다운으로 컬럼 지정 가능
```

### sys_05_csv_mixed_delimiter.csv — 혼합 구분자

```
[ ] 크래시 없이 업로드 완료
[ ] 일부 행만 파싱되어도 에러 없음
[ ] 결과가 부정확할 수 있으나 파이프라인 중단은 없음
```

### sys_06_csv_high_null.csv — 고 결측률

```
[ ] 업로드 + 매핑 성공
[ ] 코스트센터(90% NaN) 관련 경고 표시 여부 확인
[ ] 세금코드(100% NaN)가 empty_columns로 분류되는지 확인
```

### sys_07_csv_corrupted_quotes.csv — 손상된 따옴표

```
[ ] 크래시 없이 업로드 완료
[ ] 일부 행이 누락될 수 있으나 에러 표시 없음
[ ] 파싱된 행에 대해 파이프라인 정상 실행
```

### sys_08_csv_empty_cols_rows.csv — 빈 컬럼 + 빈 행

```
[ ] 빈 컬럼이 매핑에서 제외되거나 무시됨
[ ] 빈 행이 NaN으로 처리 (크래시 없음)
[ ] 유효 데이터에 대해 파이프라인 완료
```

### sys_09_csv_latin1.csv — Latin-1 인코딩

```
[ ] 인코딩 자동 감지 (latin-1 계열)
[ ] 유럽 특수문자(é, ü 등)가 깨짐 없이 표시
[ ] 인코딩 confidence에 따라 셀렉터 표시 여부 확인
```

### sys_10_tsv_header_row5.tsv — TSV + 지연 헤더

```
[ ] 탭 구분자 감지 (Sniffer 폴백)
[ ] 메타데이터 행 건너뛰고 헤더 정상 탐지
[ ] 데이터 정상 표시
```

### sys_11_txt_inconsistent_cols.txt — 열 수 불안정

```
[ ] 크래시 없이 업로드 완료
[ ] 열 수 불일치 행에 대한 경고 표시 여부 확인
[ ] 정상 행은 파싱되어 파이프라인 실행
```

### sys_12_dat_sparse.dat — 스파스 DAT

```
[ ] 탭 구분자 감지
[ ] 빈 컬럼 6개가 empty로 분류되거나 무시
[ ] 유효 데이터 20행 정상 처리
```

### sys_13_parquet_typed.parquet — Parquet fast path

```
[ ] 업로드 성공 (Parquet 형식 인식)
[ ] 타입이 이미 올바르므로 캐스팅 스킵 또는 빠른 처리
[ ] fast path → PIPELINE 바로 진입 예상
```

### sys_14_xlsx_wrong_sheet.xlsx — 잘못된 시트 우선

```
[ ] 3개 시트 모두 시트 테이블에 표시
[ ] "전표내역"(3번째 시트)이 최고 점수로 추천
[ ] 추천 시트 선택 시 매핑 정상 동작
[ ] "요약" 시트 선택 시 매핑 실패 또는 경고
```

### sys_15_xlsx_blank_rows_merged.xlsx — 빈 행 + 병합셀

```
[ ] 병합셀이 해제되어 읽힘
[ ] 빈 행/메타데이터를 건너뛰고 헤더 탐지
[ ] 데이터 행 정상 표시
```

---

## Part 3: 공통 UX 검증

### 상태 전이

```
[ ] UPLOAD → PIPELINE (fast path): sys_01로 확인
[ ] UPLOAD → REVIEW → PIPELINE: stress_01로 확인
[ ] UPLOAD → REVIEW (block): stress_04로 확인
[ ] UPLOAD → error: stress_05a, stress_05b로 확인
[ ] 파일 변경 시 전체 상태 리셋 확인
```

### 매핑 프로파일 캐시

```
[ ] 파일 업로드 후 프로파일 저장 확인 (data/profiles/ 디렉토리)
[ ] 같은 파일 재업로드 시 캐시된 매핑 자동 적용
[ ] 다른 구조의 파일 업로드 시 새 매핑 실행
```

### 세션 관리

```
[ ] 같은 파일 재업로드 시 재처리 안 함 (file_key 중복 방지)
[ ] 다른 파일 업로드 시 이전 결과 교체
[ ] 브라우저 새로고침 후 업로더가 초기 상태로 복원
[ ] 결과 있는 상태에서 업로더가 접힌 expander로 표시
```

### 에러 표시

```
[ ] Dev mode OFF: st.error()만 표시 (트레이스백 없음)
[ ] Dev mode ON: st.error() + st.exception() 표시
[ ] 경고: expander 안에 노란색 박스로 표시
[ ] 필수 컬럼 에러: 빨간색 + 영향 설명 포함
```

### 매핑 리뷰 UI (REVIEW 단계)

```
[ ] UI-1 인코딩 셀렉터: confidence < 70% 시 표시
[ ] UI-2 시트 테이블: 멀티시트 Excel에서 표시
[ ] UI-3 엄격도 슬라이더: 임계값 조정 → "엄격도 적용" 작동
[ ] UI-4 금액 퀵픽스: 중복 금액 컬럼 시 표시
[ ] Green 행: 읽기 전용 (수정 불가)
[ ] Yellow 행: 드롭다운으로 선택/무시
[ ] Red 행: 드롭다운 필수
[ ] 추천 컬럼 미매핑 시 경고 expander (비활성 룰 목록)
```

---

## 결과 기록란

| 시나리오 | 결과 | 발견 사항 |
|----------|------|-----------|
| stress_01 | | |
| stress_02 | | |
| stress_03 | | |
| stress_04 | | |
| stress_05a | | |
| stress_05b | | |
| stress_06 | | |
| stress_07 | | |
| stress_08 | | |
| stress_09 | | |
| stress_10 | | |
| sys_01 | | |
| sys_02 | | |
| sys_03 | | |
| sys_04 | | |
| sys_05 | | |
| sys_06 | | |
| sys_07 | | |
| sys_08 | | |
| sys_09 | | |
| sys_10 | | |
| sys_11 | | |
| sys_12 | | |
| sys_13 | | |
| sys_14 | | |
| sys_15 | | |
| 공통 UX | | |
