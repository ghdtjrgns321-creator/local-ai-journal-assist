# 합성데이터 재구축 마스터플랜 (2026-07-16)

> **이 문서의 역할**: 세션이 바뀌어도 이 파일 하나로 전체 그림을 복원한다.
> 목표·확정 사실·사용자 결정·6단계 로드맵·파일 지도·열린 질문을 담는다.
> 진행 상태는 각 단계의 체크박스를 갱신한다. 수치는 전부 §1 팩트시트가 정본.

## 0. 목표

**PHASE1-1(룰 31+1) + PHASE1-2(분석적 검토 신호) + PHASE2(VAE)를 합성데이터로 재현해
결과를 산출하고, 입사용 포트폴리오로 제출한다.**

성공 기준 (게이트 48개 PASS가 아니다):

| #   | 기준                                                         | 측정                           |
| --- | ------------------------------------------------------------ | ------------------------------ |
| ①   | 정상 base에서 룰 32개 각각의 발화율이 선언된 대역 안         | 발화율 표 (0% 실격, 폭주 실격) |
| ②   | fraud overlay에서 심은 FSS scheme이 review queue 상위에 잡힘 | seed 3~5개 합산 과탐·미탐      |
| ③   | VAE가 정상 밖 비정형을 추가로 surface                        | 플래그율·seed 합산 성능        |
| ④   | 재현 가능 — 설정·명령·결과가 문서로 남음                     | 본 문서 + reports/             |

## 1. 팩트시트 (2026-07-15~16 실측, 정본)

### 1a. 현재 normal(r6)이 망가진 지점 — 교체 사유

| 결함                                  | 수치                                            | 출처                                                      |
| ------------------------------------- | ----------------------------------------------- | --------------------------------------------------------- |
| 부가세율이 공급가액의 4.12% (10%여야) | 세액/공급가액 중앙값 **0.0412** (64,539행)      | 본 세션 실측. 생성기는 10% 정확, v42 덧칠이 깸            |
| 계정-적요 무관 등 계정 체계           | ACC 검사 **6~7/9 FAIL** (ACC02 위반 77,166 등)  | `reports/account_determination_unit1/gate_acc_on_r6.json` |
| 자기승인 0건 → L1-05 검증 불가        | `sod_violation` **0/376,727**                   | 본 세션 실측                                              |
| 사후 원장 변형 40여 회 (덧칠)         | `normal_coa_v30.rs:307-347`                     | 코드 확인                                                 |
| 기존 게이트 44 PASS는 신뢰 불가       | M01·M03·M04·M07 = 항등식 (어떤 데이터로도 PASS) | `reports/unit2_rescope/sidecar_consumers.md` §근거3       |

### 1b. 생성기는 대체로 건강 — 설정만 제대로 주면

clean_out(882,433행, 정본 config 재구성판) 실측:

| 항목                              | 결과                                                                             |
| --------------------------------- | -------------------------------------------------------------------------------- |
| 계정 체계                         | **ACC 8/9 PASS** (결함주입 보정 5/5 통과 — no-op 아님)                           |
| 유일 FAIL = ACC01                 | **게이트 설계 오류로 판정** (`reports/unit2_rescope/acc01_design_review.md`)     |
| 부가세                            | 세액/공급가액 **정확히 0.1000**                                                  |
| 금액 스케일                       | 중앙값 681,151원 · 승인한도 초과 15.3% (r6 12.5%와 동일 대역)                    |
| C06 (덧칠의 존재 이유였던 게이트) | **PASS — 생성 시점 자연 통과**                                                   |
| 남은 진짜 생성기 갭               | 손익 비율 (원가율 0.11~0.13, 기대 0.55~0.92) — `target_gross_margin`이 죽은 설정 |

### 1c. 제품이 실제로 읽는 것 (재범위화 근거)

| 사실                                                                                                         | 수치                                                                                     | 출처                                                                              |
| ------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| 재무 사이드카 4종(opening_balances·trial_balances·financial_statements·subledger_reconciliation) 제품 소비처 | **0 / 299 파일**                                                                         | `reports/unit2_rescope/sidecar_consumers.md`                                      |
| 제품이 읽는 사이드카                                                                                         | `_LOADERS` 18개 + `master_data/employees.json`                                           | `src/db/loader_supplementary.py:647-670`, `src/feature/amount_features.py:89-108` |
| 절대 KRW 스케일 의존 룰                                                                                      | **2 / 32** (L1-04·L2-01 ↔ `config/settings.py:81-88` 승인한도)                           | `reports/unit2_rescope/amount_scale_rules.md`                                     |
| VAE 금액 컬럼                                                                                                | **전량 학습 차단** (`LEAKAGE_DENY_COLUMNS`) — 사유 "합성 금액이 너무 깨끗해 지름길 학습" | `src/preprocessing/constants.py:63-118`                                           |
| 룰 레지스트리 실측                                                                                           | **32룰** (`RULE_SCORING_REGISTRY`)                                                       | `src/detection/rule_scoring.py`                                                   |

### 1d. 설정 사고 이력 (재발 방지)

- 손작성 config가 **12/17 섹션 유실** → 금액이 USD 기본값(`lognormal_mu 7.0` vs KRW `14.0`, e^7≈1,097배)으로 생성됨. 같은 병의 선례: `docs/debugging.md:680` (`tax:` 누락 → Phase 20 스킵).
- **진짜 normal base 설정** = `artifacts/datasynth_normal_semantic_v1_20260603.yaml` (17섹션, git 비추적). `config/datasynth.yaml`과 유사하나 seed 20260603·3사 구성.
- **규칙: DataSynth config는 손으로 새로 쓰지 않는다. 정본을 읽어 최소 변경, 섹션 수 before/after 확인.**
- **빌드 함정(2026-07-16 실측)**: 워크스페이스 루트에 빈 `[package] datasynth-workspace`가 있어 루트에서 `cargo build --release`는 **루트 패키지만 빌드하는 no-op**("Finished 0.2s"). Rust 수정 후 반드시 **`cargo build --release -p datasynth-cli`**. 스테일 바이너리로 E13 1차 재검증이 헛돌았음.
- **행수 비결정성(기존)**: 같은 바이너리·config·seed로 2회 생성 시 983,763 vs 983,741행(C001 359,104→359,126). seed 재현성은 행수 수준에서 이미 깨져 있음 — 검증은 고정 행수 대신 **±0.1% 대역**으로. 원인 미규명(기존 `Uuid::now_v7()` 벽시계 의존 의심, 별도 이슈).

## 2. 사용자 결정 로그 (2026-07-15~16)

