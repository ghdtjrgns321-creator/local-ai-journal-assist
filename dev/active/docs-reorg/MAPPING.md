# 문서 재편 매핑표 (이동 전 승인용)

작성 2026-06-16. 실제 이동·링크 수정은 본 매핑 승인 후 별도 단계.

목표 구조:
```
docs/guide/   ← 이것만 봐도 전체 이해 (요약 진입점)
docs/spec/{datasynth, phase1, phase2, common}/   ← 기둥별 상세 권위본
docs/archive/   ← 완료·폐기 (그대로)
dev/active/   ← 살아있는 작업만
```

---

## 0. 먼저 결정해야 할 경계 이슈 (배정 전 확정 필요)

| 이슈                      | 내용                                                                                                                                                         | 영향 범위                                                         |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------- |
| **시계열(TS) 귀속**       | CLAUDE.md는 TS를 PHASE1-2 family로 명시하나, spec/debugging의 TIMESERIES_* 진단과 ROLE_LOCK은 PHASE2 평가 surface와 직결. phase1로 갈지 phase2로 갈지 미확정 | PHASE2_TIMESERIES_ROLE_LOCK + debugging TS 5종 + users TS surface |
| **IC(intercompany) 귀속** | 탐지 구조는 PHASE1-2 family, 평가는 PHASE2 native case. 두 기둥에 걸침                                                                                       | INTERCOMPANY 문서 2종                                             |
| **링크 깨짐 비용**        | 하위폴더 이동 시 참조 대량 수정: DETECTION_RULES 60곳·TIER_EVIDENCE 34곳·PHASE2_GOVERNANCE 24곳·DATASYNTH 20곳 = 138곳+                                      | 이동 실행 단계 전체                                               |

---

## 1. docs/spec → 기둥별 배정 (38개)

### → spec/phase1/ (룰)
DETECTION_RULES, DETECTION_RANKING_CRITERIA, DETECTION_PARAMETERS, DETECTION_REFERENCE,
DETECTION_PORTFOLIO_REFRAME, PHASE1_TIER_EVIDENCE_BASIS, PHASE1_TIER_SCORING_SPEC,
HIGH_COMBO_GROUNDING, PHASE1_RULE_RELATIONSHIP_MAP, RULE_DETAIL_METADATA_V1_LOCK,
PHASE1_SEPARATE_BENCHMARK_SPEC, results/PHASE1_NORMAL_FP, results/PHASE1_VERIFICATION,
results/PHASE1_RULE_DOMAIN_REVIEW

### → spec/phase2/ (VAE·family 평가)
PHASE2_FITTING_AUDIT, PHASE2_GOVERNANCE_DESIGN, PHASE2_UNSUPERVISED_ROLE_REDESIGN_DECISION,
phase2_reorgani(구버전 → archive 권고), templates/phase2_evaluation_report_template,
debugging/ 9종(DUPLICATE/RELATIONAL/TIMESERIES/UNSUPERVISED native case 진단)

### → spec/datasynth/ (데이터 생성)
*(현재 spec 루트엔 datasynth 전용 문서 없음. guide/users 18·19 + dev 루트 scheme-catalog가 핵심 후보)*

### → spec/common/ (공통)
UNIT_MEASUREMENT_POLICY, GIT, metrics, CONSTRAINTS, DECISION, TROUBLESHOOT,
LOCAL_EVIDENCE_BRIEF_SPEC, LOCAL_FIRST_EVIDENCE_POLICY, PHASE2_INTERFACE_DESIGN(경계→common),
results/PHASE1_OPEN_ISSUES(경계→common)

### 경계(0번 결정 후 확정)
PHASE2_TIMESERIES_ROLE_LOCK(phase1 또는 phase2), debugging/INTERCOMPANY_INCREMENTAL_VALUE(phase1/phase2)

---

## 2. docs/guide → 분류 (35개)

### guide-유지 (사용자 진입점 요약)
PROJECT_OVERVIEW, EXPLAIN, ux-flow, 개발방법론, 룰원칙해설(phase1 요약),
users/00~06, users/10 (피칭·흐름·결정요약·협업·스토리·포지셔닝)

