# Review Queue 단위 정합화 — Context & Decisions

## Status
- Phase: Phase A 측정 완료 (doc-level 가설 부분 반증) → 옵션 가+다 진행
- Progress: 1 / 3 phases complete (A 측정 ✓ / A.5 80건 진단 / 단위 case 통일 작업)
- Last Updated: 2026-05-19

## 배경 — 이 sprint의 진화

원래 sprint는 "review queue scoring/ranking을 case → doc 단위로 전환"이었다. 사용자(빌더)가 다음 문제를 짚으면서 시작했다:
- TOP 100 case = 4,428 docs (44배 인플레이션)
- PHASE2 "단독" 큐가 사실 PHASE1 case-bound라 TS-13 80 doc 회수 불가
- VAE case-max 집계로 row-level AUROC 0.93 정보 손실
- 5-way RRF 측정에서 TOP-500 doc recall -16.46%p 손실 (intercompany 29 case 강제 점령)

Phase A 측정 결과 (2026-05-19) **사용자 가설이 부분 반증**됐다:

```
변형                              TOP-100      TOP-500
case-level PHASE1 unfold         16.77%       44.52%   ← 현재 최선
case-level RRF 2-way unfold      15.32%       26.77%
─────────────────────────────────────────────────────
최고 doc-level variant            5.16%       23.06%   ← case-level의 1/3 ~ 1/2
PHASE2 doc 큐 80건 회수            0 / 80               ← TS-13 (c) 권고 무효화
```

**진단**: case grouping은 단순 UI 묶음이 아니라 **evidence bundle**이었다. 같은 분개의 multi-row + multi-rule corroboration이 case 단위에서 응축되고, doc-level로 풀면 이 신호가 사라진다. PHASE1 V1 lock의 0.62/0.12/0.10/0.08/0.05/0.03 가중치 산식은 case grouping을 전제로 설계됐기 때문.

## 진행 결정 — 옵션 가 + 옵션 다 (2026-05-19 사용자 확정)

| # | 항목 | 결정 |
|---|------|------|
| 가 | ranking 단위 | **case 유지** (현재 PHASE1 V1 lock 그대로) |
| 다 | 80건 진단 | Phase A.5에서 PHASE2 row-level 5 family score 분포 측정 |

## 단위 정합화 — case 통일 + 분모 620 매핑

### 결정 (2026-05-19 사용자 확정)
- **ranking 단위 = case** (V1 lock)
- **평가 분모/분자 단위 = case** (정렬-평가 단위 일치)
- **truth 분모 = case 620** (1 truth doc → 1 truth case 매핑 정책 신설)
- **외부 표준(doc) 단위 = 보조 지표** (병행 표시는 보조 정보로만)

### 1 truth doc → 1 truth case 매핑 정책

PHASE1 case_builder는 한 doc이 여러 topic에 hit하면 topic마다 case를 만든다. 결과적으로 truth doc 620이 truth case 795로 매핑(1.28배 인플레이션).

**해결**: 매핑은 **measurement 단계에서만** 적용한다. case_builder 코드는 V1 lock 보존을 위해 변경하지 않는다.

```
정책: truth doc 1개 → 그 doc이 매핑된 case 중 priority_score 가장 높은 1개 case만 truth case로 카운트
결과: truth case 분모 795 → 620 (인플레이션 제거)
영향: case_builder 코드 0 변경, 측정 스크립트만 정책 적용
```

### 외부 표준 정당화

기존 정책(TS-12 2026-05-18): "외부 KPI는 doc, case는 내부 운영 지표"
변경 정책(2026-05-19): "외부 KPI는 case (본 프로젝트의 evidence-bundled journal entry), doc은 외부 비교 보조 지표"

근거:
- PCAOB AS 2401 ¶54-57의 "journal entry" 정의는 **회계적으로 의미 있는 분개 단위**이며 단일 line item이 아니다. 본 프로젝트의 case = "같은 분개에 속한 doc + topic 묶음"은 사실상 AS 2401의 journal entry 정의와 정합.
- ISA 240 ¶A45의 "corroborating evidence" 원리: 단일 증거가 아니라 누적 증거로 평가. case는 corroboration 적용 단위.
- Phase A 측정에서 case grouping이 evidence bundle 역할을 한다는 정량 증거 확보.

