# PHASE1-2 문서 ↔ 코드 정합 검증

측정 2026-07-15. 대상: 백엔드 구현([backend_verify.md](backend_verify.md))의 코드 변경을 문서에 반영한 결과 검증.

> ## ⚠️ 1차 자기보고는 독립 검증에서 REFUTED 됐다
>
> verdict: `.claude/state/verdicts/b845e72a-9d75-43a0-aa2d-e712f9c1a62a-1.json` (fresh 에이전트, 생산자 추론·스크립트 미전달, 반증 프레임)
>
> | 주장                                | 결과          | 내용                                                                 |
> | ----------------------------------- | ------------- | -------------------------------------------------------------------- |
> | C1 갱신 대상 문서 5개 **전수**      | **REFUTED**   | 최소 4개 누락(CLAUDE.md:35·:67, DETECTION_RULES.md:506·519, 룰원칙해설.md, r03-ts01 plan) |
> | C2 코드 심볼 22/22 실재 + 실제 read | 반증 실패     | 주장 유지                                                            |
> | C3 삭제 코드 현행 참조 **0건**      | **REFUTED**   | GR01(GraphDetector)·IC01~03 을 현재형 "담당/소관"으로 지목한 곳 다수 |
> | C4 구 용어 현행 서술 0건            | 반증 실패     | 주장 유지                                                            |
> | C5 문서 서술 = 코드 동작            | 반증 실패(caveat 1) | 검증자가 probe 자작·실행: 입구 가드·is_round_number 경계 12종·라운드넘버 3축·시계열 배선제거·키 분리 전건 일치. caveat = `summarize_phase1_case_result` 의 `[:5]` |
>
> **자기보고가 놓친 것**: 생산자는 CLAUDE.md 를 "ROLE_LOCK 링크 깨짐"으로만 인지했고, **CLAUDE.md 의 PHASE1-2 서술 자체가 stale** 이라는 사실은 포착하지 못했다. 내가 짠 검사기가 내 산출물에 낸 초록불은 정보량이 0이라는 것의 실례.
>
> 반증 4건은 생산자가 **직접 재확인**(sed 로 원문 확인) 후 아래 §2 에서 수정했다.

## 1. 편집한 문서 — 1차 5개 → **2차 포함 10개**

| 문서                                                    | 주요 변경                                                                                              |
| ------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| `docs/spec/DETECTION_RULES_PHASE1-2.MD`                 | 자기 큐 6→5종 · 시계열 폐기 절 신설 · 라운드넘버 명세 교체 · 입구 가드 절 신설 · 첫등장/희소 구현 갱신 |
| `docs/spec/DETECTION_RULES_PHASE2_ML.md`                | timeseries → PHASE2 lane 잔류(2곳: 상단 배너 §6·9, 하단 supersede 배너 §168)                           |
| `docs/archive/completed/PHASE2_TIMESERIES_ROLE_LOCK.md` | supersede 취소 노트 추가, 구 2026-06-30 노트를 역사 기록으로 강등                                      |
| `dev/active/phase1-2-code-rework/PLAN.md`               | 상단 변경 대조표 · Phase 1 → 입구 가드 · §6 시계열 폐기 근거                                           |
| `dev/active/phase1-2-code-rework/HANDOFF.md`            | 전면 재작성("코딩 미착수" → 완료/폐기 현황 + 미해결 5건)                                               |
| `dev/active/phase1-2-code-rework/backend_verify.md`     | §8.6 문서갱신 완료 표기                                                                                |

### 1.1 2차 — 반증으로 드러난 누락 (4개 문서 + 자기 오류 2건)

