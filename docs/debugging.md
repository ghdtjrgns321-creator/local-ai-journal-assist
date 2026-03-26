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

---

## 2026-03-22: engine.py rules 전달 형식 불일치 → pattern 피처 전부 False

### 증상

Detection E2E 테스트(DataSynth 1M행)에서 B01(매출 이상 변동), B08(수기 전표) 등이 0건.
`is_revenue_account`, `is_manual_je`, `is_intercompany`, `is_suspense_account` 피처가 전부 False.

### 원인

`audit_rules.yaml`의 YAML 구조와 피처 엔진 내부의 기대 형식 간 **깊이(depth) 불일치**.

```
audit_rules.yaml:              get_audit_rules() 반환값:
──────────────                 ────────────────────────
patterns:                      {"patterns": {
  revenue_account_prefixes:        "revenue_account_prefixes": ["4"],
    - "4"                          "manual_source_codes": ["SA", ...],
  manual_source_codes:             ...
    - "SA"                     }}
```

호출 체인에서 문제 발생 지점:

```
경로 A — pattern_features.py 직접 호출 (정상):
  add_all_pattern_features(df, rules=None)
  → rules = get_audit_rules()["patterns"]     ← 자동으로 ["patterns"] 접근
  → rules.get("revenue_account_prefixes")     ← ["4"] 반환

경로 B — engine.py 경유 (버그):
  generate_all_features(df, rules=get_audit_rules())
  → engine.py가 {"patterns": {...}} 을 그대로 pattern_features에 전달
  → rules.get("revenue_account_prefixes")     ← 최상위에 해당 키 없음
  → 빈 리스트 [] fallback → 피처 전부 False → 에러 없이 조용히 실패
```

`pattern_features.py`는 `rules=None`일 때만 자동으로 `["patterns"]`를 꺼낸다.
`engine.py`의 docstring에 "patterns 수준 dict를 넘기세요"라고 적혀있지만,
중첩 dict가 들어와도 **에러 없이 빈 리스트로 fallback**하여 버그를 감춘다.

### 영향 범위

`generate_all_features(df, rules=get_audit_rules())` 형태로 호출하는 코드에서
pattern 피처 4개가 전부 False (first_digit은 rules 미사용이라 영향 없음):

```
is_revenue_account  → B01 매출 이상 변동 미탐지
is_manual_je        → B08 수기 전표 미탐지
is_intercompany     → B10 관계사 순환거래 미탐지
is_suspense_account → C06 가계정 키워드 미탐지
```

기존 feature 단위 테스트는 `rules=None` 또는 평탄 dict로 호출하여 이 버그를 미포착.

### 해결

**`engine.py`에서 방어 처리** — 중첩 dict가 들어오면 자동으로 `["patterns"]`를 꺼냄:

```python
# src/feature/engine.py generate_all_features() 시작 부분 (L116~119)
if rules is not None and "patterns" in rules:
    rules = rules["patterns"]
```

적용 후 E2E 재실행 결과: B01 0→1,069건, B08 0→2건 정상 탐지.

### 회귀 테스트

```bash
uv run pytest tests/test_feature/ tests/test_detection/ -v
```

### 교훈

함수가 dict를 받을 때 **키 부재를 빈 리스트로 fallback하면 버그가 숨는다**.
"조용한 실패(silent failure)"는 즉시 에러보다 디버깅이 훨씬 어렵다.
방어 방법: (1) 공개 API에서 입력 형식 정규화 (2) fallback 시 warning 로그 추가.

---

## 2026-03-26: 브랜치 전략 단순화 시 벌크 커밋 발생

**증상**: `60b9603` 커밋에 116파일(11,198줄 추가)이 단일 커밋으로 들어감. "1커밋 = 1논리적 변경" 원칙 위배.

**원인**: Phase별 feature 브랜치 5개(feat/1a-ingest, 1b-detection, 2-ml, 3-llm, backup) 운용 중 작업이 브랜치 간 왔다갔다하면서 feat/1a-ingest에 미커밋 변경 91파일이 누적. develop+main 2-branch 체제로 전환하기 위해 브랜치 머지 전 안전 확보 목적으로 일괄 커밋.

**해결**: 벌크 커밋 그대로 유지. 머지 시 충돌은 ours(최신본) 기준으로 해결. 파일 손실 없음 확인 완료. 이후 feature 브랜치 전부 삭제하고 develop+main 2-branch 체제로 전환.

**교훈**: 1인 프로젝트에서 phase별 feature 브랜치는 오버엔지니어링. 작업이 phase 간 교차되면 브랜치 전환 시 미커밋 변경 분실 위험이 높아진다. 단순한 브랜치 전략(develop+main)이 안전하다.