## PHASE1 V1 lock과의 관계

V1 lock(`docs/spec/PHASE1_TOPIC_SCORING_V1_LOCK.md`, 2026-05-08)이 잠근 대상은 **case-level topic_score 산식과 가중치**다. 본 sprint는 V1 lock을 손대지 않는다:

- case priority_score, composite_sort_score 산식 보존
- case_builder의 case 생성 정책 보존 (1 doc → multiple case 매핑 그대로)
- 변경은 **truth 평가 단계의 case-truth 매핑 정책**과 **보고 단위 라벨**만

## Key Files

**Read-Only (V1 lock, 변경 금지)**:
- `src/detection/phase1_case_builder.py` — case 구조
- `src/detection/score_aggregator.py` — case priority 산출
- `src/services/queue_fusion.py` — RRF 코드 (Phase A.5 결과 보고 폐지/유지 결정)
- `tools/scripts/phase1_phase2_integration_stage7.py` — case-bound queue
- `data/companies/_ci_baseline/engagements/2026/models/phase2_unsupervised/v1/model_bundle.pt`
- `data/journal/primary/datasynth_manipulation_v7_candidate_fixed3/labels/manipulated_entry_truth.csv`

**New (본 sprint 산출)**:
- `tools/scripts/phase_a5_uncovered_truth_phase2_diagnosis.py` — 옵션 다 측정
- `artifacts/doc_level_ranking_phase_a5_20260519.json`
- `artifacts/doc_level_ranking_phase_a5_20260519.md`
- `dev/active/doc-level-ranking/doc-level-ranking-context.md` (본 문서)

**Modified (단위 정합화)**:
- `docs/spec/TROUBLESHOOT.md` — TS-12, TS-13 2026-05-19 정정 추가
- `docs/guide/users/00_INDEX.md` — 단위 결정 문서 항목 추가
- `docs/guide/users/09_DOC_VS_CASE_DECISION.md` — 신규 (가설 검증 스토리)

## Phase A 측정 결과 (2026-05-19 완료)

산출물: `artifacts/doc_level_ranking_phase_a_20260519.{json,md}`

핵심 수치 표 (truth doc 기준 분모 620, Phase A.5 후 case 620으로 통일):

```
변형                              TOP-100     TOP-500     TOP-1000    TOP-2000
case-level PHASE1 unfold         16.77%      44.52%      51.13%      58.71%
case-level PHASE2 unfold         10.97%      30.48%      37.42%      48.23%
case-level RRF 2-way unfold      15.32%      26.77%      46.94%      55.00%
─────────────────────────────────────────────────────────────────────────────
phase1_v1_max                     0.48%       1.29%       2.90%       6.13%
phase1_v1_top3mean                0.48%       1.29%       2.90%       6.13%
phase1_v1_max_corrob              3.06%       3.71%       5.00%       8.71%
phase1_v1_top3mean_corrob         3.06%       3.71%       5.00%       9.03%
phase2_family_max                 3.23%      13.23%      19.68%      28.71%
phase2_family_top3mean            1.29%      17.74%      19.19%      25.65%
phase2_family_max_corrob          2.90%      14.84%      20.00%      37.26%
phase2_family_top3mean_corrob     5.16%      23.06%      29.84%      31.13%
```

부수 발견 (이 측정이 새로 밝힌 것):
- **PHASE2 doc 큐 80건 회수 0/80** → TS-13 (c) 권고 무효화
- **doc TOP-500 → case 약 433~457개**: doc-level 정렬은 case 다양성 증가시키지만 corroboration 손실
- **corroboration weight 0.05 보너스가 max 변형 대비 PHASE1 7배 / PHASE2 1.7배** 개선 → corroboration이 점수의 본질

## Phase A.5 — 옵션 다 측정 항목 (다음 단계)

### M1. 80 truth doc의 PHASE2 row-level 분포

각 80 doc에 속한 모든 row의 5 family ECDF score 분포:
- `unsupervised` score 분포 (q50/q95/q99, nonzero rate)
- `timeseries`, `relational`, `duplicate`, `intercompany` 각각 분포
- 5 family max across rows
- 5 family top-3 mean