| 문서                                                 | 반증이 지적한 사실                                                                                                                                                                | 수정                                                             |
| ---------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| `CLAUDE.md:35`                                       | PHASE1-2 를 "graph·relational·시계열 구조 단위 전용 탐지기"로 서술 — **3요소 전부 현행 아님**                                                                                     | 자기 큐 5종 + 배지 구조로 재작성, 삭제·잔류 명시                 |
| `CLAUDE.md:67`                                       | 인덱스가 대상 문서를 "GR01/03"로 기술. 정작 그 문서 :28 은 "완전 삭제" 선언 — **정면 모순**                                                                                       | 자기 큐 5종 + 배지로 교체                                        |
| `docs/spec/DETECTION_RULES.md:506`                   | 삭제된 GR01(GraphDetector)이 순환 탐지를 "**담당**"한다고 현재형 서술                                                                                                             | "범위 외 — 단일 법인이라 영구 불가, GR01 완전 삭제"로 교체       |
| `docs/spec/DETECTION_RULES.md:519`                   | "§4.4 IC Matcher / §4.5 Graph Detector **소관이다**"(2026-06-20 이관 서술)                                                                                                        | 2026-06-30 완전 삭제가 supersede 함을 명시                       |
| `docs/guide/룰원칙해설.md:24,25`                     | 룰 개수 표에 IC(3개)·GR(2개)를 현행으로 수록                                                                                                                                      | "2026-06-30 완전 삭제(범위 외)" 표기                             |
| `docs/guide/룰원칙해설.md:210`                       | "순환은 GR01(그래프)이, 미대사는 IC01~03(매처)이 **담당한다**"                                                                                                                    | 삭제 사실 + L3-03 현행 역할로 재작성                             |
| `docs/guide/룰원칙해설.md:335`                       | IC/GR 룰 카드를 현행처럼 수록 — 비회계 사용자용 문서라 오해가 큼                                                                                                                  | 절 상단 삭제 배너 + "도메인 해설로만 읽을 것"                    |
| **자기 오류 1** `DETECTION_RULES_PHASE1-2.MD:10,128` | `UNIT_MEASUREMENT_POLICY.md` 를 "계정/프로세스 vs 거래처 단위" SoT 로 2회 인용했으나, 그 문서는 "탐지 단위는 **document·flow 두 가지뿐**"이라 못박고 macro/partner 를 다루지 않음 | 잘못된 인용 제거 + 그 정책의 범위 밖임을 명시                    |
| **자기 오류 2** `DETECTION_RULES_PHASE1-2.MD:10`     | "백엔드는 절단하지 않는다" — `phase1_case_view.py:286 summarize_phase1_case_result` 가 `macro_findings[:5]` 절단                                                                  | "finding 생성 경로는 절단 안 함 / overview 요약만 자름"으로 정정 |

> 미수정(범위 밖·기록만): `dev/active/r03-ts01-calibration/r03-ts01-calibration-plan.md:158,312` 가 삭제된 `relational_rules.py:144` 편집을 지시 — 별개 plan 문서라 해당 작업 재개 시 처리.

## 2. 코드 심볼 실재 대조 — **22/22 PASS**

검증 스크립트가 문서 6개 전문을 읽어 언급된 심볼을 코드에 grep 대조. 분모 N=22.

### 2.1 함수·모듈 정의 존재 (13/13)

| 심볼                                                                                  | 정의 위치                                         |
| ------------------------------------------------------------------------------------- | ------------------------------------------------- |
| `single_company_scope_warnings`                                                       | `src/pipeline.py:258`                             |
| `compute_partner_signals`                                                             | `src/detection/partner_signals.py:35`             |
| `_build_partner_findings`                                                             | `src/detection/phase1_case_builder.py:905`        |
| `build_phase1_partner_finding_queue`                                                  | `src/export/phase1_case_view.py:2351`             |
| `build_phase1_macro_finding_queue`                                                    | `src/export/phase1_case_view.py:2330`             |
| `compute_round_density_findings`                                                      | `src/detection/round_density_rules.py:33`         |
| `_build_round_density_macro_findings`                                                 | `src/detection/phase1_case_builder.py:863`        |
| `_compose_badge_tags`                                                                 | `src/detection/phase1_case_builder.py:4955`       |
| `add_is_round_number`                                                                 | `src/feature/amount_features.py:540`              |
| `significant_digit_stats`                                                             | `src/feature/amount_features.py:527`              |
| `compute_timeseries_concentration_findings`                                           | `src/detection/timeseries_concentration_rules.py` |
| `round_density_rules.py` / `partner_signals.py` / `timeseries_concentration_rules.py` | 파일 존재 확인                                    |

### 2.2 설정키 — 선언 AND **실제 read** (9/9)

> hollow-PASS 방지: `settings.py` 에 키가 있는 것(존재)과 그 룰이 그 키를 읽는 것(사용)은 다르다. 아래는 `settings.py` 선언 + 그 밖의 코드에서 read 하는 지점을 **양쪽 다** 확인한 결과다.

| 설정키                          | 선언 | read | 읽는 코드                                                               |
| ------------------------------- | :--: | ---: | ----------------------------------------------------------------------- |
| `round_density_min_sample`      |  Y   |    1 | `round_density_rules.py`                                                |
| `round_density_alpha`           |  Y   |    1 | `round_density_rules.py`                                                |
| `round_density_strong_alpha`    |  Y   |    1 | `round_density_rules.py`                                                |
| `round_density_min_excess`      |  Y   |    1 | `round_density_rules.py`                                                |
| `round_max_significant_digits`  |  Y   |    2 | `timeseries_detector.py` · `amount_features.py`                         |
| `round_min_digits`              |  Y   |    3 | `timeseries_detector.py` · `amount_features.py` · `timeseries_rules.py` |
| `partner_rare_quantile`         |  Y   |    1 | `partner_signals.py`                                                    |
| `partner_dormant_inactive_days` |  Y   |    1 | `partner_signals.py`                                                    |
| `partner_signal_min_population` |  Y   |    1 | `partner_signals.py`                                                    |

