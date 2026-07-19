# T0 — 생성기 경로 확정 (부분, 진행중)

작성 2026-06-30. 상태: **부분 확인** — 핵심 경로 식별, 정확한 SchemeAction→CSV 라인·firewall 검증 미완.

## 확인된 활성 경로

`crates/datasynth-generators/src/anomaly/injector.rs` = **활성 부정 주입 엔진.** 별도로 부정을 "붙이는" 게 아니라 **정상 `JournalEntry`를 변이(mutate)**한다 → 우리 설계 ③(이음새 없이 정상 안에서 생성)와 이미 정합.

핵심 구성요소(injector.rs import 기준):
| 구성요소                                                       | 파일                    | 역할                                                                                                                        | 우리 설계 대응          |
| -------------------------------------------------------------- | ----------------------- | --------------------------------------------------------------------------------------------------------------------------- | ----------------------- |
| `AnomalyMutationRecord` + `write_to_header(&mut JournalEntry)` | injector.rs             | 변이 provenance를 전표 헤더에 기록(base_event_type·mutated_field·original/mutated_value·reason·**detection_surface_hints**) | ④ expectation + truth   |
| `ScenarioCatalog`                                              | `process_gl_mapping.rs` | base 이벤트 → 부정 변이(`AnomalyMutationType`) 매핑                                                                         | ⑥ 기전 spec의 코드 자리 |
| `SemanticValidator` / `SemanticRule`                           | `semantic_validator.rs` | 변이 정합성 검증                                                                                                            | ⑦ 정합 오라클(기존!)    |
| `SchemeContext`·`SchemeAction` (from `super::schemes`)         | injector.rs:44          | multi-stage scheme 소비                                                                                                     | ③ 기전 엔진             |

## 함의 (계획 수정)

- **schemes/ 신설 부담 ↓**: 부정 주입은 schemes/ 단독이 아니라 **injector가 ScenarioCatalog 변이 + SemanticValidator + scheme orchestration**으로 돈다. T3는 "scheme 4개 신설"보다 **ScenarioCatalog에 FSS 변이 시나리오 추가**가 핵심일 수 있음.
- **T4 오라클 일부 기보유**: `SemanticValidator`가 이미 변이 정합 검증. 3층 오라클을 0부터 안 짜도 됨 — 기존 검증 범위 확인 후 갭만.
- **④ firewall 주의**: 헤더의 `detection_surface_hints`·`mutation_*` 필드가 **detection 입력으로 새면** surface 사전배정 누수(④ 위반). schema.yaml 라벨필드처럼 "detection 입력 금지"인지 **반드시 검증**(미완).

## T0 잔여 (완료조건)

- [ ] `SchemeAction`/`ScenarioCatalog` 변이가 실제 `journal_entries.csv` 컬럼으로 찍히는 라인 특정(파일:줄).
- [ ] `detection_surface_hints`·`mutation_*` 헤더필드가 PHASE1/2 detector 입력에서 제외되는지 확인(firewall).
- [ ] `SemanticValidator` 현재 검증 규칙 목록 → 3층 오라클 대비 갭.
- [ ] grep 이상(`GradualEmbezzlementScheme` 0매치) 원인 — 도구 quirk vs 실제 미사용 재확인.
