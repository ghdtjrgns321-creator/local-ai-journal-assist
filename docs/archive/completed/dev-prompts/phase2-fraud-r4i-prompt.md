# r4i 수정 프롬프트 — FS01/FS05 구조신호 복원 (S14) + 시드 회전(모의고사) 준비

> r4h 는 fidelity(shortcut 없음) 13게이트 통과했으나, utility 분석에서 FS01 가공매출 "동일 고객
> 반복"·FS05 순환거래 "3사 원환" 구조신호가 분산으로 평탄화됨이 발견됨. 구조신호 floor 게이트
> S14 추가(총 14게이트). 새 세션에 전문 붙여넣기.

[작업] ①FS01/FS05 구조신호 복원 ②완성본을 시드 회전해 채점용 데이터셋 N벌 생성.
base: data/journal/primary/datasynth_semantic_v1_normal_20260611_v41 (그대로)
직전: data/journal/primary/datasynth_semantic_v1_phase2_fraud_20260611_v1_r4h
규모기준(reference): data/journal/primary/datasynth_semantic_v1_phase2_fraud_20260611_v1_r4f_c
산출: data/journal/primary/datasynth_semantic_v1_phase2_fraud_20260611_v1_r4i (복원 완성본)
       + 시드 회전본 r4i_seed1 ~ r4i_seedN (아래 STEP 2)
구현: tools/datasynth/crates/datasynth-cli/src/phase2_scheme_overlay.rs

[완료 조건 — 유일한 종료 기준]
  STEP 1 완성본: uv run python tools/scripts/phase2_shortcut_gate.py <r4i> <r4f_c> → exit 0 (14게이트 ALL PASS)
   + uv run python tools/scripts/verify_phase2_regression.py <r4i> <v41> 회귀 유지.
  STEP 2 시드회전본: 각 seed 데이터셋도 동일 14게이트 exit 0.
게이트 임계·화이트리스트·S14 floor 변경 금지(완화는 사용자 승인).

═══════════════════════════════════════════════════════════════════════
STEP 1 — FS01/FS05 구조신호 복원
═══════════════════════════════════════════════════════════════════════

[결함 — r4h 실측 (S14 FAIL)]
shortcut 제거(거래처·회사 분산)가 부정 고유 구조까지 평탄화:
- FS01 가공매출: fictitious_sale 13건이 13개 서로 다른 고객(한 고객 최대 2건). 모뉴엘형 핵심
  시그니처 "같은 페이퍼컴퍼니에 반복 매출"이 사라짐.
- FS05 순환거래: 전부 단일 회사 C002. 카탈로그 "C001→C002→C003→C001 닫힌 원환"의 cycle 구조 없음.

[수정]
D1 (S14, FS01): 가공매출을 **소수(2~4개) 가공 고객에 반복 집중**시킨다.
  - 한 가공 고객에게 다수 매출(최소 한 고객 ≥3건, 현실적으로 5~15건). 카탈로그 FS01 (d) "같은
    가공 고객에게 다수 인보이스가 수년간 반복".
  - AR 미회수 누적(이미 있음 -138M)과 결합 — 같은 고객의 채권이 회수 안 되고 쌓이는 시계열.
  - ★ 단 그 가공 고객은 customers.json 정상 형식으로 등록, 마스터 필드(국가·은행·tax_id)는
    정상 분포 — "고객이 반복된다"는 구조만 신호이고 마스터값 누수는 금지(카탈로그 (e), shortcut 재발 방지).
  판정선: S14 = FS01 한 고객 최소 ≥3건.

D2 (S14, FS05): 순환거래를 **실제 3사(C001~C003) 원환**으로 구성.
  - A→B→C→A 매출 순환: C001이 C002에 매출 → C002가 C003에 매출 → C003이 C001에 매출(또는 용역).
    각 사 매출이 동시에 부풀고 그룹 합산으로 상쇄. 카탈로그 FS05 (c)1·(d).
  - 결제 체인도 원환(금액 거의 동일, 수수료성 차액). cross_process_links 에 재고이동 없는 매출-매입 짝.
  - intercompany lane 활용 가능(115001~/205001~), 또는 외부 공모처 1~2개로 원환 보강.
  판정선: S14 = FS05 관여 회사 ≥3.

