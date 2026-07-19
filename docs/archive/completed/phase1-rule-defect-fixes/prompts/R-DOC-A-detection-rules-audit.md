# 작업: DETECTION_RULES.md 전수 감사 — 옛정보·미입력·오입력 정정 (41룰 + 운영 기준 절)

> 한국어로 응답·보고할 것. 저장소: `C:\Users\ghdtj\workspace\portfolio\local-ai-assist`, 브랜치 `develop`.
> grep이 없으면 rg로 대체 가능 (동일 범위 + 출력 원문 첨부).
> ⚠️ **코드·설정·테스트 수정 절대 금지** — 지금 측정 파이프라인이 백그라운드로 돌고 있다.
> `src/`, `config/`, `tests/`는 읽기 전용이다. 수정 대상은 문서 1개뿐이다.

## 1. 목표

- `docs/spec/DETECTION_RULES.md`(2,983줄)의 **사실 기술**(구현 경로·함수명·점수 상수·버킷명·
  파라미터 키·필수 컬럼·breakdown 키)을 현재 코드와 전수 대조해 옛정보/미입력/오입력을 정정한다.
- 성공 기준: §6 검증 통과 + 41룰 × 6차원 검증표(전 셀 판정 기록)가 보고서에 포함 + mojibake 0.

## 2. 컨텍스트

- 감사 대상: `docs/spec/DETECTION_RULES.md` — §2.0(운영 기준)과 룰 카드 41개
  (L1-01~09, L2-01~05, L3-01~12, L4-01~06 = canonical 32 + D01/D02·GR01/GR03·IC01~03 보조,
  EV01/EV03 언급부 포함).
- 대조 기준 코드 (읽기 전용):
  - 구현: `src/detection/` (integrity_layer, fraud_rules_feature, fraud_rules_access,
    fraud_rules_groupby, anomaly_rules_simple/statistical/batch/reversal, evidence_rules,
    intercompany_rules, graph_rules, variance_rules/variance_layer, source_trust)
  - 점수 계약: `src/detection/rule_scoring.py` (REGISTRY·버킷 신호강도 사전들),
    `src/detection/topic_scoring.py` (DEFAULT_TOPIC_FLOORS/COMBO_FLOORS)
  - 설정: `config/audit_rules.yaml`, `config/phase1_case.yaml`, `config/settings.py`
- 배경 (모르면 잘못 판단할 사실):
  - **이 문서는 스펙(계약)이다. 코드와 다르다고 무조건 문서가 틀린 게 아니다.** 판정 규칙은 §3.
  - 알려진 코드 갭(스펙이 옳고 코드가 따라오는 중 — **해당 서술 수정 금지**):
    `docs/spec/results/PHASE1_OPEN_ISSUES.md` #17~#25 전부. 특히 ① L2-02의
    mixed/blank/amount fallback 3종 서술(코드 구현이 별도 작업으로 진행 중), ② L1-07 섹션
    (unknown_approver 서브패턴이 곧 추가될 예정 — 섹션 구조 변경 금지).
  - 최근 갱신분(2026-06-12/13 날짜가 박힌 항목 — L4-06 lone_batch_identity, fraud-combo 신뢰
    게이트, L3-06/L1-05/L1-04/L4-05의 "위장 게이트" 불릿)은 방금 검수된 최신 정보다.
    **삭제·수정 금지.**
  - 최근 코드 변경으로 문서가 낡았을 가능성이 높은 지점: L1-04 floor가 critical/non_approver
    한정 게이트로 바뀜(스펙은 원래 그렇게 약속 — 일치 확인만), L2-02 floor 정책 id가
    `duplicate_reference_match`(0.45)로 변경됨, repeat 무조건 medium 승급 분기 제거됨,
    `EvidenceDetector(rule_ids=("L3-11",))` 기본 배선됨.

## 3. 판정 규칙 (이대로 적용 — 임의 변경 금지)

발견한 문서-코드 불일치마다 셋 중 하나로 판정한다:

| 판정 | 기준 | 조치 |
|------|------|------|
| **문서 정정** | 사실 기술의 불일치: 파일 경로·함수명·점수/임계 상수·버킷/reason 이름·config 키 이름·필수 컬럼·breakdown 키·룰 개수 | 문서를 코드에 맞게 수정 |
| **코드 갭 (보고만)** | 규범 기술의 불일치: "탐지한다/floor를 둔다/제외한다" 같은 의도 서술이 코드에 없거나 다름 | **문서 수정 금지.** 보고서 "코드 갭 발견" 목록에 기재 (OPEN_ISSUES #17~#25에 이미 있는 건 번호만 표기) |
| **불명 (보고만)** | 어느 쪽이 정답인지 판단 불가 | 수정 금지, 보고서에 질문으로 기재 |

미입력(스펙 카드에 비어 있는 표준 항목 — 예: 다른 룰엔 있는 "필수 실행 입력"이 특정 룰에만 없음)은
코드에서 사실을 확인할 수 있으면 채우고, 확인 불가면 "불명"으로 보고.

## 4. 단계 체크리스트 (순서 고정 — 건너뛰기·합치기 금지)

- [ ] Step 1: 보호 목록 확정 — OPEN_ISSUES #17~#25 정독 + 2026-06-12/13 날짜 항목 위치 grep
      증거: `rg -n "2026-06-1[23]" docs/spec/DETECTION_RULES.md` 출력 원문 (이 줄들은 수정 금지 대상)
- [ ] Step 2: 41룰 전수 대조 — 룰마다 6차원 검증:
      ① 구현 경로/함수명 ② 점수·버킷·임계 상수 ③ 튜닝 파라미터 키(config에 실존)
      ④ 필수 입력·피처 컬럼 ⑤ breakdown·annotation 키 ⑥ 점수 흐름(floor/콤보 참여 서술)
      → 산출물: 41행 × 6열 검증표 (각 셀: 일치 / 문서정정 / 코드갭 / 불명)
      증거: 검증표 전체 + 각 "문서정정" 셀마다 코드 근거 파일:라인 1개 이상
- [ ] Step 3: §2.0 운영 기준 절(결과 표현 계층·출력 큐·점수 기준·Case Group) 동일 방식 대조
      증거: 발견 목록 (없으면 "발견 없음" + 확인 범위)
- [ ] Step 4: 문서 정정 실행 — **부분 수정(정확한 문자열 치환)만. 파일 전체 재작성·재포맷 금지.**
      한 번에 한 항목씩, 수정 전후 해당 줄만 diff로 확인
      증거: 수정 항목별 "변경 전 → 변경 후" 목록
- [ ] Step 5(항상 마지막): 전체 검증(§6) 실행 후 출력 원문 확보
※ 각 단계의 증거는 완료 보고에 원문 그대로 포함한다. 증거가 없는 단계는 미수행으로 간주한다.

## 5. 금지 사항 (1건이라도 위반 시 작업 전체 실패)

- **코드·설정·테스트 수정 금지** (src/, config/, tests/ 전부 — 측정 진행 중).
- **한글 인코딩 가드**: 파일 전체 재작성, 셸 리다이렉션/Set-Content류 일괄 치환, 포매터 적용 금지.
  정확한 부분 edit만. 작업 후 mojibake 스캔(§6) 필수.
- 보호 목록(Step 1) 서술 수정·삭제 금지. 규범 기술을 코드에 맞춰 약화 금지 (판정 규칙 §3).
- 범위 밖 수정 금지: 수정 가능 파일 = `docs/spec/DETECTION_RULES.md` **하나뿐**.
  (룰원칙해설.md·DETECTION_PARAMETERS.md 등 다른 문서의 불일치는 보고서에 목록만.)
- 검증표 셀 비우기 금지 — 41룰 × 6차원 전 셀에 판정 기록 (전수 요청 작업).
- 체크리스트 항목 생략·순서 변경 금지. 실패·미완을 완료로 보고 금지.

## 6. 최종 검증 (완료 선언 전 필수 실행)

- mojibake 스캔: `uv run python -c "s=open('docs/spec/DETECTION_RULES.md',encoding='utf-8').read(); bad=[t for t in (chr(0xFFFD),'?ㅽ','?λ') if t in s]; print('mojibake:', bad or 'NONE')"`
  → 기대: `mojibake: NONE` (chr(0xFFFD)=유니코드 대체문자)
- 보호 항목 보존: `rg -c "lone_batch_identity|trusted_automated_mask|위장 게이트" docs/spec/DETECTION_RULES.md`
  → 기대: 작업 전과 동일 이상 (Step 1에서 작업 전 수치를 떠 둘 것)
- 링크 무결성: 문서 내 상대링크 깨짐 0 — `rg -n "\]\((\.\./|\./)" docs/spec/DETECTION_RULES.md`로
  추출한 경로가 실재하는지 표본 10개 이상 확인 (수정한 절 주변은 전수)
- `git diff --stat docs/spec/DETECTION_RULES.md` → 기대: 이 파일만 변경
※ 하나라도 기대와 다르면 DONE 금지. 원인 미상이면 BLOCKED로 보고.

## 7. 완료 보고 양식 (이 양식 그대로, 항목 생략 금지)

STATUS: DONE | DONE_WITH_CONCERNS | NEEDS_CONTEXT | BLOCKED
체크리스트: 항목별 [x]/[ ] + 각 항목의 증거(명령 + 출력 원문 붙여넣기)
41룰 검증표: <전 셀 판정 — 생략 금지>
문서 정정 목록: <항목별 변경 전→후 + 코드 근거 파일:라인>
코드 갭 발견 목록: <문서 수정 안 한 규범 불일치 — 기존 이슈 번호 또는 신규 표기>
변경 파일: <docs/spec/DETECTION_RULES.md 하나여야 함>
최종 검증 결과: §6 명령별 출력 원문
미완·우회·우려 사항: <정직하게 전부. 없으면 "없음">

신뢰 규칙: 부분 실패의 정직한 보고(DONE_WITH_CONCERNS/BLOCKED)는 정상 경로이며 다음 지시로
이어진다. 거짓 DONE은 재검증에서 반드시 드러나고 작업 전체를 처음부터 재수행하게 된다.
