# HIGH 6개 조합 전수 FSS 대조 — 조건 이상(과승격) 분석 (2026-07-03)

질문: HIGH_COMBO_GROUNDING에 정의된 HIGH 조합들을 FSS 실제 감리와 대조했을 때 조건이 이상한(과승격)
조합이 있나. HIGH-4에 쓴 방법(룰 predicate를 FSS 474건에 재대입 → 실제 tier와 대조)을 6개 조합
전부에 적용했다.

원천: `dev/active/phase1-rule-basis-audit/fss_case_combo_tagging.md`(230파일 파싱, 474 사례).
대조표: `reports/normal_v53_high_combos_fss_overpromotion_20260703.csv`(302행). predicate는
`topic_scoring.py` 코드 상수와 일치(B안 반영 후 기준).

## 결론

**HIGH-4(period_end_adjustment_high)만 조건이 이상하다(과승격율 39.8%). 나머지 5개는 정상(0~5.7%).**
그리고 B안(L4-04 제거)으로 고쳤음에도 HIGH-4는 **여전히** 남은 두 다리(L3-10 추정계정·L4-03 고액)로
과승격이 잔존한다.

## 1. 6개 HIGH 조합 FSS 과승격율 (분모 = 각 조합의 FSS 매칭 N)

| 조합                           | 매칭 N | FSS-HIGH | MED/LOW | 과승격율  | 판정     |
| ------------------------------ | ------ | -------- | ------- | --------- | -------- |
| fictitious_entry_high          | 81     | 78       | 3       | 3.7%      | 정상     |
| embezzlement_concealment_high  | 70     | 66       | 4       | 5.7%      | 정상     |
| suspense_concealment_high      | 6      | 6        | 0       | 0.0%      | 정상     |
| **period_end_adjustment_high** | 83     | 49       | 33      | **39.8%** | **이상** |
| approval_bypass_high           | 56     | 54       | 2       | 3.6%      | 정상     |
| expense_capitalization_high    | 6      | 6        | 0       | 0.0%      | 정상     |

과승격율 = FSS가 MEDIUM/LOW로 매긴 사례를 룰이 HIGH 조합으로 매칭한 비율. 5개 조합은 "매칭하면 거의
실제 HIGH"(과승격 <6%)라 FSS 등급과 잘 정합한다. HIGH-4만 매칭 83건 중 33건(39.8%)이 실제 MEDIUM/LOW.

## 2. HIGH-4 과승격 33건 — B안 후에도 남은 이유

B안은 L4-04(희소계정쌍) 단독 leg를 제거했다. 그런데 남은 33건 과승격은 **L4-04가 아니라 B안이
유지한 두 직접 leg**에서 나온다:

- **L3-04 + L3-10(기말+추정계정)**: ~15건. 예 `2012-마-나`(LOW, 매도가능증권 과대), `2015-나1`(LOW,
  콘도·골프회원권 손상검토 미수행), `FSS2206-07`(LOW, 재고 감모 미인식), `A-10유형-가`(MEDIUM, 원재료
  평가손실 미인식).
- **L3-04 + L4-03(기말+고액)**: ~16건. 예 `2018-가(개발비A)`(MEDIUM, 개발비 과대), `2014-다(투자주식)`
  (MEDIUM, 손상차손 미인식), `2013-가(저축은행충당)`(MEDIUM, 자산건전성 분류 오류).

이들은 전부 **"손상·충당금 미인식/추정 과대" 유형 — 위조·고의 없는 회계추정 오류**다. 전표 직접
조작 신호가 없다.

## 3. 왜 이상인가 — 룰이 고의(intent)를 볼 수 없다

이건 근거표가 이미 인정한 한계다:
- `HIGH_COMBO_GROUNDING.md:215`: "충당금·손상 관련 위반은 건수 최다(약 55건). 단 **대부분 LOW** —
  추정 왜곡은 전표 직접조작 신호가 약하기 때문. 결산시점에 추정계정이 겹칠 때 HIGH(예 2014-가 대손충당
  **고의** 과소, 2016-가 BIS **회피 고의**)."
