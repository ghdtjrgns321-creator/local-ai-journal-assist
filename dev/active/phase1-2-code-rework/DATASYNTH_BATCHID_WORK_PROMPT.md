# 작업: 자동 계열 전표에 batch_id·job_id 부여 (Rust 생성기)

> 이 프롬프트는 datasynth(Rust 생성기) 컨텍스트 전용이다. 한국어로 보고할 것.

## 1. 목표

- automated/recurring/batch/interface/system 계열 source 전표에 **batch_id와 job_id를 둘 다**
  부여한다(같은 배치 실행에 속한 문서끼리 동일 id를 공유). manual/adjustment 계열은 사람 입력이라
  부여하지 않는다(빈칸 유지).
- **성공 기준**(검증 명령으로 확인, §6):
  1. 재생성된 정상 데이터셋에서 자동 계열 source 행의 batch_id·job_id 채움률 ≥ 0.97
     (나머지 ≤0.03 은 의도적 MCAR 결측만).
  2. manual/adjustment 행의 batch_id·job_id 채움률 ≤ 0.02 (사람 입력은 배치 id 없음).
  3. PHASE1 게이트 자가검증: `trusted_automated_mask` 가 신뢰하는 자동 계열 행 비율이
     **자동 계열 행의 ≥ 0.90** (현재 0.04 에서 회복).

## 2. 컨텍스트

- 읽어야 할 파일(수정 전 반드시 읽을 것):
  - PHASE1 게이트 로직(요건 출처): `src/detection/source_trust.py` — 특히 `automated_source_mask`,
    `lone_automated_mask`, `trusted_automated_mask`.
  - datasynth 생성 원칙: `docs/datasynth/generation-principles.md`,
    `dev/active/datasynth-journal-realism-rebuild/datasynth-normal-generation-principles.md`.
  - 현 생성기에서 source·batch_id·job_id 를 쓰는 지점: Rust 크레이트
    `tools/datasynth/crates/` 내 전표 헤더 생성 모듈(직접 grep 으로 batch_id/job_id/source 사용처 확인).
- 따라야 할 기존 패턴: 기존 컬럼 채우는 방식(같은 헤더 생성 함수에서 created_by/source 채우는 코드)을
  먼저 읽고 동일 형식으로 추가한다. 자체 포맷 발명 금지.
- 배경(모르면 잘못 판단할 사실만):
  - **왜 이 작업인가**: PHASE1 부정 콤보(자금유출+승인우회=HIGH)는 "사람 행위 전제"라 자동 전표를
    제외해야 한다. 제외 게이트(`trusted_automated_mask`)는 "자동 source 인데 batch/job 식별자도 없고
    같은 날 무리도 없으면 = 수기가 자동인 척 위장한 것"으로 보고 **신뢰하지 않는다**(`source_trust.py`
    주석). 현재 v46b 정상 데이터는 자동 source 행의 **93.9%가 batch_id 빈칸**(전체 행 95.4% 빈칸)이라,
    진짜 자동 전표가 전부 "위장 의심"으로 찍혀 신뢰 4%뿐 → 콤보가 자동 전표를 못 걸러 정상 데이터의
    HIGH 가 76%로 폭증한다(정상 HIGH 는 ~2% 여야 함, HARD 가드).
  - **게이트의 정확한 요건**(`source_trust.py:lone_automated_mask`): `weak_identity` 는 batch_id,
    job_id 를 OR 누적해 **둘 중 하나라도 빈칸이면 True**(line 57–61). 따라서 자동 전표가 신뢰받으려면
    **batch_id 와 job_id 둘 다** 비어있지 않아야 한다(한쪽만 채우면 여전히 위장 의심으로 빠진다).
  - **자동 계열 source 토큰**(`AUTOMATED_SOURCE_TOKENS`): `batch, interface, system, auto, automated,
    if, sys, recurring`. 이 토큰에 해당하는 source 가 batch/job id 대상이다. (현 정상 데이터의 자동 계열
    = `automated` 61.8% + `recurring` 12.9%.)
  - **무리지어 다녀야 한다**: 게이트의 2차 조건 `lone_same_day` 는 같은 날 자동 전표 수가 ≤10 이면
    위장 의심으로 본다. 같은 배치 실행이 여러 문서를 함께 만들고 **동일 batch_id 를 공유**하면 이 조건도
    자연히 충족된다(자동 전표는 항상 무리짐). batch_id 를 문서마다 유일값으로 주면 안 된다 — **배치 실행
    단위로 공유**해야 한다.

## 3. 설계 (이대로 구현 — 임의 변경 금지)

