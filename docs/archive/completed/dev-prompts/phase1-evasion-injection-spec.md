# PHASE1 전수 Evasion 주입 스펙

## 목적

이 문서는 PHASE1 모든 canonical 룰과 보조/독립 트랙에 대해 부정 시나리오가 정상 노이즈, suppress, drop, review-only 경계를 흉내 내어 빠져나갈 수 있는 경로를 정리한 P3-2 부정 주입 스펙이다.

범위는 분석 및 문서화까지다. 코드, 데이터, 생성기 변경은 하지 않았다.

## 기준 문서

- `docs/spec/DETECTION_RULES.md`: canonical rule count, rule semantics, suppress/drop, review-only, macro/sidecar 정책.
- `docs/spec/DETECTION_REFERENCE.md`: ISA 240/PCAOB AS 2401 전표 특성, 외감법/K-SOX 통제, FSS 189건 전수 사례의 6대 전표 조작 패턴.
- `dev/active/datasynth-journal-realism-rebuild/scenario-catalog.md`: 정상 accounting event scenario, counterparty/document/text family.
- `dev/active/datasynth-journal-realism-rebuild/phase1-rule-testability-matrix.md`: synthetic validation 가능 범위와 DataSynth 요구조건.

## Canonical 목록 및 개수 확정

Canonical PHASE1 L1~L4는 총 32개다.

| 구분 | 개수 | 룰 |
| --- | ---: | --- |
| L1 | 9 | L1-01~L1-09 |
| L2 | 5 | L2-01~L2-05 |
| L3 | 12 | L3-01~L3-12 |
| L4 | 6 | L4-01~L4-06 |
| 합계 | 32 | 31 row/review 카드 + 1 macro 카드(L4-02 Benford) |

보조/독립 트랙은 canonical count에 넣지 않는다. 본 스펙에서는 IC01~IC03, GR01, GR03, D01, D02를 별도 7행으로 전수 포함한다. Benford는 canonical L4-02이므로 별도 중복 행을 만들지 않고 L4-02 행에 `Benford alias`를 명시한다.

## Suppress/drop 때문에 evasion 필수인 룰

| 룰 | suppress/drop 또는 약화 경계 | P3-2 필수 evasion 케이스 |
| --- | --- | --- |
| L2-02 | recurring suppress, ambiguous fallback drop, near-extra context suppress | 가짜 정기 지급, reference만 바꾼 동일 거래처/금액 이중지급, automated/recurring 위장 near-extra |
| L2-03 | recurring suppress, ambiguous different-reference drop, same-document pair drop, near-extra context suppress | 가짜 월별 반복 중복전표, reference/document_number 변형 중복, 같은 문서 안 self-contained 중복/분할 |
| L2-04 | review/low_review는 confirmed flag로 승격하지 않음, normal capex keyword/doc type suppress | 비용 자산화를 정상 CAPEX 문구/문서유형으로 위장해 review-only 또는 zero-score로 남기는 케이스 |
| L2-05 | 구조적 reversal link는 high-confidence이나 routine/recurring clearing은 zero/low review, reversal-link 정상화 경계 | 부정 정정/은폐 전표가 정상 자동 역분개 링크와 reason code를 가장하거나, 링크 없이 rolling zero-out만 남기는 케이스 |
| L3-03 + IC01 | IC01 review evidence는 confirmed violation이 아님, customer/vendor code는 IC 예외에서 제외 | 관계사 거래를 고객/벤더 코드 또는 mapping_uncertain 형태로 숨기는 케이스 |
| L3-05/L3-06/L3-08/L3-10/L3-12/L4-05/L4-06 | standalone false, booster/combo/context-only | 약한 보조 신호만 남도록 분산한 부정. PHASE1 단독 승격 실패 여부와 PHASE2 타깃 여부를 측정 |
| L4-02/D01/D02/GR01/GR03 | macro/sidecar, row-level confirmed detail 없음 | 개별 전표는 정상처럼 보이나 계정/월/그래프 구조만 움직이는 부정. PHASE2 또는 macro benchmark 타깃 |

## 룰 전수 evasion 표

