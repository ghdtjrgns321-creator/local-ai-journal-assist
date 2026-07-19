# 채점 harness spec — scheme × surface 매트릭스 (T7)

목적: 주입 데이터셋에서 각 부정 scheme을 3 surface가 얼마나 잡는지 측정. **3-surface 불변식**: 병합 점수 없이 surface별로 따로 보고(DESIGN ④). 리콜은 보조지표, 주 산출은 진단(어느 단계가 어디서 약한가).

입력: 주입 데이터셋(journal_entries.csv) + truth sidecar(member_document_ids·generated_pattern_name·weak_signal·declared_violations). 출력: `benchmark_report.md`.

## 1. 분모 — in-scope scheme
- scheme = truth의 한 부정 사건(natural_unit). Phase1은 document 단위(595 = 119×5벌), Phase2는 flow/graph 단위 추가.
- 채점 분모 = **in-scope scheme 수**(seed별 분리 집계 + 합산). 헤드라인 catch = 분자/분모 M/N 명시.
- out-of-scope(blind-spot)는 분모에서 제외 — 별도 표(§10 음의공간). weak-signal scheme은 분모 포함하되 미검출을 자동 결함으로 보지 않음(§5).

## 2. catch 정의 3종 (DESIGN §1⑤ 잠금 — 사전등록 임계, 사후조정 금지)
| surface  | "잡았다" 정의                                                         | 단위     | 임계                                |
| -------- | --------------------------------------------------------------------- | -------- | ----------------------------------- |
| PHASE1-1 | scheme 전표 ≥1건이 named 룰 발화(review queue 진입)                   | scheme   | 룰 발화 binary                      |
| PHASE1-2 | scheme의 계정/사용자/거래처가 flagged 버킷 포함(Benford·D01/D02·배지) | 엔티티   | detector lock값 그대로(재튜닝 금지) |
| PHASE2   | scheme 전표가 TOP-K 진입, **K=상위 1%**(리뷰예산)                     | recall@K | K=1% 헤드라인 + 곡선 0.5/1/5%       |

- **헤드라인 단위 = scheme-level**: scheme의 전표 1건만 surface돼도 "잡았다"(감사인이 실을 당김). document-level은 보조.
- PHASE2 K는 결과 보기 전 동결. recall@K = (TOP-K 안에 든 fraud scheme 수)/(in-scope scheme 수).
- surface는 firewall 통과 입력(라벨·mutation·hint 제거)만 본다.

## 3. 산출 — scheme × surface 커버리지 매트릭스
- 행 = scheme(또는 패턴족 집계), 열 = 3 surface. 값 = caught(1/0) 또는 recall@K.
- **"어느 단계에서 얼마나"** = surface별 열 합 / 분모. 한 scheme이 여러 surface에 동시 catch = 정상(defense in depth).
- 패턴족별 분해: 가공전표·비용자산화·계정분류(Phase1) / 횡령·승인·순환(Phase2) 각각 surface별 catch율.
- seed 5벌 간 catch 안정성(벌별 편차) 병기 — 흔들리면 운빨(§8).

## 4. 진단 항목 (주 산출)
- **0-surface scheme 목록**: 어느 surface도 못 잡은 in-scope scheme(범위 내 = 결함 후보, DESIGN ⑨ 바닥선 게이트 대상). weak-signal 제외 후 집계.
- surface별 약점: 어떤 패턴족을 어떤 surface가 구조적으로 못 잡나.
- blind-spot 표(out-of-scope): 애초에 못 심은 부정(omission 등) — 분모 밖 별도.

## 5. 합격 판정 연결(T8)
- 유일 HARD 게이트 = "범위 내 scheme은 최소 1개 surface가 잡아야"(0-surface = 결함). weak-signal·out-of-scope 게이트 면제.
- 리콜 수치는 진단 보조. 병합/단일점수 금지.

## 6. surface 실행 경로 (Explore a114bd21 매핑, 코드 근거)

**표준 경로**: `AuditPipeline.run(csv_path)` (src/pipeline.py:472) → validate→feature→detect→aggregate→phase1_case. firewall(`strip_detector_forbidden_columns` schema_validator.py:42-55)·feature(`generate_all_features` feature/engine.py) 자동 통과. 반환 `PipelineResult`(pipeline.py:243): `.results`(surface별 DetectionResult), `.phase1_case_result`(전표 case+rule hits), `.data`(행 단위 점수).

| surface                   | 진입/추출                                                                                           | 상태                                                                                        | catch 추출                              |
| ------------------------- | --------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- | --------------------------------------- |
| PHASE1-1 룰               | `res.phase1_case_result.cases[*]`의 fired_rule_ids/raw_rule_hits (phase1_case_builder.py:629)       | ✅ 실행가능·학습불필요                                                                      | scheme 전표 ≥1건 룰 발화 → scheme catch |
| PHASE1-2 graph/relational | —                                                                                                   | ⛔ **삭제됨**(2026-06-30, detector 파일 없음)                                               | 측정불가(도구 경계 — blind, 결함 아님)  |
| PHASE1-2 timeseries       | `res.results` track=`timeseries`(TS01/TS02, timeseries_detector.py)                                 | ✅ 실행가능                                                                                 | flagged_indices → 전표 → scheme         |
| PHASE2 VAE                | `res.results` track=`ml_unsupervised`.scores, 또는 `run_phase2_inference` (inference_service.py:43) | ✅ 모델존재(data/companies/test·_ci_baseline). **비익명 ctx+model_dir 필수**, 아니면 빈결과 | scores 상위 K% → scheme recall@K        |

- **주의(§9 hollow 방지)**: PHASE2는 조용히 skip될 수 있음 → harness가 VAE scores **비어있지 않음**을 먼저 단언. 빈결과면 "측정불가"로 정직 표기(0 catch로 위장 금지).
- **PHASE1-2 축소 현실**: graph/relational 삭제로 순환거래(Phase2) surface가 timeseries뿐 → 순환은 PHASE1-2로 거의 못 잡을 것(구조적 blind, 결함 아님·도구경계). 리포트에 명시.
- **참고 구현 재사용**: `tools/scripts/measure_phase1_detector_catch.py`(CSV→feature→detector→truth)·`profile_phase1_v126.py`. 바퀴 재발명 금지.
- **firewall + truth 분리**: detection 입력엔 라벨 없음(자동 strip). truth는 sidecar(`labels/*_truth.csv`)에서만 로드(`ingest/datasynth_labels.py`).
