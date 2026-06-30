# 통합 쓸모 벤치마크 — FSS 부정주입 설계

작성일: 2026-06-30. 출처: 설계 grill 9턴 합의(이 세션). 본 문서가 설계 SoT.

## 0. 한 줄 정의

정상 합성 장부에 **FSS 실제 부정사례를 기전(mechanism) 그대로 재구성한 전표**를 심고, **3 surface(PHASE1-1 / PHASE1-2 / PHASE2)가 각각 얼마나 잡는지**를 단계별로 측정하는 end-to-end 쓸모 벤치마크. 단일 병합 리콜이 아니라 surface별 catch 분해다(3-surface 불변식 호환).

> 이 벤치마크는 **"이미 모델링한 유형의 부정을 잡는가"**를 증명한다. 생성도 룰도 같은 FSS 출처에서 나오므로, 높은 catch는 프로젝트가 감사지식을 잘 인코딩했다는 증거이지 **미지 부정으로의 일반화 증거가 아니다.** 이 한계를 최종 리포트에 명시한다.

## 1. 잠금 결정 9개

### ① 목적 — end-to-end 단계별 catch
룰별 발화·조합 tier 정확성은 별도 datasynth가 담당(이 벤치마크 범위 아님). 여기선 "프로젝트 전체가 실제 부정을 어느 단계에서 얼마나 올리나"만 측정.

### ② 모집단 — FSS in-scope 부분집합 (population-first)
- 권위 출처: `dev/active/phase1-rule-basis-audit/fss_case_combo_tagging.md` (474건 전수 태깅).
- **in-scope 판정 = "실제 전표 조작이 존재하는가".** tier `N/A(전표무관)` 및 `전표 조작 없음` LOW(대손충당금 과소·손상 미인식·공시누락 등 추정/정책/공시 오류)는 **심을 부정 전표 자체가 없으므로 out-of-scope.**
- out-of-scope 처리: 헤드라인 recall **분모에서 제외**하고, 별도 **blind-spot 표**로 정직하게 분리 집계(§10 음의공간). GL-only 범위 밖(가공거래처 HIGH-6·재고 HIGH-8·연결조정 HIGH-10)도 같은 분리.
- 유형 빈도가 곧 모집단 가중치: 사례를 충실히 재구성하면 "가공매출 N건·횡령 M건"이 실제 빈도로 반영됨(별도 stratification 불필요).

### ③ 번역층 — (나) 기전 엔진, rule-blind, freeze
FSS 서사 → 전표는 **손으로 빚지 않는다(타우톨로지·소N 금지).** 서사에서 **기전만 추출**(자금흐름·우회통제·오용계정·시점)해 기전기반 생성기에 먹이고 룰을 모른 채 전표를 생성.
- **rule-blind freeze**: 기전 spec 추출은 FSS 원문+감사기준만 보고, 탐지 결과 보기 **전에 동결**. 룰 발화조건 참조 금지.
- **이음새 제거**: 식별자 형식·reference 범위·승인자 풀·시점 분포가 정상과 같은 모집단. 부정 전표를 "붙이지" 않고 정상 파이프라인 안에서 생성.

### ④ surface 분리 — 채점 시점 매트릭스 (생성은 surface-blind)
케이스를 surface로 칸막이 치는 건 **생성이 아니라 채점에서.** 부정은 surface 모르고 생성. 사례별 "어느 surface가 잡아야 한다"는 **사전등록 예측(expectation)**으로 별도 기록(생성 지시 아님, 검증할 가설). 채점은 **scheme × surface 커버리지 매트릭스.** 한 scheme이 여러 surface에 동시에 잡히는 게 정상(defense in depth). "어느 단계에서 얼마나" = 매트릭스 surface별 열 합.

### ⑤ catch 정의 3종 — surface별 조작적 정의(사전등록 임계)
| surface  | "잡았다" 정의                                                         | 단위     |
| -------- | --------------------------------------------------------------------- | -------- |
| PHASE1-1 | scheme 전표 ≥1건이 named 룰 발화(review queue 진입)                   | scheme   |
| PHASE1-2 | scheme의 계정/사용자/거래처가 flagged 버킷 포함(Benford·D01/D02·배지) | 엔티티   |
| PHASE2   | scheme 전표가 TOP-K 진입, **K=상위 1%**(리뷰예산)                     | recall@K |
- 헤드라인 단위 = **scheme-level**(전표 1건만 surface돼도 감사인이 실을 당김). document-level은 보조.
- PHASE2는 K=1% 헤드라인 + 곡선(0.5%·1%·5%) 병기. K는 결과 보기 전 동결, 사후조정 금지.
- PHASE1-2 임계는 이미 lock된 detector 값 그대로(재튜닝 금지).