| #   | 결정                                                   | 함의                                                                                            |
| --- | ------------------------------------------------------ | ----------------------------------------------------------------------------------------------- |
| D1  | 범위는 "실제 ERP 근사"가 아니라 **제품이 읽는 축**     | 재무 사이드카·손익 표시용 현실성 탈락                                                           |
| D2  | **normal은 normal이어야** — 의도적 이상·부정 주입 금지 | `anomaly_injection`·`fraud` off. 이상은 overlay로                                               |
| D3  | **자기승인은 정상에 있어야** — 감사인이 볼 항목        | 겸직(compatible_extension) 파생 자기승인 유지. r6의 0건이 오히려 결함                           |
| D4  | 금액 스케일만 고치고 **손익 비율은 보류**              | M11 후순위 (PHASE1 결과물에 안 보임, L4-03은 매출>0만 요구)                                     |
| D5  | 목표에 **VAE 포함**, 입사용 포트폴리오                 | 금액 deny 해제 결정이 S1로 당겨짐 (§4 Q2)                                                       |
| D6  | ACC01 게이트도 의심하라 → **게이트 오류 판정 완료**    | 수정안 제안됨(전표 단위+금액 검증), 미구현                                                      |
| D7  | E05B는 **게이트 재설계**로 해소 (2026-07-16)           | 사용자 단위 전담 검증으로 교체 — clerk 어휘 허용표 폐기                                         |
| D8  | Q6 해소: 정상 sod_violation **라벨 제거** (2026-07-16) | check_entry는 행동 없는 주사위 라벨(정답지 유출). 정본 config 4곳 0.0. 자기승인 행동(D3)은 불변 |
| D9  | 소형 갭보다 **S1 먼저** (2026-07-16)                   | 룰 발화 실측이 진짜 심판 — 거기서 잡히는 것만 되돌아와 수정                                     |

## 3. 로드맵 — 데이터의 여정

```
[S0 normal base 재생성] ──▶ [S1 정합성: 룰 발화율 + VAE 플래그율]
        │ 진짜 설정 무수정            │ 대역표를 생성 전에 선언
        ▼                            ▼
[S2 룰 단위시험 data] ──▶ [S3 HIGH combo FSS 재구성] ──▶ [S4 combo 단위시험 data]
   (발화 여부만·성능주장 금지)   (코드반영 10건 대기분 마무리)      (발화 여부만)
        ▼
[S5 FSS scheme overlay × seed 3~5] ──▶ [S6 결과 문서화 = 포트폴리오]
   base는 깨끗하게 유지, overlay 별도 파일        과탐·미탐·VAE 성능 합산
```

원칙: **단위시험(S2·S4)은 "룰이 기술적으로 발화하는가"만 증명한다. 성능 주장은 오직 S5에서만.**
(발화하라고 만든 데이터에서 발화한 것은 성능 증거가 아니다 — 면접 방어 논리)

### 현실성 검증 3겹 구조 (2026-07-16 확정)

게이트 57종은 현실성의 전부가 아니다 — 카탈로그 **146개 중 게이트 구현 49개(34%)**
(계약서 820fd827 실측, 미구현: 시간 10·분포 5·승인 11·노이즈 7·경제적 타당성 20).
게다가 57종 안에서도 M01·M03·M04·M07은 항등식, ACC01은 역방향으로 판정 오류가 확인됐다.
따라서 "게이트 전부 PASS = 현실적"은 성립하지 않으며, 검증은 3겹으로 본다:

```
1겹  게이트 57종         구현된 축의 자동 검사. FAIL은 3분류(①데이터 결함
                          ②게이트 결함 ③제품 무관)해서 ①만 수정 대상.
2겹  S1: 룰 32개 발화율   룰이 읽는 모든 축의 실질 심판. 정상에서 룰이 폭주하면
                          데이터가 비현실적이라는 신호 (예: 금액 붕괴를 게이트가
                          아니라 L1-04 모집단 274 vs 135,071이 드러냄).
3겹  S5: overlay 성능     심은 이상이 잡히는가 — 최종 증거.
```

미구현 97개 축은 선제 게이트화하지 않는다. **S1에서 발화율이 대역을 벗어난 룰이
가리키는 축만 역으로 판다** — 룰이 안 읽는 축의 비현실은 포트폴리오 결과물(D1)에
영향이 없다.

### S0. normal base 재생성 ← **생성·판정 완료, Q1 결정 대기**

- [x] `artifacts/datasynth_normal_semantic_v1_20260603.yaml` **무수정** 생성 (2026-07-16, MD5 `c3221410…`, 출력 `<scratchpad e5adea09>/s0_normal`)
  - 실측 **983,763행** · `is_anomaly` **0** · `is_fraud` **0** · `anomaly_type` **0** · `sod_violation` **10,770 (1.095%)** ∈ 1%±0.5%p — 전부 임계 안
  - 재검증: `<scratchpad e5adea09>/s0_verify.py` (임계 미달 시 exit 1)
- [x] S0-3 라벨·금액·부가세 실측 — 부가세율 중앙값 **0.1000**(r6 0.0412) · 금액 중앙값 **676,303원** · 5B/10B/50B 초과 **219/105/57건** — 전부 임계 안
- [x] **S0-2 단일법인 필터 완료 (Q1 결정: 3사 생성 → C001 필터, 2026-07-16)**
  - 결정 근거: 관계사 거래는 "두 회사 간 실제 거래"로 생성되므로 상대(C002/C003)가 설정에 있어야 C001 원장에 흔적이 남는다. C001 단독 생성 시 `is_intercompany` 0건(지난 세션 실측) vs 3사 생성 시 0.16%. 상대 회사 원장은 버린다. 흔적만 써넣는 방식은 v42 `append_v46` 덧칠과 동일 병 — 기각.
  - 구현: `tools/scripts/filter_single_company.py` (행 선택만 하는 투영, `--company` 인자, 값 재작성 0)
  - 실측: **s0_c001 = 359,104행**, `company_code` 100% C001 · 임계 8/8 유지(라벨 0·sod 1.070%·ic 0.1621%·부가세 0.1000·중앙값 641,882원·상위한도 발화 가능)
  - 차집합 0 증명: C001 359,104 + C002 348,067 + C003 276,592 = **983,763 = 원본** (3케이스 ripple)
  - → U2-8("생성기가 단일법인 관계사 흔적을 못 만든다")은 **오진**. 덧칠 `append_v46` 불필요.
  - **새 base 후보 위치**: `<scratchpad e5adea09>/s0_c001` (재검증: 같은 폴더 `s0c001_verify.py`)