### 2.3 삭제 코드 참조 제거 (역방향)

문서 갱신 **전**: `DETECTION_RULES_PHASE1-2.MD` 가공거래처 표가 `relational_rules.py::r01_new_counterparty` · `r05_rare_account_partner_edge` · `r07_dormant_partner_reactivation` 를 "기존 코드"로 참조 — **셋 다 커밋 5d16525 에서 삭제돼 존재하지 않음**(`.pyc` 잔재만). 갱신 후 실제 코드(`partner_signals.py`)로 교체, 삭제 함수명 문서 잔존 **0건**.

## 3. ripple 잔존 검사

| 구 용어                                   | docs/·dev/ 잔존 | 판정                                                                                                                  |
| ----------------------------------------- | --------------: | --------------------------------------------------------------------------------------------------------------------- |
| `round_unit`                              |             5건 | **전부 "구 → 신" 전환 이력 문맥**(예: "구 정의는 `amount % round_unit(100만원) == 0` 이었다"). 현행처럼 서술한 곳 0건 |
| `자기 큐 6종`                             |             4건 | **전부 "6종 → 5종" 전환 문맥**. 현행을 6종으로 서술한 곳 0건                                                          |
| `round_unit` 실코드(src·config·dashboard) |         **0건** | 주석의 폐기 이력 제외 시 0 — 소비처 5/5 전환 완료                                                                     |

> **계약 편차(정직 기록)**: 계약 D4·D10 의 실패조건을 "grep 히트 ≥ 1건"으로 썼으나, 폐기 이력을 문서에 남기는 것이 규율([CLAUDE.md 이슈 추적 §교차 참조])이므로 문자 그대로면 상충한다. 실제 판정 기준은 **"현행처럼 서술된 잔존 0"** 으로 측정했고 그 기준으로 PASS. 계약 문구가 과도했다.

## 4. 문서 무결성

| 검사                         | 결과                                                                                |
| ---------------------------- | ----------------------------------------------------------------------------------- |
| U+FFFD (편집 문서 6개 전수)  | **0개** — 한글 깨짐 없음                                                            |
| 깨진 상대링크 (내가 만든 것) | 1건 발견 → 수정(`PHASE2_TIMESERIES_ROLE_LOCK.md` → `../archive/completed/` 로 교정) |
| 깨진 상대링크 (기존)         | 3건 — 본 작업 범위 밖, HEAD 에도 존재(아래 §5)                                      |

## 5. 발견했으나 고치지 않은 것 (범위 밖 · 결정 필요)

| 항목                                                                 | 사실                                                                                                                                                                                                                                                                                                                                                       |
| -------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `PHASE2_TIMESERIES_ROLE_LOCK.md` 위치                                | 파일은 `docs/archive/completed/`, CLAUDE.md 는 `docs/spec/` 로 링크 → **깨짐**. 활성 문서 5곳이 spec 경로 참조, archive 경로 참조 **0곳**(= 이관이 모든 참조를 깨뜨림). supersede 취소로 lock 은 유효 존속 → 위치 재확정 필요. `dev/active/docs-reorg/MAPPING.md` 가 이 파일을 "경계(0번 결정 후 확정)"로 **명시적 미확정** 처리 중이라 임의 이동하지 않음 |
| `DETECTION_RULES_PHASE1-2.MD:456` → `phase2_reorgani.md`             | 깨진 링크. HEAD 에도 존재(기존)                                                                                                                                                                                                                                                                                                                            |
| archive lock 문서 → `CONSTRAINTS.md`·`PHASE1_TIER_EVIDENCE_BASIS.md` | 깨진 링크 3건. archive 이관 시 상대경로 미조정(기존)                                                                                                                                                                                                                                                                                                       |
| `src/detection/__pycache__/relational_detector*.pyc`                 | `.py` 는 삭제됐는데 바이트코드 잔재                                                                                                                                                                                                                                                                                                                        |

## 6. 계약 대비 결과

D1~D11 전 항목 측정. 상세는 계약 파일. 요약 — 심볼 22/22, U+FFFD 0, 삭제 코드 참조 0, 구 용어 현행 서술 0, 내가 만든 깨진 링크 0(1건 발견→수정).