- 전표 헤더 생성에서 source 가 자동 계열(`AUTOMATED_SOURCE_TOKENS` 중 하나)일 때:
  - `batch_id` = 그 전표가 생성된 **배치 실행 단위**로 동일한 값(예: 같은 posting_date·source·
    business_process 의 배치 run 을 하나의 batch_id 로 묶음). 같은 배치의 여러 문서가 같은 batch_id 를
    공유하도록 한다. 값은 생성 과정에서 파생(run 식별자)하며 **연도·회사코드·금액 리터럴을 박지 않는다**.
  - `job_id` = 그 배치를 실행한 작업(job) 식별자. batch_id 와 다른 축(예: 스케줄/잡 종류)이되 역시
    배치 실행 단위로 공유한다. batch_id 와 job_id 가 **둘 다** 채워져야 한다(§2 게이트 요건).
- source 가 manual/adjustment(사람 입력)일 때: batch_id·job_id 는 채우지 않는다(빈칸 유지).
- **데이터 품질 규칙 보존**(CLAUDE.md): MCAR 결측·오타·서식 변동은 정상/비정상 동일 비율 유지.
  batch_id·job_id 에 의도적 결측을 넣으려면 기존 MCAR 비율(자동 계열 ≤3%)을 넘기지 않는다. 95% 결측
  같은 비현실적 누락을 만들지 않는다.
- 설계가 현 생성기 구조와 안 맞으면(예: 배치 run 개념이 코드에 없음): 임의로 우회 구현하지 말고 즉시
  멈추고 **STATUS: NEEDS_CONTEXT** 로, 무엇이 없어 막혔는지 보고할 것. 멈추는 것은 실패가 아니다.

## 4. 단계 체크리스트 (순서 고정 — 건너뛰기·합치기 금지)

- [ ] Step 1: `src/detection/source_trust.py` 와 Rust 헤더 생성 모듈에서 source/batch_id/job_id
      사용처를 읽고, 자동 계열 판정·batch 묶음 단위를 어디서 정할지 특정한다.
      → 산출물: 수정 대상 Rust 파일·함수명을 보고에 명시.
      증거: `grep -rn "batch_id\|job_id" tools/datasynth/crates/` 결과 원문 + 대상 함수 위치.
- [ ] Step 2: 자동 계열 source 전표에 배치 실행 단위로 공유되는 batch_id·job_id 를 부여하도록
      Rust 생성기를 수정한다(manual/adjustment 은 빈칸 유지).
      → 산출물: 수정된 Rust 파일.
      증거: `cargo check -p datasynth-cli` 결과가 `Finished`(기존 warning 만, 신규 error 0).
- [ ] Step 3: 정상 데이터셋을 동일 시드/구성으로 재생성한다(기존 normal 생성 커맨드 그대로).
      → 산출물: 재생성된 `data/journal/primary/<새 normal 디렉토리>/journal_entries.csv`.
      증거: 재생성 커맨드 원문 + 생성 완료 로그 마지막 줄(행 수 포함).
- [ ] Step 4: 채움률 검증(§6-1,2) 실행.
      증거: §6-1, §6-2 명령 출력 원문.
- [ ] Step 5: PHASE1 게이트 회복 검증(§6-3) 실행.
      증거: §6-3 명령 출력 원문.
- [ ] Step 6: `docs/debugging.md` 에 본 datasynth 재생성·batch_id 부여 내역 기록.
      증거: 추가한 섹션 diff.
- [ ] Step 7(마지막): §6 전체를 한 번에 재실행해 출력 원문 확보.

## 5. 금지 사항 (1건이라도 위반 시 작업 전체 실패)

- 하드코딩 금지(이 작업에서 박고 싶어질 지점):
  - batch_id·job_id 값에 **연도 리터럴**(2022/2023/2024)·회사코드·금액·고정 문자열을 직접 박지 말 것.
    값은 배치 run 파생값으로 만든다.
  - 자동 계열 판정에 source 문자열을 코드에 따로 박지 말 것 — 판정 기준은 한 곳(생성기의 source 정의)에서
    파생. PHASE1 의 `AUTOMATED_SOURCE_TOKENS` 와 의미가 어긋나면 §2 토큰을 기준으로 맞춘다.
  - 같은 날 자동 전표 수 임계(10) 같은 게이트 상수를 datasynth 에 복제해 박지 말 것 — datasynth 는 "배치는
    무리짓는다"는 성질만 만들면 된다(임계는 PHASE1 게이트 소관).
- 테스트·검증 약화 금지: 채움률 기대치를 낮추거나, 자동 계열 정의를 좁혀 분모를 줄이는 식으로 통과 만들기 금지.
- **Python 덧대기 금지**: 근본 수정은 Rust 생성기에서. 생성 후 Python 으로 batch_id 를 사후 채우는 패치 금지
  (CLAUDE.md DATASYNTH 규칙).
