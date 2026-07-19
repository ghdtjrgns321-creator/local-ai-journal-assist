# 3.9 서비스형 구조 분리 계획

## 목표
- `dashboard`가 `CompanyRepository`, `ConnectionManager`, `batch_reader`, `AuditPipeline`을 직접 조합하는 구조를 줄인다.
- UI는 화면 렌더링과 입력 수집에 집중하고, 상태 복원/배치 로드/phase 실행은 서비스 계층으로 이동한다.

## 1차 범위
- `src/services/session_service.py`
  - 회사 전환 시 상태 초기화
  - 저장 배치 session 복원
  - 현재 표시 결과 선택
- `src/services/batch_service.py`
  - 저장 배치 목록 조회
  - 저장 배치 로드 + session 반영
- `src/services/analysis_service.py`
  - phase1/phase2 재분석 orchestration
  - 재탐지 orchestration
  - 공통 `AuditTrail` 생성

## 적용 대상
- `dashboard/app.py`
- `dashboard/components/batch_selector.py`
- `dashboard/components/analysis_runner.py`
- `dashboard/components/_redetect.py`
- `dashboard/components/data_uploader.py`

## 비범위
- REST API 추가
- 인증/권한 모델
- queue worker 분리
- `AuditPipeline` 내부 도메인 분해