- [x] **S0-4 1겹 게이트 57종 실행 (2026-07-16)** — **PASS 30 / FAIL 15 / BLOCKED 9** (`reports/unit2_rescope/verifier_s0_c001.json`). clean_out 대비 G08_G09·I05·K02·K03·K04 소멸. **복식부기 A01·A02, 계정결정 ACC02, 부가세율, C06 전부 PASS — "말도 안 되는 회계처리" 계열 이상 없음.**
  - FAIL 15+BLOCKED 9 전수 3분류는 계약서(e5adea09) 기록. 남은 진짜 생성기 갭(①): 소형 3(A07 0.95%·B18 계정1개·O02 marker) · ~~중형 3 + K05 전부 완료~~ · 필터 확장 1(K08 사이드카) · 보류 1(M11 손익, D4)
  - **E13 완료(2026-07-16)**: `JournalEntryHeader::assign_automation_identity()`(core, FNV-1a 내용주소형 UUID·멱등) + je_generator 위임 + **오케스트레이터 최종 수집 지점 일괄 부여**(suspense flag 선례와 동일 패턴). s3_c001 실측 `auto_missing 0/274,240`·human 채움 0·E13 PASS, 57게이트 신규 FAIL 0. 새 base 후보 = **s3_c001**(s0 대체 — E13·ACC08 반영분).
  - **E05B 완료(2026-07-16, 게이트 재설계 — 사용자 결정)**: 원인은 코드가 아니라 **어휘 불일치** — 게이트 허용표의 clerk 어휘(ap_clerk 등)가 생성기 UserPersona enum에 부재(원리상 만족 불가, ACC01 계열 게이트 오류). 위 표의 "라운드로빈" 진단은 사이드카 쪽이고 원장 E05B와는 무관했음. 재설계: 사용자 단위 전담 검증(junior 폭 1 · senior+ 폭 ≤2 & 두 번째는 반드시 R2R(결산 겸직) · junior×TRE 0). s3 PASS(67 사용자)·주입본 FAIL 재현.
  - **K05+K07 완료(2026-07-16, 한 원인)**: 위 표의 K07 제안(PURCHASE 시나리오 추가)은 헛다리 — 진짜 원인은 K05의 GL 접두 게이트(`is_intercompany_for_csv`)가 관계사 문서의 일부 라인만 플래그 → 매입 문서가 대변 청산 라인만 방향 집계에 들어가 편측. 접두 게이트 제거(실제 SAP trading partner는 전 라인) 후 s4에서 **K05·K07 동시 PASS**, K02 대역 내 유지. 57게이트 **PASS 35 / FAIL 10**. **새 base 후보 = s4_c001**.
  - **D10 거래 종류 5종 확장 완료(2026-07-16)**: R2R_BAD_DEBT_WRITEOFF·R2R_RETIREMENT_ACCRUAL·TRE_EXEC_ADVANCE·A2R_DEV_CAPITALIZATION·R2R_MISC_INCOME (전 계정 기존 재활용, weight ×10 스케일 후 세밀 저빈도 — 신규 비중 2.43%). 죽은 룰 부활: **L3-10 0→709 · L2-04 0→251 · L4-04 5→20**, L1-03 3,594→0(제품 CoA 3계정), E05C 운영예외 명시 주입(한도초과 0.231%). Q6(D8)로 sod 라벨 0 + 부수: L1-05 행동 주입 경로 확인(je_generator:3828 — 전결 rate 분리 필요, 미구현). 57게이트 PASS 37/FAIL 8 (시작 30/15).
  - **L1-05 전결 + E05C 운영예외 완료(2026-07-16)**: `self_approval_rate: 0.02`(라벨 없는 전결 — sod 라벨 불변) 신설 + 배선 2경로(from_generator_config·빌더 체인 — 빌더 누락이 1차 FAIL 원인). 운영예외(한도초과 승인)는 5라운드 근본 추적 끝에 **승인권 구조가 원인**(can_approve_je가 Manager 10억부터 → 한도초과가 구조적으로 불가) — Senior(1억) 승인권 부여 + 최종 approved_by 지점 주입 0.05. s9 실측: **L1-05 392(0.110%)** · E05C 0.24% · 게이트 PASS 37/FAIL 8 유지. **새 base = s9_c001**.
  - **원인 코드 특정 완료 (2026-07-16 조사)**:
    | 갭   | 원인                                                                                                                                                                                                                                              | 수정 지점                                                                                                                               |
    | ---- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
    | E13  | je_generator가 source=Automated/Recurring 설정(`je_generator.rs:1661`)하면서 `batch_id`/`job_id`를 안 채움. 채우는 곳은 orchestrator 특수전표 3곳뿐(reclass `:7489`·close `:7765`·batch `:7936`) → 5.1%                                           | 헤더 빌드에서 source와 batch/job id를 **동시 설정**으로 결합                                                                            |
    | E05B | 프로세스 전속 개념이 je_generator에는 있음(`rebuild_user_process_map` `:1039-1113`, junior=단일 프로세스). 그런데 문서흐름 P2P/O2C의 `created_by`는 `employees[i % len]` 라운드로빈(`enhanced_orchestrator.rs:6730-6736`·`6801-6807`) — 전속 무시 | 문서흐름·급여 경로의 사용자 선택을 process map으로 필터                                                                                 |
    | K07  | 시나리오 카탈로그에 `IC_INTERCOMPANY_SALE`(판매측)만 있고 **매입측 시나리오 부재**(`process_gl_mapping.rs:1069-1098`) + output_writer가 IC를 무조건 SALE로 매핑(`output_writer.rs:335,344`)                                                       | `IC_INTERCOMPANY_PURCHASE` 시나리오 추가 + 매핑 분기. ※조사자 주장 "매입행 미생성"은 IC_PAYABLE 328행 존재와 상충 — 수정 착수 시 재검증 |
    | K05  | `is_intercompany`가 헤더 값이 아니라 **CSV 출력 시점 계산**(`output_writer.rs:351-380`)이며 GL 접두 게이트(1150/2050/4500/2700)로 제한 — `trading_partner` 설정처(je_generator `:1706-1723`)와 조건 불일치                                        | GL 접두 게이트 제거 또는 플래그를 헤더로 승격                                                                                           |
  - 게이트 쪽 수정 대상(②): ACC01 역방향 · ~~ACC08 IC subtype 4종~~ **완료(2026-07-16)** — 722행 전수 측정(1:1 결정적) 후 표에 4항목+역방향 대표 2건 추가. ACC08 722→0, ACC02 위반 0 유지·covered +722, Rust 테스트 8/8. 잔여: M05/M06/M13/M14 공통 게이트 구조 · N07/N09/N10의 v42 계정 가정(미확정)
  - **Q6 (신규 결정 필요)**: E05 — 정상에 자기승인 **행동**은 유지(D3)하되 `sod_violation=true` **라벨**을 지울지, 게이트를 완화할지

