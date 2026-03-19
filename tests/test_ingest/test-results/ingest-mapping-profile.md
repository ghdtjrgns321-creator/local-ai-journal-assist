# Ingest: Mapping Profile 테스트 결과

> 실행: `uv run pytest tests/test_ingest/test_mapping_profile.py -v`
> 일시: 2026-03-19

## 결과: 26 passed

| #  | 카테고리          | 테스트                                     | 결과 |
|----|-------------------|--------------------------------------------|------|
| 1  | fingerprint       | 동일 컬럼 → 동일 해시                       | PASS |
| 2  | fingerprint       | 순서 무관 동일 해시                          | PASS |
| 3  | fingerprint       | 다른 컬럼 → 다른 해시                       | PASS |
| 4  | fingerprint       | 해시 길이 12자                               | PASS |
| 5  | fingerprint       | 공백 포함 정규화                             | PASS |
| 6  | fingerprint       | 대소문자 무관 동일 해시                      | PASS |
| 7  | save_profile      | JSON 파일 생성                               | PASS |
| 8  | save_profile      | JSON 구조 필수 필드 검증                     | PASS |
| 9  | save_profile      | 프로파일에 suggestions 미포함                | PASS |
| 10 | save_profile      | 디렉토리 자동 생성                           | PASS |
| 11 | save_profile      | 재저장 시 created_at 유지                    | PASS |
| 12 | _save_mapping_log | suggestions 있으면 로그 생성                 | PASS |
| 13 | _save_mapping_log | 로그에 suggestions/unmapped 포함             | PASS |
| 14 | _save_mapping_log | 깨끗한 결과 → 로그 미생성                    | PASS |
| 15 | load_profile      | save → load 왕복 일치                        | PASS |
| 16 | load_profile      | 로드 결과 suggestions 빈 상태                | PASS |
| 17 | load_profile      | 없는 프로파일 → None                        | PASS |
| 18 | load_profile      | 손상 JSON → None                             | PASS |
| 19 | load_profile      | 필수 필드 누락 → None                        | PASS |
| 20 | list_profiles     | 빈 디렉토리 → 빈 리스트                     | PASS |
| 21 | list_profiles     | 복수 프로파일 목록 반환                      | PASS |
| 22 | list_profiles     | 메타데이터 필드 포함 확인                    | PASS |
| 23 | delete_profile    | 삭제 성공 + 파일 제거                        | PASS |
| 24 | delete_profile    | 존재하지 않는 프로파일 → False               | PASS |
| 25 | delete_profile    | 관련 로그 함께 삭제                          | PASS |
| 26 | 통합              | save → load → list → delete 전체 워크플로우  | PASS |