| rule | 무엇을 잡나 | 적용된 suppress/drop(있으면) | evasion 벡터(실제 사례 근거) | 주입할 evasion 케이스 | 기대 결과 | 비고 |
| --- | --- | --- | --- | --- | --- | --- |
| L1-01 | 전표 document 단위 차대변 불균형 | 작은 차이는 낮은 참고 신호로 유지 | 실제 FSS 패턴은 가공전표/횡령은폐가 균형 전표로 기록되는 경우가 많아 불균형 자체를 만들지 않는 방식이 우회 경로 | 균형은 맞지만 허위 매출 또는 선급금/대여금 은폐 전표를 O2C/R2R document로 주입 | PHASE1 L1-01은 못 잡음, L4-01/L3-02/L4-03/PHASE2 타깃 | 표준 위반형 불균형도 별도 positive로 유지 |
| L1-02 | 필수 필드 누락 | 결측 필드가 없으면 해당 없음 | 부정자가 필수 필드는 모두 채우고 의미 없는 정상값을 입력하면 schema/null 룰 회피 | 모든 필수 필드를 정상 채운 가공 매출/가공 지급 document | PHASE1 L1-02는 못 잡음, 의미/통계/통제 룰 또는 PHASE2 타깃 | 표준 위반으로 충분한 룰이나 완전 입력 evasion 필요 |
| L1-03 | 무효/비사용 계정 | 유효 CoA면 drop 없음 | FSS 가공전표는 실제 계정과목을 써서 기록될 수 있음. 무효 계정 대신 정상 revenue/AP/prepaid/loan 계정 사용 | CoA상 유효한 revenue, prepaid, loan, AP 계정으로 허위 전표 주입 | PHASE1 L1-03은 못 잡음, L4-01/L4-04/D01/D02/PHASE2 타깃 | 표준 위반으로 충분하나 유효계정 우회 확인 |
| L1-04 | 승인한도 초과 | 한도 이하 거래는 미탐 | 승인한도 바로 아래 분할은 ISA 240 A45(e)의 round/consistent ending 및 승인 우회 실무 패턴 | 동일 거래처/목적 금액을 승인한도 직하 여러 document로 분할 | L2-01/L2-03/L4-06가 잡아야 함, L1-04는 못 잡음 | L2-01과 조합 측정 |
| L1-05 | 자기 승인 | automated/recurring 등 인간 승인 요구 제외 맥락 | 오스템 사례처럼 1인 입력/승인/실행이 핵심이나, 승인자를 다른 공모자 또는 시스템 계정으로 바꾸면 자기승인 회피 | created_by와 approved_by는 다르지만 동일 사용자그룹/공모자, 또는 system approver로 승인된 고액 수기 전표 | L1-05는 못 잡음, L1-06/L1-07/L3-02/PHASE2 user-behavior 타깃 | 부정 확정 아님, 공모형 통제 우회 후보 |
| L1-06 | 직접 SoD 충돌 | SoD를 정상에서 제거, L3-12와 분리 | 1인이 전체 수행하지 않고 여러 공모자에게 단계를 분산하면 direct SoD 충돌 회피 | P2P 지급 흐름에서 작성자, 승인자, 지급 실행자를 서로 다른 사용자로 두되 동일 부서/소규모 ring에 집중 | L1-06은 못 잡을 수 있음, L3-12/GR01/PHASE2 graph 타깃 | SoD 정상 제거 경계 악용 케이스 |
| L1-07 | 승인 생략 | source/threshold상 승인 불필요 맥락은 약화 | 부정자가 금액을 승인 불필요 구간으로 쪼개거나 automated source로 위장 | 승인 임계값 이하 split documents와 automated source 지급 document | L1-07은 못 잡음, L2-01/L2-02/L4-06/PHASE2 타깃 | 승인정책 calibration 필요 |
| L1-08 | 회계기간 불일치 | fiscal_period와 posting_date가 일치하면 없음 | 결산 수정 조작은 날짜와 fiscal_period를 일치시킨 채 cutoff substance만 왜곡 가능 | fiscal_period는 맞지만 document_date, delivery_date 또는 revenue cutoff가 다른 O2C document | L1-08은 못 잡음, L3-07/L3-11/D02 타깃 | 표준 위반형 기간 불일치는 별도 positive 유지 |
| L1-09 | 승인일 누락 | 승인일 존재 시 없음 | 승인일을 사후 입력하거나 approval_date만 정상 범위로 채우면 누락 룰 회피 | approved_by와 approval_date는 존재하지만 approval_date가 posting 후 비정상 또는 공모 사용자 승인 | L1-09는 못 잡음, L1-04/L1-06/L3-02/PHASE2 approval timing 타깃 | 사후승인/지연승인은 현재 직접 룰 밖 |
| L2-01 | 승인한도 직하 | routine_razor_review는 약하게 반영 | 승인한도 직하를 피하고 더 작은 금액 여러 건 또는 threshold와 무관한 고액 정상문서로 위장 | 동일 거래처/동일일 N건 소액 분할, 합산 시 한도 초과 | L2-01 일부만 잡거나 못 잡음, L2-03c/L4-06/PHASE2 타깃 | FSS 횡령은 분할/은폐와 결합 가능 |
| L2-02 | 동일 거래처/금액/reference/date 기반 중복 지급 | recurring suppress, ambiguous fallback drop, near-extra context suppress | 중복 지급을 정기지급처럼 월별 간격으로 만들거나 reference를 바꿔 ambiguous fallback으로 떨어뜨림 | 같은 vendor/amount, 서로 다른 reference, 25~35일 간격 3건 이상. 그중 1건은 실제 가공/이중지급 | PHASE1 L2-02는 suppress/drop 가능, PHASE2 duplicate/outflow 타깃 | suppress 흉내 필수 |
| L2-03 | 정확/유사/분할/시차 중복 전표 | recurring suppress, ambiguous different-reference drop, same-document pair drop | 가공전표를 정기 accrual/maintenance처럼 반복하거나 같은 문서 내부 line 조합으로 self-contained 처리 | R2R/P2P recurring source, 동일 amount/account/partner, reference만 월별 변경. 별도 same-document duplicate line 케이스 포함 | PHASE1 L2-03 artifact는 drop/suppress 가능, PHASE2 duplicate family 타깃 | suppress/drop 흉내 필수 |
| L2-04 | 비용 자산화/자산-비용 분류 불일치 | review/low_review는 confirmed 미승격, normal capex keyword/doc type이면 zero-score 가능 | 개발비/자산 과대계상은 FSS 결산수정/가공전표 주요 패턴. 정상 CAPEX 문구와 AA/FA 문서유형으로 위장 가능 | 실제 비용성 서비스/수선비를 fixed asset 계정으로 차변 처리하되 line_text에 설비투자/자산취득 정상 키워드 삽입 | PHASE1은 review-only 또는 미승격 가능, PHASE2 semantic/substance 타깃 | confirmed-only 경계 필수 |
| L2-05 | 역분개, 상계, 재분류, rolling zero-out | routine/recurring candidate는 zero/low review, 구조적 reversal link는 정상 링크로 보일 수 있음 | 결산 조작 후 역분개로 흔적을 없기는 FSS 결산수정 패턴과 부합. 정상 reversal reason/link를 가장하면 위험 점수 약화 가능 | 기말 허위 매출 또는 비용 이연 후 다음월 linked reversal, source=automated/recurring 또는 정상 reason code 사용 | PHASE1 L2-05는 low/normal population일 수 있음, D02/PHASE2 timing-flow 타깃 | reversal-link 제외/정상화 경계 악용 |
| L3-01 | business_process와 account/text/counterparty 불일치 | semantic-clean 정상화 후 contamination hit 억제 | 부정자가 scenario catalog의 정상 조합을 그대로 사용하면 misclassification 회피 | O2C 허위 매출을 CUSTOMER, CUSTOMER_INVOICE, CUSTOMER_BILLING, 정상 revenue 계정으로 구성 | PHASE1 L3-01은 못 잡음, L4-01/D01/D02/PHASE2 타깃 | 정상 흉내 핵심 케이스 |
| L3-02 | 수기/adjustment 전표 모집단 | source가 automated/recurring이면 약화 | 수기 조작을 인터페이스/배치 입력처럼 source를 바꾸면 manual override 회피 | source=interface/batch인 결산 조정 document, created_by는 시스템 또는 batch user | PHASE1 L3-02는 못 잡음, L4-06/L3-04/D02/PHASE2 타깃 | source 위장 케이스 |
| L3-03 | 관계사/특수관계자 거래 모집단 | 단독 weak, IC sidecar와 결합 필요 | 순환거래/특수관계 거래를 외부 고객/벤더 코드로 기록하거나 trading_partner를 비워 관계사 모집단을 회피 | IC 성격 거래를 CUSTOMER/VENDOR counterparty로 처리, IC GL prefix를 쓰지 않는 매출/매입 계정 사용 | PHASE1 L3-03/IC가 못 잡을 수 있음, GR01/GR03/PHASE2 graph 타깃 | ISA 550/FSS 순환거래 근거 |
| L3-04 | 기말/기초 결산 전표 | 정상 결산 close/accrual 맥락은 낮은 우선순위 | 결산 조작을 월말 직전/직후가 아닌 평일 중간일로 분산하면 window 회피 | 12월 마지막 2주 대신 12월 중순 또는 11월 말에 허위 매출/비용 이연 주입 | PHASE1 L3-04는 못 잡음, L4-01/D01/D02/PHASE2 trend 타깃 | FSS 결산수정 패턴 |
| L3-05 | 주말/공휴일 전기 | standalone false/context-only | 비정상 시점 부정은 평일 영업시간에 처리하면 캘린더 룰 회피 | 평일 10:00 posting으로 고액/허위 전표 생성 | PHASE1 L3-05는 못 잡음, 다른 룰 또는 PHASE2 타깃 | evasion 불요에 가까우나 정상시간 우회 확인 |
| L3-06 | 심야 전기 | standalone false/context-only, 결산기 야근 저위험 반영 | 심야 입력 대신 정상 업무시간 또는 결산 야근 허용 시간대로 위장 | 18:30~22:00 결산기 또는 평일 14:00 입력으로 고액 수기/배치 전표 | PHASE1 L3-06은 약화/미탐, PHASE2 behavior 타깃 | context-only 경계 |
| L3-07 | posting_date와 document_date 장기 괴리 | gap이 작으면 없음 | cutoff 부정은 문서일도 조작해 posting_date와 맞출 수 있음 | delivery/document evidence는 실제 전기와 다르지만 document_date는 posting_date와 일치 | PHASE1 L3-07은 못 잡음, L3-11/PHASE2 evidence 타깃 | 증빙일 컬럼 확장 필요 |
| L3-08 | 적요 결손/파손 | standalone false/context-only | 허위 전표도 정상처럼 구체적 적요를 쓰면 결손 룰 회피 | 정상 text family를 사용한 가공 매출/가공 지급. 반대로 정상 노이즈처럼 짧고 약한 적요만 남긴 weak fraud도 주입 | PHASE1 L3-08은 못 잡거나 booster만 작동, PHASE2 NLP/local semantics 타깃 | 텍스트 의미 이해 한계 |
| L3-09 | 가수금/미결/clearing 장기체류 | aging/open-item lifecycle 없으면 신뢰 제한 | 장기 체류를 피하고 단기간 clearing 또는 정상 재분류로 은폐 | suspense/clearing 계정에 단기 체류 후 반대전표로 해소, 실질은 횡령 은폐 | PHASE1 L3-09는 못 잡을 수 있음, L2-05/D01/PHASE2 lifecycle 타깃 | open-item sidecar 필요 |
| L3-10 | 고위험 계정 사용 | booster/context-only, standalone false | 고위험 계정 리스트를 피하고 일반 계정에 분산하면 회피 | prepaid, misc receivable, ordinary expense 등 민감 리스트 밖 계정으로 횡령 은폐 | PHASE1 L3-10은 못 잡음, D01/L4-03/L4-04/PHASE2 타깃 | client-specific 계정 calibration 필요 |
| L3-11 | 매출 cutoff mismatch | 배송/증빙 컬럼 없으면 제한 | 매출 조작은 문서상 배송일/전표일을 맞추거나 증빙을 위조해 cutoff 룰 회피 | O2C invoice에서 posting/document/delivery를 일치시키되 실제 기간 외 거래로 sidecar truth 표시 | PHASE1 L3-11은 못 잡음, L4-01/D02/PHASE2 evidence 타깃 | FSS 밀어내기/조기인식 근거 |
| L3-12 | 업무범위 집중 review | review-only, L1-06 direct SoD와 분리, standalone false | 부정 작업을 여러 사용자에게 나눠 broad-scope 집중을 낮추거나 정상 senior user 업무범위로 위장 | 여러 사용자 ring이 회사/프로세스별로 나눠 허위전표 처리. 각 개인은 정상 scope 내 | PHASE1 L3-12는 약하거나 못 잡음, GR01/PHASE2 user graph 타깃 | confirmed-only units 경계 |
| L4-01 | 매출 이상 변동 | 분포 기반, 정상 대형 거래와 분리 필요 | 허위 매출을 여러 기간/고객에 분산하면 account/period outlier가 약해짐 | O2C 허위 매출을 6개월에 걸쳐 다수 customer로 분산, 각 금액은 peer 분포 안 | PHASE1 L4-01은 못 잡거나 약함, D01/D02/PHASE2 trend 타깃 | FSS 가공매출 최다 패턴 |
| L4-02 | Benford 위반(Benford alias) | macro-only, sample size guard, row detail 없음 | 금액 첫자리 분포를 Benford 또는 정상 그룹에 맞춰 설계하면 macro finding 회피 | 허위 지급/매출 금액을 첫자리 분포가 정상 계정군과 유사하도록 분산. 표본 500건 미만 소그룹도 포함 | PHASE1 L4-02는 못 잡거나 sidecar holdout, PHASE2/statistical ensemble 타깃 | Benford는 개별 전표 위반 아님 |
| L4-03 | 이상 고액 | 정상 대형거래 control과 raw hit 분리 | 고액 부정을 여러 소액으로 쪼개면 high amount outlier 회피 | 동일 목적의 허위 지급을 여러 document로 분할하여 각 금액을 account peer p95 이하로 유지 | PHASE1 L4-03은 못 잡음, L2-01/L2-03/D01/PHASE2 타깃 | FSS 횡령 은폐와 결합 |
| L4-04 | 희소 차대 계정쌍 | semantic-clean 정상 희소쌍은 normal context, null-side 제외 | 정상적으로 흔한 계정쌍을 사용하면 희소쌍 룰 회피 | 정상 P2P/O2C/R2R 계정쌍으로 허위 전표 생성, 단 counterpart/text만 조작 | PHASE1 L4-04는 못 잡음, L3-01/D01/D02/PHASE2 semantic 타깃 | 구조적 한계 룰 |
| L4-05 | 비정상 시간대 집중 | standalone false/context-only | 조작을 여러 사용자/시간에 분산하거나 정상 야근 시즌에 섞으면 cluster 회피 | 동일 ring이 평일 업무시간에 소량씩 분산 posting | PHASE1 L4-05는 못 잡거나 context만, PHASE2 behavior 타깃 | 비정상 시점 FSS 빈도는 낮지만 조합 신호 |
| L4-06 | 배치성 자동 전표 검토 신호 | combo/context, standalone false, recurring은 batch source 아님 | 부정자가 source를 정상 batch/interface로 위장하되 batch 규모를 정상 분포로 맞추면 회피 | interface source로 2~3건씩 소규모 허위전표를 여러 날 분산 | PHASE1 L4-06 단독 승격 안 됨, PHASE2 batch behavior 타깃 | source 위장 경계 |
| IC01 | 관계사 미대사 | review evidence는 confirmed score 0, customer/vendor code 제외 | 관계사 상대방을 비표준/결측/mapping_uncertain 또는 고객/벤더 코드로 넣으면 high IC01 회피 | IC 성격 거래에 trading_partner blank, nonstandard partner, vendor-like code 세 가지 변형 | IC01 high는 못 잡고 review/미탐 가능, PHASE2 IC probability 타깃 | unmatched-IC review 강등 경계 |
| IC02 | 관계사 금액 불일치 | cross-currency/극단 금액비는 점수 억제 | 금액 차이를 통화 차이처럼 보이게 하거나 허용오차 이내로 쪼개면 회피 | IC pair 금액 차이를 4.9% 이하 여러 건으로 분산하거나 currency mismatch sidecar 부여 | PHASE1 IC02 약화/미탐, PHASE2 IC amount probability 타깃 | 대사 보조 finding |
| IC03 | 관계사 시차 불일치 | date window/timing tolerance 이내면 미탐 | 기간 차이를 허용 window 안에 맞추거나 여러 월말/월초로 분산 | reciprocal document를 허용 window 안에 두되 실질 cutoff는 다음 period sidecar truth로 표시 | PHASE1 IC03 미탐 가능, D02/PHASE2 timing 타깃 | cutoff와 결합 |
| GR01 | N-hop 순환거래 | graph sidecar, normal cycle controls 존재 | 순환거래를 N-hop limit 밖으로 늘리거나 정상 IC cycle처럼 금액/시점을 맞추면 회피 | A→B→C→D→E→A 또는 length_bound 초과 cycle, 정상 settlement text/document 사용 | PHASE1 GR01 못 잡거나 review-only, PHASE2 graph 타깃 | FSS 순환거래 근거 |
| GR03 | 양방향 IC price asymmetry | graph sidecar, pricing/evidence 필드 의존 | 가격 차이를 세금/운임/FX 차이처럼 보이게 하거나 허용범위로 분할 | 동일 품목/서비스 IC 양방향 거래에서 단가 차이를 여러 작은 차이로 분산 | PHASE1 GR03 약화/미탐, PHASE2 graph/pricing 타깃 | transfer pricing sidecar 필요 |
| D01 | 계정 활동량 급변 | macro-only, row score 0, 신규/결측 계정 제외 | 활동량 변화를 여러 계정/기간에 smoothing하거나 신규 계정으로 이동하면 회피 | 허위 비용/매출을 여러 gl_account로 분산, 신규 계정 또는 blank/null GL edge case 별도 표시 | D01 못 잡거나 제외, L1-02/L4-03/PHASE2 trend 타깃 | macro review signal |
| D02 | 월별 분포 패턴 변화 | macro-only, row score 0, 신규 계정/비교 부족 제외, 반복/배치 정상 context 분리 | 월별 집중을 계절성/반복 배치처럼 위장하거나 여러 월로 smoothing | 기말 집중 조작을 recurring/interface batch 정상 macro context에 섞고 월별 JSD를 임계값 아래로 유지 | D02 약화/미탐, L3-04/L2-05/PHASE2 time-series 타깃 | macro smoothing evasion |