### S1. 정합성 확인 (base 하나로 PHASE1+PHASE2) — ✅ **완료 (2026-07-17)**

> **확정 base 영구 위치**: `data/journal/primary/datasynth_semantic_v1_normal_s10_c001_20260717/` (355,786행+사이드카 2.5GB, scratchpad `s10_c001`에서 복사·행수 대조 일치. 행수 비결정성 때문에 재생성으로는 동일본을 못 만드므로 이 사본이 유일 정본 — data/는 gitignore라 git 이력 없음, 덮어쓰기 금지)

- [x] **룰별 정상 발화율 대역표를 실측 전에 선언** — `docs/0716/S1_RULE_BANDS.md` (2026-07-16 선언, 재선언 9건은 전부 ③ 도메인 근거 병기)
- [x] PHASE1 파이프라인 실행 → 32룰 발화율 실측 — **s10_c001 최종 판정 PASS 27 / FAIL 1 (판정 분모 28 = 대역표 33행 − 비대상 5)** 【정정: L1-09·L3-01·L3-08은 탐지기 부재 구 ID라 비대상 — 최초 "PASS 29/분모 30"은 hollow-PASS 포함 오류, 중간 "분모 27"은 행 수 오산】. "대역 밖 0개" 기준은 미달 — 유일 FAIL **L4-03**은 ①생성기 손익 비정합(비용이 매출의 3.4배) + ②룰 마감분개 식별 키 불일치(NI 오산출→임계 붕괴) 복합 결함으로 확정, 수정은 기등록 L4-03·L1-05 중요성 재설계 라운드(Q5 연동)로 이연하고 판정 기록으로 종결. 상세: `S1_RULE_BANDS.md` §S1 최종 판정·§s10 재판정 (2026-07-17)
  - [x] **s10 라운드 완료 (사용자 지적 "정상에 cutoff 0건 이상하다" → 재개봉)**: 발화 0 룰 12종 전수 재점검 → 수정 3 / 0 정당 6 / 탐지기 부재 3. 수정: L3-11(DR/KR delivery_date 원설계 복원, 최종 전기일 후 앵커) 257건 0.072% · L3-07(증빙 31~90일 지연 꼬리) 143건 0.040% · L3-09(is_cleared 정리신호 신설 — 원장 컬럼 추가) 482건 0.136% — **3종 모두 측정 전 선언 대역 안**, 57게이트 회귀 0. 0이 정당: L1-01/02/03(ERP 강제)·L1-08(특별회계기간 미사용 ERP는 기간=전기월)·L1-07-02(명부 실재)·L3-12(E05B 전담 설계와 정합 — 주입 시 게이트 충돌). **새 base = s10_c001**
  - [x] 발화 0 룰 원인 분류 완료 — 죽은 룰 누적 8종 부활(L1-04·L1-05·L3-10·L2-04·L4-04 + L3-11·L3-07·L3-09)
- [x] PHASE2 VAE 학습(정상만) → 플래그율이 오염 설정 근처 — **PASS (2026-07-17)**: train 50k/calibration 50k(random), 71피처(현행 LEAKAGE deny 그대로), **미학습 정상 플래그율 1.056% vs 오염설정 1.00%** (사전 선언 대역 [0.3×, 3×] 안). 파생 수정: 결측 불리언 피처가 sklearn passthrough에서 터지는 제품 버그 → `_build_bool_transformer` 신설(docs/debugging.md). 증거: `reports/s1_normal_s10/vae_flagrate.json`
- [x] ~~**Q2 결정: 금액 deny 해제**~~ → **S5로 이동** (§4 Q2 참조 — 판단 재료가 overlay 금액 설계라 S1 결정 불가·불필요. S1 측정은 현행 deny 그대로 수행)
- [x] 게이트 최소 정비 완료 (2026-07-17): ① ACC01 전표 단위 2축 재설계 — (a) 세액 전표에 부가세 계정 줄 존재 (b) 문서 단위 부가세줄 세액합÷공급가액 ∈ [9%,11%] — 합격판정 **r6 FAIL(미계상 37,765) / s10 PASS(중앙값 0.1000)** 달성. 원제안의 라인식은 오설계로 판명(정상 26% 오탐 — 세액이 거래줄·부가세줄 양쪽에 붙는 구조)해 문서식으로 교체 ② 항등식 M01/M03/M04/M07 → verdict()에서 INFO 강등(hollow-PASS 차단, M07 PASS→INFO 실측) ③ M02의 "FS 파일 없는 갈래"는 부존재 확인 — 원장 단독 회계등식 검사는 복식부기상 항등식이라 신설도 무의미, balance 사이드카 생성 전까지 BLOCKED 유지. 정비 후 게이트: **PASS 37 / FAIL 7 / BLOCKED 9 / INFO 4** — 남은 FAIL 7 전부 기지·보류(A07·B18·K08·M11·N07/09/10, 손익 재설계·v42 검토 연동). 증거: `reports/unit2_rescope/verifier_s10_gatefix.{json,md}`, `acc01_design_review.md` §구현 완료

### S2. 룰 단위시험 데이터 → 발화 능력 전수 확인 — ✅ **완료 (2026-07-17): 29/29 PASS**

**결과**: 활성 표면 29룰 전수가 자기 정답 문서에서 발화(표적 적중 기준, `reports/s2_unit_firing/adjudication.json`). 분모 확정: 레지스트리 35룰 − 비활성 확장 6(AA01~04·EV01/EV03 — 설정 게이트 기본 off, **AA02는 미구현 스켈레톤**) = 29 (`rule_denominator.json`). 데이터: 배경 FY2024 119,205행 + 표적 주입 74행/36문서 (`data/journal/unit/s2_unit_firing_20260717/`), 레시피·정답지 저장소 보존(`tools/scripts/s2_unit_recipes.py`·`s2_build_unit_dataset.py`·`s2_adjudicate_unit_firing.py`, 근거 명세 `firing_specs_a/b/c.json`). 1차 26/29 → 미발화 3건 전부 시험 장치 결함으로 판명·교정(L1-03: '999999'가 실제 CoA 등재 계정 / L2-03: exact 키의 타임스탬프·거래처 요건 미충족 / L3-12: 검토 신호 전용 채널을 판정기가 미독). **룰 결함 0건.**