[유지 — 건드리지 말 것]
- r4h 의 성과 전부: donor 상속(조합누수 0), 소액 혼입, document_id 36자, 시스템필드, 월말 실재,
  S8 계정정합, 자연 단순분개, 경제효과 방향, 부작위 금액 파생, FS03 규모 복원, FS14 급여.
- FS01/FS05 복원이 기존 게이트(S2 단일피처·S11 조합·S8 계정정합)를 깨지 않게: 고객 반복·회사
  원환은 "구조"만 부여하고, 메타필드·계정·승인자는 donor 상속 유지(shortcut 재발 금지).
- base v41 무수정. 14 scheme 전수·prevalence 0.1%.

═══════════════════════════════════════════════════════════════════════
STEP 2 — 시드 회전으로 채점용 데이터셋 N벌 (모의고사 확대)
═══════════════════════════════════════════════════════════════════════
목적: 부정 밀도(0.1%)는 유지하고, 같은 회사 구조(C001~C003)를 다른 난수(seed)로 N벌 생성해
채점 시 합산 → scheme별 instance 가 1 → N 으로 늘어 "부정 N건 중 M건 탐지" 수치 가능.
배경·원칙은 docs/guide/users/17_PHASE2_MOCKEXAM_SEED_ROTATION.md 참조(운영 1벌 vs 채점 N벌, 회사
추가 아님, 밀도 불변).

[절차]
1. STEP 1 완성본(r4i)이 14게이트 통과한 뒤에만 시드 회전 시작(결함 데이터 복제 금지).
2. overlay 의 RNG seed 만 바꿔 N=5~10 벌 생성: r4i_seed1 ~ r4i_seedN.
   - base normal(v41) 은 공유 재사용(재생성 안 함). overlay 만 seed 회전.
   - 각 seed 에서 scheme 의 회사·기간·금액·고객 배치가 달라져 서로 다른 사례가 됨.
   - 각 벌은 동일하게 부정 14종·0.1%·회사 3개 — 밀도 불변.
3. 각 seed 데이터셋도 14게이트 + 회귀 통과 확인(품질 동일 보장).
4. 채점 시: N벌의 truth/provenance 를 합산해 scheme별 instance N개로 평가
   (단일 벌 밀도를 올리지 않음).

[★ 문서화 지시 — 반드시 수행]
시드 회전(모의고사 확대) 전략을 **datasynth 생성원칙 문서에도** 본인이 나중에 보고 이해할 수
있게 쉬운 말로 정리한다:
  - 대상 문서: tools/datasynth/CLAUDE.md 의 DATASYNTH 생성 규칙 절(또는 프로젝트 루트 CLAUDE.md
    "DATASYNTH 생성 규칙" 절) — 어느 쪽이든 datasynth 생성원칙이 적힌 곳.
  - 내용: docs/guide/users/17_PHASE2_MOCKEXAM_SEED_ROTATION.md 와 동일 취지를 1개 항목으로 요약 추가.
    핵심 — "표본이 필요하면 한 데이터셋 밀도를 올리지 말고 시드를 바꿔 데이터셋을 N벌 생성해
    채점 시 합산한다(회사 추가 아님, 밀도 0.1% 불변, 운영은 1벌)". 상세는 users/17 링크.
  - 비전공자 친화·한국어 평서체(시험문제 1개=0/100점 비유 포함).

[검증 — 자동 루프]
1. STEP 1: 수정 → r4i 생성 → 14게이트(ref=r4f_c) + 회귀 + 심층스캔. exit 0 아니면 재수정.
2. STEP 2: r4i 통과 후 seed 회전 → 각 seed 14게이트 통과.
3. 매 회차 reports/ + docs/debugging.md 누적 기록.

[금지]
- 게이트 통과용 회계 훼손 우회 금지(무관계정·가짜분할·식별자변형·메타조합·규모축소 재발 금지).
- FS01 고객 반복·FS05 원환 부여하며 마스터값/계정/메타 누수로 shortcut 재발 금지.
- 시드 회전으로 단일 데이터셋 부정 밀도 올리기 금지(0.1% 불변).
- detector 성능으로 주입 튜닝 금지. 한국어 보고.
