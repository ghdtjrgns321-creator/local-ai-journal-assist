# PHASE2 fraud overlay 실행 프롬프트 (r1)

> 새 세션에 아래 전문을 붙여넣어 사용. r2는 [scheme 선택] 절의 목록만 교체.

[작업] PHASE2용 woven fraud overlay 데이터셋 생성.
Base: data/journal/primary/datasynth_semantic_v1_normal_20260610_v31c (COA 확장 normal, 확정본)
산출: data/journal/primary/datasynth_semantic_v1_phase2_fraud_<날짜>_v1_r1

[SoT — 반드시 먼저 읽을 것]
dev/active/phase2-fraud-scheme-catalog.md — 부정 scheme 카탈로그 (FS01~FS14).
각 scheme의 (b)회계 메커니즘 → (c)다문서/다계정/다기간 구성 → (d)주입 시그니처·component_role →
(e)anti-shortcut → (f)prevalence 를 그대로 구현한다. 카탈로그에 없는 부정 임의 발명 금지,
카탈로그 구성요소 임의 생략 금지(생략 시 사유 명시).

[★ 절대 원칙 — ANTI-FITTING]
- 읽지 말 것: docs/spec/DETECTION_RULES.md, dev/active/phase1-evasion-injection-spec.md.
- 탐지 룰이 잡는지/놓치는지를 주입 설계·파라미터 조정에 사용 금지. 탐지 성능은 데이터 완성 후
  탐지기를 돌려 사후 관찰만 한다 (생성 단계에서 detector 실행 후 주입을 고치는 루프 금지).
- 부정의 형태는 오직 카탈로그 (b)~(f)에서만 나온다.

[scheme 선택 — r1 회차]
- 카탈로그 §4 기준 5~8개 조합. r1은 카테고리 균형으로:
  FS01(가공매출), FS03(횡령), FS05(순환), FS07(재고), FS09(cutoff), FS11(IC 특관), FS12(low-trace)
  — 총 7개. 나머지 7개(FS02·04·06·08·10·13·14)는 r2 회차로 이월
  (한 바퀴에 14개 전부 1회 이상 규칙, 카탈로그 §4).
- instance 수·문서 수는 카탈로그 (f) 범위 내. 전체 부정 문서 0.04~0.14% 준수.

[구현 원칙]
1. RUST로 근본 구현: tools/datasynth 크레이트에 overlay profile 추가
   (전례: crates/datasynth-cli/src/p3_2_overlay.rs 의 phase1-recall-overlay). Python 덧대기 금지.
2. 실제 flow 멤버십 (r23 교훈): woven 구성요소는 진짜 document_flows/·intercompany/·relationships/·
   subledger/·master_data/ 파일에 들어간다. 라벨 전용 가짜 sidecar flow 금지.
3. 식별자: document_id/UUID·document_number 채번은 정상과 같은 generator 경유
   (stride·범위 분리 금지).
4. 데이터 품질(MCAR 결측·오타·서식)은 정상/부정 동일 비율 적용.
5. 라벨: 카탈로그 §1 스키마 — scheme_id, scheme_instance_id, component_role, is_fraud, fraud_type,
   severity. FS10·12·13의 부작위(미인식 금액)는 instance 메타 sidecar에 기록 (문서 라벨 아님).
6. base 문서는 1건도 수정·삭제하지 않는다 (순수 overlay + 신규 문서 추가).
7. 다기간 scheme(FS01·FS03 등)은 연도 경계를 실제로 걸친다 (2022~2024 내 배치).

[검증 — 전 항목 통과 후 완료 선언]
1. 문서 불변량: base 문서 수(v31c 실측) + 주입 N = 출력 문서 수 정확 일치.
2. truth 정합: scheme별 instance 수·문서 수가 설계표와 일치. scheme_instance_id로 묶었을 때
   component_role 구성이 카탈로그 (c)와 일치.
3. shortcut 스캔: uv run python tools/scripts/scan_overlay_shortcuts.py <출력경로> → findings 0.
   추가로 전 컬럼 오라클 스캔(단어 grep 아님): truth 컬럼 제외 모든 표면 컬럼에서 is_fraud와
   완전 분리되는 값/범위/형식이 없는지 확인.
4. 정상 쌍둥이: 부정에 사용된 모든 계정·문서유형·시간대 패턴이 정상 문서에도 존재
   (부정 전용 계정 0개).
5. 회계 정합: 전 분개 차대 균형, flow 체인(PO→GR→INV→PAY / SO→DLV→INV) 정합, IC pair 양측 정합
   (FS11 의도적 불일치는 라벨된 것만).
6. low-trace stratum: FS12 instance 메타에 미인식 금액 존재, 평가 stratum 태그 확인.
7. 측정 리포트를 <출력경로>/reports/ 에 저장, 회차별 결과는 파일에 즉시 누적 기록.
8. 완료 후 docs/debugging.md 업데이트 (datasynth 재생성 규칙).

[금지]
- 검증 실패 상태에서 완료 선언 금지. 빈 집합/fallback PASS 금지
  (최소 기대치: 주입 문서 수 > 0, scheme 7개 전부 instance >= 1).
- PHASE1 탐지 결과를 보고 주입을 수정하는 행위 금지 (사후 측정은 별도 태스크).
- 한국어로 보고.