**방식 = 정상 배경 + 룰별 표적 주입 (오버레이)**. S1이 "정상에서 조용한가"라면 S2는 "쏴야 할 때 쏘는가".

```
정본 base(s10_c001)                 룰별 주입 레시피(스크립트)          실제 파이프라인
FY2024 슬라이스 ─▶ [배경 ~12만행] ─▶ [+ 교과서 위반 전표 2~5건/룰] ─▶ [AuditPipeline] ─▶ 판정: 룰별 "자기 정답 전표에서 발화?" M/N
                                        │                                                 ▲
                                        └▶ 정답지 sidecar(rule_id↔document_id, 본체 무흔적) ┘
```

- **분모**: 문서의 "32" 불신 — 탐지기 레지스트리에서 스크립트로 추출해 파일로 고정(census, L1-09 유령 ID 재발 방지). L4-02(PHASE1-2)·PHASE2는 비대상.
- **배경**: 정본 base FY2024 연도 슬라이스(통계형 룰의 모집단 유지 + 실행 시간 절약). 정본 원본 무변경.
- **주입**: 룰 스펙(DETECTION_RULES.md) 근거의 최소 사례. 주입 스크립트·정답지 저장소 보관(재현 가능). 대안(datasynth 이상 모듈 주입)은 S5 성능 측정의 정본으로 남기고 S2엔 비채택(룰 1:1 커버리지 갭).
- **판정**: 전수 M/N 스크립트 exit 0 = 완료 선언. "발화했지만 다른 전표에서"는 실패로 센다(표적 적중 기준).

### S3. HIGH combo FSS 재구성 — **신규 아님, 마무리** ← **다음 작업 (재개점 2026-07-17)**

> **컴팩션 재개 노트 (2026-07-17)**: S0·S1·S2 완료 상태에서 S3 착수 직전.
>
> - **완료 상태**: S1 = 28룰 판정 PASS 27/FAIL 1(L4-03 이연·Q5 연동) + 게이트 정비(ACC01 재설계·항등식 4종 INFO) + VAE 플래그율 1.056% PASS(Q2는 S5로 이동). S2 = 활성 29룰 발화 29/29 PASS(분모: 레지스트리 35 − 비활성 확장 6, AA02 미구현 발견). 상세·증거·VERIFY는 본 문서 각 섹션 + 계약서(`.claude/state/contracts/e5adea09-*.md`) + `reports/s1_normal_s10/`·`reports/s2_unit_firing/`.
> - **정본 base**: `data/journal/primary/datasynth_semantic_v1_normal_s10_c001_20260717/` (재생성 불가 — 덮어쓰기 금지). 단위시험: `data/journal/unit/s2_unit_firing_20260717/`.
> - **S3 입력**: ① 코드반영 10건 목록 — 메모리 `project_high_combo_code_reflection_pending` + `docs/spec/HIGH_COMBO_GROUNDING.md`·`dev/active/phase1-rule-basis-audit/fss_case_combo_tagging.md`(발견 위치) ② HIGH-7(역분개+관계사, FSS 실증 0건) 유지/폐기 = **사용자 결정 필요** ③ 메모리 `project_phase1_high5_high9_recheck` 참조.
> - **미커밋**: 이번 세션 변경 전부 미커밋(사용자 요청 시만 커밋 원칙). 브랜치 `feature/l2-05-reversal-tolerance`.
> - **주의 습관**: datasynth 빌드는 nohup+Monitor(10분 캡), 측정 스크립트도 10분 초과 가능(같은 패턴). 대역/판정은 측정 전 선언. 문서 수정 후 U+FFFD 검사.

> **S3 전면 재정의 (2026-07-17, 사용자 확정)**: 구 계획(코드반영 10건 + HIGH-7 결정)은 **폐기**.
> tier 자동 등급(HIGH/MEDIUM/LOW/CONTEXT) 전면 폐지 → **조합 빌더 + 프리셋**으로 대체, 데이터정합성(L1-01~03)은 별도 패널.
> 결정 경위: FSS v3 재태깅(731행)으로 구 HIGH 조합의 "금감원 실증" 근거 붕괴(기말×추정 12~22건 외 전부 0~3건)
> + 합성데이터는 등급 근거 불가(자문자답) + 등급 선언 자체를 제거하면 방어할 휴리스틱이 0.
> 새 SoT: `docs/spec/PHASE1_COMBO_BUILDER_SPEC.md` (어휘 몸통10×특징10, 결합 의미론, 프리셋 4종, 폐지 목록, S4/S5 검증 계획).
> Q4(HIGH-7)는 tier 폐지로 소멸.

- S3 구현 단계: ① 빌더 엔진 ✅ ② tier 제거 ✅(핵심) ③ 대시보드 ✅ ④ 잔여 정리 대기 (2026-07-18 진행 기록)
  - ✅ ①: `config/combo_builder.yaml` + `src/export/phase1_combo_builder.py` + 계약 테스트 12개(`tests/modules/test_export/test_phase1_combo_builder.py`) 전부 PASS
  - ✅ ③: `dashboard/components/phase1_combo_builder_panel.py` 신설, tab_phase1 검토케이스 탭 주 큐를 빌더로 교체, 커버리지 표 tier 컬럼 제거. 정합성은 기존 별도 탭 유지
  - ✅ ②: `topic_scoring.py` 재작성(662→195줄 — combo floor 12종·특례 집합·fraud combo·HIGH/MEDIUM 생산 전부 삭제, LOW/CONTEXT는 standalone 게이트로만 잔존), case_builder 호출부 축소 + config floor 승격 삭제 + `_priority_band`/`_legacy_floor_tier`/`_fraud_combo_rule_scope`/floor plumbing 삭제. 계약 테스트 재작성(test_topic_tiers 전면·test_rule_scoring combo 블록·stage1 floor 4건·combo 기록 1건 → 폐지 계약)
  - **검증**: detection 1,095 PASS. 전 모듈 3,730 PASS / 실패 26+에러 8은 전수 확인 결과 **전부 기존 결함**(v7 구 데이터셋 경로 부재 14 · stage7 스크립트 부재 8 · 대시보드 리뷰큐/L4-02 기대 4 · RULE_CODES 68 카운트 낡음 · batch_reader duplicate 트랙 · phase2 leakage deny 54→57(s10 신설 컬럼 여파) 등). tier 제거 기인 신규 실패 0
  - ✅ **④ 완료 (2026-07-18)**: (a) tab_phase1 도달불가 구 6-탭 블록+tier 렌더 함수 삭제(310줄, `_VIOLATION_CASES_CAP` 상수 복원 포함) (b) phase1_case_view `build_phase1_transaction_queue`·`_unit_band_rank`·`_unit_sort_key` 삭제, coverage band 분해 → documents+units (c) Excel/PDF/Brief band 컬럼 제거 (d) 문서 supersede 3종(TIER_EVIDENCE_BASIS·TIER_SCORING_SPEC·RANKING_CRITERIA)+CLAUDE.md 로드맵·인덱스 갱신+debugging.md 기록+메모리 갱신 (e) 기존 실패 처리 방침 = 본 분류표 유지, S4 착수 전 별도 라운드(대부분 구 데이터셋 경로·스테일 계약이라 삭제/갱신 대상). 최종 검증: detection+export+dashboard+llm 1,868 PASS / 잔여 4 FAIL 전부 기존 결함(리뷰큐 2·L4-02 스테일 기대 2)