- 범위 밖 수정 금지: PHASE1 탐지 코드(`src/detection/*`)·게이트(`source_trust.py`)·설정(`config/*`) 변경 금지.
  본 작업은 datasynth 생성기(Rust)와 재생성 산출물만 건드린다. 게이트는 읽기 전용(요건 출처)이다.
- 체크리스트 항목 생략·순서 변경 금지. 실패·미완을 완료로 보고 금지.

## 6. 최종 검증 (완료 선언 전 필수 실행 — `<NEW_DIR>` = Step 3 재생성 디렉토리)

- §6-1 자동 계열 채움률:
  ```
  uv run python -c "
  import duckdb
  j='data/journal/primary/<NEW_DIR>/journal_entries.csv'
  con=duckdb.connect(); con.execute(f\"CREATE VIEW j AS SELECT * FROM read_csv_auto('{j}', ALL_VARCHAR=1)\")
  print(con.execute('''SELECT
    SUM(CASE WHEN lower(source) IN ('automated','recurring','batch','interface','system','auto','if','sys') THEN 1 ELSE 0 END) auto_rows,
    SUM(CASE WHEN lower(source) IN ('automated','recurring','batch','interface','system','auto','if','sys')
             AND trim(batch_id)<>'' AND trim(job_id)<>'' THEN 1 ELSE 0 END) auto_both_filled
  FROM j''').fetchdf().to_string())
  "
  ```
  기대: `auto_both_filled / auto_rows ≥ 0.97`.
- §6-2 manual/adjustment 미부여:
  ```
  uv run python -c "
  import duckdb
  j='data/journal/primary/<NEW_DIR>/journal_entries.csv'
  con=duckdb.connect(); con.execute(f\"CREATE VIEW j AS SELECT * FROM read_csv_auto('{j}', ALL_VARCHAR=1)\")
  print(con.execute('''SELECT
    SUM(CASE WHEN lower(source) IN ('manual','adjustment') THEN 1 ELSE 0 END) human_rows,
    SUM(CASE WHEN lower(source) IN ('manual','adjustment') AND (trim(batch_id)<>'' OR trim(job_id)<>'') THEN 1 ELSE 0 END) human_with_id
  FROM j''').fetchdf().to_string())
  "
  ```
  기대: `human_with_id / human_rows ≤ 0.02`.
- §6-3 PHASE1 게이트 회복(자동 계열이 실제로 trusted 되는지):
  ```
  uv run python -c "
  import pandas as pd
  from src.detection.source_trust import automated_source_mask, trusted_automated_mask
  df=pd.read_csv('data/journal/primary/<NEW_DIR>/journal_entries.csv', dtype=str, keep_default_na=False)
  auto=automated_source_mask(df); trusted=trusted_automated_mask(df)
  rate=(auto & trusted).sum()/max(auto.sum(),1)
  print(f'auto={auto.sum()} trusted_within_auto={(auto&trusted).sum()} rate={rate:.3f}')
  "
  ```
  기대: `rate ≥ 0.90` (현재 0.04 에서 회복).
- ※ 하나라도 기대와 다르면 DONE 금지. 원인 미상이면 BLOCKED 로 보고.

## 7. 완료 보고 양식 (이 양식 그대로, 항목 생략 금지)

```
STATUS: DONE | DONE_WITH_CONCERNS | NEEDS_CONTEXT | BLOCKED
체크리스트: Step 1~7 각 [x]/[ ] + 각 단계 증거(명령 + 출력 원문 붙여넣기)
변경 파일: <경로 목록 — 실제 변경한 파일만>
재생성 디렉토리: data/journal/primary/<NEW_DIR>
최종 검증 결과: §6-1/§6-2/§6-3 각 출력 원문 + 기대 대비 충족 여부
미완·우회·우려 사항: <정직하게 전부. 없으면 "없음">
```

신뢰 규칙: 부분 실패의 정직한 보고(DONE_WITH_CONCERNS/BLOCKED)는 정상 경로다. 거짓 DONE 은
요청 컨텍스트의 재검증(§6-3 재실행 + 채움률 재현)에서 반드시 드러나고 작업 전체를 재수행하게 된다.

---

## 요청 컨텍스트(나) 후속 — datasynth 측 작업 아님

- 재생성 후 PHASE1 정상 데이터 HIGH band 비율이 ~2% 로 수렴하는지(현 76%) + kpi a2 HARD 가드 통과를
  요청 컨텍스트가 재측정한다. datasynth 컨텍스트는 §6-3 게이트 회복까지만 책임진다.
- L1-07(승인생략) binary 발화는 설계 의도(커버리지)로 유지 — 본 작업으로 수정하지 않는다.
