# text_features 단위 테스트 결과

> 실행일: 2026-03-20 | 38 passed, 0 failed | 0.18s

## 1. 테스트 요약

| 테스트 클래스              | 케이스 수 | 결과 | 검증 대상                         |
|:---------------------------|:---------:|:----:|:----------------------------------|
| TestCombineText            | 5         | ✅   | line+header 결합: 양쪽 있음/한쪽만/양쪽 None/텍스트 컬럼 부재 |
| TestCleanText              | 4         | ✅   | 키워드 매칭 전 정제: 공백/특수문자 제거, 한글+영숫자 보존, None→빈문자열 |
| TestIsNoisePattern         | 11        | ✅   | 노이즈 판정: 자음만/특수문자만/동일문자 반복/정상 텍스트/빈 문자열 |
| TestMatchRiskLevel         | 5         | ✅   | 키워드 등급: high/medium/low, high 우선순위, 빈 텍스트 |
| TestDescriptionQuality     | 6         | ✅   | 적요 품질 3단계: normal/missing/poor, concat 구제, 노이즈→poor, 커스텀 min_length |
| TestHasRiskKeyword         | 4         | ✅   | 위험 키워드: 기본 매칭, 은폐 패턴 관통, None→low, 커스텀 키워드 |
| TestAddAllTextFeatures     | 3         | ✅   | 2개 컬럼 생성, 텍스트 컬럼 없어도 동작, in-place 반환 |

---

## 2. 발견된 문제점

없음. 모든 케이스 정상 통과.

---

## 3. 주요 edge case 커버리지

| edge case                          | 테스트                         | 처리 방식                          |
|:-----------------------------------|:-------------------------------|:-----------------------------------|
| line_text + header_text 모두 None  | test_both_none                 | NaN 반환 → missing 판정            |
| 텍스트 컬럼 자체 부재             | test_no_text_columns           | 전체 NaN → missing/low             |
| 은폐 패턴 ("상 품 권", "[상품권]") | test_obfuscated_patterns       | _clean_for_keyword로 정제 후 매칭  |
| 자음/모음만 (ㅋㅋㅋ, ㅎㅎ)         | test_jamo_only                 | _is_noise_pattern → poor           |
| 특수문자만 (..., ---)              | test_special_only              | _is_noise_pattern → poor           |
| 동일문자 반복 (aaa, 111)           | test_repeat_char               | _is_noise_pattern → poor           |
| line만 poor + header 구제          | test_concat_rescue             | concat 후 normal로 승격            |
| strip 원본 길이 사용               | test_strip_length_not_cleaned  | "A B" → len=3 → normal (cleaned면 poor) |
| min_length 커스텀                   | test_custom_min_length         | "ABCD" + min_length=5 → poor       |

---

## 4. 남은 문제점

| 문제                                    | 현상                                          | 해결 시점  |
|:----------------------------------------|:----------------------------------------------|:-----------|
| description_quality 규칙 기반 한계      | 길이+패턴만으로 정밀도 부족                    | Phase 2    |
| 은어/동의어 매칭 불가                   | 정확한 키워드에만 반응 (의미 유사도 미지원)    | Phase 2~3  |
| semantic_similarity/anomaly stub        | no-op + logger.info (Phase 2/3 구현 예정)      | Phase 2~3  |

---

## 5. 실행 명령어

```bash
uv run pytest tests/test_feature/test_text_features.py -v
```