## 주입 단위 가이드

| 주입 단위 | 적용 룰 | 최소 구성 |
| --- | --- | --- |
| `document` | L1/L2/L3/L4 row 룰 대부분 | balanced debit/credit, valid CoA, source/document_type/counterparty/text family를 scenario catalog와 정합하게 구성 |
| `duplicate_flow` | L2-02, L2-03 | 2개 이상 document, partner/amount/reference/date/reason-code 변형, suppress/drop counter metadata |
| `reversal_flow` | L2-05, D02 | original/reversal document pair, structural link 유무, reversal reason, 다음 period timing |
| `intercompany_flow` | L3-03, IC01~IC03, GR01, GR03 | company pair, trading_partner, reference, amount/date tolerance, reciprocal/cycle edge |
| `macro_account_group` | L4-02, D01, D02 | company_code + gl_account + fiscal_year/month population, sidecar truth와 normal/boundary controls 분리 |
| `user_behavior_flow` | L1-05, L1-06, L1-07, L3-12, L4-05, L4-06 | created_by/approved_by/source/business_process/user ring, direct SoD와 work-scope review 분리 |

## 룰별 ✅ 체크리스트

### Canonical L1~L4 32개

- ✅ L1-01
- ✅ L1-02
- ✅ L1-03
- ✅ L1-04
- ✅ L1-05
- ✅ L1-06
- ✅ L1-07
- ✅ L1-08
- ✅ L1-09
- ✅ L2-01
- ✅ L2-02
- ✅ L2-03
- ✅ L2-04
- ✅ L2-05
- ✅ L3-01
- ✅ L3-02
- ✅ L3-03
- ✅ L3-04
- ✅ L3-05
- ✅ L3-06
- ✅ L3-07
- ✅ L3-08
- ✅ L3-09
- ✅ L3-10
- ✅ L3-11
- ✅ L3-12
- ✅ L4-01
- ✅ L4-02 / Benford alias
- ✅ L4-03
- ✅ L4-04
- ✅ L4-05
- ✅ L4-06

### 보조/독립 7개

- ✅ IC01
- ✅ IC02
- ✅ IC03
- ✅ GR01
- ✅ GR03
- ✅ D01
- ✅ D02

누락 0: canonical 32/32, 보조/독립 7/7, 총 39행 작성 완료.

## 범위 제한

범위 축소 없음. 요청한 canonical L1-01~L4-06, 보조/독립 IC01~IC03, GR01/GR03, D01/D02, Benford(L4-02)를 모두 포함했다. 이 문서는 주입 스펙 문서이며 실제 DataSynth Rust 구현, Python detector 변경, 데이터 재생성, 테스트 실행은 포함하지 않는다.