- **S3 종료.** 다음 = S4(빌더 정확성 단위시험 — S2 단위 데이터 재사용, 스펙 §7) → S5(FSS scheme overlay 성능 증거)

### S4. 빌더 정확성 단위시험 (구 "HIGH 조합별 발화 확인"은 tier 폐지로 재정의) ✅ **완료 (2026-07-18, exit 0)**

**진행 기록 (2026-07-18)**:

- **판정 스크립트**: `tools/scripts/s4_adjudicate_combo_builder.py` → `reports/s4_combo_builder/adjudication.json`. 검증 계약: V0a 엔진 evidence ⊆ 오라클(details/review 양 채널) fabrication 검사(HARD) / V0b 발화→표면 커버리지 실측(기록만) / V1·V2 결합 의미론 120셀(몸통10×특징10+단독20) 기본·엄격 모드 독립 재구현 대조(HARD) / V3 프리셋 4종+`build_combo_builder_result` 뷰 정합·top_n 절단(HARD) / V4 정답지(s2_expected.csv) 하한 — 어휘 20룰 단독 선택 시 표적 문서 일치(HARD).
- **최종 판정 PASS**: V0a 위반 0(36,804 units) / V1 120/120 / V2 120/120 / V3 4종 PASS / V4 20/20 (gate_excluded 0).
- **발견·수정한 결함 — L3-03 스테일 topic (1차 판정 FAIL 원인)**: `rule_detail_metadata.py` L3-03 entry가 `final_topic="intercompany_cycle"`(TOPIC_REGISTRY에서 2026-06-14 제거된 topic)을 유지 → `_collect_raw_hits`의 topic 게이트(phase1_case_builder.py:1368)에서 L3-03 hit **전량 탈락**(evidence 보유 unit 0, 자기 표적 문서조차 빌더 미매칭). rule_scoring 쪽은 account_logic으로 재배치됐는데 rule_detail_metadata만 갱신 누락 — rule_detail_metadata final_topic이 rule_scoring보다 우선 적용되는 구조라 치명. tier 시절엔 booster라 증상이 안 보였고 빌더 몸통(FSS 80건) 승격으로 표면화. 수정 = `final_topic="account_logic"`(중복되는 secondary 제거). 수정 후 evidence 보유 unit 0→199, 파급 테스트 179 PASS.
- **V0b 표면 유실 실측 → L2-05 룰 수정으로 해소 (2026-07-18 사용자 확정)**: ① 최초 실측 **L2-05 발화 135 문서 중 109 유실** — detector(c11 path B: 계정+동액+45일)는 발화하지만 flow 승격 게이트(context_score≥2)에서 탈락 + L2-05는 `_FLOW_UNIT_RULES`라 document unit에서도 제외. 사용자 결정("아예 룰을 수정해버려")으로 2단 수정: (1) **context_score 게이트 폐기**(phase1_case_builder.py `_l205_one_to_one_pairs`) — 적요·작성자까지 닮는 역분개는 ERP 자동 역분개(path A가 이미 커버)고 수기 은폐형일수록 탈락하는 역선택이었다. 점수는 link_key 참고 정보로만 잔존. (2) **document unit fallback**(`_build_document_units`) — flow 승격 탈락 L2-05 발화는 document unit에 적재(absorbed 문서는 기존 분기가 걸러 이중 적재 없음). 결과: 유실 109 → 45(게이트 폐기) → **2**(fallback, disjoint dedup이 복수 쌍 상대를 버리는 경우 해소). 잔여 2건 = L2-02 flow에 흡수된 문서(표면에는 존재, L2-05 표시만 해당 unit에 없음 — flow 간 상호 흡수 미지원 한계, 기록만). 최종 S4 전 축 PASS 재확인, 파급 테스트 78 PASS. 스펙 반영: DETECTION_RULES.md L2-05 "검토 표면화" 절 신설. ② L3-04 436/16,980·L3-06 110·L3-05 94·L4-03 86 등 1~3% 소량 유실 — `_case_candidate_index_labels`의 risk_level Normal 게이트(aggregate 단계) 잔재로 추정, 실측치만 기록(adjudication.json v0b_surface_coverage).

### ~~S4 재개 노트~~ (완료로 대체) — 원문 보존