### spec 이관 (권위·상세 성격)
users/05_DOMAIN_BRIDGE→phase1, users/07_PHASE1_PRIORITY_RANKING→phase1,
users/08_PHASE2_FAMILY_STRUCTURE→phase2, users/09_REVIEW_QUEUE_RRF_FUSION→phase2(legacy),
users/11~16(phase2 scoring/queue/responsibility 결정), 
users/17_MOCKEXAM_SEED→datasynth, users/18_DATASYNTH_DOMAIN_AUDIT→datasynth,
users/19_DATASYNTH_FULL_COLUMN_LEAK_SCAN→datasynth,
users/{INTERCOMPANY,TIMESERIES,RELATIONAL,DUPLICATE_NATIVE,DUPLICATE_PAIR,UNSUPERVISED}_*_SURFACE→phase2

### archive 이관 (완료 결과 리포트)
DETECTION_RESULTS_CONTRACT_V3, DETECTION_RESULTS_MANIPULATION_V7_FIXED3_PHASE2,
DETECTION_RESULTS_MANIPULATION_V7_FIXED4_PHASE2

---

## 3. dev/active → 완료/진행 판정 (34개 폴더)

### done → docs/archive/completed (11개)
batch-history-loader, ic-matcher-redesign, phase1-rule-defect-fixes, phase2-detector-expansion,
phase2-family-ranking, phase2-streamlit-alignment, phase2-unsupervised-autoencoder,
phase2-unsupervised-explainability-surface, service-architecture-separation, topic-scoring-antifit-calibration
*(phase2-native-cases는 최근 커밋에 구현 반영 → done 가능성 높음, 확인 필요)*

### alive → 유지 (14개)
case-centric-master-detail, datasynth-duplicate-realism-s1, datasynth-journal-realism-rebuild,
detection-explanation-standardization, doc-level-ranking, hitl-feedback-loop-hardening,
l1-06-sod-scoring, oracle-arm-demo-deploy, phase1-rule-basis-audit, phase2-train-automl,
phase2-ui-resiliency, phase2-unsupervised-doc-review-surface, rules-settings-simplification,
supervised-ml-gate-hardening

### unknown → 사용자 확인 필요 (8개)
l107-scoring-calibration, main-ux-cleanup, manipulation-truth-signal-audit-20260602,
performance-evaluation-report, phase1-unit-unification, phase2-native-cases,
r03-ts01-calibration, relational-circular-ownership-20260602
*(체크리스트 없음/0% 체크 — 코드 반영 여부로 판단 필요)*

---

## 4. dev/active 루트 단독 파일 (30개)

- **유지(현역 핸드오프)**: HANDOFF_phase2_datasynth.md
- **삭제(2026-07-15)**: HANDOFF_CURRENT.md — 2026-06-07 시점에서 정지. 기준 데이터셋(NORMAL v29,
  overlay v11/v12)이 모두 디스크에서 사라져 내용 전체가 무효였다. 현행 진행 상태는 dev/active 하위
  각 plan 폴더가 관리한다.
- **archive 이관(완료 스펙·프롬프트 히스토리 19개)**: p3-2-overlay-injection-audit, phase1-evasion-injection-spec,
  phase1-rule-detail-audit-note, phase1-rule-recall-checklist, phase2-fraud-scheme-catalog,
  phase2-fraud-*-prompt 다수(r1f/r2/v33-r3/r4f~r4m/v42-r4l/deshortcut/unrecognized-fix/overlay)
- **삭제후보(일회성 덤프 9개)**: v4~v7_*_sample_dump.txt(6), v4_sample_audit.txt, v4_sample_audit.py, v4_sample_dump.py

---

## 5. 별도 정합성 문제 (재편과 무관하게 즉시 처리 권고)

1. **역전**: PROJECT_OVERVIEW·CLAUDE.md 인덱스가 FIXED3을 "최신"으로 가리킴 → 실제 최신은 FIXED4. 링크 교체 필요.
2. **손상**: docs/archive/completed/datasynth개선사항.md 전체 mojibake / datasynth_renewal_plan.md 빈 파일 → 사용자 확인 후 복구·삭제 (한글 인코딩 가드 대상, 추측 복구 금지).
3. **중복 검토**: DUPLICATE_NATIVE_REVIEW_SURFACE ↔ DUPLICATE_PAIR_EVIDENCE_SURFACE 내용 중복 → 통합/상하위 명시.

---

## ripple-search 실측 (링크 깨짐 위험)

| 이동 대상 대표 파일           | 참조 문서 수 |
| ----------------------------- | ------------ |
| DETECTION_RULES.md            | 60           |
| PHASE1_TIER_EVIDENCE_BASIS.md | 34           |
| PHASE2_GOVERNANCE_DESIGN.md   | 24           |
| DATASYNTH_* 계열              | 20           |

→ 하위폴더 이동 실행 시 최소 138곳 링크 수정 필요. 0건 아님(측정됨).