### ⑥ 빈칸 분류 A/B/C/D — 사례 분석의 산출물
빈칸을 **랜덤 일괄**로 채우면(B 오용) 논리 모순 분개가 나온다. 4분류로 각각 다르게:
| 종류       | 정의                  | 채우는 법                                | 5벌 사이     |
| ---------- | --------------------- | ---------------------------------------- | ------------ |
| A 기전고정 | 부정 정체성이 강제    | 사례 분석으로 고정                       | 동일         |
| B 정상풀   | 부정 무관, 안 튀면 됨 | 정상 데이터 **조건부**(공동출현) 추출    | 다시 뽑음    |
| C 범위     | 자유롭되 현실 범위    | 범위 안에서만 추출                       | 범위 내 다시 |
| D 상태의존 | 실재 장부 대상 참조   | 실시간 장부 상태에서 선택, 지어내기 금지 | 상태 따라    |
- **조건부 추출**: B/C는 고정된 A값에 맞는 것끼리(가수금↔그 계정과 공동출현하는 거래처·승인자). 독립 추출 금지.
- A·C·D 분류와 값/범위는 탐지 결과 보기 전 **동결**. B는 정상추출이라 안전.

### ⑦ 정합 검증 — 3층 오라클 + "spec 선언 위반만 깸"
정적 체크리스트만으론 상태 결함(없는 매출채권 갚기)을 못 잡는다. 3층:
| 층         | 본다                            | 도구                                                            |
| ---------- | ------------------------------- | --------------------------------------------------------------- |
| 1 한 줄    | 차대균형·계정짝·거래처-계정     | 정적 체크리스트                                                 |
| 2 줄 사이  | 갚을 invoice·되돌릴 원전표 실존 | `tools/scripts/audit_document_flow.py`                          |
| 3 장부상태 | 없는 AR 갚기·불가능 잔액        | `tools/scripts/audit_balance_integrity.py`, `audit_temporal.py` |
- **1차 방어 = 상태 인지 생성**(존재하는 것만 골라 건드림). 오라클은 그물.
- **핵심 정의**: *부정 전표는 자기 spec이 "깬다"고 선언한 규칙만 깨고 나머지 정합은 전부 지킬 때 정상이다.* spec 선언 위반=의도된 부정(truth), spec 밖 위반=사고=재생성. 사고 0건이어야 통과.
- **truth 정의 겸함**: "이 전표가 일부러 깬 규칙 목록" = "왜 부정인가"의 정답.
- **LLM 역할**: 게이트 아님. 표본으로 의미적 타당성·번역 충실성만 보완 점검. 발견 결함은 오라클 규칙으로 굳혀 재현화. (재현성 없는 LLM 판정을 truth 게이트로 쓰지 않음.)

### ⑧ 변형 = 위치만, 모의고사 5벌
사례의 금액·은닉·범위는 **실제 사건 그대로 충실 복원·동결**(난이도 임의 비틀기 금지 — 허구 측정). 변하는 건 **숨긴 위치뿐**(어느 회사·달·주변 정상 속, B/C 재추출). 모의고사 **5벌**(각 벌에 in-scope 사건 전부를 다른 위치로), 합산 채점 + 벌 사이 점수 안정성 확인(흔들리면 운빨=발견).

### ⑨ 합격 기준 — 진단 리포트 + 바닥선 게이트
PHASE1 역할원칙상 리콜은 보조지표. 따라서:
- **주 산출 = 진단 리포트**(어느 단계가 어디서 약한지 scheme×surface 매트릭스).
- **유일한 HARD 게이트 = "범위 내 scheme은 최소 1개 surface가 잡아야 한다"**(0 surface = 결함). 범위 밖은 게이트 면제.
> 이 기준에 이의 있으면 본 섹션을 수정하고 후속 재합의. (사용자 수용: 2026-06-30, 명시적 재확인 대기)

## 2. journal 46컬럼 빈칸 분류표

스키마 SoT: `config/schema.yaml` (Header 31 + Line 15 = 코어 46 + 라벨/clearing sidecar). 분류: 자동=엔진계산 / A·B·C·D=§1⑥.