- `:468`: "충당금·손상 단순 추정 누락(위조·**고의 없는** 저가법 미반영) → LOW, **고의·고액 결합 시**
  HIGH-4."

즉 근거표는 "기말+추정계정" 중 **고의**가 있는 것만 HIGH이고 단순 추정오류는 LOW로 의도했다. 그러나
전표 라인 피처(L3-04 기말·L3-10 추정계정·L4-03 고액)로는 고의와 단순오류를 구분할 수 없다. 룰은
"기말 + 추정계정/고액"을 전부 HIGH-4로 올리므로, FSS가 LOW로 본 단순 추정오류 33건을 과승격한다.

## 4. v53 정상데이터 HIGH 구성 (분모 = HIGH 1,010)

| primary_topic       | 건수 | 비율  | 조합                        |
| ------------------- | ---- | ----- | --------------------------- |
| closing_timing      | 541  | 53.6% | period_end_adjustment_high  |
| approval_control    | 362  | 35.8% | approval_bypass_high        |
| account_logic       | 41   | 4.1%  | expense_capitalization_high |
| duplicate_outflow   | 35   | 3.5%  | embezzlement/suspense       |
| revenue_statistical | 31   | 3.1%  | fictitious_entry_high       |

- 정상 HIGH의 절반(53.6%)이 HIGH-4다. FSS 과승격이 확인된 바로 그 조합이 정상 데이터 HIGH의 몸통.
- **별도 관찰**: approval_control(HIGH-5)이 정상 HIGH의 35.8%(362건)다. HIGH-5는 FSS 조건 정합
  (과승격 3.6%)인데 정상 데이터에서 크게 발화한다. FSS로는 못 재는 "정상데이터 FP"이므로 조건 이상은
  아니나, 정상 SoD(L1-06 1.71%)·고액 동반 패턴이 현실적인지는 별도 점검 대상이다(이번 범위 밖).

## 5. 판정과 함의

- **조건이 이상한 HIGH 조합은 HIGH-4 하나다.** B안은 L4-04 아티팩트 과승격을 제거했으나, HIGH-4의
  근본 전제("기말+추정계정/고액=HIGH")가 FSS 실증과 어긋나는 부분(단순 추정오류를 HIGH로)은 남는다.
- 이건 **탐지 한계(고의 미관측)**이지 단순 버그가 아니다. L3-10/L4-03 leg를 빼면 FSS 실제 HIGH
  (2016-가 대손충당 고의 등 49건 중 상당수)의 recall이 떨어진다 — precision/recall 트레이드오프라
  임의 변경 불가.
- 선택지(결정 필요):
  1. 현행 유지 — HIGH-4를 "결산 추정 검토 후보"로 두고 과승격을 감수(감사인 리뷰로 고의 판정).
  2. HIGH-4를 MEDIUM으로 강등하고, 고의 신호(예 L2-05 역분개·L3-02 수기 동반 등 추가 강신호) 있을
     때만 HIGH — 단 FSS HIGH recall 손실 측정 선행 필요.
  3. 추정계정 조작 전용 강신호(반복 조정·전기 역전 등) 신설 후 그와 결합 시만 HIGH.

## 6. 분모·한계

- FSS 대조: 474건 전수 재대입(표본 아님). 6조합 매칭·과승격 전건 CSV 산출.
- v53 정상 HIGH: 1,010 전건 primary_topic 집계.
- FSS 과승격율은 "조건 vs 실제 부정 등급" 지표다. "정상데이터 FP"는 FSS로 측정 불가(FSS는 전부 실제
  부정) — approval_control 정상 다발은 별도 분석 필요.
- 조치는 하지 않음(분석만). HIGH-4 강등/신호추가는 부정 recall 측정 후 결정 대상.
