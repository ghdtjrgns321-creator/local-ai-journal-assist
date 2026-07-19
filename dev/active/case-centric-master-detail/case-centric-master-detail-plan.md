# PHASE1 룰별 위반 표시 — Case-Centric Master/Detail 재구성

## 배경

현재 PHASE1 룰별 expander의 표는 전표(document) 단위로 행을 펼치고, 각 전표의 "Case Band" 컬럼에 그 전표가 속한 case의 priority_band를 그대로 상속해 표시한다. 결과적으로 차이 2원짜리 전표가 "high"로 보이는 등 **개별 전표의 위험 신호와 case 단위 위험도가 시각적으로 일치하지 않아** 감사인이 의미를 잃는다.

또한 expander 헤더 `(case High 15 · Low 2 · 전표 230건)` 는 case와 document 단위가 다름을 알리지만, 표 자체가 여전히 전표 단위라 헤더 정보와 표 정보의 단위가 어긋난다.

## 목표

룰별 expander를 **case 1차 / 위반 전표 2차 / 하이라이트 원장 3차** 3단 master/detail 구조로 재편한다. case 자체가 PHASE1의 위험 평가·검토 단위이므로 표의 1차 행도 case가 되어야 자연스럽다.

## 새 흐름

```
룰 expander 펼침
  └─ ① case 목록 표 (master 1)
        · 자연어 라벨 (theme별 템플릿)
        · 전표 수, 합계 금액, priority_band, 위험 사유 한 줄
        └─ case 행 클릭
              └─ ② 그 case 안 위반 전표 목록 (master 2)
                    · 전표번호, 위반 요약, 거래금액, 룰별 보강 컬럼
                    · Case Band 컬럼 제거 (같은 case 안에서는 모두 동일하므로 무의미)
                    └─ 전표 행 클릭
                          └─ ③ 그 전표의 하이라이트 원장 라인 (detail)
                                · 기존 _render_raw_lines_table 그대로 재사용
```

## 단계별 작업 (5단계)

### Step 1. theme별 자연어 라벨 함수 + 코드→한글 매핑 사전

`case_key_parts` (dict) 를 자연어 한 줄로 변환하는 헬퍼.
8 theme 분기 + 코드→한글 사전 (`account_family`, `business_process`, 일부 신규 매핑은 신설 필요).

| theme | 라벨 템플릿 |
|---|---|
| logic_mismatch | `{년월} {전표유형} 전표 {계정군} 위반 N건 · {합계}` |
| control_failure | `{작성자}가 {년월} {업무프로세스}에서 통제위반 N건 · {합계}` |
| access_scope_review | `{작성자}({사용자유형})가 {년월} 권한범위 위반 N건 · {합계}` |
| timing_anomaly | `{작성자}가 {기말 ±N일 윈도우} {계정군}에서 의심거래 N건 · {합계}` |
| duplicate_or_outflow | `{거래처}와 {금액대} 거래 중복·유출 의심 N건 · {합계}` |
| intercompany_structure | `{회사쌍}-{거래처} {년월} 그룹간 거래 N건 · {합계}` |
| statistical_outlier | `{년월} {업무프로세스}-{계정군} 통계 이상 N건 · {합계}` |
| data_integrity_failure | (Step 5에서 보강 후 결정) |

배치: 신규 모듈 `dashboard/components/case_label.py` 또는 `src/export/phase1_case_label.py`. 후자가 export 영역과 일관성 있음.

### Step 2. case 단위 master 표 렌더러

신규 함수 `_render_rule_case_master(rule_id, cases, *, pr, key_suffix)`.
- `phase1.cases` 에서 해당 룰을 가진 case만 필터.
- AgGrid single selection.
- 컬럼: `자연어 라벨 / 전표 수 / 합계 / Band / 위험 사유 한 줄`
- 정렬: priority_band rank → 합계 금액.

### Step 3. case 클릭 시 그 case의 위반 전표 목록 master

선택된 case_id로 `build_phase1_rule_documents` 결과를 필터링.
- 기존 `_build_master_display` 재사용 가능 — `priority_band` 컬럼만 제거 (같은 case 안에서는 모두 동일하므로 의미 없음).
- AgGrid single selection.

### Step 4. 전표 클릭 시 하이라이트 원장 detail

`build_phase1_rule_document_detail` + `_render_raw_lines_table` 그대로 재사용.
기존 `_render_rule_master_detail` 의 detail 패널 부분을 분리해 case → 전표 선택 흐름에 연결.

### Step 5. data_integrity_failure theme case_key 보강

L1-01·L1-02·L1-08은 명시적 case_key가 없어 fallback `(company, doc_type, load_batch)`을 사용. 식별력이 약함.

옵션:
- **A**: `_make_case_key_parts` 에 `data_integrity_failure` 분기 추가 — `(company, doc_type, period_month)` 또는 `(period_month, account_family)`.
- **B**: 이 theme은 case 묶음 의미가 약하므로, master 표를 case 대신 룰 직접(=현재 구조)으로 두고 1·2·3·4 구조에서 예외 처리.
- 결정은 Step 4 완료 후 실데이터 확인하면서 정한다.

## 회피할 것

- Case Band 컬럼을 전표 단위 표에 다시 넣지 말 것 (혼동의 원인).
- master 표를 너무 정보 밀도 높게 만들지 말 것 — 자연어 라벨 + 핵심 3개 숫자(전표수·합계·band) + 사유 한 줄로 한정.

## 영향 범위

- `dashboard/tab_phase1.py` — `_render_rule_master_detail` 및 호출부 2곳 (`_render_dq_rule_expanders` 1805, `_render_topic_rule_expanders` 1948).
- 신규 모듈 1개 (자연어 라벨).
- `src/detection/phase1_case_builder.py` — Step 5 결정에 따라 `_make_case_key_parts` 분기 추가 가능성.

## 검증

- L1-08 (data_integrity_failure) 17 case → 자연어 라벨 17개가 사람이 읽을 수 있는 형태인지 확인.
- L1-04 (control_failure) — 작성자 기반 case 라벨 검증.
- L2-03 (duplicate_or_outflow) — 거래처·금액대 case 라벨 검증.
- 각 theme에 속한 룰 1개씩 샘플 검증.
