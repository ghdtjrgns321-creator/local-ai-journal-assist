# Debugging Log

트러블슈팅 히스토리. 발생한 문제와 해결 과정을 기록하여 같은 실수를 반복하지 않기 위한 문서.

---

## 작성 가이드

```
## YYYY-MM-DD: 문제 제목

**증상**: 무엇이 잘못되었는지
**원인**: 왜 발생했는지
**해결**: 어떻게 고쳤는지
**교훈**: 다음에 주의할 점
```

---

## 2026-03-20: charset_normalizer가 latin-1을 ascii로 오탐

**증상**: bpi2019(527MB, latin-1) 파일 읽기 시 `'ascii' codec can't decode byte 0x96 in position 249785`

**원인**: `text_reader._detect_encoding()`이 64KB만 샘플링. bpi2019의 latin-1 특수문자(0x96)가 249KB 지점에 첫 등장 → 샘플 범위 밖 → charset_normalizer가 ascii로 오탐 → `pd.read_csv(encoding="ascii")`에서 에러

**해결**: `_detect_encoding()`에서 ascii 감지 시 latin-1로 폴백 (1줄 추가). ascii ⊂ latin-1 이므로 부작용 없음.

**교훈**: 샘플 기반 감지는 대용량 파일에서 오탐 가능. "샘플 크기 확대"는 땜질 — 타입 시스템의 포함관계(ascii ⊂ latin-1)를 활용하는 것이 근본 해결.

---

## 2026-03-20: 헤더 탐지 키워드 80% 의존 → 구조적 신호로 전환

**증상**: financial-anomaly(Amount, Timestamp), general-ledger(Date, EntryNo)에서 헤더 탐지 실패 (confidence=0.20). keywords.yaml에 미등록된 범용 영문 컬럼명.

**원인**: 스코어 공식이 `KeywordScore × 0.80 + StringRatio × 0.20` — 키워드 없으면 최대 0.20

**해결**: 5개 구조 신호 가중합으로 전환. TypeDiversity(0.35) + Uniqueness(0.25) + NullDensity(0.15) + Keyword(0.15) + StringRatio(0.10). 키워드 없어도 구조적으로 헤더/데이터 행을 구분.

**교훈**: "키워드를 더 등록"하는 땜질 대신 "데이터 자체의 구조적 신호"를 활용하면 미지의 데이터셋에도 범용 동작.

---

## 2026-03-20: fuzzy 매핑 타입 비호환 오매핑 (drcrk→debit_amount)

**증상**: sap-merged에서 drcrk(차대변 indicator, 'S'/'H' 문자열)가 debit_amount(float)에 매핑 → 캐스팅 100% NaN

**원인**: rapidfuzz가 'drcrk'와 'debit' 문자열 유사도만 비교. 실제 데이터 타입(str vs float)을 무시.

**해결**: 이중 방어 — (1) dc_indicator 표준 컬럼 등록으로 정확 매칭 우선 (2) `_type_compat.py`에서 fuzzy 후보의 소스 타입↔스키마 타입 비교, 비호환 시 스코어 0

**교훈**: 문자열 유사도 매칭은 반드시 타입 검증과 병행해야 한다. "이름이 비슷해도 타입이 다르면 틀린 매핑".
