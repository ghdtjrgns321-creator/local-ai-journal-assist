# LLM 전처리 제안 (③) 테스트 결과

## 요약

| 항목         | 값                |
|:-------------|:------------------|
| 테스트 수    | 70                |
| 통과         | 70                |
| 실패         | 0                 |
| 소요 시간    | 0.22s             |
| 실행 환경    | ollama 패키지 미설치 (mock 기반) |

## 모듈별 테스트 현황

| 모듈                        | 테스트 수 | 통과 |
|:----------------------------|:----------|:-----|
| test_models.py              | 22        | 22   |
| test_ollama_client.py       | 14        | 14   |
| test_prompt_templates.py    | 14        | 14   |
| test_preprocessing_advisor.py | 20      | 20   |

## 핵심 검증 항목

### Pydantic 스키마 (test_models.py)
- StrEnum 5종 값 정확성 + 문자열 비교 호환
- ModelGroupStrategy 기본값/유효값/무효값
- ColumnPreprocessing 필수 필드 누락 → ValidationError
- PreprocessingAdvice JSON 파싱 + 왕복 직렬화 + model_json_schema() 생성

### Ollama API 래퍼 (test_ollama_client.py)
- is_available: 모델 존재/미존재/부분 매칭/연결 실패
- chat: format=dict(Structured Output)/format="json"/format=None 분기
- chat: temperature 커스텀/타임아웃 예외 전파
- stream_chat: 토큰 단위 yield + 빈 토큰 필터링 + stream=True 플래그

### 프롬프트 빌더 (test_prompt_templates.py)
- profile_to_llm_context: 수치형 is_highly_skewed/has_many_outliers 판정
- profile_to_llm_context: 범주형 is_high_cardinality/datetime/boolean/빈 프로파일
- profile_to_llm_context: settings 임계값 변경 시 판정 변동 (monkeypatch)
- build_preprocessing_prompt: 메시지 구조(system+user)/프로파일 데이터 포함

### 전처리 어드바이저 (test_preprocessing_advisor.py)
- rule_based_fallback: 고왜도→median/저왜도→mean/고카디널리티→target/저카디널리티→ordinal
- rule_based_fallback: tree_model scaler=none/distance_model robust vs standard
- rule_based_fallback: datetime→forward_fill/범주형→distance_model scaler=none
- advise: LLM 미실행→폴백/LLM 성공→source="llm"/파싱 실패→2회 시도 후 폴백
- advise: Structured Output format=schema 전달 확인
- to_pipeline_config: tree vs distance 분기/필수 키/imbalance/encoders

## 개선 방안

1. Ollama 실제 연결 E2E 테스트 → `OLLAMA_AVAILABLE=1` 환경변수로 활성화
2. Phase 2 Pipeline 빌더 구현 후 `to_pipeline_config()` → 실제 sklearn Pipeline 생성 통합 테스트
