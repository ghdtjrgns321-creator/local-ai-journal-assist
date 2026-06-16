# Design Decisions

> **PHASE1 역할 원칙**: PHASE1은 `fraud`를 확정하거나 정답 라벨을 맞히는 단계가 아니다. PHASE1의 목적은 전수 모집단에서 규칙 위반, 정책 위반, 이상 징후, 분석적 검토 신호를 넓게 올려 **감사인이 봐야 할 항목과 우선순위**를 만드는 것이다. DataSynth의 `is_fraud`/`is_anomaly`와 precision/recall은 개발 검증 보조 지표이며, 운영 해석은 예외 처리 대상, 감사인 리뷰 대상, 고위험 후보를 구분하는 review queue 기준으로 한다.

> Current DataSynth production baseline: `data/journal/primary/datasynth/` freeze `v126` as of 2026-05-02. Older `v20.x`, `v23`, and `v45` entries are historical decision records.

> **결정 ID 발번 규칙 (2026-05-15)**: D001~D049 는 모두 발번 완료. 다음 신규 결정 ID 는 **D050 부터** 사용한다. D046 은 2026-05-15 ID 충돌 정정 시 D040 으로 통합되었기 때문에 본문 stub 만 유지하며, D043~D045 / D049 는 모두 점유 상태다. 모든 `### D{n}:` 헤더는 unique 해야 하며 `tools/scripts/audit_decision_ids.py` 가 CI 에서 회귀 가드로 강제한다.


> **포트폴리오 주장 범위 (2026-05-19)**: 이 프로젝트는 `fraud`를 판정하거나 실제 운영 부정 탐지 성능을 보장하는 모델이 아니다. 전수 모집단에서 감사인이 먼저 볼 review queue를 만들고, 무작위 검토 대비 상위 구간에 review-worthy synthetic anomaly를 강하게 농축하는 로컬 감사 분석 보조 도구다. DataSynth 기반 precision/recall은 개발 검증 보조 지표이며, 실데이터 운영 성능으로 주장하지 않는다.
> **금지 표현**: "부정을 정확히 탐지", "실무 운영 성능 검증 완료", "TOP100 precision 충분", "fraud 확정/자동 적발"처럼 확정적이거나 운영 성능을 보장하는 표현은 사용하지 않는다.

?꾪궎?띿쿂쨌湲곗닠 ?좏깮 寃곗젙 濡쒓렇. ?덈줈??寃곗젙 ???댁슜 異붽?.

---

### D040: Phase 2 ML 평가 강제 protocol (Stage 10 Audit 통합)
- **결정**: PHASE2 ML 평가 보고서는 5 protocol 항목과 S9 6개 부가가치 게이트를 모두 만족 시에만 promotion 가능하다.
  (1) bootstrap 95% CI 동봉, CI > 0.15 시 `[insignificant]` 마커
  (2) 시나리오별 fold × scenario truth count matrix 첨부 (fold truth < 5 시 fold-level 통계 금지, `unusual_timing_manipulation` n=21 은 fold-level 보고 금지)
  (3) 10 trivial binary feature 합산 baseline 동시 보고, Δrecall < 0.05 시 fitting 의심 마킹
  (4) Phase 2 ML 부가가치 6 게이트 통과 (S9: macro AUPRC ≥ 0.4898, macro F2 @ top-1% ≥ 0.118, embezzlement recall ≥ 0.495, circular recall ≥ 0.276, 다른 4 시나리오 recall 손실 |Δ| < 0.05)
  (5) macro-F2 unweighted + prevalence-weighted 두 값 동시 보고
- **6번째 게이트 (BLOCK 조건)**: `ensemble macro AUPRC / trivial_10feature macro AUPRC ≤ 4.0`. 4 배 초과 시 synthetic shortcut 의심으로 마킹하고 DataSynth v4 빌드 전까지 BLOCK 한다. 본 ratio cap 단일 조건만 BLOCK 정책으로 적용한다 (코드 구현: `src/services/phase2_evaluation.py::evaluate_anti_shortcut_cap`, `ANTI_SHORTCUT_RATIO_CAP = 4.0`).
- **보조 측정값 (보강 진단, BLOCK 아님)**: Top-5 LEAKAGE_DENY_RULES (`rule_L3-02`, `rule_L3-09`, `rule_L1-03`, `rule_L2-03`, `rule_L1-05`) 제거 후 재학습한 ML 앙상블의 macro AUPRC 잔존율 ≥ 30% AND 절대값 ≥ 0.30. v4 S5 §5 재측정값 (24-dim AUPRC 0.397 → Top-5 deny 후 0.056, 잔존 14.0%, drop ratio 0.86) 의 정량 trace 용도이며, deterministic 5 룰 의존도의 진단 지표로 보고하되 BLOCK 으로 격상하지 않는다. 본 측정값을 BLOCK 조건으로 격상하려면 `phase2_evaluation.py` 에 Top-5 deny 후 재학습 ML 의 잔존율/절대값 산출 함수 신설이 선행되어야 하며, 현 코드에는 미구현 상태다.
- **AND 조건**: S4 P4 `Δrecall ≥ 0.05` 와 anti-shortcut cap 은 OR 조건이 아니다. 둘 중 하나라도 미달하면 PHASE2 promotion gate 는 BLOCK 이다.
- **구현 위치**: `tools/analysis/compute_trivial_baseline.py` 가 S4 10-feature trivial baseline 을 ensemble 평가와 동일 fold 구성으로 재산정하고, `src/services/phase2_evaluation.py` 가 S4 P4 + anti-shortcut cap (ratio ≤ 4.0) 을 AND 정책으로 판정한다.
- **사유**: v3 dataset 의 합성 shortcut 위험(S4 RED L-08~L-10) 때문에 0.99급 AUPRC 가 실제 일반화 성능이 아니라 trivial surface 대비 과도한 shortcut 증폭일 수 있다. ratio cap 은 trivial baseline 대비 증폭 배수로서 shortcut 의 직접 지표이고, 보조 측정값(Top-5 deny 잔존율)은 deterministic 룰 의존도의 정량 진단이다.
- **영향 범위**: `phase2_training_service`, PHASE2 평가 entry, CI workflow, `tests/datasynth_quality_gate/results/phase2_fitting_audit/`.
- **관련 audit**: `docs/spec/PHASE2_FITTING_AUDIT.md`, `artifacts/S4_evaluation_protocol.md`, `docs/archive/completed/S9_phase2_value_baseline.md`, `artifacts/S5_phase2_input_redesign.md`.
- **관련 결정**: D027(Hold-out Fraud Type), D029(데이터 분할 전략), D034(Stacking Meta-Learner), D037(모델 드리프트 재학습).

---

### D041: Phase 3 v2 rescope to Review Queue Narrator (2026-05-14)
- **Status**: Superseded by D068. Historical only.
- **Historical decision**: Phase 3 단일 목표를 Review Queue Narrator로 좁히고, LLM이 PHASE1 룰 히트 + PHASE2 ML 스코어 + 전표 메타를 요약하는 방향을 검토했다.
- **현재 해석**: 이 결정은 더 이상 active product contract가 아니다. PHASE3 LLM Narrator, LLM reranking, AI review memo, Text-to-SQL, 룰 피드백 루프는 active product path에서 제거되었다.
- **대체**: [LOCAL_FIRST_EVIDENCE_POLICY.md](LOCAL_FIRST_EVIDENCE_POLICY.md)의 Local Evidence Brief.

---

### D042: PHASE1 룰 메타 변경 금지 + unusual_timing 11/21 ceiling 정식 채택 (2026-05-15)
- **결정**: PHASE1 룰 정의(`src/detection/rule_scoring.py`의 `scoring_role`, `standalone_rankable`, `final_topic`)는 단일 시나리오 truth 회수를 위해 변경하지 않는다. `datasynth_manipulation_v2` 의 `unusual_timing_manipulation` 21건 중 11건 closing_timing topic 진입을 **PHASE1 본질적 detectability ceiling**으로 정식 채택한다.
- **반려 옵션 (P1: L3-06 promote)**:
  - 제안: `L3-06 after_hours_activity`를 `scoring_role="primary"`, `standalone_rankable=True`로 promote하면 21/21 진입 가능.
  - 반려 사유: `L3-05 weekend_posting` / `L3-06 after_hours_activity`는 정상 결산기 야근, 분기말 마감 보정, 주말 휴일 전기 등 한국 중견 제조업의 합법적 운영 패턴에서도 자연스럽게 hit한다. booster + standalone_rankable=False 설계는 정상 운영의 false positive 폭증을 방지하기 위한 의도된 게이트다. standalone primary로 promote하면 review queue high band가 정상 야근 거래로 점령되어 감사인 정밀도가 회귀한다. **단일 시나리오 truth 11→21 회수 이득 < 정상 운영 모집단 FP 폭증 손실**.
- **채택 옵션 (P2: 11/21 ceiling 수용)**:
  - 11/21은 `after_hours_posting` 시나리오의 PHASE1 본질적 한계로 baseline freeze.
  - 18→11은 회귀가 아니라 incidental case bundling artifact 제거. 직전 18/21은 L3-04 보유 non-truth co-doc과 우연히 같은 케이스로 묶인 corroboration이었다.
  - 정상 야근 거래와 의심 시간대 거래의 분리는 **PHASE2 ML(multi-feature 분류)** 또는 향후 local-only NLP 검토 영역으로 이관한다.
- **반려 옵션 (P3: DataSynth day 이동)**:
  - 제안: `materialize_datasynth_manipulation_v2.py:256-262` `day = 23 + (bucket % 5)` → `day = 26 + (bucket % 5)`로 변경하여 period_end window 안에 강제 배치.
  - 반려 사유: 두 시나리오(`unusual_timing` vs `period_end_adjustment`)의 taxonomic clarity 손상. 합성 데이터의 의도된 정의가 변질된다.
- **영향 범위 (룰 메타 변경 금지 원칙의 일반화)**:
  - `src/detection/rule_scoring.py` `RULE_SCORING_REGISTRY` 항목의 `scoring_role`, `standalone_rankable`, `final_topic`은 정상 모집단 FP 영향 평가 없이 변경 금지.
  - 시나리오 진입률 회복이 필요하면 DataSynth mutation 보강 (fictitious T7 D1) 또는 PHASE2/local-only 후속 단계로 이관.
  - PHASE1 KPI 가드는 truth recall 향상을 강제하지 않는다(`tests/phase1_rulebase/kpi_baseline.json` `_meta.principle`).
- **단일 출처**: `docs/archive/completed/DETECTION_RESULTS_MANIPULATION_V2.md` §6.1, §8.1, §10, `tests/phase1_rulebase/kpi_baseline.json` `c4_scenario_full_entry_count.scenario_entry_ceilings.unusual_timing_manipulation`, `artifacts/unusual_timing_regression_trace.md` §7, `artifacts/manipulation_v3_mutation_recovery.md` Guard 3.

---

### D043: Phase 3 v2 안착 — provider 단일화 잠정 유지 + multi-provider 재평가 트리거 조건 (2026-05-15)
- **Status**: Superseded by D068. Historical only.
- **Historical decision**: Sprint G 마감 시점에 GPT provider 단일화를 잠정 유지하는 방안을 기록했다.
- **현재 해석**: OpenAI/GPT provider, Structured Output, BudgetGuard 기반 LLM 호출은 active product dependency가 아니다. 관련 기록은 historical LLM experiment로만 보존한다.
- **대체**: 외부 provider 재평가 트리거는 폐기한다. active explanation path는 local deterministic Local Evidence Brief다.

---

### D044: T9 Rust 승격 baseline PR 템플릿 의무화 (2026-05-15)
- **결정**: T9 Rust 승격 또는 `datasynth_manipulation_v3_rust` 계열 baseline 갱신 PR은 description에 아래 섹션을 반드시 포함한다.

```markdown
## fiscal_period 정확화로 인한 truth 정정

- 변경 전/후 fiscal_period 산출 기준:
- truth label 변동:
- circular / embezzlement 수치 변화:
- 회귀가 아닌 과탐 정정으로 보는 근거:

## fitting-risk check

- label, scenario, document id, 특정 생성 패턴에 맞춘 scoring/rule 조정 여부:
- 정상 모집단 false-positive 영향:
- rollback 필요 여부:
- PHASE2 sub-detector tier 변경 여부 — 변경 시 `config/phase2_subdetector_tiers.yaml` 출처가 기준서(PCAOB/ISA) 또는 분포 측정값임을 확인하고 truth recall 향상은 사유로 사용하지 않았음을 명시:

## 후속 action

- baseline 갱신:
- detector/scoring 변경:
- 문서 갱신:
```

- **해석 원칙**: fiscal_period 정확화로 circular/embezzlement 수치가 바뀌는 경우, 먼저 truth surface 정정 또는 기존 과탐 제거로 해석한다. detector 회귀로 단정하지 않는다.
- **롤백 조건**: fitting-risk check에서 label, scenario, document id, 특정 생성 패턴에 맞춘 scoring/rule 조정이 발견되면 해당 변경은 롤백하거나 scoring 변경을 제거한다.
- **단일 출처**: `artifacts/phase2_handoff_band_axis_audit.md` §6.

---

### D045: Defer Codex PostToolUse mojibake guard
- **Decision**: Codex PostToolUse mojibake guard is deferred because file path/payload stability is not confirmed. Use AGENTS.md and `local-ai-assist-testing` manual validation guidance instead.

---

### D051: PHASE2 Layer A/B/C 가드 3계층 + A3/A4 운영 임계 calibration (2026-05-17)
- **결정**: PHASE2 unsupervised autoencoder MVP의 학습/추론 검증을 3계층 가드로 운영한다. Layer A(학습 누설)와 Layer B(모델 품질)는 **HARD** (GO/NO-GO 차단), Layer C(PHASE1↔PHASE2 정합)는 **SOFT WARN**으로 분리한다.
- **Layer A — HARD (학습 누설)**: 8가드. A1 dataset_version 명시, A2 deny-list 적용 + 누적 제외 컬럼 ≥76, A3 split_strategy=`group_by_document_id`, A4 fit_only_on_train (val/test transform-only), A5 train/val/test 간 document_id 누수 없음, A6 fit→transform 순서, A7 target_used=false, A8 reconstruction loss only (label-based loss 키 부재).
- **Layer B — HARD (모델 품질)**: 5가드. B1 val/train recon ratio < 1.3, B2 test↔val recon |drift| ≤ 0.5, B3 KS(top-N score 분포 분리) ≥ 0.3, B4 ECDF 학습/추론 일관성, B5 top-1% scenario entropy ≥ 0.7 (normalized).
- **Layer C — SOFT WARN (PHASE1↔PHASE2 정합)**: 4지표. C1 PHASE1 priority_score 비파괴(PASS 강제), C2 PHASE1∩PHASE2 top-500 overlap rate (INFO), C3 PHASE2-only 신규 발굴 case 수 (INFO), C4 PHASE1 high ∩ PHASE2 high truth recall (INFO only).
- **HARD/SOFT 분리 사유**: Layer A/B는 학습 정합성과 모델 동작 자체의 결함을 차단해야 한다. Layer C는 PHASE1과 PHASE2의 신호가 어느 정도 보완성을 가질지 사전 단정할 수 없고, 동일 후보 집합이 되는 redundancy(과도한 overlap)도 보완성 결여(과도한 분리)도 모두 운영상 정상 범위가 다양하다. 따라서 truth recall과 overlap rate은 informational만 산출하고 차단 게이트로 격상하지 않는다.
- **truth recall 가드**: `feedback_phase1_truth_recall_guard`에 따라 truth recall은 PHASE1/PHASE2 변경의 정당화 사유로 사용 금지. Layer C의 truth 관련 지표(C3/C4)는 모두 informational only.
- **운영 기준**: HARD 트랙 중 하나라도 FAIL이면 promotion BLOCK. SOFT 트랙은 결과 보고에 표기하되 BLOCK 사유로 사용 금지.
- **A3/A4 운영 임계 calibration**: ECDF q95를 PHASE2 high-score 정의로 유지하되, 정상 모집단의 high_ratio 운영 임계는 A3/A4 모두 8%로 둔다. ECDF q95 정의상 정상 모집단도 약 5%가 HIGH가 되며, 300행 표본의 sampling noise와 contract_v2 정상 모집단 분포 변동을 합산해 3%p buffer를 둔다.
- **A3/A4 측정 범위**: A3는 `datasynth_manipulation_v7_candidate_fixed3` test partition에서 truth가 아닌 정상 300행 동적 fixture를 사용한다. A4는 `datasynth_contract_v2_enriched_normal` mutation-free fixture만 사용한다. 이 calibration은 PHASE2 Layer A 운영 가드 임계 조정이며, D050의 DataSynth fixed3 promotion status를 변경하지 않는다.
- **정상 baseline 정의**: `datasynth_contract_v2_enriched`에는 legacy mutation provenance가 5,135/1,077,767행(0.48%) 포함되어 있었으므로, A4 normal baseline은 `mutation_type`이 비어 있는 1,072,632행 subset으로 제한한다. 해당 subset은 contract_v2 전용이며 `datasynth_manipulation_v7_candidate_fixed3`에는 적용하지 않는다.
- **truth recall 영향**: q95 자체를 q99로 올리지 않으므로 모델의 tail definition과 truth recall 측정 방식은 유지된다. truth recall 수치는 evaluation-only/informational로만 보고하며 PHASE1/PHASE2 변경 정당화 사유로 사용하지 않는다.
- **단일 출처**: `artifacts/phase2_layer_a_audit_2026-05-17.md`, `artifacts/phase2_layer_b_audit_2026-05-17.md`, `artifacts/phase2_layer_c_audit_2026-05-17.md`, `artifacts/phase1_phase2_integration_report_2026-05-17.md`.
- **관련 결정**: D040(Phase 2 ML 평가 강제 protocol — supervised promotion gate), D027(Hold-out Fraud Type), D029(데이터 분할 전략).