> **컴팩션 재개 노트 (2026-07-18)**: S0·S1·S2·S3 완료 상태에서 S4 착수 직전.
>
> - **S3 완료 요약**: tier 자동 등급(HIGH/MEDIUM/LOW/CONTEXT) **전면 폐지** → 조합 빌더+프리셋 대체(2026-07-17 사용자 확정, 07-18 구현 완료 — 상세·검증·잔여실패 분류표는 §S3 진행 기록 참조). **새 SoT = `docs/spec/PHASE1_COMBO_BUILDER_SPEC.md`** (어휘 몸통10×특징10·결합 의미론·프리셋4·폐지 목록·S4/S5 검증 계획).
> - **S3 산출 핵심 파일**: 엔진 `src/export/phase1_combo_builder.py` + 어휘 `config/combo_builder.yaml` + UI `dashboard/components/phase1_combo_builder_panel.py` + 계약테스트 `tests/modules/test_export/test_phase1_combo_builder.py`(12개). topic_scoring.py는 195줄로 재작성(LOW/CONTEXT = standalone 게이트만, 등급 아님). `priority_band` 필드는 "low" 고정 deprecated(artifact/PHASE2 호환).
> - **S4 할 일 (스펙 §7)**: S2 단위시험 데이터(`data/journal/unit/s2_unit_firing_20260717/` + 정답지 `labels/s2_expected.csv`) 재사용 → 파이프라인 실행 후 빌더 조합 선택별 일치 전표 집합을 정답지와 대조. 검증 축: ① 그룹 내 OR/그룹 간 AND 기본 모드 ② 엄격 모드 ③ 프리셋 4종 ④ 몸통만/특징만 모드. 판정 스크립트는 `tools/scripts/s2_adjudicate_unit_firing.py` 패턴(양 채널 독취 — details + metadata["review_score_series"]) 참고해 s4_* 신설. exit 0 = 완료 선언(census 원칙).
> - **정본 base**: `data/journal/primary/datasynth_semantic_v1_normal_s10_c001_20260717/` (재생성 불가 — 덮어쓰기 금지, data/는 gitignore 이력 0).
> - **미커밋**: 186파일, 브랜치 `feature/l2-05-reversal-tolerance`. 커밋은 사용자 요청 시만(AI 문구 금지).
> - **기존 실패 정리 라운드(S4 착수 전 권장)**: 전 모듈 3,730 PASS / 잔여 실패 26+에러 8은 전부 S3 이전 기존 결함 — 분류표 §S3. 대부분 삭제된 구 데이터셋 경로(v7 계열)·부재 스크립트(stage7)·스테일 계약(RULE_CODES 68, L4-02 revenue 기대, 리뷰큐 render_candidate_card, phase2 leakage deny 54→57=s10 신설 컬럼 여파).
> - **습관 주의**: PHASE1 전수 측정·datasynth 빌드는 10분 캡 초과 → nohup+Monitor. 문서 편집 후 U+FFFD 검사. 포맷터 훅이 편집마다 재정렬 — 테이블은 공백 연속 없는 짧은 고유 조각으로 편집.

### S5. FSS scheme overlay × seed 3~5 — **성능 증거는 여기서만** ← 진행 중 (2026-07-18)

- base는 그대로 두고 overlay 데이터셋 별도 생성 (r6처럼 base 안에 섞지 않는다 — D2)
- 기존 자산: scheme 카탈로그 FS01~14, `phase2-real-schemes`/`phase2-fraud-r1` 프로파일
- 시드 회전 원칙(`tools/datasynth/CLAUDE.md`): 같은 base·같은 밀도·다른 배치, 평가는 합산, 데모는 1개
- 종료: PHASE1 과탐·미탐 + VAE 성능, seed 합산으로 보고

**진행 기록 (2026-07-18)**:

- **overlay 생성기 s10 정합 재작업 (완료)**: 첫 생성에서 shortcut 게이트 5 FAIL — `phase2_scheme_overlay.rs`가 구 base(v42j) 전제(3개 법인 C001~C003, 6자리 확장계정 23종 도입, subtype 하드코딩)라 s10(단일 법인 C001, 4자리 39계정, semantic_account_subtype 신설)과 전면 충돌. Rust 근본 수정(2190→1768줄): ① transaction_for 계정 매핑을 s10 실존+정상 다사용 계정 22종으로 전면 교체(신규 계정 도입 폐기 — NEW_ACCOUNTS 삭제, 정상 문서수 희소한 1300·3200·4500·6300 사용 금지) ② 회사 C001 고정, FS05 순환·FS11/FS13 관계사를 base 관행(trading_partner='C002'/'C003' + is_intercompany='true')으로 재설계 ③ 부정 행 subtype = base 실측 사전 조회(미존재 계정 즉시 에러) ④ IC sidecar 하드코딩 제거(편측 부정 IC는 매칭 시스템 미기재가 현실적). 게이트 스크립트 세대교체(임계 TH_* 불변): EXT_ACCOUNTS 빈 목록(신규 계정 도입 폐기로 검사 대상 소멸 — 계정 지름길은 S2 precision이 감시), S8 화이트리스트 재산정, S14 FS05 원환 = 회사수→관계사 파트너 기준, seed diversity 배정 벡터 = 회사→trading_partner(단일 법인화로 회사 축 소멸 — 파트너 회전은 실측 확인 후 교체).
- **데이터셋 4종 완성**: `datasynth_semantic_v1_phase2_fraud_s10_20260718_r1`(대표본) + `_seed1~3`. 각각 14 scheme × 부정 330 문서(+660행), 밀도 0.29%. 대표본·seed1 shortcut 게이트 16종 ALL PASS, regression 클린(base 무수정·자기상쇄 0·불균형 0), seed diversity PASS(내용 100% 상이·거래처 배정 전 쌍 상이). 독립 스팟체크(에이전트 셀프채점 방지): 부정 행 회사 C001 유일·base 밖 계정 0·subtype 사전 불일치 0·차대 불균형 0.
- **운영 주의**: overlay 생성을 3개 병렬로 돌리면 10분 캡 초과로 killed — 단독 실행 시 수 분. 전수 측정(s5_measure_builder_performance.py)은 데이터셋당 10분+라 nohup+Monitor 필수.
- **PHASE1 빌더 성능 측정 완료 (2026-07-18)**: 결과 SoT = `reports/s5_fraud_overlay/BUILDER_PERFORMANCE_SUMMARY.md`. 요지 — 표면 커버리지 59.7~61.8%(seed 4 일관), 프리셋 적중: 역분개·은폐 85~103(12~13 scheme, 표면 1.08만) / 비용자산화 20~25(밀도 8.7~10.6% 최고) / 수익인식 6~10 / 추정·관계사 7~11. 측정 중 발견·수정: **L3-10 추정계정 s10 목록 갭**(D10이 2220만 반영 — 대손 6900·감가 6000·무형상각 6050·상각누계 1510 추가, `config/audit_rules.yaml`, 적중 0~2→7~11). 무반응·미표면의 원인 분해(L4-01=금액 도메인 귀결, FS05 순환·FS14 유령급여=PHASE1 구조적 한계로 PHASE2/거래처 축 몫, 위장 컴포넌트 ~40%=설계 의도)는 요약 보고서 §3.
- **VAE 측정 완료 — 행 단위 VAE 검증 실패로 기록 (2026-07-18 사용자 확정)**: seed 4 합산 문서 AUROC 0.5187 / recall@top1% 0.0038 / PHASE1 미표면 회수 2건. 합성데이터 경로로는 행 단위 비지도 탐지를 검증할 방법이 없음(흔적 심으면 자문자답·안 심으면 정보 부재로 무반응 — 어느 쪽도 성능 증거 불가). 실패 원인 분해와 빅4 도구 조사(EY GLAD=지도학습, KPMG Clara=MindBridge 앙상블, PwC Halo=룰+의심점수, Deloitte Omnia=기준 분석 — "룰 주력+ML 보조"가 실무 관행)가 산출물. 상세 = `reports/s5_fraud_overlay/BUILDER_PERFORMANCE_SUMMARY.md` §4.
- **Q4→Q2 결정 (2026-07-18)**: VAE 금액 deny **유지** — overlay 금액 설계가 정상 분포 내 은폐로 확정, 해제해도 부정 신호 기여 정보 없음(raw amount 입력에도 무반응) + 고액 정상 과탐 축만 추가.
- **순환형(FS05) 단일 법인 한계 확정 (2026-07-18)**: 원환(A→B→C→A) 탐지는 자금 네트워크 전체가 보이는 시점(은행·감리당국·연결 실체) 전제라 단일 법인 GL로는 원리상 불가능 — GNN 문헌도 그 전제 위 결과라 본 프로젝트 범위 미적용. 단일 법인의 상한 = 순환 단면 신호(관계사 매출·매입 양방향 대칭·기말 집중)를 검토 신호로 올리는 것까지, 실물 대사는 감사인 절차 몫(FSS 감리 방식과 동일).
- **S5 종료.** 다음 = S6(포트폴리오 결과 문서화).