산출 목적: PHASE2가 정말 80건에 신호 없는지, 아니면 신호는 있는데 집계에서 묻혔는지 진단.

### M2. case-level ceiling 재산정

1 truth doc → 1 truth case 매핑 적용 후 ceiling 재계산:
- 큐 진입 truth case 수
- 큐 미진입 truth case 수 (TS-13의 80 doc이 case 단위로 몇 개)
- case-level ceiling 비율

### M3. case-level 분모 변환 표

기존 doc-level recall 측정을 case 단위로 재산정:
- baseline_phase1_case_unfold → phase1_case (분모 case 620)
- baseline_phase2_case_unfold → phase2_case
- baseline_rrf_2way_case_unfold → integrated_2way_case
- TOP-100/500/1000/2000 모두

## 영향 — 정정·갱신 대상

### 코드 (변경 없음)
- 본 sprint에서는 어떤 src/ 코드도 변경하지 않는다.

### 문서 정정 (단위 라벨 + 분모 정정)
- `docs/spec/TROUBLESHOOT.md` TS-12 §6.1, §6.2, §7 — 2026-05-19 정정 추가
- `docs/spec/TROUBLESHOOT.md` TS-13 §6 (c), §7 — PHASE2 80건 회수 0 측정 결과 추가
- `docs/guide/users/00_INDEX.md` — 신규 09 문서 항목 추가
- `docs/guide/users/09_DOC_VS_CASE_DECISION.md` — 신규 (가설 검증 스토리)

### 보고 문서 단위 정정 (선택)
- `docs/archive/completed/DETECTION_RESULTS_MANIPULATION_V7_FIXED3.md` 분모 표기 case 통일 — Phase A.5 후
- `docs/guide/DETECTION_RESULTS_MANIPULATION_V7_FIXED3_PHASE2.md` 동일 — Phase A.5 후

## Known Issues

- Phase A.5 측정이 80건의 PHASE2 신호가 정말 0임을 확인하면 ceiling 87.10% (또는 case 단위 등가)가 확정 공시. 80건은 어떤 방법으로도 회수 불가로 결론.
- Phase A.5에서 80건의 PHASE2 신호가 있다고 나오면 옵션 나(cross-doc corroboration 추가) 재검토 가능.
- 어느 경우든 ranking 단위는 case로 유지. doc-level 정렬은 합성 데이터에서 case-level의 1/3 수준임이 측정으로 확인됐다.

## Rollback Strategy

- 본 sprint는 코드 변경 0이므로 rollback 대상은 문서 정정뿐.
- TS-12/TS-13 정정은 추가 기록 형태(2026-05-19 정정 섹션)로 들어가므로 기존 결정 이력은 보존.

## Next Action

1. **TS-12/TS-13 정정 작업** (본 sprint 즉시)
2. **docs/guide/users/09_DOC_VS_CASE_DECISION.md 작성** (본 sprint 즉시)
3. **Phase A.5 측정 프롬프트 발행** (다음 행동)
4. **Phase A.5 결과 보고 ceiling 확정 또는 옵션 나 재검토** (사용자 승인 후)

UI 단계 진입은 본 sprint 완료 + 사용자 승인 후 별도 sprint로.

## Decision Log

| 날짜 | 결정 | 근거 |
|------|------|------|
| 2026-05-18 (TS-12) | 외부 KPI = doc, 내부 = case | RRF k=60 채택 시 |
| 2026-05-19 (Phase A) | doc-level 가설 부분 반증 (1/3 수준) | 8 variant × 4 TOP-N 측정 |
| 2026-05-19 (Phase A) | TS-13 (c) PHASE2 doc 큐 권고 무효 | 80건 회수 0/80 측정 |
| 2026-05-19 (본 sprint) | 단위 case 통일, 분모 620 매핑 정책 | 정렬-평가 단위 일치 + AS 2401 journal entry 정합 |
| 2026-05-19 (본 sprint) | 옵션 가 + 옵션 다 진행 | case-level 정렬 유지 + 80건 마지막 진단 |