---

> **Legacy/mojibake decision block**: D001~D039 below are pre-cleanup historical records. Any LLM/OpenAI/Vanna/Text-to-SQL/Phase 3 references in this legacy block are superseded by D068 and are not active product capability.

### D001: Qwen3-8B 1?쒖쐞 (Qwen2.5-Coder ?대갚)
- **?댁쑀**: Qwen3 Ollama 吏?? reasoning ?깅뒫 ?μ긽. RTX 3070 Ti 8GB??Q4_K_M ?곹빀 (6~7GB VRAM)
- **?대갚**: Qwen2.5-Coder-7B (Text-to-SQL ?뱁솕)

### D002: Vanna AI 2.0 梨꾪깮 (吏곸젒 ?꾨＼?꾪듃 ???
- **?댁쑀**: DuckDB+Ollama+ChromaDB ?ㅼ씠?곕툕, agent-based API, ?먮룞 Plotly, 媛쒕컻?쒓컙 80% ?덇컧
- **?몃젅?대뱶?ㅽ봽**: Vanna ?섏〈??利앷?, 而ㅼ뒪?곕쭏?댁쭠 ?쒗븳

### D003: kiwipiepy ?⑤룆 (konlpy ?쒓굅)
- **?댁쑀**: JVM ?섏〈???쒓굅, ?쒖닔 Python, pip install ??以??꾧껐

### D004: fpdf2 梨꾪깮 (reportlab ???
- **?댁쑀**: 寃쎈웾?? 媛꾨떒??媛먯궗議곗꽌??異⑸텇

### D005: LangGraph ?쒓굅
- **?댁쑀**: Vanna+PandasAI濡?異⑸텇. Phase 3?먯꽌 ?꾩슂 ???ы룊媛

### D006: BaseDetector 異붿긽 ?대옒???⑦꽩
- **?댁쑀**: 紐⑤뱺 ?먯? ?몃옓??`detect() -> DetectionResult` ?명꽣?섏씠??怨듭쑀. ?몃옓 異붽? ??score_aggregator ?섏젙 理쒖냼??
### D007: LLM ?놁씠 MVP ?숈옉
- **?댁쑀**: Phase 1? LLM ?몄텧 0. 而щ읆 留ㅽ븨 ?ㅽ뙣 ???섎룞 UI ?대갚. ?먯쭊??蹂듭옟??利앷?

### D008: dependency-groups 遺꾨━
- **?댁쑀**: `uv sync --group core,dashboard`濡?MVP 理쒖냼 ?ㅼ튂. ML/LLM? ?꾩슂 ?쒖뿉留?
### D009: 개요서 → 기능별 구현 가이드 10개 분리
- **이유**: 하나의 개요서(380줄)에서 구현 시 참조가 어려움. 기능 영역별 분리로 각 모듈 구현 시 해당 가이드만 참조
- **구조**: `docs/archive/completed/raw-plan/01~10-*.md`, 공통 포맷(목적/관련 파일/핵심 클래스/데이터 흐름/구현 순서/의존성/테스트/Phase/주의사항)
- **원본 유지**: `completed/raw-plan/개요서.md`는 전체 뷰 용도로 보존, 구현 가이드는 상세 레퍼런스

### D010: EY-ASU DataSynth瑜?硫붿씤 ?곗씠???뚯뒪濡?梨꾪깮
- **寃곗젙**: 32媛?怨듦컻 ?곗씠?곗뀑/?꾧뎄 寃???? EY-ASU DataSynth(tools/datasynth/)濡??앹꽦???⑹꽦 ?꾪몴瑜?硫붿씤 ?곗씠?곕줈 梨꾪깮. 湲곗〈 ?섏쭛 ?곗씠??sap-merged, schreyer-fraud ??5醫???寃利앹슜?쇰줈 ?꾪솚
- **?댁쑀**:
  - SAP ACDOCA 71?꾨뱶 ?ㅼ씠?곕툕 援ъ“ (?ㅼ젣 SAP S/4HANA? ?숈씪 ?꾨뱶紐?
  - Fraud ?덉씠釉?132醫??댁옣 (49 fraud + 28 error + 22 process + 18 statistical + 15 relational)
  - 蹂듭떇遺湲???벑??李??) 蹂댁옣, Benford 遺꾪룷 以??  - PCAOB/ISA/COSO/SOX 媛먯궗湲곗? 肄붾뱶 ?덈꺼 援ы쁽
  - seed 怨좎젙?쇰줈 ?숈씪 ?곗씠???ы쁽 媛??  - ?ы듃?대━?ㅼ뿉??"EY+ASU 怨듬룞 媛쒕컻 ?꾧뎄 湲곕컲"?쇰줈 ?댄븘
- **anomaly ?좏삎???숈닠쨌?곗뾽 洹쇨굅**:
  - **ACFE Fraud Tree**: 49媛?遺??scheme ???붿????꾪몴 ?섍꼍?쇰줈 ?뺤옣
  - **PCAOB AS 2401 / ISA 240 / COSO 2013 / SOX 302쨌404**: ?ㅻТ 媛먯궗湲곗? 肄붾뱶 援ы쁽
  - **Schreyer & Sattarov ?곌뎄** (arXiv 1709.05254, 1908.00734): ?꾪몴 ?댁긽移?遺꾨쪟 ?숈닠 ?쒖?
  - ?????꾨젅?꾩썙?ъ쓽 援먯감 ?ㅺ퀎瑜?諛뷀깢?쇰줈 ?꾩옱 ?댁쁺 湲곗?蹂몄뿉?쒕룄 fraud/anomaly/SoD? 蹂꾨룄 `anomaly_labels.csv`瑜??④퍡 ?좎??쒕떎. ?몃? 二쇱엯 ?섏튂??freeze 硫붾え 湲곗??쇰줈 愿由ы븳??