### S6. 결과 문서화 (포트폴리오 제출물) ✅ 핵심 산출물 완료 (2026-07-18)

**완료**: ① `docs/guide/VALIDATION_RESULTS_2026-07.md` 작성(234줄 — 3-surface 검증 상태 표·방법론·룰 표면 성공 수치·VAE 실패 기록·원리적 한계·빅4 정합·재현 방법 7절. 금지 표현 0·링크 17개 실존·U+FFFD 0 검수 통과) ② 문서 인덱스 반영(CLAUDE.md 최신 결과 표·PROJECT_OVERVIEW §활성 문서 인덱스 — 겸사 구 tier 3종 활성 락 표기를 SUPERSEDED로 정정). **잔여(별도 회차)**: README 전면 개작(readme-maker 인터뷰 필요).

**스코프 (2026-07-18 확정)**:

1. **검증 결과 종합 문서** `docs/guide/VALIDATION_RESULTS_2026-07.md` — 포트폴리오 본문. 3-surface 구조가 "왜 이렇게 생겼는지"를 검증 여정(S2 룰 단위시험 → S3 tier 폐지·조합 빌더 → S4 빌더 exit 0 → S5 fraud overlay 성능 실측)과 수치로 서술. 성공(룰 표면)과 실패(행 단위 VAE — 합성 경로 검증 불가)와 원리적 한계(순환형 단일 법인)를 전부 명시. 빅4 도구 조사로 실무 정합성 매듭.
2. 활성 문서 인덱스 반영(CLAUDE.md·PROJECT_OVERVIEW §활성 문서 인덱스).
3. README 전면 개작은 별도 회차(readme-maker 인터뷰 필요)로 분리 — 본 회차 범위 아님.

**원칙**: CONSTRAINTS 포트폴리오 주장 범위 준수(금지 표현 — "부정을 정확히 탐지"·"운영 성능 검증 완료" 류 금지), truth 수치는 개발 검증 보조 지표로만, 실패·한계를 숨기지 않는 서술이 본 문서의 정체성.

## 4. 열린 질문

| #   | 질문                                                                                       | 결정 시점                                                                                                             |
| --- | ------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------- |
| Q1  | 단일법인 전환 방식 (S0-2의 a/b/c)                                                          | S0 측정 직후                                                                                                          |
| Q2  | VAE 금액 deny 해제                                                                         | **S5로 이동** (2026-07-17 — 판단 재료가 overlay 금액 설계라 S1엔 결정 불가. S1 플래그율은 현행 deny 설정 그대로 측정) |
| Q3  | ACC01 수정안 구현 (제안만 있음)                                                            | S1 게이트 정비                                                                                                        |
| Q4  | ~~HIGH-7 유지/폐기~~ → tier 폐지로 소멸(2026-07-17)                                        | S3                                                                                                                    |
| Q5  | 손익 비율(`target_gross_margin` 배선) — D4로 보류 중. 포트폴리오 신뢰성 관점에서 재론 가능 | S5 이후                                                                                                               |

## 5. 파일 지도

| 무엇                               | 어디                                                                                                   |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------ |
| **진짜 normal base 설정**          | `artifacts/datasynth_normal_semantic_v1_20260603.yaml` (무수정 사용, git 비추적)                       |
| 참고: manipulation base 설정       | `artifacts/datasynth_manipulation_normal_base_20260602.yaml`                                           |
| 생성기 바이너리                    | `tools/datasynth/target/release/datasynth-data.exe` (`generate --config <yaml> --output <dir>`)        |
| 검증기 (realism 게이트 57종)       | `tools/scripts/normal_data_realism_verifier_20260603.py`                                               |
| ACC 계정 검사 9종                  | `tools/scripts/normal_realism_account_checks.py` (git 미추적 주의)                                     |
| 계정결정 표 (Unit 1 산출)          | `tools/datasynth/crates/datasynth-generators/config/account_determination.yaml`                        |
| 현재 normal (교체 대상, 원본 보존) | `data/journal/primary/datasynth_semantic_v1_normal_20260703_v53_account_determination_r6/`             |
| 오늘 근거 문서 3종                 | `reports/unit2_rescope/` — `sidecar_consumers.md` · `amount_scale_rules.md` · `acc01_design_review.md` |
| 세션 계약서 (측정 상세)            | `.claude/state/contracts/820fd827-*.md`(Unit1) · `e5adea09-*.md`(재범위화)                             |
| 룰 레지스트리                      | `src/detection/rule_scoring.py` (`RULE_SCORING_REGISTRY`, 32룰)                                        |
| VAE deny 목록                      | `src/preprocessing/constants.py:63-118`                                                                |

## 6. 여정 이력 (과거 — 본문과 분리)

- **v42 덧칠 시대 (~2026-07)**: base 생성 후 `normal-coa-v42` 프로파일이 원장 40여 회 변형 + 사이드카 하드코딩으로 r6을 만들었다. C06 게이트가 결과만 보고 방법을 안 봐서 fitting(normalize_v53 최빈계정 강제치환)을 유발했다. Unit 1(계약서 820fd827)이 계정결정 표를 생성기에 넣어 덧칠의 존재 이유를 소멸시켰다.
- **2026-07-15 재범위화**: "재무 사이드카 9개 포팅"이던 U2-1이 소비처 0/299로 폐기 방향 확정. 금액 1,223배 사고가 설정 유실로 판명. Unit 2의 "회귀 28개" 명세는 유실 데이터 기준이라 무효.
- **2026-07-16 목표 확정**: 입사용 포트폴리오, PHASE1-1/1-2 + VAE. 본 플랜 수립.