| #   | 컬럼                     | 분류 | 근거                                     |
| --- | ------------------------ | ---- | ---------------------------------------- |
| 1   | document_id              | 자동 | 엔진 순차·정상형식                       |
| 2   | company_code             | A    | 단일법인 고정(또는 base 회사)            |
| 3   | fiscal_year              | 자동 | posting_date 파생                        |
| 4   | fiscal_period            | 자동 | posting_date 파생                        |
| 5   | posting_date             | C    | 기전 window(결산/심야/업무시간) 내       |
| 6   | document_date            | C    | posting 근처 범위                        |
| 7   | document_type            | A    | 기전 결정(SA수기/DR매출/KR매입…)         |
| 8   | gl_account               | A    | 기전 핵심(가수금/매출/선급금…)           |
| 9   | debit_amount             | C    | 중요성 위~회사 규모 범위                 |
| 10  | credit_amount            | C    | 차대균형, 9에 종속                       |
| 11  | currency                 | 자동 | KRW                                      |
| 12  | exchange_rate            | 자동 | 1.0                                      |
| 13  | reference                | D    | PO/GR/Invoice 실재 참조                  |
| 14  | header_text              | B    | 적요 정상풀(튀면 안 됨)                  |
| 15  | created_by               | B    | 페르소나 풀(기전이 대표이사면 A제약)     |
| 16  | user_persona             | A    | 기전: 횡령범 직급 고정                   |
| 17  | source                   | A    | 기전: 가공=Manual(L3-02 트리거)          |
| 18  | business_process         | B    | 계정 종속 정상풀                         |
| 19  | counterparty_type        | B    | 정상풀(관계사 기전이면 A제약)            |
| 20  | ledger                   | 자동 | 0L                                       |
| 21  | approved_by              | B    | 정상풀(자기승인 기전이면 =created_by, A) |
| 22  | approval_date            | C    | posting 근처(급속승인 기전이면 제약)     |
| 23  | is_fraud                 | 자동 | truth 라벨=true                          |
| 24  | fraud_type               | A    | 기전 유형 라벨                           |
| 25  | is_anomaly               | 자동 | truth                                    |
| 26  | anomaly_type             | A    | 기전 라벨                                |
| 27  | sod_violation            | A    | 의도위반 플래그(승인우회 truth)          |
| 28  | sod_conflict_type        | A    | 의도위반 유형                            |
| 29  | has_attachment           | B    | 정상풀(증빙없음 기전이면 A)              |
| 30  | supporting_doc_type      | B    | 정상풀(위조증빙 기전이면 A)              |
| 31  | delivery_date            | C    | WE전표 컷오프 범위                       |
| 32  | invoice_amount           | 자동 | supply×1.1                               |
| 33  | supply_amount            | C    | 금액 종속 범위                           |
| 34  | ip_address               | B    | 정상풀                                   |
| 35  | document_number          | 자동 | company+year+seq                         |
| 36  | line_number              | 자동 | 라인 순차                                |
| 37  | local_amount             | 자동 | =amount(KRW)                             |
| 38  | cost_center              | B    | 정상풀                                   |
| 39  | profit_center            | B    | 정상풀                                   |
| 40  | line_text                | B    | 적요 정상풀                              |
| 41  | tax_code                 | B    | 계정 종속 정상풀                         |
| 42  | tax_amount               | 자동 | supply×0.1                               |
| 43  | trading_partner          | A/D  | 관계사 기전=A, 실재거래처=D              |
| 44  | auxiliary_account_number | D    | 보조원장 실재                            |
| 45  | auxiliary_account_label  | D    | 보조원장 실재                            |
| 46  | is_suspense_account      | A    | 기전: 가수금이면 true                    |
| (s) | amount_open              | C/D  | 미결산 잔액(state)                       |
| (s) | is_cleared               | A/D  | clearing state                           |
| (s) | settlement_status        | A/D  | clearing state                           |
| (s) | lettrage                 | D    | 대사그룹 실재                            |
| (s) | lettrage_date            | C/D  | 대사일(state)                            |

집계: 코어 46/46 분류 완료 — 자동 12 / A 12 / B 13 / C 8 / A·D 혼합 1(#43). (s)=clearing sidecar 5종 별도. 줄당 **손이 가는 건 A+C+D ≈ 13**, 나머지는 자동·B(조건부추출).

## 3. 스코프 현실치(2026-06-30 부분확인)

- FSS 474건 중 **in-scope = "전표조작 실존" 부분집합 ≈ 절반 안팎(150~230 추정).** 정확치는 T1 전수 집계로 확정(아직 80/474만 확인 — 미확인 394건).
- 사례는 6대 패턴으로 군집(가공전표/수익통계·횡령은폐/중복자금유출·결산수정/결산시점·승인SoD·계정분류·비용자산화). → **180 수작업 아님, ~15 파라미터화 scheme 템플릿.**
- 기전 엔진 기보유: `embezzlement`(횡령은폐)·`revenue_manipulation`(가공전표)·`kickback`. 증설 필요 ≈ 4(결산수정·가수금은닉·승인우회·비용자산화).

## 4. 미해결 / 검증 부채

- [확정전제] 이 multi-stage scheme 엔진(`anomaly/schemes/`)이 실제로 journal CSV를 만드는 활성 생성기인지 미확인(grep상 컬럼 번역부 0건). T0에서 생성기 경로 확정 필요 — 아니면 어디가 찍는지부터.
- in-scope 정확 N: T1 전수 집계 전까지 추정치.
- 합격기준 ⑨ 사용자 명시 재확인 대기.