- **?꾧뎄 理쒖떊??*: DataSynth ?덊룷 湲곕컲 ?꾨줈?앺듃 fork瑜?怨꾩냽 蹂댁젙 以묒씠硫? ?꾩옱 ?ㅼ궗??湲곗?蹂몄? 2026-05-02 ?숆껐 `v126`?대떎. `v23`??B04 duplicate payment 蹂댁젙, `v45`??L3-10 ?됯? 怨꾩빟, `v52~v54`??Benford group truth/holdout, `v55~v57`??D01/D02 怨꾩젙 ?⑥쐞 sidecar? ?뺤긽 ?議곌뎔, `v58`??L1-09/L2-02 ?꾩닔 truth 蹂듦뎄, `v126`??L1-03/L3-01 CoA 寃쎄퀎 蹂댁젙???꾩쟻 諛섏쁺?덈떎.
- **???寃??*: ?ㅼ젣 SAP ?곗씠??sap-merged 332K)???댁긽移??덉씠釉?1%肉? Schreyer(533K)???좎쭨 ?놁쓬+?꾨? ?듬챸?? BPI 2019(1.6M)???꾪몴媛 ?꾨땶 ?대깽??濡쒓렇
- **?앹꽦 ?ㅼ젙**: `config/datasynth.yaml` (seed 2024, 36媛쒖썡, 3?뚯궗, fraud 2%)
- **?꾩옱 湲곗? 寃곌낵**: 1,109,435?쇱씤(319,193?꾪몴), 52而щ읆, `anomaly_labels.csv` 3,149嫄?
### D011: 24媛?猷?L1/L2/L3/L4 泥닿퀎 ?뺤젙
- **寃곗젙**: 湲곗〈 R001~R008(8媛?猷?+ Benford) 泥닿퀎瑜??먭린?섍퀬, DataSynth 52媛?anomaly ?좏삎?먯꽌 3異??됯?(踰뺢퇋 洹쇨굅 횞 FSS ?ㅼ쬆 횞 ?곗씠??媛?⑹꽦)濡??좊퀎??24媛?猷?L1/L2/L3/L4 泥닿퀎濡??꾨㈃ ?ъ꽕怨?- **?댁쑀**:
  - 湲곗〈 R001~R008? 媛먯궗湲곗???240?몃쭔 李몄“???먯깋???ㅺ퀎. 踰뺢퇋 洹쇨굅쨌?ㅼ쬆 鍮덈룄쨌?곗씠???곹빀?꾩쓽 泥닿퀎???됯? 遺??  - FSS 媛먮━吏?곸궗濡 189嫄??꾩닔 ?쎄린 遺꾩꽍 ??6? 遺???⑦꽩(媛怨듭쟾??53%, 寃곗궛?섏젙 29%, ?〓졊???26% ?? ?꾩텧
  - 3異??됯?濡?Must(7~9??/Should(4~6)/Could(2~3)/Drop(0~1) ?먯젙 ??Phase蹂?紐낇솗??援ы쁽 踰붿쐞
- **援ъ“**:
  - L1 (?뺤젙 ?ㅻ쪟/?꾨컲): L1-01~L1-08
  - L2 (媛뺥븳 遺???뺥솴): L2-01~L2-05
  - L3 (寃???꾩슂 ?댁긽吏뺥썑): L3-01~L3-11
  - L4 (?듦퀎???댁긽移?: L4-01~L4-06
- **Phase蹂??뺤옣**: Phase 1(24媛?猷? ??Phase 2(+16媛?ML) ??Phase 3(+5媛?NLP/洹몃옒?? = 珥?41媛??좏삎
- **?몃? 寃利?*: CAQ 15媛??쒕굹由ъ삤 93% 而ㅻ쾭, PCAOB AS 2401 짠61 11媛??뱀꽦 91% 而ㅻ쾭

> Current note (2026-04-28): D011? 珥덇린 泥닿퀎 ?뺤젙 湲곕줉?대떎. ?꾪뻾 PHASE1 援ы쁽 踰붿쐞??32媛?L1~L4 猷곗씠硫? L3??L3-01~L3-12源뚯? ?ы븿?쒕떎. L3-12??L1-06 direct SoD? 遺꾨━???낅Т踰붿쐞 review signal?대떎.

### D012: FSS 媛먮━吏?곸궗濡 189嫄?湲곕컲 ?ㅼ쬆 遺꾩꽍
- **寃곗젙**: 湲덇컧???뚭퀎?ы깉 媛쒕퀎 ?щ? 189嫄?2011~2025)??蹂몃Ц(HWP/PDF)??吏곸젒 ?섏쭛쨌遺꾩꽍?섏뿬 ?꾪몴 議곗옉 ?⑦꽩 6醫?遺꾨쪟
- **?댁쑀**: ?⑥닚 嫄댁닔 湲곕컲???꾨땶 蹂몃Ц ?댁슜 湲곕컲 遺꾩꽍?쇰줈 ?ㅼ쭏??遺???⑦꽩 ?꾩텧. ?쒕ぉ留뚯쑝濡?6嫄댁씠??"?〓졊 ???媛 蹂몃Ц 遺꾩꽍 ??24嫄?4諛??쇰줈 利앷????щ? ??- **寃곌낵**: ?꾪몴 愿??94嫄?50%), 6? ?⑦꽩(媛怨듭쟾??50, 寃곗궛?섏젙 27, ?〓졊???24, ?쒗솚嫄곕옒 10, ?뱀씤/SoD?꾨컲 5, 鍮꾩젙?곸떆??4)
- **?쒖슜**: 3異??됯???"異?: ?ㅼ쬆 鍮덈룄" ?먯닔 ?곗젙 洹쇨굅

#### D012 ?낅뜲?댄듃: PHASE1 ?먯닔 湲곗? ?뺤젙 (2026-04-27)
- **寃곗젙**: row-level 湲곕낯 ?먯닔?????댁긽 `layer_a/layer_b/layer_c/benford` 怨좎젙 媛以묓빀???ъ슜?섏? ?딅뒗?? ?대떦 ?대쫫? detector ?ㅽ뻾/????명솚??track name?쇰줈留??좎??쒕떎.
- **?꾩옱 湲곗?**: `RULE_LEVEL_WEIGHTS = L1 0.40 + L2 0.25 + L3 0.20 + L4 0.15`.
- **?꾪뿕?깃툒**: `High >= 0.7`, `Medium >= 0.4`, `Low >= 0.2`, 洹???`Normal`.
- **蹂댁셿**: `L1-05` immediate/escalated ?먭린?뱀씤, `L1-04`, `L1-06`, `L1-07` immediate ?듭젣 ?꾨컲? row `risk_level`怨?case `priority_score` ?묒そ??policy floor瑜??곸슜?쒕떎.

### D013: ?먯닔 泥닿퀎 ?ъ꽕怨?- **寃곗젙**: MVP ?먯닔??L1/L2/L3/L4 rule-family 湲곗??쇰줈 怨꾩궛?쒕떎. `layer_a`, `layer_b`, `layer_c`, `benford`???ㅽ뻾 ?붿쭊 ?명솚??track name?쇰줈留??좎??쒕떎.
- **?댁쑀**: ?ъ슜???붾㈃, 媛먯궗 ?뺤콉, 肄붾뱶??理쒖쥌 ?먯닔 湲곗???L1~L4濡??듭씪?댁빞 "??怨좎쐞?섏씤???먯뿉 ?놁??" 媛숈? ?ㅻ챸 遺덉씪移섎? 以꾩씪 ???덈떎.
- **?꾪뿕?깃툒**: `High >= 0.7`, `Medium >= 0.4`, `Low >= 0.2`, `Normal < 0.2`
- **?뺤콉 floor**: ?ш컖???듭젣 ?꾨컲? row-level `risk_level`怨?case-level `priority_score` ?묒そ??理쒖냼 ?밴꺽 湲곗????곸슜?쒕떎.

### D014: ?뚯씪 移댄뀒怨좊━蹂?寃利??꾨왂 (file_validator 3遺꾨쪟)
- **寃곗젙**: 10媛??뺤옣?먮? 3媛?移댄뀒怨좊━(Excel/Text/Columnar)濡?遺꾨쪟?섏뿬 媛곴컖 ?ㅻⅨ ?ш린 ?쒗븳쨌寃利??꾨왂 ?곸슜. PDF/HWP???꾨줈?앺듃 踰붿쐞 ?몃줈 嫄곕?
- **?댁쑀**:
  - Excel(.xlsx/.xls/.xlsb): ?쒗듃??104留???臾쇰━ ?쒗븳 ??100MB 異⑸텇. 媛곴컖 openpyxl/xlrd/pyxlsb濡??먯긽 寃利?  - Text(.csv/.tsv/.txt/.dat): ?ш린 ?쒗븳 ?녿뒗 ?щ㎎, ?몄퐫???ㅼ뼇(UTF-8/CP949/latin-1) ??800MB + charset_normalizer ?먮룞 媛먯? + ascii?뭠atin-1 ?대갚
  - Columnar(.parquet): ?뺤텞 ?⑥쑉 ?믪븘 1GB ?덉슜. pyarrow 硫뷀??곗씠?곕쭔 ?쎌뼱 寃利?  - PDF/HWP: 鍮꾩젙??臾몄꽌 ?곗씠??異붿텧? 蹂꾨룄 ?꾨줈?앺듃 踰붿쐞 (CONSTRAINTS.md 李멸퀬)
- **援ъ“**: `file_categories.py`(移댄뀒怨좊━ ?뺤쓽) + `integrity_checkers.py`(?뺤옣?먮퀎 ?닿린 寃利? + `file_validator.py`(?쇱궗?? 3?뚯씪 遺꾨━ (SRP)
- **?ㅼ젙**: `settings.py`??`allowed_extensions`/`max_file_size_mb`??deprecated. 移댄뀒怨좊━蹂??쒗븳? `file_categories.py` ?곸닔濡?愿由?(?뚯씪 ?щ㎎ 臾쇰━???뱀꽦?대?濡??ъ슜???ㅼ젙???꾨떂)

### D016: UX 1단계 — 데이터 수집 투명성 (Ingest v2)
- **UX 단계 체계**: UX 1단계(수집 투명성) → UX 2단계(룰 세팅+파생변수) → UX 3단계(전처리+EDA). 상세: [ux-flow.md](../guide/ux-flow.md)
- **정의**: 사용자가 데이터를 넣으면 AI가 헤더/컬럼을 자동 지정하고, 애매한 부분은 사용자에게 위임하며, 판단 근거(신뢰도, 매칭 방식)를 투명하게 노출하는 UX 모델
- **결정**: 헤더 탐지를 구조적 신호 기반으로 전환, fuzzy 매핑에 타입 검증 추가, 매핑 판단 근거를 ReviewItem으로 구조화
- **UX 원칙**:
  - **80/20 자동화**: 확신 높은 80%는 자동 처리(action="auto"), 나머지 20%는 사용자 검토(action="review")
  - **판단 투명성 확보**: 모든 매핑에 reason(판단 근거) + confidence(신뢰도) + source_type/target_type 노출
  - **3-tier 시각 피드백**: 확정(초록) / 추천+확인 필요(노랑) / 차단됨(빨강)
- **구현 내용**:
  - A1. 구조적 헤더 탐지 — 키워드 없어도 데이터 구조(타입다양성/고유값/null밀도)로 헤더 판별
  - B1. 타입 호환성 검증 — fuzzy 후보의 소스↔스키마 타입 비교, 비호환 차단
  - B3. Null 3단계 분기 — 유령 컬럼 조용히 분리, 오매핑 의심 명시 경고
  - C. dc_indicator 표준 컬럼 등록
  - D. ReviewItem 모델 — action/confidence/reason/source_type/target_type 구조
  - E. ascii→latin-1 인코딩 폴백 — 대용량 CSV 오탐 근본 해결
- **결과**: 5종 실데이터셋 전체 올그린 (bpi2019 527MB 1.6M행 포함), 197 tests passed
- **Phase 1c 연계**: ReviewItem → Streamlit 매핑 확인 UI의 데이터 소스로 직접 사용

### D017: ascii?뭠atin-1 ?몄퐫???대갚
- **寃곗젙**: `text_reader._detect_encoding()`?먯꽌 charset_normalizer媛 "ascii"濡?媛먯??섎㈃ "latin-1"?쇰줈 ?대갚
- **?댁쑀**: charset_normalizer??64KB ?섑뵆 湲곕컲. bpi2019(527MB, latin-1)??泥??뱀닔臾몄옄(0x96)媛 249KB 吏?????섑뵆 踰붿쐞 諛???ascii ?ㅽ깘 ???쎄린 ?ㅽ뙣
- **洹쇨굅**: ascii??latin-1??吏꾨?遺꾩쭛??0x00~0x7F). latin-1? 0x00~0xFF ?꾩껜 留ㅽ븨?대?濡??대뼡 諛붿씠?몃뱺 ?먮윭 ?놁씠 ?쏀옒. ?쒖닔 ascii ?뚯씪??latin-1濡??쎌뼱??寃곌낵 ?숈씪 ??遺?묒슜 ?놁쓬
- **???寃??*: ?섑뵆 ?ш린 ?뺣?(256KB~1MB)?????ㅼ뿉 ?뱀닔臾몄옄媛 ?섏삤硫????ㅽ뙣 ??洹쇰낯 ?닿껐 ?꾨떂

### D015: ?뚯씪 ?쎄린 4-由щ뜑 遺꾨━ + read_only=False 寃곗젙
- **寃곗젙**: pre-plan???⑥씪 `excel_reader.py`(WorkbookInfo) ??4媛?由щ뜑 + 1媛??쇱궗??+ 1媛?紐⑤뜽濡??뺤옣. xlsx??`read_only=False`濡?蹂묓빀? 泥섎━ ?곗꽑
- **?댁쑀**:
  - `read_only=True`? `merged_cells.ranges`??openpyxl?먯꽌 ?묐┰ 遺덇?. ERP ?묒???蹂묓빀?? 留ㅼ슦 ?뷀븿
  - xlsx/xls/xlsb/csv/tsv/txt/dat/parquet 10媛??뺤옣?먭? 紐⑤몢 ?ㅻⅨ ?쇱씠釉뚮윭由?텮PI ?ъ슜 ???⑥씪 ?뚯씪濡?遺덇? (SRP ?꾨컲, 100以?珥덇낵)
  - DataSynth CSV(319MB)媛 硫붿씤 ?곗씠?곗씤??openpyxl 寃쎈줈瑜??硫???????CSV fast path ?꾩닔
  - CSV/Parquet? "?쒗듃" 媛쒕뀗???놁쑝誘濡?WorkbookInfo ????듯빀 `ReadResult` ????꾩슂
- **援ъ“**: `models.py`(ReadResult) + `excel_reader.py`(xlsx/xls/xlsb) + `text_reader.py`(csv/tsv) + `parquet_reader.py` + `reader_api.py`(?쇱궗??
- **硫붾え由??덉쟾?μ튂**: file_validator??100MB ?쒗븳??read_only=False??硫붾え由??꾪뿕???곸뇙 (16GB RAM)

### D018: ?댁긽移??뱀씠移??댁쨷 ?먯? 泥닿퀎
- **寃곗젙**: ?댁긽移?Outlier, ?쇰꺼 ?덈뒗 ?곗씠????Classification(XGBoost ??, ?뱀씠移?Novelty, ?뺤긽留??숈뒿)??VAE+IF ?숈긽釉붾줈 ?댁쨷 ?먯?
- **?댁쑀**: 吏?꾪븰?듭? "?대? 蹂??⑦꽩"留??먯?. VAE??"?뺤긽 遺꾪룷 諛??대㈃ 誘몄???遺?뺣룄 ?먯? 媛??(unseen-pattern review signal discovery)
- **??븷 遺꾨━**: XGBoost??DataSynth 踰ㅼ튂留덊겕 + ?꾩씠?숈뒿 蹂댁“ ?먯닔, VAE+IF???ㅼ쟾 硫붿씤 ?먯? ?붿쭊

### D019: ML 紐⑤뜽 ?꾨낫 ?좎젙
- **寃곗젙**: 吏?꾪븰??4醫?LR 踰좎씠?ㅻ씪?? RF, XGBoost 硫붿씤, LightGBM) + 鍮꾩???2醫?IF, VAE). KNN/LOF ?쒓굅, DNN 蹂대쪟
- **?댁쑀**: KNN/LOF??1M嫄댁뿉??O(n짼) ?ㅼ??쇰쭅 臾몄젣. DNN? ?쇱쿂 ?붿??덉뼱留??꾨즺 ?곹깭?먯꽌 ?댁젏 媛먯냼. cv_selector媛 ?꾨낫 4醫??먮룞 鍮꾧탳
- **洹쇨굅**: 2025 踰ㅼ튂留덊겕?먯꽌 ?뚯씠釉??곗씠?곕뒗 XGBoost媛 Transformer蹂대떎 ?덉젙???곗쐞

### D020: VAE ?꾪궎?띿쿂 ??Basic FC + Phase 3 BiLSTM+Attention 援먯껜
- **寃곗젙**: Phase 2??Basic FC VAE(50??2????2??0) + IF ?숈긽釉? Phase 3?먯꽌 vae_model.py瑜?BiLSTM+Attention?쇰줈 援먯껜 ?ㅽ뿕
- **?댁쑀**: (1) ?뚯씠?꾨씪???명솚????2D ?좎?, 3D 蹂?섏? vae_wrapper ?대? 罹≪뒓??(2) ?뚭퀎 ?꾪몴??媛쒕퀎 ?ш굔(Discrete Events) ???쒓컙 ?쇱쿂???대? 異붿텧??(3) IF+VAE ?숈긽釉??쒕꼫吏濡?異⑸텇
- **援먯껜 ?꾨왂**: vae_wrapper.py ?몃? ?명꽣?섏씠??sklearn 2D)???좎?, ?대?留?援먯껜. ?섑띁 ?⑦꽩???듭떖 媛移?
### D021: ?곗씠??遺덇퇏??泥섎━ ??紐⑤뜽 臾닿? 4?④퀎 ?꾨왂
- **寃곗젙**: (1) ?뚭퀬由ъ쬁 ?덈꺼(scale_pos_weight/class_weight ?먮룞 留ㅽ븨) 1?쒖쐞 (2) ?됯? 吏??PR-AUC/F2 (3) SMOTE-ENN ?좏깮??(4) Threshold Moving
- **?댁쑀**: ?뚭퀬由ъ쬁 ?섏? 議곗젙???곗씠???섏?(SMOTE)蹂대떎 ?덉젙??(ICML 2025). SMOTE??train set?먮쭔 ?곸슜 ?꾩닔 (data leakage 諛⑹?)
- **紐⑤뜽蹂?留ㅽ븨**: XGBClassifier?뭩cale_pos_weight, RandomForest?뭖lass_weight="balanced", LGBMClassifier?뭝s_unbalance=True

### D022: ?깅뒫 ?됯? 吏??泥닿퀎
- **寃곗젙**: 1李?AUPRC+F2-score, 2李?MCC+DR@FAR=5%, 3李?ROC-AUC(caveat 紐낆떆), 蹂닿퀬??Precision/Recall/F1
- **?댁쑀**: 洹밸떒??遺덇퇏??<1%)?먯꽌 Accuracy/ROC-AUC 臾댁쓽誘? F2??Recall 2諛?媛以?遺???볦튂??鍮꾩슜 > ?ㅽ깘 鍮꾩슜). DR@FAR=5%??媛먯궗?몄뿉寃?媛??吏곴???- **UI ?붽뎄**: ??쒕낫?쒖뿉??媛?吏?쒕? 鍮꾩쟾臾멸? 移쒗솕?곸쑝濡?tooltip ?ㅻ챸
- **PHASE1 ?곸슜 二쇱쓽**: ??吏??泥닿퀎??紐⑤뜽 ?깅뒫 鍮꾧탳? 媛쒕컻 寃利앹슜?대떎. PHASE1 ?댁쁺 寃곌낵??理쒖쥌 遺??遺꾨쪟媛 ?꾨땲???꾨낫 紐⑥쭛?④낵 case priority?대?濡? DataSynth `is_fraud` / `is_anomaly` 湲곗? precision/recall留뚯쑝濡??깃났쨌?ㅽ뙣瑜??먮떒?섏? ?딅뒗?? PHASE1?먮뒗 `rule_truth`, review population coverage, macro finding coverage, exception rate瑜??④퍡 ?ъ슜?쒕떎.

### D023: ?쇰꺼留??꾨왂 ???먮룞 ?숈뒿 紐⑤뱶 ?꾪솚
- **寃곗젙**: label_strategy.py?먯꽌 ?묒꽦 ??0嫄?AND ??%?대㈃ 吏?꾪븰?? 誘몃떖 ???먮룞?쇰줈 鍮꾩???VAE+IF) ?꾪솚
- **?댁쑀**: StratifiedKFold 5-fold 湲곗? 媛?fold 理쒖냼 ?묒꽦 10嫄??꾩슂. DataSynth??2%(~21K嫄?濡?異⑸텇?섏?留??ㅻТ ?곗씠?곕뒗 遺議깊븷 ???덉쓬
- **?꾩씠 ?숈뒿**: DataSynth濡??숈뒿??XGBoost瑜??ㅻТ ?곗씠?곗뿉 ?꾩씠 ?곸슜 (蹂댁“ ?먯닔). Phase 3?먯꽌 媛먯궗???쇰뱶諛?猷⑦봽濡??ы븰??
### D024: score_aggregator ??L1/L2/L3/L4 rule-family aggregation
- **寃곗젙**: PHASE1 湲곕낯 row-level ?먯닔??L1/L2/L3/L4 rule family蹂?max score瑜?留뚮뱺 ??`RULE_LEVEL_WEIGHTS`濡??⑹궛?쒕떎.
- **?꾩옱 湲곗?**: `L1 0.40`, `L2 0.25`, `L3 0.20`, `L4 0.15`.
- **?명솚??*: `layer_a`, `layer_b`, `layer_c`, `benford` track name? detector ?ㅽ뻾/????명솚?⑹쑝濡??좎??쒕떎. 紐낆떆?곸쑝濡?legacy weight dict瑜??섍릿 寃쎌슦?먮쭔 legacy track weighted sum???ъ슜?쒕떎.
- **?뺤옣**: ML ?먮뒗 TrendBreak媛 遺숇뒗 寃쎌슦 `RULE_LEVEL_WEIGHTS_WITH_ML`, `RULE_LEVEL_WEIGHTS_WITH_TRENDBREAK`濡?L1~L4 異뺤쓣 ?좎???梨?extra track??異붽??쒕떎.
- **?꾪뿕?깃툒**: threshold??`>`媛 ?꾨땲??`>=`濡??곸슜?쒕떎.
- **?뺤콉 floor**: 移섎챸 ?듭젣 ?꾨컲? 蹂댁“ 猷?遺議??뚮Ц??Low/Medium??癒몃Ъ吏 ?딅룄濡?row `risk_floor_reasons`? case `priority_floor_reasons`瑜??④린怨??밴꺽?쒕떎.
- **L3-12 蹂닿컯**: `L3-12`??`access_scope_review` weak/booster濡?L3 family max???쏀븯寃?諛섏쁺?쒕떎. ?⑤룆?쇰줈 policy high floor瑜?留뚮뱾吏 ?딆쑝硫? `work_scope_combo_score`?먯꽌 ?낅┰ 蹂닿컯 evidence group 2媛??댁긽?대㈃ Medium, 3媛??댁긽?대㈃ High floor瑜??곸슜?쒕떎. L3-12??review-only ?좏샇?대?濡?`details`/`flagged_rules`?먮뒗 ?뺤젙 ?꾨컲泥섎읆 ?곸옱?섏? ?딄퀬 `review_score_series`/`row_annotations.review_score`濡쒕쭔 ?먯닔泥닿퀎???좎엯?쒕떎.
- **Percentile Ranking 踰붿쐞**: Percentile Ranking? 紐⑤뜽 ?먯닔泥섎읆 ?ㅼ??쇱씠 ?ㅻⅨ ?몃? score瑜??⑹튌 ?뚯쓽 蹂댁“ ?뺢퇋??媛쒕뀗?대떎. PHASE1 湲곕낯 猷??먯닔??source of truth??`RULE_LEVEL_WEIGHTS`??

### D025: PHASE1 confirmed/review 猷?李몄“ 遺꾨━ (2026-04-27)
- **寃곗젙**: `flagged_rules`??`DetectionResult.details > 0`??confirmed/immediate 猷곕쭔 ?닿퀬, `review_rules`??`details == 0`?댁?留?`row_annotations.review_score` ??annotation score媛 ?덈뒗 review-only ?꾨낫留??대뒗??
- **?댁쑀**: `flagged_rules`??DB `anomaly_flags`, dashboard, export, LLM narrative?먯꽌 ?뺤젙 ?꾨컲 猷곗쿂???뚮퉬?쒕떎. review ?꾨낫瑜?媛숈? 而щ읆???욎쑝硫?DB?먮뒗 ?녿뒗 ?꾨컲 猷곗씠 由ы룷?몄뿉 ?몄슜?????덈떎.
- **?먯닔 湲곗?**: row-level `anomaly_score`? PHASE1 case priority??confirmed? review ?꾨낫瑜?紐⑤몢 諛섏쁺?????덈떎. ?ㅻ쭔 ?꾨컲 猷?吏묎퀎? `anomaly_flags` ?곸옱 湲곗?? confirmed `flagged_rules`??
- **耳?댁뒪 湲곗?**: `RawRuleHitRef.signal_status`濡?`confirmed`? `review_candidate`瑜?援щ텇?쒕떎.

### D026: preprocessing/detection ?⑤갑???섏〈
- **寃곗젙**: ?붾젆?좊━ 遺꾨━ + detection ??preprocessing ?⑤갑??import
- **?댁쑀**: ?꾩쿂由щ뒗 "?곗씠?곕? 紐⑤뜽??癒밴린 醫뗪쾶 ?붾━", ?먯???"?붾━瑜?癒밴퀬 ?먮떒". 寃고빀??理쒖냼?? ?쒗솚 ?섏〈 ?놁쓬
- **援ы쁽 ?쒖꽌**: 1?④퀎 detection 猷?24媛? ??2?④퀎 preprocessing(11媛?紐⑤뱢) ??3?④퀎 detection ML

### D049: VAE ?숈뒿 ?곗씠????寃利??ㅼ쟾 紐⑤뱶 遺꾨━
- **寃곗젙**: 寃利?紐⑤뱶(DataSynth)??is_fraud=False留??꾪꽣留? ?ㅼ쟾 紐⑤뱶(?쇰꺼 ?놁쓬)???꾩껜 ?곗씠???ъ엯
- **?댁쑀**: ?ㅼ쟾?먯꽌 ?뺤긽留?遺꾨━ 遺덇?. ?댁긽移?<2%?대㈃ VAE ?좎옱 怨듦컙? ?뺤긽 ?꾩＜濡??뺤꽦 (Contamination Tolerance)

### D027: ML ?뚯뒪????Hold-out Fraud Type + 蹂댁셿 ?뚯뒪??- **寃곗젙**: 8媛?遺???좏삎 以?6媛??덈젴, 2媛?suspense_account_abuse, expense_capitalization)??誘몄? ?좏삎?쇰줈 ?뚯뒪?? 蹂댁셿: Feature Perturbation + t-SNE/UMAP ?좎옱 怨듦컙 ?쒓컖??- **?댁쑀**: VAE??zero-day ?먯? ?λ젰 ?ㅼ쬆. XGBoost??誘몄? ?좏삎 紐??↔퀬 VAE???〓뒗 寃껋쓣 蹂댁뿬二쇰㈃ ?ы듃?대━??李⑤퀎??
### D028: DataSynth ?꾨줈?몄뒪 諛곗젙 ?꾩떎????遺??湲곕컲 SoD
- **寃곗젙**: shuffle 湲곕컲 ?쒕뜡 諛곗젙 ??persona蹂?遺??湲곕컲 諛곗젙?쇰줈 援먯껜
  - Junior: ?⑥씪 ?꾨줈?몄뒪 100% ?꾨떞 (Maker only, 寃몄쭅 遺덇?)
  - Senior+: compatible_pairs 湲곕컲 ?꾩떎??寃몄쭅 ?덉슜 (25%)
  - 7%: anomalous_pairs 湲곕컲 鍮꾪쁽?ㅼ쟻 寃몄쭅 (媛먯궗 ?먯? ???
  - AutomatedSystem: ?꾩껜 ?꾨줈?몄뒪 (?쒗븳 ?놁쓬)
- **?댁쑀**: 湲곗〈 shuffle()濡?H2R+O2C 媛숈? ?꾩떎?먯꽌 遺덇??ν븳 議고빀???쇱긽?곸쑝濡?諛쒖깮. ?ㅻТ?먯꽌 Junior??AP?꾨떞/AR?꾨떞?쇰줈 ?꾧꺽 遺꾨━?섎ŉ, 鍮꾪쁽?ㅼ쟻 寃몄쭅 ?먯껜媛 媛먯궗 ?곷컻 ???- **?뱀씤?쒕룄 蹂寃?*: 湲곗〈 [1M~100M] ??[10M~50B] KRW (?쒖“???꾧껐洹쒖젙 諛섏쁺)
- **?몃젅?대뱶?ㅽ봽**: seed ?ы쁽??breaking change (?꾨줈?몄뒪 諛곗젙 濡쒖쭅 蹂寃쎌쑝濡?湲곗〈 seed 異쒕젰 ?щ씪吏?
- **洹쇨굅**: generation_principles.md 짠2, FSS 189嫄?遺꾩꽍, ?쒓뎅 以묎껄 ?쒖“???ㅻТ ?쇰뱶諛?
### D029: ?곗씠??遺꾪븷 ?꾨왂 ??Stratified 60/20/20 + Holdout ?좏삎
- **寃곗젙**: DataSynth 1.1M嫄댁쓣 train 60% / val 20% / test 20%濡?遺꾪븷. `fraud_type` 湲곗? 痢듯솕異붿텧(StratifiedSplit)
- **?댁쑀**:
  - ?묒꽦 2%(~22K嫄? 洹밸떒 遺덇퇏?????⑥닚 ?쒕뜡 遺꾪븷 ???쇰? ?좏삎???뱀젙 ?뗭뿉 ?몄쨷 ?꾪뿕
  - 8媛?fraud_type蹂?鍮꾩쑉 ?좎?媛 紐⑤뜽 ?됯? ?좊ː?꾩쓽 ?듭떖
  - 60/20/20? 1.1M嫄?洹쒕え?먯꽌 val/test 媛?~220K嫄댁쑝濡??듦퀎???덉젙??異⑸텇
- **Holdout ?뺤콉**:
  - test set? 理쒖큹 遺꾪븷 ??**?숆껐** (紐⑤뜽 媛쒕컻 以??덈? ?ъ슜 湲덉?)
  - val set?쇰줈 ?섏씠?쇳뙆?쇰????쒕떇 + 紐⑤뜽 ?좏깮
  - test set? 理쒖쥌 蹂닿퀬??1???됯?留??덉슜
- **Hold-out Fraud Type** (D027 ?곌퀎):
  - 8媛??좏삎 以?suspense_account_abuse(5%), expense_capitalization(5%)? train?먯꽌 ?쒖쇅
  - test set?먯꽌 ??2媛??좏삎??VAE ?먯??⑤줈 zero-day ?λ젰 寃利?- **援ы쁽**: `sklearn.model_selection.train_test_split` 2??泥댁씠??(60??0/20), `stratify=fraud_type`
- **?ㅻТ ?곗씠??*: ?쇰꺼 ?놁쓬 ??label_strategy.py媛 ?먮룞?쇰줈 鍮꾩????꾪솚 (D023). 遺꾪븷 遺덊븘?? ?꾩껜 ?곗씠?곕줈 VAE+IF ?숈뒿

### D030: WU5 ?ㅼ젙 而댄룷?뚰듃 ???ы깘吏 遺꾨━ + 而ㅼ뒪? ?꾨━???뺤콉
- **寃곗젙**: ?ㅼ젙 蹂寃????ы깘吏 ??`_generate_features`瑜?嫄대꼫?곌퀬 `_run_detection` + `aggregate_scores`留??ㅽ뻾. 而ㅼ뒪? ?꾨━?뗭? ?붿뒪??誘몄???session_state ?꾩슜)
- **?댁쑀**:
  - `PipelineResult.data`?먮뒗 ?대? ?뚯깮 ?쇱쿂媛 ?ы븿?섏뼱 ?덉뼱 ?ъ엯????而щ읆 異⑸룎(`_x`, `_y`) 諛쒖깮
  - `PipelineResult.featured_data`???쇱쿂 ?앹꽦 吏곹썑 ?대┛ DF瑜??ㅻ깄?룻븯???ы깘吏 異쒕컻??蹂댁옣
  - Docker/?대씪?곕뱶 ?섍꼍?먯꽌 ?뚯씪 ?쒖뒪??Read-only ?먮뒗 ?ㅼ쨷 ?ъ슜??Race Condition 諛⑹?
- **二쇱슂 ?ㅺ퀎**:
  - `AuditPipeline.redetect(df, weights, thresholds)` 怨듦컻 硫붿꽌??異붽?
  - "?곸슜" 踰꾪듉 ?⑦꽩 ??留??щ씪?대뜑 蹂寃쎈쭏???ъ떎??????쇨큵 ?ㅽ뻾?쇰줈 ?⑥쑉??  - 鍮꾪솢??猷곗? `details` 0 留덉뒪??+ `flagged_rules` 臾몄옄???뺢퇋??移섑솚 2?④퀎 泥섎━ (`deepcopy`濡??먮낯 蹂댄샇)
  - 媛以묒튂 ?⒱돖1.0?대㈃ ?곸슜 踰꾪듉 `disabled=True` ???섎せ??score ?먯쿇 李⑤떒
  - `aggregate_scores`, `classify_risk_level`, `_apply_topside_escalation`??`settings`/`thresholds` ?좏깮???뚮씪誘명꽣 異붽? (湲곗〈 ?명솚)
- **援ы쁽 ?뚯씪**: `_redetect.py`, `preset_selector.py`, `threshold_sidebar.py`, `rule_panel.py`, `pipeline.py`, `score_aggregator.py`
- **?몃젅?대뱶?ㅽ봽**: `featured_data` ?ㅻ깄?룹쑝濡?硫붾え由??ъ슜??~2諛?利앷? (?洹쒕え ?곗씠?곗뿉??怨좊젮 ?꾩슂)

### D032: BiLSTM + Attention ?쒗???먯? 異붽? (Phase 2b)
- **寃곗젙**: Phase 2b??BiLSTM + Attention ?쒗???먯?湲?異붽?. 湲곗〈 ???⑥쐞(row-level) ?먯????쒓퀎瑜??ъ슜???쒓컙 ?쒗??而⑦뀓?ㅽ듃濡?蹂댁셿
- **?쒗??援ъ꽦 ?꾨왂**: `created_by` 湲곗? 洹몃９ ??`posting_date` ?뺣젹 ??seq_len=16 ?щ씪?대뵫 ?덈룄??stride=1). 3嫄?誘몃쭔 ?ъ슜?먮뒗 ?쒕줈 ?⑤뵫 + attention 留덉뒪??- **?꾪궎?띿쿂**: BiLSTM(hidden=64, layers=1, bidirectional) ??Additive Attention ??FC(128??4??). VRAM ~100MB (batch=256)
- **?댁쑀**:
  - ISA 240 "寃쎌쁺吏?override" ??遺?뺤? ?ъ슜??以묒떖 諛섎났 ?⑦꽩. ???⑥쐞 紐⑤뜽? ???쒓컙???섏〈??誘명룷李?  - ?뚭퀎 ?꾪몴???낅┰ ?됱씠吏留? 媛숈? ?ъ슜?먯쓽 ?곗냽 ?낅젰?먯꽌 ?쒗???⑦꽩(?먯쭊??湲덉븸 利앷?, 諛섎났???섍린 ?낅젰 ?? 議댁옱
- **sklearn ?듯빀**: `BiLSTMDetector(BaseEstimator)` ?섑띁媛 ?몃? 2D API ?좎?, ?대??먯꽌 `sequence_builder`濡?3D 蹂??- **洹쇨굅**: vae_wrapper.py ?⑦꽩 ?ъ궗?? RTX 3070 Ti 8GB?먯꽌 ~100MB濡??ъ쑀 異⑸텇
- **D020 蹂寃?*: "Phase 3?먯꽌 BiLSTM+Attention?쇰줈 援먯껜 ?ㅽ뿕" ??Phase 2b?먯꽌 ?낅┰ ?먯?湲곕줈 利됱떆 援ы쁽

### D033: FT-Transformer Tabular ?먯? 異붽? (Phase 2b)
- **寃곗젙**: Phase 2b??FT-Transformer(Feature Tokenizer + Transformer) 異붽?. 42李⑥썝 ?뺥삎 ?곗씠?곗쓽 ?쇱쿂 媛??곹샇?묒슜??self-attention?쇰줈 ?숈뒿
- **紐⑤뜽 ?좏깮**: TabTransformer(踰붿＜?뺣쭔 attention) / TabNet(踰ㅼ튂留덊겕 ?댁꽭) ???FT-Transformer 梨꾪깮
- **?꾪궎?띿쿂**: 42 features ??Feature Tokenizer(媛?64-dim embedding) + [CLS] token ??Transformer Encoder(2 layers, 4 heads, dim=64, ff=128) ??FC(64??). VRAM ~300MB (batch=256)
- **?댁쑀**:
  - 猷?寃곌낵 媛?議고빀 ?⑦꽩(?? weekend AND manual AND period_end AND high_amount)??attention???먮룞 ?숈뒿 ??Top-side 議고빀 ?먯닔???숈뒿 踰꾩쟾
  - Gorishniy et al. (2021) "Revisiting Deep Learning Models for Tabular Data" ??FT-Transformer媛 medium-size tabular?먯꽌 XGBoost? 寃쎌웳??  - ?대뼡 ?곗씠?곌? ?ъ? 紐⑤Ⅴ誘濡? tree 紐⑤뜽怨??ㅻⅨ 愿??attention 湲곕컲)???먯?湲??뺣낫 媛移?- **D019 蹂寃?*: "DNN 蹂대쪟" ??FT-Transformer濡?援ъ껜?뷀븯??Phase 2b???ы븿
- **sklearn ?듯빀**: `FTTransformerDetector(BaseEstimator)` ?섑띁, vae_wrapper.py ?⑦꽩 ?숈씪

### D034: Stacking Meta-Learner濡?媛以묓빀 ?泥?(Phase 2b)
- **寃곗젙**: 湲곗〈 怨좎젙 媛以묓빀(D024: rule 0.20 + supervised 0.25 + vae 0.20 + benford 0.15 + duplicate 0.20)??Stacking meta-learner(Logistic Regression, L2)濡??泥?- **援ъ“**:
  - Level 0: 6媛?base model (24媛?猷? XGBoost, VAE, IF, BiLSTM, FT-Transformer)
  - Level 1: LR(Ridge) meta-learner ??6媛??뺣쪧媛??낅젰 ??理쒖쥌 anomaly_score 異쒕젰
- **?댁쑀**:
  - 湲곗〈 媛以묒튂 5媛쒖뿉 洹쇨굅 ?놁쓬 (D013, D024 紐⑤몢 "?ㅼ륫 ???쒕떇 ?덉젙"?대씪 紐낆떆)
  - LR 怨꾩닔媛 怨??곗씠??湲곕컲 媛以묒튂 ??媛?紐⑤뜽???ㅼ젣 湲곗뿬?꾨? ?먮룞 ?숈뒿
  - ?낅젰 6媛쒖뿉 蹂듭옟??meta-learner(XGBoost ????怨쇱쟻??+ self-amplification ?꾪뿕
- **Leakage 諛⑹?**: 5-fold out-of-fold prediction ?꾨줈?좎퐳. base model? train folds濡쒕쭔 ?숈뒿, OOF prediction?쇰줈 meta-learner ?숈뒿 ?곗씠???앹꽦
- **Fallback**: stacking ?숈뒿 遺덇? ???쇰꺼 遺議? 湲곗〈 Percentile Ranking 媛以묓빀?쇰줈 ?대갚

### D031: WU6 EDA ??+ 硫붿씤 ???듯빀 ??Lazy Loading + ?꾪꽣 ?낅┰
- **寃곗젙**: EDA ?꾨줈?뚯씪???낅줈?????숆린 怨꾩궛???꾨땶, EDA ??理쒖큹 ?뚮뜑 ??Lazy Loading?쇰줈 怨꾩궛. ?ъ씠?쒕컮 ?꾪꽣? 臾닿??섍쾶 ?낅줈???먮낯 ?꾩껜 ?곗씠??湲곗??쇰줈 ?꾨줈?뚯씪留?- **?댁쑀**:
  - 100留?嫄??곗씠?곗뿉??`profile_dataframe()` ?숆린 ?몄텧 ???낅줈???湲??쒓컙??2諛??댁긽 泥닿컧 利앷?
  - EDA???먯떆 ?곗씠?곗쓽 援ъ“???덉쭏 吏꾨떒 紐⑹쟻. ?꾪꽣留곷맂 遺遺꾩쭛?⑹쓽 ?꾨줈?뚯씪? 媛먯궗 ?섎?媛 ?놁쓬
  - ?ы깘吏(?꾧퀎媛?媛以묒튂 蹂寃? ??EDA ?ш퀎??遺덊븘?????곗씠???먯껜媛 蹂?섏? ?딆쑝誘濡?- **罹먯떛 ?꾨왂**: `@st.cache_data`???ㅻ? `(upload_key, total_rows, total_columns)` ?ㅼ뭡?쇰줈 ?쒗븳. EDAProfile 媛앹껜瑜?吏곸젒 ?댁떆?섎㈃ UnhashableType ?꾪뿕
- **?ъ씠?쒕컮 UX**: ?낅줈?????뚯씪紐??됱닔 1以??붿빟留??쒖떆, ?꾪꽣? ?ㅼ젙? 媛곴컖 `st.expander`濡??묒뼱 13?몄튂 ?명듃遺??ㅽ겕濡?理쒖냼??- **???쒖꽌**: EDA ??Summary ??Benford ??Explorer (?곗씠???덉쭏 ?뺤씤??遺꾩꽍蹂대떎 ?좏뻾)
- **援ы쁽 ?뚯씪**: `app.py`(?좉퇋), `tab_eda.py`(?좉퇋), `eda_charts.py`(?좉퇋), `_state.py`(?섏젙), `data_uploader.py`(?섏젙)

### D036: DataSynth v20.4 ?댁쁺 湲곗? ?뺤젙
- **寃곗젙**: `data/journal/primary/datasynth/`瑜??꾩옱 ?댁쁺 湲곗?蹂?`v20.4`濡??뺤젙. Phase 1/2/3 湲곕낯 ?곗씠?곕뒗 ??寃쎈줈瑜??곕Ⅸ??
- **?댁쑀**:
  - V20: A04/B04/B10 諛?IC CoA ?뺥빀??蹂댁젙
  - V20.1: MisclassifiedAccount媛 InvalidAccount瑜??ㅼ뿼?쒗궎??鍮껩oA 怨꾩젙 移섑솚 臾몄젣 ?쒓굅
  - v20.3: `created_by`/`approved_by`? `employees.user_id` 議곗씤 蹂듦뎄
  - v20.4: `ExceededApprovalLimit`瑜?`approved_by.approval_limit` 湲곗??쇰줈 ?뺤젙
  - `document_number` 100% 臾몄옄??梨꾩?, approval violation `0`, B04 JE 吏湲됱뙇 蹂듭썝 媛??- **?곸꽭**: `FREEZE_V20.md` (현재 체크아웃에 없음)

### D039: DataSynth v23 ?댁쁺 湲곗? ?밴꺽
- **寃곗젙**: ?뱀떆 `data/journal/primary/datasynth/`瑜??댁쁺 湲곗?蹂?`v23`濡??밴꺽?덈떎. ?꾩옱 湲곗?蹂몄? ?곷떒??`v57` 硫붾え瑜??곕Ⅸ??
- **?댁쑀**:
  - `v22_candidate`??`B04`??`誘명깘 0 / 怨쇳깘 0`?쇰줈 benchmark ?뺣젹???덈Т 媛뺥뻽??  - `v23`? `P2P + KZ` duplicate payment pair瑜??좎??섎㈃?쒕룄 ?쇰? 誘명깘/怨쇳깘???④꺼 test fitting???꾪솕
  - `pair lineage`? `negative control`???④퍡 ?쒓났???ㅻ챸?깃낵 ?ㅻТ ?좎궗?깆쓣 ?뺣낫
- **?댁쁺 ?섏튂**:
  - `DuplicatePayment` labeled docs: `33`
  - `L2-02` 湲곗? detected docs: `28`
  - false negatives: `5`
  - false positives: `6`
- **?곸꽭**: `FREEZE_V23.md` (현재 체크아웃에 없음)

### D035: type_caster ?뺢퇋??洹쒖튃 ?몃?????cleaning.yaml
- **寃곗젙**: `type_caster.py`???섎뱶肄붾뵫???듯솕 湲고샇쨌null 媛뮻룸텋由ъ뼵쨌Excel serial 踰붿쐞쨌DC 吏?쒖옄瑜?`config/cleaning.yaml`濡?遺꾨━. 怨쇳븰???쒓린踰?2E+11) 媛먯?/蹂듭썝怨??쒓뎅 ERP null ?쒗쁽(`誘몄젙`, `?대떦?놁쓬`) 吏??異붽?
- **?댁쑀**: ??ERP ?щ㎎ ?????肄붾뱶 蹂寃??놁씠 YAML留??몄쭛. 湲곗〈??`keywords.yaml`, `schema.yaml`, `audit_rules.yaml` ?⑦꽩???덉쑝誘濡??숈씪 援ъ“ 梨꾪깮
- **援ы쁽 ?뚯씪**: `config/cleaning.yaml`(?좉퇋), `config/settings.py`(`get_cleaning_config()` 異붽?), `src/ingest/type_caster.py`(由ы뙥?좊쭅)

### D037: 紐⑤뜽 ?쒕━?꾪듃 ?ы븰???뺤콉 (SOC 2 / ISO 27001 ???
- **寃곗젙**: ML 紐⑤뜽 ?ы븰???몃━嫄곕? PSI 湲곕컲 ?먮룞 媛먯? + 遺꾧린蹂?二쇨린 ?ы븰?듭쑝濡??댁썝??  - **?먮룞 ?몃━嫄?*: `drift_detector.compute_drift_report()` ??`max_psi ??0.25` (critical) ?먮뒗 `schema_mismatch=True` ??利됱떆 ?ы븰?????깅줉
  - **二쇨린 ?몃━嫄?*: 留?媛먯궗 ?ъ씠??遺꾧린/??留덈떎 base 紐⑤뜽 ?ы븰??諛?OOF Stacking ?ъ떎??  - **紐⑤땲?곕쭅 ?몃━嫄?*: `max_psi ??[0.1, 0.25)` (warn) ???ы븰?듭? ?섏? ?딅릺 ??쒕낫??諛곕꼫 + 媛먯궗 濡쒓렇 湲곕줉
- **?댁쑀**:
  - 媛먯궗 ?ъ씠?댁? ??1?뚭? ?쇰컲?곸씠?댁꽌 ?숈뒿 紐⑤뜽??1???댁긽 ?ъ궗?⑸맆 ?꾪뿕
  - ?좉퇋 ?먰쉶???몄닔, ?뚭퀎?뺤콉 蹂寃? ERP ?낃렇?덉씠?쒕줈 ?명븳 遺꾪룷 蹂?붿뿉 ?좎젣 ????꾩슂
  - SOC 2 / ISO 27001 "AI 紐⑤뜽 嫄곕쾭?뚯뒪" ??ぉ??"?ы븰???뺤콉 臾몄꽌" ?꾩닔
- **?꾧퀎媛?洹쇨굅**:
  - PSI < 0.10 ??遺꾪룷 ?덉젙 (?ㅻТ ?낃퀎 愿??
  - 0.10 ??PSI < 0.25 ???쏀븳 ?쒕━?꾪듃, 紐⑤땲?곕쭅 媛뺥솕
  - PSI ??0.25 ??媛뺥븳 ?쒕━?꾪듃, ?ы븰???꾩닔
- **援ы쁽 ?뚯씪**:
  - `src/preprocessing/drift_detector.py` ??PSI 怨꾩궛 ?좏떥 (numeric 媛?곗떆??bin + categorical Top-N)
  - `src/preprocessing/data_stats.py` ???숈뒿 ?쒖젏 遺꾪룷 硫뷀??곗씠?????  - `src/preprocessing/model_registry.py` ??`ModelMetadata.training_data_stats` ?꾨뱶
  - `dashboard/components/drift_banner.py` ???곷떒 寃쎄퀬 諛곕꼫 + ?쒕━?꾪듃 ?곸꽭 expander
- **愿??寃곗젙**: D013(Stacking), D034(LR Ridge meta), D036(DataSynth ?섎졃)
- **?ν썑 ?뺤옣**: `tools/scripts/retrain_all_models.py` ?ㅽ겕由쏀듃 (CI/CD cron ?곕룞), Slack/?대찓???뚮┝ ?듯빀

### D038: FT-Transformer ?좎? + Ablation ?뺤콉 (Phase 2b)
- **寃곗젙**: FT-Transformer(ML03)???밸텇媛?8-model Stacking???좎?. ??`tools/scripts/ft_ablation_study.py`濡?遺꾧린蹂?ablation ?ㅼ륫 ???좎?/?쒓굅 ?먮떒.
- **?댁쑀**:
  - 42李⑥썝 ?낅젰?먯꽌 XGBoost ?鍮?FT-T??self-attention ?대뱷???⑹꽦 ?곗씠???섍꼍?먯꽌 ?ㅼ쬆 遺덇?
  - 洹몃윭??Ridge(positive=True) meta-learner媛 湲곗뿬????? 紐⑤뜽 怨꾩닔瑜??먮룞?쇰줈 0???섎졃?쒗궎誘濡??좎? 鍮꾩슜????쓬
  - ?쒓굅???섎룎由????녿뒗 寃곗젙?대?濡?"?곗씠?곕줈 利앸챸?????쒓굅"媛 ?덉쟾
- **?먯젙 湲곗?** (ft_ablation_study.py): ? F1-macro (8-model vs 7-model)
  - `? ??+0.5%` ??keep (?좎?)
  - `|?| < 0.5%` ??inconclusive (蹂대쪟, seed 諛섎났)
  - `? < -0.5%` ??remove (?쒓굅 寃??
- **援ы쁽 ?뚯씪**: `tools/scripts/ft_ablation_study.py` (怨④꺽), `tests/modules/test_tools/test_ft_ablation_study.py`
- **愿??寃곗젙**: D033(FT-T 異붽?), D034(Stacking)

### D046: Phase 2 ML 평가 6번째 게이트 — D040 으로 통합 (2026-05-15)
- 본 항목은 [D040](#d040-phase-2-ml-평가-강제-protocol-stage-10-audit-통합) 으로 통합되었다. anti-shortcut cap 의 BLOCK 정책 (`ratio ≤ 4.0`) 과 보조 측정값 (Top-5 LEAKAGE_DENY_RULES 제거 후 잔존율 ≥ 30% AND 절대값 ≥ 0.30) 의 단일 출처는 D040 이며, 본 ID 는 2026-05-15 ID 충돌 정정 시점에 stub 으로 남겨둔 historical anchor 다.

### D047: BiLSTM 트랙 PHASE2 본 평가 보류 조건 (Stage 7 + 10 Audit)
- **결정**: BiLSTM (ML_SEQUENCE) 트랙은 다음 3 조건 모두 통과 시에만 PHASE2 본 평가에 포함한다. 미통과 시 본 평가 제외, FT-Transformer + VAE + Supervised 7 트랙 ensemble 만 유지.
  - (1) `split_user_year_holdout` 적용 후 정확 날짜 매칭 overlap < 5%
  - (2) ±7일 인접 매칭 overlap < 20%
  - (3) val F1 (시퀀스 단위) 와 doc-level recall 의 격차 < 15pp
- **사유**: S7 측정 결과 현 split 정책에서 cross-user temporal context leakage 가 75% 에 달한다 (val truth 의 75% 가 train 의 ±7일 인접 시점에서 학습됨). stride=1 만 수정해도 단일 fold 내 16x context 중복 효율 손실은 해소되나 cross-user 시점 leakage 는 해소 불가.
- **영향 범위**: `src/preprocessing/split_strategy.py`, `config/settings.py`, `src/detection/sequence_detector.py`, `src/services/phase2_training_service.py`
- **관련 audit**: `artifacts/S7_sequence_split_redesign.md`, `docs/spec/PHASE2_FITTING_AUDIT.md`
- **관련 결정**: D032(BiLSTM + Attention 시퀀스 탐지 추가)

### D048: DataSynth manipulation v4 active lock (Stage 10 Audit, SUPERSEDED 2026-05-17)
- **상태**: **SUPERSEDED** — `data/journal/primary/datasynth_manipulation_v4_candidate/` 는 Stage 10 당시 Phase1/Phase2 측정 active lock 이었으나, 2026-05-17 D050에서 `datasynth_manipulation_v7_candidate_fixed3` 로 승격됐다. v3/v4 디렉토리는 회귀 비교 reference 로 유지한다.
- **결정**: DataSynth manipulation v4 profile 빌드 완료. v3 의 6 시나리오 + 2 hold-out 시나리오 (`suspense_account_abuse`=100, `expense_capitalization`=100, raw-plan D027 의도) 추가하여 총 8 시나리오 / 620 truth docs. 합성 shortcut 분포 노이즈화 (`f_manual` 0.41 정상 vs 시나리오별 0.45-0.79, `unusual_timing` 4 피처 stealth split, fictitious revenue amount upper-tail bucket sampling).
- **사유**: Stage 10 audit RED 4건 중 3건 (L-08 f_manual, L-09 trivial shortcut, L-10 unusual_timing degenerate) 이 모두 v3 dataset 의 합성 설계 결함에서 비롯된다. v4 빌드는 합성 shortcut 자체를 제거하는 근본 해법으로, raw-data guard (`tools/scripts/audit_manipulation_v4_candidate.py`) 8 check 모두 PASS.
- **재검증 결과 (2026-05-16, `artifacts/manipulation_v4_audit_rerun_summary_20260516.md`)**:
  - S3 trivial 10-feature macro AP: 0.1292 (v3) → **0.0237** (v4), 81.7% 감소.
  - S4 trivial top-1% recall: 4/6 scenario at ≥80% (v3) → 2 scenario at 1.0 (circular_related_party, unusual_timing_manipulation) + approval_sod_bypass 0.86 (v4). hold-out 2 시나리오는 trivial 기여 0.0/0.29.
  - S5 24-dim rule AUPRC = 0.397 (LOW band, 독립 신호), top-5 concentration drop = 0.86 → top-5 deny-list 정책 유지. v4 Top-5 ID 는 `rule_L3-02`, `rule_L3-09`, `rule_L1-03`, `rule_L2-03`, `rule_L1-05` 이며, v3 에서 강했던 `rule_L1-09`, `rule_L2-02` 는 v4 shortcut noise 로 약화되어 deny 에서 제외한다.
  - S8 ensemble overall AUPRC = 0.99 → **Phase2 supervised raw feature leak (모델 설계 문제)** 로 잔존. 데이터 측 해소는 완료, Phase2 모델 설계 후속 작업으로 이관.
  - S9 anti-shortcut cap: ensemble macro AP / trivial floor ratio = 33-40 → **BLOCK** (v4 가 trivial floor 를 낮춰 게이트 강도 약 6배 상승, 의도된 효과).
- **영향 범위**: `tools/datasynth/crates/datasynth-cli/src/manipulation_v4.rs`, `tools/scripts/audit_manipulation_v4_candidate.py`, S4/S5/S8 reproducer, Phase1 회귀 (`artifacts/phase1_manipulation_v4_candidate_20260515.*`), `docs/spec/PHASE2_FITTING_AUDIT.md` 의 RED → **YELLOW** 전환 (데이터 RED 해소 / 모델 RED 잔존).
- **비용**: Rust profile 설계 + 빌드 + 검증 — 완료.
- **관련 audit**: `docs/spec/PHASE2_FITTING_AUDIT.md`, `docs/archive/completed/S9_zero_day_protocol_alternatives.md` §3.3, `artifacts/manipulation_v4_audit_rerun_summary_20260516.md`
- **관련 결정**: D027(Hold-out Fraud Type), D028(DataSynth 프로세스), D036(DataSynth v20.4), D039(DataSynth v23)

### D050: DataSynth manipulation v7 fixed3 active promotion (2026-05-17)
- **상태**: **ACTIVE GO-WITH-CAVEAT** — `datasynth_manipulation_v7_candidate_fixed3` 가 최신 active manipulation synthetic 기준이다. v3/v4/fixed2는 회귀 비교 reference 로 유지한다.
- **결정**: V7 에서는 생성기로 고칠 수 있는 회계 substance 결함만 고친다. P2P vendor invoice 의 GR/IR credit, O2C customer invoice revenue 누락, normal near-threshold proxy, suspense line text ordering, period-end 발생액 line text 보존을 generator 에서 수정했다. 반면 amount/approval/scenario-specific shortcut 은 더 이상 DataSynth fitting 으로 밀지 않고 `LEAKAGE_DENY_COLUMNS` 로 PHASE2 feature policy 에 위임한다.
- **검증 결과**:
  - manipulation truth check: PASS, truth docs 620, label docs 620, missing provenance 0.
  - V7 quality verification: GO, hard failures 0, soft failures 0.
  - period_end adjustment expense line 92개 전부 발생액/환입 의미 line_text 포함.
- **PHASE2 policy**: `src/preprocessing/constants.py` 의 `LEAKAGE_DENY_COLUMNS_V6_BASELINE` + `LEAKAGE_DENY_COLUMNS_V7_DERIVED` 를 학습/inference 공통 deny-list 로 고정한다. 해당 컬럼은 real-data 재검증 전까지 개별 해제하지 않는다.
- **PHASE2 Layer A calibration과의 관계**: A3/A4 운영 임계 조정은 D051의 PHASE2 guard calibration이며, 본 D050의 fixed3 승격 상태나 DataSynth 생성물에는 영향을 주지 않는다.
- **관련 산출물**: `artifacts/datasynth_v7_quality_verification.md`, `tests/datasynth_quality_gate3/results/manipulation_v7_candidate_fixed3_truth_check.json`.
- **관련 결정**: D040(PHASE2 평가 protocol), D048(DataSynth manipulation v4 active lock), D051(PHASE2 Layer A/B/C guard calibration)

### D052: Supervised ML label gate hardening (2026-05-17)
- **결정**: PHASE2 supervised track은 label source와 low-signal 기준을 통과한 경우에만 학습한다. GateDecision 값은 `eligible`, `low_signal_fallback`, `hard_fail`, `unavailable` 네 가지로 고정한다.
- **임계값**:
  - `supervised_min_positive = 50`
  - `supervised_min_positive_rate = 0.01`
  - 허용 label source: `ground_truth`, `synthetic`, `holdout_test`, `train_oof`, `oof_fold`
- **정책**:
  - trusted source라도 `positive_count < 50` 또는 `positive_rate < 0.01`이면 `low_signal_fallback`으로 supervised 학습을 차단한다.
  - `detection_scores`, `pseudo_fallback`은 `circular_label_risk`로 supervised 학습을 차단한다.
  - label source가 없으면 `unavailable`, 양성 0건이면 `hard_fail`로 기록한다.
  - 기존 `label_quality`/`gate_status` 필드는 하위 호환으로 유지하되, 신규 계약은 `quality_grade`/`gate_decision`/`gate_reason`을 표준으로 사용한다.
- **영향 범위**: `src/preprocessing/label_strategy.py`, `src/detection/supervised_detector.py`, `src/preprocessing/model_registry.py`, `src/services/phase2_training_models.py`, `src/services/phase2_training_service.py`.
- **운영 관측성**: `training_report.json` 최상위 `supervised_gate` 필드에 decision, reason, label_source, positive_count, positive_rate, thresholds, eligible, allowed_label_sources를 기록한다.
- **관련 산출물**: `artifacts/sprint_phaseA_A1_handoff_2026-05-17.md`.

### D053: Phase 2 training/inference separation and auditable promotion policy (2026-05-17)
- **결정**: PHASE2는 `run_phase2_training()` 학습 경로와 `run_phase2_inference()` 추론 경로를 분리한다. 추론은 최신 training snapshot의 promoted model contract만 사용하며, cold-start bootstrap 상태를 추론 mode로 승격하지 않는다.
- **학습 산출물**:
  - `training_report.json`: 기존 report 계약 유지 + `supervised_gate`, `metadata.inference_contract`.
  - `leaderboard.json`: family × trial × preset row, metric/status/artifact/model_version/schema_hash 저장.
  - `promotion_decision.json`: promotion policy, family별 승격/탈락 사유, promoted models 저장.
- **promotion policy**: `best_per_family`를 기본으로 하며, eligible status, 최소 completed trial 수, family별 metric threshold, search diversity, failure ratio, registry requirement를 JSON으로 보존한다.
- **inference contract**: `promoted_versions` 하위 호환 키를 유지하면서 `model_versions.{model}.model_version`, `source_trial_variant`, `schema_hash`, `fixture_contract`를 추가한다.
- **산출 경로**: `{model_dir}/phase2_train/{report_id}/reports/` 아래 report/leaderboard/promotion decision을 저장하고, promoted family artifact target은 `data/companies/{company_id}/engagements/{year}/models/phase2_<family>/vNNNN/`로 표준화한다.
- **영향 범위**: `src/services/phase2_training_service.py`, `src/services/phase2_inference_service.py`, `src/services/phase2_leaderboard.py`, `src/services/phase2_promotion_policy.py`.
- **관련 산출물**: `artifacts/sprint_phaseA_A2_handoff_2026-05-17.md`.

### D054: Rule-based detector family promotion into PHASE2 contract (2026-05-17)
- **결정**: `timeseries`, `relational`, `duplicate`, `intercompany` rule-based detector를 PHASE2 train/inference family로 승격한다. 기본 active family는 `unsupervised` + 4 rule-style family이며, `supervised`, `transformer`, `sequence`, `stacking`은 dormant 상태로 유지한다.
- **사유**: 기존 rule detector가 PHASE1 rule panel과 pipeline track에만 남아 있으면 leaderboard, promotion decision, inference contract, provenance가 PHASE2 운영 계약에서 분리된다. A3는 detect logic을 바꾸지 않고 registration/promotion/artifact 계약만 통합한다.
- **정책**:
  - rule-style family는 `model_bundle.pt`를 재학습하거나 생성하지 않는다.
  - 승격 산출물은 `{model_dir}/phase2_<family>/vNNNN/calibration_metadata.json`에 calibration metadata로 저장한다.
  - `schema_hash`는 rule-style family에서 `null`을 허용한다.
  - leaderboard metric은 family별 이름을 쓰되, `metric_interpretation=rule_proxy_score`로 truth recall 해석을 금지한다.
  - `sequence` family의 D047 leakage guard는 BiLSTM/user-temporal track에만 적용하고, transaction-level `timeseries` burst detector에는 적용하지 않는다.
- **영향 범위**: `src/services/phase2_training_service.py`, `tests/modules/test_services/test_phase2_detector_expansion.py`, `tests/modules/test_services/test_phase2_training_service.py`, `docs/spec/DETECTION_RULES.md`.
- **관련 산출물**: `artifacts/sprint_phaseA_A3_handoff_2026-05-17.md`.

### D055: Intercompany IC01 accepts PHASE1 unmatched-reference sidecar evidence (2026-05-18)
> **Superseded by D065 (2026-05-23)** — IC01 sidecar 직접 의존 제거, evidence level 정책으로 재정의.
- **결정**: PHASE2 `intercompany` family의 IC01 `unmatched_intercompany`는 그룹 대사 결과뿐 아니라 PHASE1 case input의 `ic_unmatched_reference=True` evidence를 high-confidence unmatched IC evidence로 수용한다.
- **사유**: V7 fixed3 PHASE1 case input에는 IC 거래 자체(`counterparty_type=IntercompanyAffiliate`, `business_process=Intercompany`, `is_intercompany=True`)와 `ic_unmatched_reference` sidecar evidence가 존재하지만, matched-pair source document reference는 PHASE2 matcher의 `reference` grouping key로 전달되지 않는다. 기존 IC01은 그룹 대사만 보아 V7 fixed3 2022/2023/2024에서 0건이 되었고, sidecar unmatched evidence를 버렸다.
- **정책**:
  - `ic_unmatched_reference=True`는 IC01 unmatched reference evidence로만 반영한다.
  - IC02 amount mismatch와 IC03 timing gap은 matched-pair amount/date 대사에 필요한 pair reference가 있을 때만 산출한다.
  - 이 결정은 truth recall 개선 근거가 아니며, PHASE2 rule proxy score 입력 계약 보강이다.
  - UI는 `metric_confidence=sidecar_unmatched_reference_only`인 경우 IC01 active, IC02/IC03 zero-hit 상태를 숨기지 않는다.
- **영향 범위**: `src/detection/intercompany_rules.py`, `tests/modules/test_detection/test_intercompany_v7_fixed3_smoke.py`.
- **관련 산출물**: `artifacts/sprint_phaseA_diag1_intercompany_handoff_20260518.md`, `artifacts/phase2_inference_v7_fixed3_year_2024_intercompany_rerun.json`.


### D056: Duplicate detector candidate blocking for PHASE2 inference latency (2026-05-18)
- **결정**: PHASE2 `duplicate` family의 L2-03b/L2-03c/L2-03d는 full pair scan 대신 amount/date/gl-account blocking과 early guard를 사용한다. Fuzzy text comparison은 amount tolerance 후보에만 RapidFuzz를 적용하고, split detection은 date-window two-sum range, time-shift detection은 amount bucket + date sliding window로 제한한다.
- **사유**: V7 fixed3 2024 partition에서 duplicate inference가 83.66s로 Streamlit UI 진입 병목이 되었다. 동일 partition 최적화 후 3회 평균 2.744s, full V7 fixed3 1,032,864 rows 기준 3회 평균 4.533s를 기록했다.
- **정합성 정책**: L2-03a exact_duplicate_amount는 deterministic exact match로 유지한다. L2-03b/L2-03c/L2-03d는 Phase A smoke baseline 대비 ±5% 이내를 허용하지만, 이번 변경에서는 2024 기준 4개 sub-detector hit count가 모두 동일했다.
- **금지한 대안**: Sampling(C)은 사용하지 않는다. Truth recall은 최적화 정당화 근거로 사용하지 않는다.
- **영향 범위**: `src/detection/duplicate_rules.py`, `tests/modules/test_detection/test_duplicate_performance.py`.
- **관련 산출물**: `artifacts/sprint_phaseA_diag2_duplicate_optimization_handoff_20260518.md`, `artifacts/phase2_duplicate_perf_before_after_20260518.json`.

### D057: PHASE2 Streamlit 3-state family contract UI (2026-05-18)
- **결정**: Streamlit `Phase2 결과` 탭은 사용자-facing 상태를 `Not trained`, `Training report available`, `Inference complete` 세 가지로 표시한다. 학습 버튼은 `run_phase2_training_analysis()` 경로, 추론 버튼은 `run_phase2_inference_analysis()` 경로를 호출하며 같은 버튼으로 숨기지 않는다.
- **표시 계약**:
  - 9 family matrix는 active 5(`unsupervised`, `timeseries`, `relational`, `duplicate`, `intercompany`)와 dormant 4(`supervised`, `transformer`, `sequence`, `stacking`)를 항상 함께 표시한다.
  - rule-style family는 `metric_interpretation=rule_proxy_score`로 표시하고, truth recall/precision을 승격 또는 우선순위 사유로 쓰지 않는다.
  - `intercompany`는 Diag-1 meta contract에 따라 active family로 표시하되 `active, IC01 only`, `metric_confidence=sidecar_unmatched_reference_only`, IC02/IC03 carry-over zero-hit을 명시한다.
  - `leaderboard.json`과 `promotion_decision.json`은 latest training snapshot sidecar로 읽으며, rule-style family의 `schema_hash=null`은 정상 값으로 표시한다.
- **partition 정책**: UI partition selector는 `2022`, `2023`, `2024`, `전체` 네 옵션을 제공한다. 선택된 연도는 추론 실행 시 `fiscal_year` 필터로 적용하고, UI summary artifact도 동일 partition 형식으로 표시한다.
- **PHASE1 lock**: `dashboard/tab_phase1.py`, `dashboard/components/rule_panel.py`, `dashboard/tab_overview.py`는 본 UI sprint 범위에서 변경하지 않는다. PHASE2 UI는 PHASE1 `priority_score`와 `composite_sort_score`를 sort key로 변경하지 않고 별도 overlay/provenance 화면으로만 동작한다.
- **영향 범위**: `dashboard/tab_phase2.py`, `dashboard/components/phase2_family_matrix.py`, `dashboard/components/phase2_subdetector_grid.py`, `dashboard/components/phase2_leaderboard_view.py`, `src/services/phase2_inference_service.py`.
- **관련 산출물**: `artifacts/sprint_phaseB_a4_phase2_streamlit_handoff_20260518.md`.

### D063: PHASE2 rule-style training variant de-duplication and timing observability (2026-05-22)
- **결정**: PHASE2 rule-style family(`timeseries`, `relational`, `duplicate`, `intercompany`)는 training queue에서 `baseline_core` feature variant만 사용한다. 각 family의 search preset은 2개 그대로 유지해 promotion policy의 최소 completed/search diversity 조건을 만족한다.
- **사유**: rule-style detector 4종은 `_build_variant_frame()`에서 feature variant를 사용하지 않고 필요한 원천 컬럼이 포함된 `cleaned_df`를 사용한다. 여러 feature variant를 반복 실행하면 동일 입력에 대한 결정론적 trial만 중복 생성되어 latency만 증가한다.
- **관측성**: PHASE2 inference는 `phase2.redetect.*` 및 `phase2.inference.*` timing log를 남겨 detector 이후 aggregate, SHAP, report, overlay, persistence, session cache 비용을 분해 측정한다.
- **로그 정책**: `phase2_only` score aggregation에서 Phase 1 legacy track(`layer_a`, `layer_b`, `layer_c`, `benford`, `ml_supervised`) 누락은 expected missing으로 보고 debug 처리한다. 기본 Phase 1/일반 aggregation에서는 누락 warning을 유지한다.
- **영향 범위**: `src/services/phase2_training_service.py`, `src/services/phase2_inference_service.py`, `src/pipeline.py`, `src/detection/score_aggregator.py`, 관련 tests.

### D064: PHASE2 unsupervised preset 단일화 + epochs_half + policy 완화 (2026-05-23)
- **결정**: `_DEFAULT_SEARCH_PRESETS["unsupervised"]` 를 `balanced` 1개(`vae_epochs=20`)로 축소하고, `_build_promotion_policy.family_min_search_variants["unsupervised"]` 를 1로 완화한다. 다른 family(timeseries/relational/duplicate/intercompany)의 preset 2개와 search_variants=2 정책은 그대로 유지한다.
- **사유**: 100k sample 3 시나리오 측정(2026-05-23) 결과:
    - baseline(3 preset × 7 variant = 21 trial, 1241s) vs epochs_half(epochs 10/20/30, 21 trial, 770s) vs preset_balanced_only(1 preset × 7 variant = 7 trial, 478s)
    - 세 시나리오의 `unsupervised_selection_score` 최고치는 모두 0.547~0.548 (편차 ±0.0003, noise 수준).
    - `unsupervised_selection_score` 는 score_tail_gap + topk_stability + capacity_penalty 의 ranking proxy 라 epoch/preset variant 의 차이가 metric 에 의미 있게 반영되지 않는다.
- **효과**: 1M rows 학습 ~955s → ~250s 추정(-74%). feature variant 7개는 유지 → search diversity 보존.
- **품질 영향**: `feedback_phase1_truth_recall_guard` 위반 없음. metric 차이가 noise 수준이라 truth recall 추구가 아닌 ranking-proxy 안정성 기반 결정.
- **영향 범위**: `src/services/phase2_training_service.py`, `tests/modules/test_services/test_phase2_training_service.py`.
- **관련 산출물**: `tools/scripts/measure_phase2_scenarios.py` (3 시나리오 측정 스크립트), 측정 데이터는 `tools/scripts/measure_phase2_scenarios.py` 재실행으로 재현 가능.

### D065: IC01 sidecar 직접 의존 제거 + evidence level 정책 재정의 (2026-05-23, supersedes D055)
- **결정**:
  - `ic_unmatched_reference` sidecar 의 IC01 score 직접 의존을 제거한다. IC01 은 group matching 결과 + `related_party_master` (또는 dataset distinct `company_code` 폴백) 대사 기반으로 재정의한다.
  - evidence level sidecar 부착: `ic01_evidence_level` ∈ {`"high"`, `"review"`, `""`}, `ic01_review_reason` ∈ {`"missing_partner"`, `"nonstandard_format"`, `"mapping_uncertain"`, `""`}.
  - 외부 rule id `IC01` 단일을 유지한다. `RULE_CODES` / `SEVERITY_MAP` / `RULE_DETAIL_METADATA_REGISTRY` / dashboard / metrics 표시 맵은 변경하지 않는다.
- **사유**:
  - **Fitting 증거**: `src/detection/intercompany_rules.py:354` 의 `partner.str.endswith("-UNMATCHED")` 휴리스틱이 `tools/scripts/build_datasynth_v38_ic_exception_labels.py:316` 의 `f"C{n}-UNMATCHED"` patch signature 와 직접 매칭. 메모리 `feedback_phase1_truth_recall_guard` 의 "PHASE1 변경은 도메인 정합성으로만 정당화. truth recall 직접 추구 금지" 정면 위반.
  - **Label leakage**: `ic_unmatched_reference` sidecar 가 DataSynth v38 라벨 산출물에서 흘러와 row 단위로 부착되고 detector score 의 fallback 경로로 사용된다 (`src/detection/intercompany_rules.py:332~340`). detector score 에 직접 반영하면 평가 leakage 가 발생한다.
  - **도메인 정합 재정렬**: IFRS 10 §B86 (그룹 내부거래 전부 제거), K-IFRS 1110 (연결재무제표 작성 시 내부거래 제거 절차), K-IFRS 1024 §18 (특수관계자 공시), KICPA Issue Paper 46 (JET 완전성), ISA 600 (그룹감사 구성단위 잔액 대사) 으로 1차 근거를 재정렬. ISA 550 §23 은 특수관계자 거래의 "사업상 합리성" 평가로 범위가 다르므로 보조 근거로만 유지.
- **정책**:
  - `score_aggregator._apply_intercompany_exception_corroboration()` 의 floor 정책:
    - evidence=`high` 만 Medium floor (`RISK_THRESHOLDS[MEDIUM]=0.40`) 자격.
    - evidence=`review` 는 Low floor (`RISK_THRESHOLDS[LOW]=0.20`).
    - IC02 / IC03 단독 → Low floor (기존 유지).
    - 2 개 이상 IC 예외 결합 → Medium floor (기존 유지).
  - `SEVERITY_MAP` 변경 없음 (`IC01=3, IC02=2, IC03=2`, `src/detection/constants.py:195`).
  - `intercompany_exception_reasons` 문자열에 IC01 hit 시 `IC01[high]` / `IC01[review]` qualifier 부착. base rule id 는 `IC01` 단일 유지.
  - `config/audit_rules.yaml::patterns.intercompany` 의 신규 키:
    - `related_party_master`: 명시적 관계사 리스트. 빈 리스트 / 미지정 시 dataset distinct `company_code` 폴백.
    - `partner_format`: `ic_partner_regex`, `customer_partner_regex`, `vendor_partner_regex` regex 정책. customer / vendor 코드는 IC 모집단에서 제외.
  - `config/settings.py` 의 신규 옵션: `ic_use_related_party_master: bool = True`, `ic_period_boundary_days: int = 5`.
  - `ic_unmatched_reference` sidecar 자체는 평가 / 리포트 read-only 비교용으로 유지 가능. detector score 에서는 사용하지 않는다.
  - **Sidecar 저장 위치**: 두 sidecar column (`ic01_evidence_level`, `ic01_review_reason`) 은 `DetectionResult.metadata["row_sidecar"]: dict[str, pd.Series]` 에 보관한다. `DetectionResult.details` 는 numeric rule-score (IC01/IC02/IC03 `float64`) matrix 계약을 유지하여 `src/metrics/ground_truth_evaluator.py:1152, 1537` 및 `src/detection/score_aggregator.py::_collect_flagged_rules` 의 `> 0` 비교에서 TypeError 가 발생하지 않도록 한다.
  - **Review-only 신호의 confirmed 격상 방지**: IC01 review-level (`ic01_evidence_level == "review"`) 은 `details["IC01"]` score 가 `0.0` 으로 유지된다. 따라서 `flagged_rules` / case seed / ground-truth 평가에서 confirmed violation 으로 격상되지 않는다. `score_aggregator._apply_intercompany_exception_corroboration()` 는 `metadata["row_sidecar"]` 에서 evidence level 을 read 하여 row-level `anomaly_score` 의 Low floor (0.20) 만 부여한다. 근거: `AGENTS.md` "review-only signals must not become confirmed violations".
  - **PHASE2 overlay 표시 계약**: IC01 review-only 는 `phase2_family_scores` / family nonzero hit 에는 더하지 않는다. 대신 case overlay 의 `family_contributions[].review_only_count` / `review_reasons` 와 `family_review_only` 메타로 보존하고, `intercompany` lane 에서 확인 가능하게 한다. 이 메타는 `top_family`, `coverage_breadth_q95`, `phase2_review_band` 를 승격하지 않는다.
- **영향 범위**:
  - `src/detection/intercompany_rules.py::ic01_unmatched_intercompany` — `(score, evidence_level, review_reason)` 튜플 반환. review 분기는 `score=0.0`, high 만 `score=1.0`. evidence_level/review_reason 는 high/review/"" 그대로 산출.
  - `src/detection/intercompany_matcher.py::_build_result` — `details` 는 numeric rule-score (IC01/IC02/IC03 float64) 만 유지. 두 sidecar series 는 `DetectionResult.metadata["row_sidecar"]: dict[str, pd.Series]` 로 부착.
  - `src/detection/score_aggregator.py::_extract_ic01_evidence_level` — `metadata["row_sidecar"]["ic01_evidence_level"]` 에서 read. 구버전 details fallback 도 지원.
  - `src/detection/score_aggregator.py:1001~1110` — `_apply_intercompany_exception_corroboration()` 재구성
  - `src/services/phase2_case_family_aggregator.py`, `src/services/phase2_case_contract.py`, `src/services/phase2_lane_sort.py`, `dashboard/components/phase2_family_lanes.py` — IC01 review-only sidecar 를 case overlay/lane 메타로 전달하되 score/family hit 집계는 유지.
  - `config/audit_rules.yaml:309~` — `patterns.intercompany` 신규 키 (`related_party_master`, `partner_format`)
  - `config/settings.py:198~199` — `ic_use_related_party_master`, `ic_period_boundary_days` 신규 옵션
  - `tools/scripts/build_datasynth_v38_ic_exception_labels.py` — P4 에서 `-UNMATCHED` patch 제거 예정
  - `docs/spec/DETECTION_RULES.md` — L3-03 절 evidence level sidecar 정책 표 + IFRS / K-IFRS / ISA 600 근거 추가
  - `docs/spec/DETECTION_REFERENCE.md` — §2.5a IFRS 10 §B86 / §2.5b K-IFRS 1110 / §2.5c K-IFRS 1024 / §2.5d ISA 600 신규 절, §2.10 요약 표 행 추가
  - `docs/spec/RULE_DETAIL_METADATA_V1_LOCK.md` — IC01 evidence level sidecar 정책 절 신규 추가 (canonical 32 count 변경 없음)
  - `docs/archive/completed/PHASE1_TOPIC_SCORING_V1_LOCK.md` — 관계사·내부거래·순환구조 topic floor 차별 보조 절 추가 (Primary rules 본문 변경 없음) — **2026-06-14 주석**: 해당 topic은 PHASE1-2 family로 이관됨 (D072 참조). 본 항목은 D057 시점 영향 범위의 역사 기록으로 보존.
  - `docs/spec/PHASE1_RULE_RELATIONSHIP_MAP.md` — intercompany_structure evidence type 표 본문은 유지, evidence level sidecar 보조 주석 추가
  - `tests/modules/test_detection/test_intercompany_matcher.py`, `tests/modules/test_detection/test_score_aggregator.py` — fixture 갱신 (`ic01_evidence_level=["high"]` 등)
- **관련 산출물**:
  - `docs/archive/completed/ic-matcher-redesign/ic-matcher-redesign-plan.md`
  - `docs/archive/completed/ic-matcher-redesign/ic-matcher-redesign-context.md`
  - `docs/archive/completed/ic-matcher-redesign/ic-matcher-redesign-tasks.md`

### D058: PHASE1+PHASE2 통합 큐에 Reciprocal Rank Fusion (RRF) 적용 + 3개 큐 분리 (2026-05-18, 2026-05-19 갱신)
- **현재 결정**: review queue 를 `PHASE1 단독`, `PHASE2 단독`, `통합` 3개로 분리한다. 통합 큐의 최종 정렬식은 Reciprocal Rank Fusion(RRF) 이며 `k=60` 으로 고정한다. 단, PHASE2 내부 family 는 RRF voter 로 직접 넣지 않고 zero-preserving ECDF 기반 Noisy-OR 로 먼저 `phase2_internal_noisy_or` 단일 voter 로 결합한다.
  - RRF 식: `RRF_score(case) = Σ 1/(k + rank_i)`.
  - `rank_i` 는 `phase1_composite`, `phase2_internal_noisy_or` 2개 ranker다.
  - `phase1_composite` 는 `phase1_composite_sort_score` 내림차순 rank(method="min"), `phase2_internal_noisy_or` 는 5-family Noisy-OR score 내림차순 rank. PHASE2 score 가 없는 family row 는 Noisy-OR 내부에서 0/NaN 무신호로 보존한다.
  - 통합 큐 정렬: `rrf_score` 내림차순 1차, `phase1_composite_sort_score` 내림차순 tiebreak.
- **2026-05-19 갱신**:
  - PHASE2 active family 5개(`unsupervised`, `timeseries`, `relational`, `duplicate`, `intercompany`)를 직접 RRF ranker 로 넣는 5-way/hierarchical RRF 는 V7 fixed3 측정에서 reject.
  - 낮은 family 간 상관은 "결합 가능성" 근거이지 "동등 voter" 근거가 아니므로, 5 family 는 Noisy-OR 단일 PHASE2 voter 로 결합한다.
  - `intercompany`는 near-dormant family이며 0/NaN row 는 Noisy-OR 에 0 contribution 으로 들어간다.
- **사유**:
  - PHASE1 ↔ PHASE2 상관계수 +0.07/-0.23 (사실상 독립). 두 신호의 union recall(상위 1% 합집합) 이 단독보다 6%p 이상 크다.
  - PHASE2 family 간 score 상관도 낮아 family signal 의 보완성은 인정되지만, score 형태가 연속/이산/희소로 달라 동일 RRF voter 로 취급하지 않는다.
  - RRF 는 Microsoft Azure AI Search / OpenSearch 2.19 / Elasticsearch / Vespa / Weaviate / MongoDB 의 hybrid search 표준이며 학술 근거(Cormack, Clarke, Büttcher, SIGIR 2009)가 견고하다.
  - `k=60` 은 위 산업 표준 default. truth label 로 grid search 하지 않아 [[feedback_phase1_truth_recall_guard]] 위반 위험 0.
- **V1 lock 정책**:
  - PHASE1 단독 큐(`queue_phase1.parquet`)는 기존 `composite_sort_score` V1 lock 정렬을 그대로 유지. `queue.parquet`/`queue_top500.parquet`/`queue_top100.parquet` 는 PHASE1 단독 큐의 별칭(legacy 호환).
  - PHASE1 priority_score, composite_sort_score 값 변경 금지. RRF 는 별도 컬럼(`rrf_score`, `rrf_rank`)에만 적재.
- **UI 정책**:
  - Streamlit review queue 탭은 3 sub-tab: `통합 큐`(기본 활성) · `PHASE1 우선` · `PHASE2 우선`. 기존 historical `Narrator 분석` sub-tab은 active product path에서 제거되었다 (D068).
  - 알고리즘 명칭(RRF, k=60)은 본문에 노출하지 않고 tooltip help 에만 표기.
  - 메인 KPI 는 doc 단위(truth 라벨이 있는 합성 데이터에서만 표시), case 단위 수치는 보조 라인.
- **영향 범위**: `src/services/queue_fusion.py`(신규), `tools/scripts/phase1_phase2_integration_stage7.py`, `dashboard/tab_review_queue.py`, `dashboard/components/review_queue_browser.py`(신규).
- **관련 결정**: [TS-12](TROUBLESHOOT.md#ts-12-phase2-점수가-통합-정렬에-미반영--truth-case-분모-인플레이션) §6.1 (수정 방향 확정).
- **재현 metric (V7 fixed3, queue_integrated.parquet, informational only — `feedback_phase1_truth_recall_guard` 준수)**:
  | TOP N | legacy PHASE1+VAE 2-way RRF | Noisy-OR voter | Δ pp |
  |---|---:|---:|---:|
  | 100 | 16.77% (104) | **22.42% (139)** | **+5.65** |
  | 500 | 43.23% (268) | **45.48% (282)** | **+2.26** |
  | 1,000 | **53.71% (333)** | 49.68% (308) | **-4.03** |
  | 2,000 | **63.55% (394)** | 59.68% (370) | **-3.87** |

  Noisy-OR voter 는 **단조 우월 아니다.** TOP 100/500 에서 +5.65/+2.26pp 개선, TOP 1,000/2,000 에서 -4.03/-3.87pp 손실. TOP 100~2,000 평균 Δ ≈ 0pp 로 **종합 truth recall 동률**. 분포가 상단으로 재배치된 형태이며, 채택은 truth recall 개선이 아니라 단일 PHASE2 voter + 무신호 보존 + parameter 0개 architecture standardization 으로 정당화한다. 산출물: `artifacts/phase1_phase2_integration_report_noisy_or_20260519.{json,md}`.

### D059: Tritscher ERP-Fraud external shadow benchmark policy (2026-05-19)
- **결정**: Tritscher ERP-Fraud 공개 데이터셋은 PHASE2 `unsupervised` family의 외부 synthetic ERP shadow benchmark로만 사용한다. 이 결과는 active VAE의 보조 일반화 근거이며, supervised/transformer/sequence/stacking dormant family 활성화 근거로 사용하지 않는다.
- **검증 결과**:
  - Tritscher row-level VAE 평균 AUROC: 0.6521.
  - Tritscher document-level VAE 평균 AUROC: 0.8670.
  - Tritscher document recall@100 평균: 0.4375.
  - 빠른 진단용 IsolationForest 대비 VAE가 document-level에서 우세했다. document AUROC 0.8670 vs 0.7948, document recall@100 0.4375 vs 0.1815.
- **해석**:
  - 외부 SAP ERP simulation에서도 document-level ranking은 의미 있게 유지된다.
  - row-level ranking은 불안정하므로 PHASE2 운영 해석은 document-prioritized evidence가 맞다.
  - Tritscher도 synthetic simulation이므로 실데이터 운영 성능이나 지도학습 일반화 성능을 보장하지 않는다.
- **정책**:
  - `Label`, `source_file`, `run_id`는 feature deny. `run_id`는 holdout boundary로만 사용한다.
  - VAE shadow 학습은 `Label == NonFraud`인 non-holdout run rows만 사용한다.
  - 산출물은 외부 검증 artifact로 보존하되 promotion gate를 자동 통과시키지 않는다.
  - supervised track은 D052의 label gate와 real/golden trusted positive 조건이 충족될 때까지 `low_signal_fallback`/dormant 상태를 유지한다.
- **관련 산출물**:
  - `artifacts/external_validation/tritscher_erp_fraud_20260519/tritscher_vae_shadow_benchmark.md`
  - `artifacts/external_validation/tritscher_erp_fraud_20260519/tritscher_shadow_benchmark_comparison.md`
  - `artifacts/external_validation/tritscher_erp_fraud_20260519/phase2_external_shadow_summary.md`
- **관련 결정**: D052(Supervised ML label gate hardening), D054(Rule-based detector family promotion), D058(RRF integration).

### D060: PHASE1 priority_score 0.90 critical 승격 원칙 5조 잠금 (2026-05-20)
- **결정**: `config/phase1_case.yaml` 의 `priority_floors` 에서 `min_priority_score: 0.90` 인 entry 의 신설/유지 조건은 다음 5조를 모두 만족해야 한다.
  1. **강한 seed 1개** — primary rule 의 raw_score 가 medium 이상 또는 명시적 escalated label
  2. **금액성/중요성 1개** — L4-03 또는 materiality 임계 초과 또는 escalated_materiality 라벨
  3. **독립 보강근거 1개** — timing/manual/SoD/duplicate 중 seed/금액성과 다른 축 1개
  4. **단독 금지** — macro-only / manual-only / timing-only / approval-only / sensitive-only 단독으로는 0.90 진입 불가
  5. **건수 목표로 조건 재조정 금지** — count 가 목표 범위 밖이어도 도메인적으로 타당하면 entry 유지. count 보고 조건을 조이거나 푸는 행위는 fitting 으로 간주한다.
- **fraud scenario 표시명 격하 원칙**: 내부 tag 는 fraud scenario 명 (예: `embezzlement_concealment`, `fictitious_entry`) 을 유지해도 되나 UI/export/LLM 노출 시 단정형 (`횡령 은폐`, `가공 거래`, `대형 자금 유용 사례`) 사용 금지. "검토 신호 / 결합 리스크" 형태로 격하한다. 직접 fraud scenario 명칭 노출은 자금성 계정 / vendor·employee / bank·payment 같은 직접 증거가 있을 때만 허용.
- **사유**: PHASE1 priority_score 분포 튜닝 중 "0.90+ 100~200건 목표" 라는 count 기반 의사결정이 0.80~0.89 분석 → 조건 재설계 흐름을 통해 fitting 패턴으로 흐른 사례 (Stage 2 prep 단계) 가 있었다. `scripts/fitting_audit.py` 측정에서 (a) stage_1 의 0.80~0.89 band 가 단일 floor 인공물 (100% 매칭), (b) 4종 critical 의 94~100% overlap, (c) 도메인 조건 매칭 case 의 ~16% 만 진입하는 자기 floor 의존성 확인. 본 원칙은 향후 priority_floors 신규 entry 신설 시 fitting 회피선이다.
- **영향 범위**: `config/phase1_case.yaml::priority_floors`, `src/detection/phase1_case_builder.py::_apply_priority_floors`, `docs/archive/completed/PHASE1_SCORE_DISTRIBUTION_LOG.md`, Stage 2-A/2-B 신규 entry 설계.
- **관련 산출물**:
  - `docs/archive/completed/PHASE1_SCORE_DISTRIBUTION_LOG.md`
  - `scripts/fitting_audit.py`
  - `scripts/simulate_stage1_priority_score.py` (Stage 1 복원 근사용)
- **관련 결정**: D055(IC01 sidecar evidence), D058(RRF integration).

### D061: Stage 2-A/2-B 보류 + priority_score 계층 재설계 방향 (2026-05-21)
- **결정**: `config/phase1_case.yaml` 의 `priority_floors` 에 `approval_bypass_critical` + `period_end_adjustment_critical` 0.90 entry 7종을 신설하려던 Stage 2-A 작업을 **보류**한다. 신설 yaml entry 와 `_priority_floor_corroboration_match` 의 `required_rules_any` 지원 모두 roll back. Stage 1 종료 상태 (`priority_score = max(topic, priority_score_pre_macro)`) 로 복귀하며 0.90+ = fy2022 21건 / fy2023 23건 유지. Stage 2-B (outflow/duplicate + revenue/manual critical) 도 동일 이유로 보류한다.
- **사유**: `scripts/simulate_stage2_critical.py` 측정 결과 D060 5조 원칙 정합 entry 인데도 fy2022 1,043건 / fy2023 1,130건 promote — `period_end_adjustment_critical` 만 950~1,022건. 조건을 좁혀 count 를 100~200 으로 맞추면 D060 5조 5번 ("건수 목표로 조건 재조정 금지") 위반. 본질 문제는 critical 정의가 아니라 priority_score 계층이 0.75/0.90 2단계만 도메인 의미를 가지고 0.80/0.85 는 단일 floor 인공물이라는 점이다. 4,000건 검토대상을 의미있게 세분화하려면 계층 재설계 필요.
- **`approval_bypass_critical` / `period_end_adjustment_critical` 결합 신호의 후속 활용**: 즉시검토 floor 가 아니라 **검토대상 상단의 정렬/필터 축**으로 이관. UI 작업에서 이 결합 신호를 가진 case 를 상위 정렬·필터하는 보조 차원으로 활용.
- **다음 작업 — priority_score 계층 재설계**: 0.90 즉시검토 (20~50건, 도메인 정합) / 0.85 상위 검토대상·supervisor review (100~300건) / 0.80 검토대상 상단 (500~1,000건) / 0.75 일반 검토대상 (수천 건) 의 4단 계층을 priority_floors 의 다단계 entry 로 구현. 본 작업은 별도 Stage (Stage 5) 로 분리하며 D060 5조 (특히 5번 count 재조정 금지) 정신을 유지한다.
- **fraud scenario 단정형 명칭 처리**: D060 의 표시명 격하 원칙은 본 결정과 독립. `embezzlement_concealment` / `fictitious_entry` 같은 단정형의 UI/export/LLM 격하는 Stage 4 UI 작업에서 진행.
- **영향 범위**: `config/phase1_case.yaml::priority_floors` (7 entry 제거), `src/detection/phase1_case_builder.py::_priority_floor_corroboration_match` (required_rules_any 제거), `tests/modules/test_detection/test_phase1_case_builder_stage2.py` (삭제).
- **보존 산출물**: `scripts/simulate_stage2_critical.py`, `scripts/analyze_stage2_candidates.py`, `scripts/fitting_audit.py` 는 향후 priority_score 계층 재설계 시 검증 도구로 재사용.
- **관련 산출물**:
  - `docs/archive/completed/PHASE1_SCORE_DISTRIBUTION_LOG.md` Stage 2-A/2-B 섹션
  - `scripts/simulate_stage2_critical.py` 측정 결과 (fy2022/fy2023 시뮬레이션)
- **관련 결정**: D060 (priority_score 0.90 critical 승격 원칙 5조).

### D062: PHASE2/PHASE1+2 통합 3등급 분류 정책 (2026-05-21)
- **결정**: PHASE2 단독 큐와 PHASE1+2 통합 큐의 표시 등급을 PHASE1 과 같은 3등급 (즉시검토 / 검토대상 / 후보 / 신호없음) 으로 통일한다. 점수 임계 기반 분류 대신 **subdetector tier (yaml 도메인 잠금) + coverage_breadth_q95 (다중 family 동의) + ml_only ECDF** 결합 정책을 사용한다.

#### PHASE2 단독 등급 (v2 채택)

```
즉시검토:
  max_evidence_tier == "strong" AND coverage_breadth_q95 >= 2

검토대상:
  max_evidence_tier == "strong" AND coverage_breadth_q95 < 2
  OR (max_evidence_tier == "moderate" AND coverage_breadth_q95 >= 2)
  OR (max_evidence_tier == "ml_quantile" AND family in ml_only_families
      AND max_family_ecdf >= 0.995 AND coverage_breadth_q95 >= 2)

후보:
  phase2_noisy_or > 0 AND 위 조건 미달

신호없음:
  phase2_noisy_or == 0
```

`ml_only_families` 는 `unsupervised` (VAE) 만 포함. 단정 fraud scenario 명칭 (`embezzlement_concealment`, `fictitious_entry`) UI/export/LLM 직접 노출 금지 (D060 격하 원칙 정합).

#### PHASE1+2 통합 등급 — "max band 취하되 즉시검토만 교집합"

```
통합 즉시검토:
  PHASE1 즉시검토 AND PHASE2 즉시검토              (양측 모두 통과)

통합 검토대상:
  PHASE1 즉시검토
  OR PHASE2 즉시검토
  OR PHASE1 검토대상
  OR PHASE2 검토대상                              (max band)

통합 후보:
  PHASE1 후보 OR PHASE2 후보

통합 신호없음:
  양측 모두 신호없음
```

즉시검토만 교집합으로 보수적 정의 (양측 도메인 잠금 모두 통과). 그 외 등급은 max band — PHASE1 검토대상이 PHASE2 신호없음 만으로 통합 후보로 격하되지 않도록 안전망.

#### 신규 필드 (band 만, 가상 점수 신설 없음)

```
phase1_review_band    # 기존 priority_band 표시 alias
phase2_review_band    # 신규
phase12_review_band   # 신규
```

`phase2_review_score` / `phase12_review_score` 같은 가상 점수는 신설 안 함 — band 만 도입. 표시/필터/KPI/badge 용도. **정렬 키 변경 금지**:
- PHASE1 단독 큐: `priority_band → composite_sort_score → priority_score → ...` (기존)
- PHASE2 단독 큐: `primary_rrf_score → coverage_breadth_q95 → strong_count → ...` (기존 ladder)
- 통합 큐: `final_rrf_score = 1/(60+rank_P1) + 1/(60+rank_P2)` (기존 RRF)

#### UI 표시 정책 (P2-C, 2026-05-21)

- PHASE2 결과 탭 KPI는 `phase2_review_band` 기준의 `즉시검토 / 검토대상 / 후보`를 표시한다. `strong tier` raw count 자체를 즉시검토로 노출하지 않는다.
- 통합 Review Queue 표는 `통합 등급 → PHASE1 등급 → PHASE2 등급`을 먼저 보여주고, 정렬 점수 컬럼은 본문 기본 표에서 숨긴다.

- 정렬 알고리즘명(`RRF`, `k=60`, `Noisy-OR`)은 사용자 본문에 노출하지 않고 감사인 검토 언어로 설명한다.
- 합성 truth 검증 KPI는 "부정 발견"이 아니라 "검증 라벨 매칭"으로 표시한다. 운영 UI에서 fraud scenario 단정 표현을 쓰지 않는다.
- `dashboard/tab_phase1.py` 와 `dashboard/tab_overview.py` 는 본 UI 변경 범위에서 제외해 PHASE1/전체개요 표시 계약을 보존한다.

#### Fitting 회피 (D060 5조 정합)

1. **강한 seed**: strong tier 는 `subdetector_tiers.yaml` 의 도메인 잠금 — 변경 X.
2. **중요성/금액성**: 통합 단계에서 PHASE1 의 L4-03 floor / materiality 가 자동 반영.
3. **독립 보강**: `coverage_breadth_q95 >= 2` 가 다중 family 동의를 강제.
4. **단독 금지**: weak / moderate 단독 / ml_quantile 단독 / 단순 ECDF / 단순 coverage 즉시검토 진입 불가. strong tier 는 yaml 도메인 잠금이라 본 원칙 적용 대상이 아니지만, 즉시검토는 coverage>=2 까지 강제하여 한 번 더 안전망 적용.
5. **count 보고 재조정 금지**: yaml 임계 (`coverage_breadth_q95 >= 2`, `ml_only_families`, `min_max_family_ecdf: 0.995`) 는 yaml 잠금 — 측정 후 결과 보고 변경 금지.

#### 사유

- v3 안 (strong 단독 즉시검토 + max(P1, P2) 통합) 은 PHASE1 Stage 2-A 가 fitting 으로 폭증한 패턴과 동일 위험 ("도메인상 맞아 보여도 모집단에서 흔하면 즉시검토 폭증") 을 재현할 가능성. v2 안 (strong + coverage>=2 + 통합 교집합) 이 보수적이고 TS-15 학습 정합.
- PHASE2 raw family score (`phase2_internal_noisy_or` 등) 의 절대값은 데이터 분포 의존이라 도메인 의미가 약함. 점수 임계 기반 분류 대신 yaml 잠금된 tier + coverage 결합 정책이 fitting 회피에 안전.

#### 영향 범위

- `config/phase2_review_band.yaml` (신규)
- `src/services/phase2_case_contract.py::Phase2CaseOverlay` (필드 추가) + `classify_phase2_review_band` helper 신규
- 통합 build 위치 (`queue_fusion.py` 또는 동등) — `phase12_review_band` 컬럼 추가 (정렬식 변경 X)
- `dashboard/tab_phase1.py` / `tab_phase2.py` / 통합 review queue 탭 — UI 라벨 통일 ("즉시검토 / 검토대상 / 후보"), 알고리즘명 (RRF, k=60, noisy-or) 본문 노출 금지
- `docs/guide/users/08_PHASE2_FAMILY_STRUCTURE.md` / `09_REVIEW_QUEUE_RRF_FUSION.md` 분류 정책 추가
- `docs/spec/CONSTRAINTS.md` PHASE2 band fitting 회피 정책 추가
- `docs/spec/TROUBLESHOOT.md` TS-16 신규

#### 관련 산출물

- `config/phase2_review_band.yaml`
- `docs/archive/completed/PHASE1_SCORE_DISTRIBUTION_LOG.md` 후속편 또는 PHASE2 별도 로그
- `src/services/subdetector_tiers.py` (strong/moderate/weak/ml_quantile tier 정의)
- `docs/spec/TROUBLESHOOT.md` TS-16 (Stage7 cache 측정 한계와 운영 경로 분리)

#### 관련 결정

- D058 (PHASE1+PHASE2 통합 큐 RRF) — 본 결정은 D058 의 정렬 정책을 변경하지 않고 band 표시만 추가.
- D060 (PHASE1 priority_score 0.90 critical 승격 5조) — PHASE2 분류에 동일 5조 정신 적용.
- D061 (Stage 2-A 보류 + priority_score 계층 재설계) — 본 결정의 v2 채택 사유 (count 폭증 회피).

### D066: IC02 tolerance 및 cross-currency 가드 재보정 (2026-05-23)

- **결정**: IC02 기본 금액 허용 오차를 `0.02` 에서 `0.05` 로 상향한다. `currency` 는 IC 그룹 매칭 키에서 제외해 통화가 다른 관계사 쌍도 대응 관계 자체는 인식하되, 명시 통화 불일치 또는 금액비 `20x` 초과 쌍은 `cross_currency=True` 로 표시하고 IC02 점수를 억제한다.
- **사유**: IC02는 관계사 양측 금액이 비교 가능한 경우의 대사 예외다. FX 환산표나 기준환율이 없는 상태에서 통화가 다른 금액을 직접 비교하면 정상 관계사 pair가 금액 불일치 후보로 과대 유입된다. 통화 차이는 미대사(IC01)가 아니라 비교 불가/FX 확인 사유로 분리한다.
- **운영 의미**: `IC02`는 계속 금액 불일치 검토 후보이며 단독 Low floor 정책은 유지한다. 다만 cross-currency 쌍은 IC02 high-confidence 금액 차이로 보지 않고 후속 FX/환산 기준 확인 대상으로 남긴다.
- **영향 범위**: `src/detection/intercompany_rules.py::match_ic_groups`, `ic02_amount_mismatch`, `src/services/phase2_training_service.py` intercompany search presets, `config/settings.py::ic_amount_tolerance`, `ic_cross_currency_ratio_threshold`, `tests/modules/test_detection/test_intercompany_matcher.py`.

---

### D067: PHASE3 selected PHASE1 case brief integration (2026-05-26)
- **Status**: Superseded by D068. Historical only.
- **Historical decision**: PHASE3 LLM narrative의 운영 위치를 `Phase 1 -> 검토 케이스` drilldown의 단일 selected case로 고정하는 방안을 기록했다.
- **현재 해석**: selected-case AI memo와 LLM narrative는 active product path에서 제거되었다. PHASE1 selected case 화면은 외부 LLM 호출 없이 Local Evidence Brief만 사용할 수 있다.
- **대체**: `docs/spec/LOCAL_FIRST_EVIDENCE_POLICY.md`의 Local Evidence Brief.

### D068: PHASE3 LLM Narrator 제거 및 Local Evidence Brief 전환 (2026-05-26)
- **Decision**: PHASE3 LLM Narrator, LLM-based reranking, AI review memo, Text-to-SQL/rule-feedback LLM 기능을 active product path에서 제거한다.
- **Reason**: 이 프로젝트는 local-first ledger analytics assistant다. 원장/전표/작성자/승인자/거래처/적요/룰 히트 근거를 외부 LLM API로 전송하는 것은 제품 신뢰 경계와 충돌한다.
- **Replacement**: PHASE1 selected case 화면에는 필요한 경우 Local Evidence Brief를 둔다. 이는 기존 PHASE1 rule evidence, review_focus, recommended_audit_actions, PHASE2 family lane signal을 deterministic template으로 요약한다.
- **Non-scope**: PHASE1 scoring, PHASE2 detector, PHASE2 family lane ranking, DataSynth는 변경하지 않는다.
- **Policy**: LLM/OpenAI references may remain only as historical/deprecated documentation, not as active capability.
- **Single source**: [LOCAL_FIRST_EVIDENCE_POLICY.md](LOCAL_FIRST_EVIDENCE_POLICY.md), [PHASE3_REVIEW_NARRATOR_SPEC.md](../archive/abandoned/PHASE3_REVIEW_NARRATOR_SPEC.md).

### D069: PHASE2 row_ref_map sidecar optional manifest contract (2026-05-28)

- **Decision**: `phase2_case_store` schema `1.1` introduces explicit
  `row_ref_map_status` with values `generated` or `omitted`. The default save path
  remains `generated` for backward compatibility. Callers may opt into
  `write_row_ref_map=False`; then `row_ref_map_hash=null` and load succeeds without
  `row_ref_map.jsonl`.
- **Compatibility**: schema `1.0` artifacts remain supported and are interpreted as
  `row_ref_map_status=generated`. Missing or tampered sidecar files still fail for
  generated manifests. Only schema `1.1` manifests that explicitly declare `omitted`
  bypass sidecar integrity checks.
- **Reason**: S6.next Phase 1/2 moved PHASE1-PHASE2 linking to hit-hash direct matching
  (`canonical_label_hash`, `doc_id_hash`, `line_number_key`, `company_code_hash`) with
  row_ref_map only as a legacy fallback. Store-level deprecation must be explicit so old
  artifacts do not silently lose their fallback integrity guard.
- **Non-scope**: This does not anonymize family jsonl payloads; those still contain raw
  `row_refs` fields by design for auditor UI/debugging. External distribution still
  requires a separate anonymized export contract.

### D070: Duplicate S0 운영 KPI 재프레이밍 (2026-06-01)

- **Decision**: PHASE2 duplicate 성능 판단은 단일 TOP500 recall 점수 개선이 아니라
  `normal_sample_300` native duplicate false-positive rate와 n=19 recall confidence
  band를 함께 보고한다.
- **Current measurement**: 정상 FP는 0 native duplicate cases / 300 normal documents
  = 0.0%. Duplicate primary TOP500 recall은 8/19 = 42.1053%이며, ±1문서 band는
  7/19 = 36.8421% ~ 9/19 = 47.3684%다.
- **Reason**: duplicate primary denominator는 19문서라 1건 이동이 5.3%p다. 이전
  duplicate native quality 진단은 row score recall 부족이 아니라 정상 반복 exact
  duplicate가 TOP500 surface를 점유하는 base-rate/precision 병목을 확인했다.
- **Guardrail**: truth/owner metadata는 denominator 및 평가 join에만 사용한다.
  selector, gate, rank, threshold, PHASE1 ranking, PHASE2 fusion에는 사용하지 않는다.
- **Non-scope**: S2 정상-반복 억제 신호 연결, S3 retention/ranking 정책 변경,
  sidecar probe 추가, 합성 점수 튜닝은 S1 DataSynth duplicate 현실화 및 baseline
  재측정 전에는 수행하지 않는다.
- **Source**:
  `tools/scripts/measure_phase2_family_responsibility_recall_v33d_fixed5_ownermeta_v33d_20260601.py`,
  `artifacts/phase2_family_responsibility_recall_v33d_fixed5_ownermeta_v33d_20260601.json`,
  `docs/debugging.md` Duplicate S0 기록.

### D071: PHASE1 점수체계 tier 전환 — 가중합·floor·band 컷 폐기 (2026-06-14)
- **결정**: PHASE1 case 우선순위를 가중합 점수식(`0.62·max_primary + 0.08·secondary + …`)·floor 숫자값(`0.75`/`0.60`/`0.45`)·band 컷(`high≥0.90`/`medium≥0.75`)으로 줄세우는 방식을 폐기한다. 이들은 근거 없는 숫자 정밀도(false precision)다. 대신 근거 있는 트리거 조건에서 **명명된 결정규칙(tier: 순서형 HIGH / MEDIUM / LOW / CONTEXT)**으로 직접 매핑한다.
- **tier 정의**: tier는 "판정"이 아니라 review queue 우선순위(순서형 ordinal)다. HIGH가 MEDIUM보다 "먼저 본다"는 순서일 뿐 "0.9만큼 위험"이라는 크기(cardinal)가 아니다. 두 HIGH case 사이 미세 점수차에는 의미를 부여하지 않는다.
- **연속점수 역할 격하**: `composite_sort_score`(연속점수)는 tier 내부 정렬 tiebreak 전용으로만 사용한다. 큐 등급(band)을 만드는 결정 입력이 아니다.
- **사유**: (1) 가중합 계수(0.62/0.08 등)는 설계자가 손으로 정한 값이고, PHASE1은 정책상 truth recall로 가중치를 보정하는 것이 금지(`feedback_phase1_truth_recall_guard`)되어 데이터로 정당화할 길이 없다. (2) band는 사실 가중합이 아니라 floor/combo가 만든다(가중합 단독으로는 high 0.90 도달 불가) — `PHASE1_TOPIC_SCORING_V1_LOCK.md` line 106이 이미 자인한 사실이다. 숫자 장난을 제거하고 근거 있는 조건 → tier 직접 매핑으로 전환한다.
- **정직성 가드**: 어느 tier도 "세상 부정의 X% 적발"·"미지 부정 적발"·"이상치=부정"을 주장하지 않는다.
- **근거 SoT**: [PHASE1_TIER_EVIDENCE_BASIS.md](PHASE1_TIER_EVIDENCE_BASIS.md) (§3 설계 원칙, §4 tier 결정 조합, §5 단일 룰 floor).
- **관련 결정**: D060(0.90 critical 승격 — supersede 대상), D061(priority_score 계층 재설계 방향), D013/D024(가중합 점수체계 — supersede 대상).

### D072: 7주제 → 6주제 — intercompany_cycle topic 삭제 (2026-06-14)
- **결정**: PHASE1 7개 topic 중 `intercompany_cycle`(관계사·내부거래·순환구조) topic을 삭제하여 6주제로 전환한다. IC01~IC03·GR01/GR03의 PHASE1 점수경로를 제거한다. 해당 영역은 PHASE1-2 family로 이관한다.
- **L3-03 잔존**: L3-03만 PHASE1-1에서 account_logic booster(관계사 모집단 맥락)로 잔존한다. standalone_rankable=False이며 단독 case seed를 만들지 않는다.
- **사유**: 순환거래·관계사 구조는 한 전표만 봐서는 보이지 않는 구조 패턴이라 전표 단위 룰(PHASE1-1)로 표현할 수 없다. 여러 전표·관계를 엮는 graph/relational 탐지기(family, PHASE1-2)가 맡는 것이 옳다. 근거(IFRS 10 §B86 / K-IFRS 1110·1024 / ISA 600 / 550 §23)도 PHASE1-2 family에 귀속한다.
- **영향 범위 (구현 단계 이월)**: `src/detection/rule_scoring.py` topic 매핑, `PHASE1_TOPIC_SCORING_V1_LOCK.md` 순환거래 subtype, `PHASE1_RULE_RELATIONSHIP_MAP.md` §7.7(관계사). 기존 문서의 관련 floor/topic 기록은 역사 보존하며 "PHASE1-2 family로 이관" 주석을 단다.
- **근거 SoT**: [PHASE1_TIER_EVIDENCE_BASIS.md](PHASE1_TIER_EVIDENCE_BASIS.md) §4·§7.3, §8.

### D073: C안 3-surface 아키텍처 — 절대 비병합 불변식 (2026-06-14)
- **결정**: 탐지를 출력 의미가 다른 **3개 surface**로 분리한다.
  - **PHASE1-1 = 룰**: 전표(행) 단위 결정론 규칙 → 전표 1건 + 명명된 위반 + tier.
  - **PHASE1-2 = family**: graph·relational·시계열 전용 탐지기 → 그룹(순환 A→B→C→A, 직원-거래처 쌍, 시계열) + 명명된 구조 패턴. 순환거래의 정식 집.
  - **PHASE2 = VAE**: 정상 분포 비지도 학습 → 전표 + 점수 + 비정형 사유. companion(부정 확정 아님).
- **불변식**: 3 surface는 절대 비병합한다. 독립 탭/뷰/큐로 표시하며 단일 점수로 합치지 않는다. 룰·family는 "구체적 명명 발견", VAE는 "막연한 비정형 점수"라 단위·신뢰도가 안 맞아 병합하면 표시가 깨진다(과거 family+VAE 병합 실패의 원인).
- **PHASE3 제거**: PHASE3는 쓰지 않는다(구 LLM Review Narrator 자리 — active product path에서 제거됨, D068).
- **사유**: 단층선은 "알려진/미지"가 아니라 "근거 있는 결정론적 명명 탐지(PHASE1-1·1-2) vs 학습된 통계 surface(PHASE2)"다. 한계의 인정이 아니라 아키텍처 판단이다.
- **근거 SoT**: [PHASE1_TIER_EVIDENCE_BASIS.md](PHASE1_TIER_EVIDENCE_BASIS.md) §7·§7.1·§7.2.

### D074: PHASE2 = VAE 단독 surface, family = PHASE1-2 귀속 (2026-06-14)
- **결정**: 순환거래·관계사 구조는 family(PHASE1-2)가 맡고, VAE는 PHASE2 단독 companion surface로 격리한다. 과거 family + VAE 병합 구조는 폐기한다.
- **격리 사유**: VAE는 학습·통계·companion으로 셋 중 가장 약한 보조 신호다. 혼자 격리하는 것이 곧 D073 비병합 불변식의 운영 방어책이다. family(결정론·근거 있는 구조 발견)와 VAE(명명 안 된 비정형 점수)를 같은 surface에 두면 신뢰도가 섞인다.
- **정직성 가드**: PHASE2 VAE는 "정상 밖 비정형 surface"로만 주장한다. "이상치=부정" 표현을 금지한다.
- **영향 범위 (구현 단계 이월)**: family 탐지기(graph/relational/TS)의 PHASE1-2 귀속, VAE의 PHASE2 단독 surface화, 대시보드/export 탭 분리.
- **근거 SoT**: [PHASE1_TIER_EVIDENCE_BASIS.md](PHASE1_TIER_EVIDENCE_BASIS.md) §7.2·§7.3·§7.4.

### D075: A안 — HIGH 17건 재감사 → 셋째 다리 확장 (2026-06-16)
- **결정**: D071 tier 전환 후 HIGH 조합을 근거화하던 중, FSS HIGH 158건 전수 재집계에서 기존 5조합 밖 17건을 발견했다. 17건 원문(수법)을 분석한 결과 11건이 조합1(가공전표)·조합2(횡령은폐)와 **같은 스토리, 셋째 정황(2차 정황)만 다른** 사례였다. 따라서 **A안 — 신규 조합을 만들지 않고 기존 조합1·2의 인정 2차정황 풀을 FSS 실증에 맞게 확장**한다.
  - 조합1(가공전표) 셋째 다리: `(L4-04|L2-03)` → `+ L3-03·L3-04·L3-10·L1-05·L1-09·L3-11` 추가.
  - 조합2(횡령은폐) 통제 분기: `승인우회(L1-04~07)` 필수 → `or (L2-05 역분개 + L3-02 수기)` 분기 추가(승인 흔적 없는 은폐 포착).
- **기각 대안**: B안(메타규칙 `수기+고액+아무 2차정황 1개=HIGH` 일반화)은 약한 정황까지 HIGH로 올려 과탐 위험 최대. C안(신규 조합 2~3개 추가)은 같은 스토리를 쪼개 조합 수·관리부담 증가. 둘 다 기각.
- **오태깅·이관 처리**: 17건 중 오태깅 2건(기존 조합 정정), family 3건(순환거래 → PHASE1-2 graph, D072/D074), 2-rule 약신호 1건(FSS2112-07-1 HIGH 자격 별도 검토).
- **과탐 HARD 가드 (코드 단계 미결)**: 셋째 다리에 기말(L3-04)·자기승인(L1-05) 포함 시 정상 결산 전표가 HIGH로 샐 위험. 코드 반영 후 정상 데이터로 **HIGH ≤ 2%** 재측정, 초과 시 FAIL → 해당 다리 좁히기. 측정 전 완료 선언 금지.
- **상태**: 설계·문서 확정. 코드 반영(`topic_scoring.py::_fraud_combo_floor_results` 조합1·2)은 다음 세션.
- **근거 SoT**: [HIGH_COMBO_GROUNDING.md](HIGH_COMBO_GROUNDING.md) §5b·§7·§8, [PHASE1_TIER_EVIDENCE_BASIS.md](PHASE1_TIER_EVIDENCE_BASIS.md) §4.5, [TROUBLESHOOT.md](TROUBLESHOOT.md) TS-15.
- **관련 결정**: D071(tier 전환), D072(IC→family).
