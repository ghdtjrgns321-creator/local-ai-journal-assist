# Audit Domain Reference (Final)

감사 도메인 지식 — 한국 회계감사 환경 기준으로 처음부터 설계.
DataSynth 52개 anomaly 유형 × 한국 감사기준서 × 금감원 감리지적사례 × 내부회계관리제도를 교차 분석하여 도출.

---

## 1. 적용 법규 체계

| 계층       | 명칭                                           | 역할                      | 비고             |
|------------|------------------------------------------------|---------------------------|------------------|
| **법률**   | 외감법 (주식회사 등의 외부감사에 관한 법률)      | 감사 의무, 제재, 내회관 근거 | 2018 전면 개정   |
| **시행령** | 외감법 시행령                                   | 감사 대상, 지정 기준        |                  |
| **규정**   | 외부감사 및 회계 등에 관한 규정 (금감원)         | 감리·심사, 과징금 기준      |                  |
| **기준서** | 회계감사기준서 (KICPA 제정, 2023 개정)          | ISA 직역 채택, 문단번호 동일 |                  |
| **회계기준** | K-IFRS (한국채택국제회계기준)                  | 재무제표 작성 기준          |                  |
| **내부통제** | 내부회계관리제도 모범규준 (COSO 2013 기반)     | 외감법 제8조               | K-SOX            |

---

## 2. 기준서·내회관이 요구하는 것 → 룰 도출

> 기준서/법이 "이걸 검사하라"고 말한다 → 그 요구를 자동화하면 이런 룰이 된다.

### 2.1 감사기준서 240호 — 전표검사의 핵심

#### §32: 전표검사 의무

> 감사인은 경영진에 의한 내부통제 무력화 위험에 대한 평가 결과에 **관계없이**,
> 총계정원장에 기록된 분개기입과 재무제표 작성과정에서 이루어진 기타 수정사항의
> 적정성을 테스트하기 위한 감사절차를 설계하고 수행**하여야 한다**.
>
> (a) (i) 재무보고과정에 관여하는 개인에게 분개기입 및 기타 수정사항의 처리와 관련된
>         **부적절하거나 비정상적인 활동**에 대하여 질문한다.
>     (ii) **보고기간 말**에 작성된 분개기입 및 기타 수정사항을 선정하여 검사한다.
>     (iii) **보고기간 전체**에 걸쳐 분개기입 및 기타 수정사항을 검사할 필요성이 있는지 고려한다.
>
> (b) 회계추정치에 경영진의 **편의**(bias)가 개입되어 있는지를 검토한다.
>
> (c) 기업의 정상적인 영업과정을 벗어나거나 비정상적으로 보이는 **유의적 거래**에 대하여
>     그 **사업상 합리성**을 평가한다.

```
§32(a)(ii)  → C01 기말 대규모
§32(a)(iii) → 22개 룰 전체 (연중 대상)
§32(c)      → B01 매출 이상변동, C08 이상 고액
```

#### A44: 전표검사의 성격·시기·범위

> 부정에 의한 재무제표의 중요왜곡표시는 **부적절하거나 비인가된 분개기입**의 기록을 통해
> 이루어지는 경우가 많다. 이는 **보고기간 전체 또는 보고기간 말**에 발생할 수 있다.

```
→ C01 기말 대규모 (기말 집중) + 나머지 21개 룰 (연중 전체 대상)
```

#### A45: 부정한 분개의 식별 특성

> 부적절한 분개기입 또는 기타 수정사항은 고유한 식별 특성을 가지는 경우가 많다.
> 그러한 특성에는 다음과 같은 기입이 포함될 수 있다.

| #   | 한국 감사기준서 원문                                                                  | 도출된 룰              |
|-----|--------------------------------------------------------------------------------------|------------------------|
| (a) | 관련 없는, 비경상적이거나 **거의 사용되지 않는 계정**에 대한 기입                        | **A03**, **C09**       |
| (b) | **통상적으로 분개기입을 하지 않는 개인**에 의한 기입                                     | **B08**                |
| (c) | **보고기간 말** 또는 마감후 수정분개로 기록되며 **설명이 거의 없거나 전혀 없는** 기입      | **C01~C04**, **C06**   |
| (d) | 재무제표 작성 전이나 작성 중에 기록되며 **계정번호가 없는** 기입                          | **A02**                |
| (e) | **단수(round number)** 또는 **일관된 끝자리 숫자**를 포함하는 기입                       | **B02**, **C07**       |

#### A46: CAATs 활용

> 감사인은 **컴퓨터 보조 감사 기법**을 사용하여 검사 대상 분개기입 또는 기타 수정사항을
> 식별할 수 있다 (예: 총계정원장에서 **비정상적인 분개기입**을 식별).

```
→ 이 프로젝트 자체가 A46의 구현체.
  22개 룰 = CAATs 쿼리를 Python으로 자동화한 것.
```

### 2.2 외감법 §8 — 내부회계관리제도 (K-SOX)

#### §8 제1항: 내부회계관리제도 구축 의무

> 회사는 신뢰할 수 있는 회계정보의 작성과 공시를 위하여 다음 각 호의 사항이 포함된
> 내부회계관리규정과 이를 관리·운영하는 조직(이하 "내부회계관리제도"라 한다)을 갖추어야 한다.

이 조항들이 전표에 대해 요구하는 통제를 자동 검증하면:

```
1호 "식별·측정·분류·기록 및 보고 방법"
  → C06 위험 적요 — 적요가 공백이거나 무의미하면 "기록 방법" 위반
  → C04 소급 전기 — 거래일 대비 전기일이 과도하게 늦으면 "적시 기록" 위반

2호 "오류를 통제하고 수정하는 방법"
  → A01 차대변 균형 — 차대 불일치 = 오류 통제 미작동
  → A02 필수필드 누락 — 계정번호 등 누락 = 오류 통제 미작동

4호 "위조·변조·훼손 및 파기를 방지하기 위한 통제"
  → B05 중복 전표 — 동일 전표 반복 = 위조 징후
  → B04 중복 지급 — 동일 건 이중 지급 = 변조 또는 오류

5호 "업무 분장과 책임"
  → B06 자기 승인 — 입력자 = 승인자 = 업무 분장 위반
  → B07 직무분리 위반 — 동일인이 전체 프로세스 수행
  → B02/B03 승인한도 — 승인 권한 체계 우회/미작동
  → B09 승인 생략 — 승인 절차 자체를 건너뜀
```

#### §8 제2항: 우회 금지

> 누구든지 내부회계관리제도에 의하지 아니하고 회계정보를 작성하거나
> 내부회계관리제도에 따라 작성된 회계정보를 **위조·변조·훼손 및 파기**하여서는 아니 된다.

```
→ B08 수기 전표 — source='manual'인 고액 전표 = 자동 프로세스 우회
→ B09 승인 생략 — 승인 절차 없이 처리된 한도 초과 전표 = §8② 직접 위반
```

> **금감원 실증**: 오스템임플란트(2021) — 재무팀장 1인이 입력·승인·이체 전부 수행, 2,215억 횡령.
> 금감원 권고: "전표 입력 시 적절한 승인권자의 승인이 이루어질 수 있도록 통제절차를 마련하여야 한다."

#### §8 제6항: 감사인의 내회관 검토/감사 의무

> 감사인은 회계감사를 실시할 때 해당 회사가 이 조에서 정한 사항을 **준수했는지 여부**를 검토하여야 한다.

감사인이 내회관 준수 여부를 검토/감사해야 하므로, 위 1항·2항의 통제가 실제로 작동하는지를 전표 데이터에서 확인하는 것이 §8⑥의 이행이다.

```
→ 22개 룰 전체가 §8⑥의 "준수 여부 검토" 수단
```

### 2.3 감사기준서 315호 §26(a)(ii) — 전표 통제 이해

> 감사인은 재무보고와 관련된 기업의 정보시스템에 대한 이해를 획득하여야 하며,
> 여기에는 **분개기입에 대한 통제**가 포함된다. 특히 비경상적이거나 비정상적인 거래
> 또는 수정사항을 기록하는 데 사용되는 **비표준 분개기입에 대한 통제**를 포함한다.

```
→ B06 자기 승인, B07 직무분리, B08 수기 전표 — 비표준 전표 통제 위반 탐지
```

### 2.4 감사기준서 520호 §5 — 분석적절차

> 감사인은 실증적 분석적절차를 설계하고 수행할 때 다음을 하여야 한다.
> (a) 특정 주장에 대하여 해당 실증적 분석적절차의 적합성을 결정한다.
> (c) 기록된 금액이나 비율에 대한 **기대값을 개발**하고, 그 기대값이 충분히 정확한지를 평가한다.
> (d) 추가적인 조사 없이 수용할 수 있는, 기록된 금액과 **기대값 간의 차이 금액**을 결정한다.

```
→ C07 Benford 위반 — Benford 분포 = 기대값, 실제 분포와의 차이 = MAD/KS 검정
```

> 520호에 Benford's Law 명시는 없으나, "기대값 개발 → 차이 분석" 프레임워크에 정확히 부합.
> Mark Nigrini (2012), Journal of Accountancy 등 학술·실무에서 분석적절차 도구로 널리 인정.

### 2.5 감사기준서 550호 §23 — 특수관계자

> 기업의 정상적인 영업과정을 벗어나는 것으로 식별된 유의적 특수관계자 거래에 대하여,
> 감사인은 그 근거가 되는 약정이나 합의사항을 검사하고, 해당 거래의 **사업상 합리성**이
> 그 거래가 **부정한 재무보고에 관여**하거나 **자산의 유용을 은폐**하기 위하여
> 이루어졌을 수 있음을 시사하는지 평가하여야 한다.

```
→ B10 관계사 순환거래 — 합리적 사업 근거 없는 특수관계자 거래 탐지
```

> **금감원 실증**: 2024년 중점심사 4대 이슈 중 하나로 "특수관계자거래 회계처리" 선정.

### 2.6 감사기준서 240호 §32(a) — 포괄적 적정성 검사

§32(a)의 "분개기입의 적정성을 테스트" 요구는 위 특정 조항에 매핑되지 않는 룰의 포괄 근거:

```
→ A01 차대변 균형 — 복식부기 위반 = 분개 자체가 부적정
→ B04 중복 지급 — 동일 건 이중 지급 = 적정하지 않은 분개
→ B05 중복 전표 — 동일 전표 반복 = 가공 전표
→ C05 기간 불일치 — 회계기간 ≠ 전기일 = 기간귀속 오류
```

### 2.7 요약 — 기준서 조항 → 룰 도출 흐름

```
감사기준서 240호 §32     "전표의 적정성을 테스트하여야 한다"    → 22개 룰 전체
  ├─ §32(a)(ii)          보고기간 말 전표 선정·검사             → C01
  ├─ §32(c)              비경상적 중요 거래 합리성 평가          → B01, C08
  ├─ A44                 기말 집중 + 전체 기간 필요성 고려       → C01 + 나머지
  ├─ A45(a)              unrelated, unusual, seldom-used accounts → A03, C09
  ├─ A45(b)              individuals who typically do not make JE  → B08
  ├─ A45(c)              end of period + little or no explanation  → C01~C04, C06
  ├─ A45(d)              do not have account numbers               → A02
  ├─ A45(e)              round numbers or consistent ending        → B02, C07
  └─ A46                 computer-assisted audit techniques        → 프로젝트 자체

외감법 §8①5호            업무 분장과 책임                       → B02, B03, B06, B07, B09
외감법 §8①1호            기록 방법                              → C06
외감법 §8②               내회관 우회 금지                       → B09
감사기준서 315호 §26      controls over journal entries           → B06~B08
감사기준서 520호 §5       develop an expectation                  → C07
감사기준서 550호 §23      business rationale of related party      → B10
```

---

## 3. 금감원 감리지적사례 — 189건 전수 읽기 분석

FSS 회계포탈 개별 사례 189건의 **본문(HWP/PDF)을 직접 수집·읽고** 전표 조작 여부를 분류.
원본: `data/finding/` (FSS1912, FSS2008, FSS2112, FSS2206~FSS2512 등 189개 파일)

### 3.1 분석 대상 및 연도별 건수

```
기간         건수   누적    파일 형식    원본 파일명 패턴
──────────────────────────────────────────────────────────
2011~2014     27     27    HWP         FSS2112-01~27
2015~2017     34     61    HWP         FSS2008-01~34
2018~2019     29     90    HWP         FSS1912-01~29
2020          16    106    HWP         개별 파일명 (매출 허위계상 등)
2021          15    121    PDF         FSS2206-01~15
2022          18    139    PDF         FSS2311-01~18
2023          14    153    PDF         FSS2405-01~14
2024 H1       13    166    PDF         FSS2409-01~13
2024 H2       14    180    PDF         FSS2505-01~14
2025 H1       10    190    PDF         FSS2512-01~10
──────────────────────────────────────────────────────────
합계(중복1건 제외) 189건     연평균 ~13건
```

> FSS 포탈 검색 시 229건 표시되나, 종합문서·중복·분류체계 문서 등 제외하면 개별 사례 189건.

### 3.2 전표 조작 관련 여부 — 189건 전수 읽기 결과

FSS 포탈 개별 사례 189건(HWP+PDF)의 **본문을 직접 수집후 분석하여** 전표/분개 조작 관여 여부를 분류.
(data/finding/ 폴더에 원본 보관)

```
기간         전체   전표 관련   전표 무관   전표 비율
──────────────────────────────────────────────────
2011~2014     27       17         10        63%
2015~2017     34       19         15        56%
2018~2019     29       16         13        55%
2020          16       12          4        75%
2021          15        8          7        53%
2022          18        4         14        22%
2023          14        5          9        36%
2024 H1       13        7          6        54%
2024 H2       14        3         11        21%
2025 H1       10        3          7        30%
──────────────────────────────────────────────────
합계         189       94         95        50%
```

> **방법론**: 각 사례 본문에서 허위계상/가공/조작/은폐/횡령/위변조/허위전표 등 키워드 + 문맥 확인.
> 전표 조작 = 실제 거래 없이 전표 생성, 금액/계정/시점 의도적 왜곡, 증빙 위조 후 기록.
> 전표 무관 = 회계기준 해석 오류, 추정치 판단 착오, 주석 공시 누락, 분류 오류 등.

### 3.3 전표 조작 패턴 분류 (94건, 중복 포함)

전표 관련 94건을 본문 내용 기반으로 6대 패턴으로 분류. 하나의 사례에 복수 패턴 해당 가능.

```
패턴                  건수   비율(94건 대비)  대표 사례                                    탐지 룰
───────────────────────────────────────────────────────────────────────────────────────────────────
가공 전표              50     53%            실물 없이 세금계산서/계약서 위조 후            B01, B05, B08
(fictitious entry)                          매출/자산 분개 생성
결산 수정              27     29%            손상 미인식, 충당금 환입, 원가 이연,           C01, C08
(period-end adj.)                           개발비 과대 자산화
횡령 은폐              24     26%            선급금/대여금/매출채권 허위계상으로             B04, B06, B09
(embezzlement)                              횡령액 은폐
순환거래               10     11%            페이퍼컴퍼니·특수관계자 간                    B10
(circular)                                  A→B→C→A 가공매출 순환
승인/SoD 위반           5      5%            1인 입력·승인·실행, 이사회 미의결              B06, B07, B09
(approval bypass)
비정상 시점              4      4%            연말 밀어내기, 납품 전 조기인식                C01, C02, C03
(unusual timing)
───────────────────────────────────────────────────────────────────────────────────────────────────
합계 (중복 포함)       120
```

> **핵심 발견**:
> - "횡령 은폐"는 제목만으로 6건이었으나, 본문 읽기 결과 **24건**으로 4배 증가.
>   선급금/대여금/유형자산 "허위계상"의 상당수가 실제로는 횡령 은폐 목적.
> - "가공 전표"가 절반 이상(53%). 허위 매출이 가장 흔하지만, 유형자산/재고 가공도 다수.
> - 2016~2017년 "공사진행률 조작" 사례 급증 — 조선·건설업 구조조정기와 일치.

### 3.4 프로젝트 시사점

189건 전수 읽기에서 도출된 **전표테스트 자동화 우선순위**:

1. **가공 전표** (50건, 최다) → B01(매출이상변동), B05(중복전표), B08(수기전표) 필수
2. **결산 수정 조작** (27건) → C01(기말대규모) 감도 강화, 결산월 가중치 상향
3. **횡령 은폐** (24건, 고액) → B06(자기승인), B07(직무분리), B09(승인생략) **조합 탐지 필수**
4. **순환거래** (10건) → B10(관계사순환거래) Phase 1부터 구현
5. **승인/SoD 위반** (5건) → B06, B07 — 횡령 은폐의 전제 조건으로 함께 탐지
6. **비정상 시점** (4건) → C02(주말), C03(심야) — false positive 관리 필요

---

## 4. DataSynth 52개 anomaly 유형 — 채택 기준과 우선순위

> **이 섹션의 역할**: §2(법규 요구)와 §3(FSS 실증)을 근거로 DataSynth 52개 유형 중
> **어떤 것을 왜 채택하는지** 선택 근거를 문서화한다. **어떻게 구현하는지**는 §5에서 다룬다.

### 4.1 선택 방법론 — 3축 평가

DataSynth가 정의한 52개 anomaly 유형을 아래 3개 축으로 평가하여 채택 범위를 확정한다.

```
축 1. 법규 근거 (§2 기반)
  3 = 기준서 직접 명시 (240-A45/A49 개별 항목, 520§5, 550§23)
  2 = 기준서 포괄 근거 (240§32 "적정성 테스트")
  1 = 내회관(외감법§8)만, 기준서 미명시
  0 = 한국 법규 매핑 불가

축 2. 실증 빈도 (§3 FSS 189건 기반)
  3 = FSS 주요 패턴 20건+ (가공전표 50, 결산수정 27, 횡령은폐 24)
  2 = FSS 5~19건 (순환거래 10, 승인/SoD위반 5)
  1 = FSS 1~4건 (비정상시점 4)
  0 = FSS 사례 없음

축 3. 데이터 가용성 (29개 컬럼 스키마 기반)
  3 = 29개 컬럼만으로 즉시 탐지 (룰 기반 if문)
  2 = 파생 피처·통계 모델 필요 (ML/통계)
  1 = 외부 마스터 데이터 또는 NLP/그래프 필요
  0 = 현재 스키마로 탐지 불가
```

**채택 판정 기준:**

```
Must  (7~9점) → Phase 1 필수 구현 (룰 기반)
Should(4~6점) → Phase 2 구현 (ML/통계)
Could (2~3점) → Phase 3 이후 검토 (NLP/그래프)
Drop  (0~1점 또는 특별 사유) → 제외
```

### 4.2 Tier 1 — Must: Phase 1 채택 (20개 유형)

법규가 직접 요구하고, FSS에서 실제 발생하고, 29개 컬럼으로 즉시 탐지 가능한 유형.

#### 4.2.1 데이터 무결성 — 전표테스트의 전제조건 (3개)

전표 데이터 자체의 신뢰성을 확보해야 이후 탐지가 의미있다.

```
DataSynth 유형       법규  실증  데이터  합계  §2 근거                    §3 근거
─────────────────────────────────────────────────────────────────────────────────
UnbalancedEntry       3     2     3      8    240§32 복식부기 원칙        횡령은폐 수법(차대 불일치)
MissingField          3     1     3      7    240-A45(d) 계정번호 없음    가공전표(증빙 미비)
InvalidAccount        3     1     3      7    240-A45(a)+315 비정상계정   가공전표(미사용계정 악용)
```

> **선택 근거**: 240-A45가 (a)(d)에서 직접 명시한 "특성"이며, FSS 가공전표 50건의 전제가 되는 데이터 품질 검증.
> 이 3개 룰이 통과하지 않으면 나머지 17개 룰의 탐지 결과 신뢰도가 떨어진다.

#### 4.2.2 가공 전표 탐지 — FSS 최다 패턴 (5개)

§3에서 **50건(53%)** 으로 가장 빈번한 패턴. 허위 매출·자산·재고 분개 생성.

```
DataSynth 유형          법규  실증  데이터  합계  §2 근거                    §3 대표사례
──────────────────────────────────────────────────────────────────────────────────────────
RevenueManipulation      3     3     3      9    240보론2, §32(c) 비경상거래  FSS최다: 매출 허위계상
DuplicateEntry           2     3     3      8    240§32 적정성 테스트         동일 전표 반복 = 가공
ManualOverride           3     3     3      9    240-A45(b) 비인가자 입력     source='manual' 고액 = 우회
JustBelowThreshold       3     2     3      8    240-A45(e) 단수/끝자리      승인한도 직하 반복 = 의도적 분할
BenfordViolation         3     2     2      7    520§5 기대값-차이 분석       금액 분포 조작 탐지
```

> **선택 근거**: 가공전표는 "실물 없이 전표만 생성"하므로 **금액 패턴**(단수, Benford 위반, 한도 직하)과
> **입력 경로**(수기, 중복)에서 흔적을 남긴다. 240-A45가 이 5가지 특성을 직접 열거.

#### 4.2.3 횡령 은폐 탐지 — FSS 고액 패턴 (4개)

§3에서 **24건(26%)**, 오스템임플란트 2,215억 등 **단건 피해액이 가장 큰** 패턴.

```
DataSynth 유형                   법규  실증  데이터  합계  §2 근거              §3 대표사례
────────────────────────────────────────────────────────────────────────────────────────────
SelfApproval                      1     3     3      7    외감법§8①5호 업무분장  오스템: 1인 입력·승인·이체
SegregationOfDutiesViolation      1     3     3      7    외감법§8①5호 업무분장  동일인 전프로세스 수행
SkippedApproval                   1     3     3      7    외감법§8② 우회금지     한도초과+승인없음
DuplicatePayment                  2     3     3      8    240§32 적정성          동일건 이중지급 = 횡령/오류
```

> **선택 근거**: 횡령은 반드시 **통제 우회**(자기승인, 직무분리위반, 승인생략)를 동반한다.
> §3.3에서 "승인/SoD위반 5건"이 독립 패턴이지만, 횡령은폐 24건에도 **전제조건**으로 포함되어 실질 빈도는 29건+.
> 외감법§8 제2항이 "내회관 우회 금지"를 직접 규정하므로 법적 근거도 명확.

#### 4.2.4 결산 수정 조작 — FSS 두 번째 패턴 (4개)

§3에서 **27건(29%)**, 기말 집중 처리되어 탐지 시점이 명확.

```
DataSynth 유형          법규  실증  데이터  합계  §2 근거                      §3 대표사례
──────────────────────────────────────────────────────────────────────────────────────────────
RushedPeriodEnd          3     3     3      9    240§32(a)(ii)+A44 기말검사    손상미인식, 충당금환입
UnusuallyHighAmount      2     3     3      8    240§33(b), 315               개발비 과대자산화
BackdatedEntry           3     2     3      8    240-A45(c) 기말+설명없음      거래일 대비 전기 지연
WrongPeriod              2     2     3      7    240§32 기간귀속 적정성        회계기간 ≠ 전기일
```

> **선택 근거**: 240§32(a)(ii)가 "보고기간 말 전표를 **선정하여 검사**"하라고 직접 명시.
> A44가 "보고기간 말에 발생할 수 있다"고 부연. 결산월 가중치 상향 필요.

#### 4.2.5 순환거래·비정상 시점 — FSS 보조 패턴 (4개)

```
DataSynth 유형          법규  실증  데이터  합계  §2 근거                      §3 대표사례
──────────────────────────────────────────────────────────────────────────────────────────────
CircularIntercompany     3     2     3      8    550§23 특수관계자 합리성      페이퍼컴퍼니 A→B→C→A 순환
WeekendPosting           3     1     3      7    240-A45(c) 비정상시점         연말 밀어내기
AfterHoursPosting        3     1     3      7    240-A45(c) 비정상시점         납품전 조기인식
UnusualAccountPair       3     1     2      6    240-A45(a), 315 비정상계정    차변-대변 쌍 빈도 하위1%
```

> **선택 근거**: 순환거래는 §3에서 10건이지만 550§23이 직접 요구하고 금감원 2024년 중점심사 4대 이슈.
> 비정상 시점은 FSS 4건으로 적으나 240-A45(c)가 직접 명시하여 false positive 관리하며 포함.

#### 4.2.6 보조 징후 (2개 추가)

```
DataSynth 유형          법규  실증  데이터  합계  §2 근거                      비고
──────────────────────────────────────────────────────────────────────────────────────────
ExceededApprovalLimit    1     2     3      6    외감법§8①5호 승인체계         B02(직하)의 보완 — 한도 초과
VagueDescription         3     3     3      9    240-A45(c) 설명없음, §8①1호  적요 공백·위험키워드 탐지
```

**Tier 1 합계: 22개 룰로 구현되는 20개 DataSynth 유형**
(B02↔B03이 JustBelowThreshold/ExceededApprovalLimit 쌍, C07이 BenfordViolation의 세부 구현)

### 4.3 Tier 2 — Should: Phase 2 채택 (16개 유형)

룰만으로 한계가 있거나, 파생 피처·ML 모델이 필요한 유형. Phase 1의 22개 룰 결과를 pseudo-label로 활용.

```
DataSynth 유형              법규  실증  데이터  합계  채택 근거
────────────────────────────────────────────────────────────────────────────────────────────
ImproperCapitalization       2     3     2      7    FSS결산수정 27건 중 "비용→자산 전환" 다수
FictitiousEntry              2     3     2      7    FSS가공전표 50건, Phase 1 룰로 부분탐지만 가능
FictitiousVendor             2     3     1      6    FSS가공전표의 허위거래처, 마스터 교차검증 필요
RoundDollarManipulation      3     1     2      6    240-A45(e), B02보다 정밀한 끝자리 분포 분석
MisclassifiedAccount         2     2     2      6    계정-프로세스 불일치, Phase 1 A03의 ML 확장
ReversedAmount               2     1     2      5    차대 반전 쌍 탐지, VAE 적합
TransposedDigits             2     0     2      4    자릿수 전환 오류, VAE 적합
FutureDatedEntry             2     1     2      5    미래일자 전기, Phase 1 C04의 역방향
CurrencyError                2     1     1      4    환율 불일치, local_amount/currency 컬럼 필요
StatisticalOutlier           2     1     2      5    Z-score 외 다변량 이상치, VAE+IF 앙상블
ExactDuplicateAmount         2     2     2      6    B05보다 넓은 범위의 금액 중복 패턴
TransactionBurst             2     2     2      6    시계열 밀도 급증, FSS가공전표 집중기간 탐지
UnusualFrequency             2     1     2      5    특정 계정/사용자의 비정상 빈도
DormantAccountActivity       3     2     2      7    240-A45(a) "거의 사용되지 않는 계정" — ML확장
NewCounterparty              1     2     1      4    신규 거래처 대액 지급, 벤더 마스터 필요
UnmatchedIntercompany        2     2     1      5    내부거래 미매칭, B10의 확장
```

> **Tier 2 선택 논리**: 법규 근거(축1)나 실증 빈도(축2) 중 하나가 2 이상이면서,
> 데이터 가용성(축3)이 2 이하여서 ML/통계 기법이 필요한 유형.
> 특히 ImproperCapitalization, FictitiousEntry, DormantAccountActivity는 합계 7점으로
> Tier 1에 근접하지만, **룰 기반으로는 정밀도가 부족**하여 Tier 2로 분류.

### 4.4 Tier 3 — Could: Phase 3 검토 (5개 유형)

NLP(적요 분석), 그래프(거래 네트워크), 시계열 추세 등 고급 기법이 필요한 유형.

```
DataSynth 유형             법규  실증  데이터  합계  채택 근거
──────────────────────────────────────────────────────────────────────────────────────────
LatePosting                 1     1     1      3    시계열+NLP 복합, C04의 프로세스 관점 확장
MissingDocumentation        2     2     1      5    NLP 적요 분석으로 증빙 누락 추론
CircularTransaction         3     2     1      6    550§23, B10의 그래프 기반 확장 (A→B→C→A)
TransferPricingAnomaly      2     2     1      5    이전가격 이상, 그래프+금액 복합
TrendBreak                  2     1     1      4    시계열 추세 이탈, 520§5 분석적절차 확장
```

> **Tier 3 선택 논리**: 법규 근거는 있으나 **현재 29개 컬럼만으로는 탐지가 어렵고**
> NLP·그래프·시계열 고급 기법을 결합해야 의미있는 정밀도 달성 가능.
> CircularTransaction(6점)은 Tier 2 수준이지만, 그래프 순환 탐지가 필수여서 Phase 3으로 배치.

### 4.5 Drop — 제외 (11개 유형)

```
DataSynth 유형              법규  실증  데이터  합계  제외 사유
──────────────────────────────────────────────────────────────────────────────────────────────
RoundingError                0     0     3      3    실무 중요성 sev1, false positive 과다
WrongCostCenter              0     0     0      0    코스트센터 마스터 없이 정합성 판단 불가
DecimalError                 0     0     0      0    시스템 레벨 방지, 전표테스트 범위 외
LateApproval                 1     0     0      1    승인 타임스탬프 로그 데이터 없음
IncompleteApprovalChain      1     0     0      1    승인 체인 데이터 없음
UnusualTiming                3     1     3      7    C02/C03과 완전 중복 → 별도 유형 불필요
RepeatingAmount              2     1     2      5    ExactDuplicateAmount(Tier2)와 중복
UnusuallyLowAmount           1     0     2      3    false positive 과다, 실무 가치 낮음
MissingRelationship          1     0     0      1    document_flows 데이터 의존, 스키마 외
CentralityAnomaly            0     0     0      0    그래프 분석 범위 초과, Phase 3에서도 ROI 낮음
AnomalousRatio               1     0     1      2    비율 이상치, StatisticalOutlier에 포섭
```

> **제외 원칙**: ① 한국 법규 매핑 불가(축1=0), ② 현재 스키마로 탐지 불가(축3=0),
> ③ 기채택 유형과 완전 중복(UnusualTiming↔C02/C03, RepeatingAmount↔ExactDuplicateAmount)
> 중 하나 이상 해당하면 제외. UnusualTiming은 합계 7점이지만 **중복 제외** 적용.

### 4.6 선택 결과 요약

```
판정     유형 수   Phase    커버 범위                         FSS 6대 패턴 커버
──────────────────────────────────────────────────────────────────────────────
Must      20개    Phase 1   룰 기반 즉시 탐지                 6/6 (전부 커버)
Should    16개    Phase 2   ML/통계 확장                      가공전표·결산수정 정밀도↑
Could      5개    Phase 3   NLP/그래프 고급 탐지               순환거래 정밀도↑
Drop      11개    —         제외                              —
──────────────────────────────────────────────────────────────────────────────
합계      52개              Phase 3 누적: 41개 유형 커버
```

**핵심 판단:**
- Phase 1(20개 유형)만으로 FSS 6대 패턴을 **전부 커버** — MVP 가치 확보
- Phase 2(+16)에서 가공전표·결산수정의 **정밀도(precision)** 를 ML로 끌어올림
- Phase 3(+5)에서 순환거래·이전가격 등 **관계형 탐지**를 그래프로 보완

### 4.7 외부 시나리오 출처와의 교차 검증

위 3축 평가 결과가 업계 표준 시나리오와 정합하는지 검증한다.

#### 시나리오 출처 계층

```
권위 수준    출처                              내용                            프로젝트 활용
──────────────────────────────────────────────────────────────────────────────────────────
공식 기준    ISA 240 A49 / PCAOB AS 2401 §61   의심 전표 5~11가지 "특성" 제시    근거 인용
준공식       CAQ Practice Aid (AICPA 산하)      15개 CAAT 쿼리 시나리오          주요 참조
실무 참고    Joy Accounting (한국 감사실무자)    12개 시나리오 (A3+B9)            보조 참고
벤더         ACL/IDEA/MindBridge               도구별 내장 시나리오              기능 참고
```

#### CAQ 15개 시나리오 커버리지

```
CAQ #   시나리오                  A49   프로젝트 대응           Tier
──────────────────────────────────────────────────────────────────────
 1      Unbalanced entries        (d)   UnbalancedEntry         Must
 2      Sequential gaps           —     MissingField            Must
 3      High-dollar entries       —     UnusuallyHighAmount     Must
 4      Duplicate account entries —     DuplicateEntry          Must
 5      Round-dollar entries      (e)   JustBelowThreshold      Must
 6      By employee analysis      (b)   SegregationOfDuties     Must
 7      Specific employee entries (b)   SelfApproval            Must
 8      Entry type codes          —     ManualOverride          Must
 9      Manual entries only       (b)   ManualOverride          Must
10      Random/high-dollar sample —     (샘플링 전략)           —
11      Month/day/JE# filter      (c)   RushedPeriodEnd 등      Must
12      Specific accounts         (a)   UnusualAccountPair      Must
13      Account range             (a)   RevenueManipulation     Must
14      Unusual descriptions      (c)   VagueDescription        Must
15      Weekend postings          (c)   WeekendPosting          Must
```

> **결과**: CAQ 15개 중 14개를 Tier 1(Must)에서 커버. #10(샘플링)은 탐지 유형이 아닌 방법론.

#### PCAOB AS 2401 §61 — 11가지 특성 커버리지

```
#   특성                                     A49   프로젝트 대응           Tier
──────────────────────────────────────────────────────────────────────────────────
 1  비경상·저사용 계정                        (a)   InvalidAccount 등       Must
 2  비인가자 입력                             (b)   SelfApproval 등         Must
 3  기말/결산후 수정, 설명없음                (c)   RushedPeriodEnd 등      Must
 4  계정번호 없이 입력                        (d)   MissingField            Must
 5  단수 금액/일관된 끝자리                   (e)   BenfordViolation 등     Must
 6  비정상 거래 포함 계정                     —     UnusualAccountPair      Must
 7  유의적 추정치·기말 수정 계정              —     RushedPeriodEnd         Must
 8  과거 오류 이력 계정                       —     (이력 데이터 필요)      —
 9  미조정 차이 계정                          —     WrongPeriod             Must
10  내부거래 계정                             —     CircularIntercompany    Must
11  부정위험 관련 계정                        —     Tier 1 전체             Must
```

> **결과**: 11개 중 10개 커버. #8(과거 오류 이력)은 히스토리 데이터 의존으로 현재 스키마 외.

> **교차 검증 결론**: 3축 평가로 도출한 Tier 1(Must) 20개 유형이
> CAQ 15개 시나리오의 93%, PCAOB 11개 특성의 91%를 커버.
> 외부 시나리오에서 요구하지만 프로젝트가 미커버하는 항목은
> "과거 이력 의존"(히스토리 데이터)과 "샘플링 전략"(방법론)뿐으로,
> 전표 데이터 기반 자동탐지 프로젝트의 범위 내에서는 **빈틈 없음**.

---

## 5. Phase별 탐지 룰 설계 — DataSynth 52개 유형에서 선택

> **흐름**: §2(법규 요구) → §3(FSS 실증) → **§4(3축 평가로 채택 확정)** → 이 섹션에서 Phase별 구현.
> §4에서 확정된 Must/Should/Could 판정에 따라 각 Phase의 탐지 로직·피처·레이어를 설계한다.

### 설계 원칙

1. **한국 법규 근거가 있는 유형만 채택** — 감사기준서 조항 또는 금감원 감리사례에 매핑 불가한 유형은 제외
2. **전표 데이터(29개 컬럼)만으로 자동탐지 가능한 유형 우선** — 외부 데이터(마스터, 승인로그) 필요 유형은 Phase 구분
3. **Phase 1은 룰 기반** (`if문` 구현) / **Phase 2는 ML 학습 레이블** / **Phase 3은 NLP+그래프**

### Phase 1: MVP 룰 기반 — 3개 레이어, 22개 룰

#### Layer A: 데이터 무결성 (3개)

전표테스트의 전제조건. 이 검증을 통과해야 이후 탐지가 의미있음.

| ID  | 룰명         | DataSynth 유형               | Sev | 근거                         | 탐지 로직                              | 피처                            |
|-----|-------------|------------------------------|-----|------------------------------|---------------------------------------|---------------------------------|
| A01 | 차대변 균형  | `UnbalancedEntry`            | 5   | 240§32, 복식부기 원칙         | `sum(debit) ≠ sum(credit)` per doc_id | `debit_amount`, `credit_amount` |
| A02 | 필수필드 누락 | `MissingField`              | 2   | 240-A49(d), SOX전표기록       | 9개 필수 컬럼 NULL 검사                | 전체 필수 컬럼                   |
| A03 | 무효 계정    | `InvalidAccount`             | 3   | 240-A49(a), 315              | `gl_account NOT IN chart_of_accounts` | `gl_account`                    |

#### Layer B: 부정 탐지 (10개)

| ID  | 룰명           | DataSynth 유형                     | Sev | 근거                              | 탐지 로직                                            | 피처                                    |
|-----|---------------|-------------------------------------|-----|-----------------------------------|-----------------------------------------------------|-----------------------------------------|
| B01 | 매출 이상 변동 | `RevenueManipulation`              | 5   | 240보론2, **FSS최다유형**          | 매출 계정(4xxx) 금액 > 통계 임계값                    | `gl_account`, `debit_amount`            |
| B02 | 승인한도 직하  | `JustBelowThreshold`               | 3   | 240-A49(e), SOX승인               | `금액 ∈ [threshold×0.9, threshold)`                  | `debit_amount`, `credit_amount`         |
| B03 | 승인한도 초과  | `ExceededApprovalLimit`            | 3   | SOX승인, 240§32                   | `금액 > threshold`                                   | `debit_amount`, `credit_amount`         |
| B04 | 중복 지급      | `DuplicatePayment`                 | 3   | 240§32, FSS횡령은폐               | 동일 벤더·금액·기간 내 2건+                            | `auxiliary_account_number`, 금액, 날짜   |
| B05 | 중복 전표      | `DuplicateEntry`                   | 3   | 240§32, FSS가공전표               | 동일 금액·계정·일자 매칭                               | `gl_account`, 금액, `posting_date`      |
| B06 | 자기 승인      | `SelfApproval`                     | 3   | **SOX직무분리**, **FSS오스템**     | `created_by` 기반 추론                                | `created_by`, `source`                  |
| B07 | 직무분리 위반  | `SegregationOfDutiesViolation`     | 4   | **SOX직무분리**, **FSS오스템**     | 동일인 다단계 프로세스                                 | `created_by`, `business_process`        |
| B08 | 수기 전표      | `ManualOverride`                   | 4   | 240-A49(b), SOX, FSS가공전표      | `source == 'manual'` + 고액                           | `source`, 금액                          |
| B09 | 승인 생략      | `SkippedApproval`                  | 4   | SOX승인, FSS오스템                | 한도 초과 + 승인 없음                                 | 금액, `source`, `created_by`            |
| B10 | 관계사 순환거래 | `CircularIntercompany`            | 4   | **550호**, **FSS순환거래**         | company_code 간 순환 패턴                             | `company_code`, `reference`             |

#### Layer C: 이상 징후 (9개)

| ID  | 룰명          | DataSynth 유형                | Sev | 근거                             | 탐지 로직                                | 피처                                 |
|-----|--------------|-------------------------------|-----|----------------------------------|-----------------------------------------|--------------------------------------|
| C01 | 기말 대규모   | `RushedPeriodEnd`             | 3   | 240§32(b)-A49(c), FSS결산        | 월말 5일 이내 + 금액 > Q3                | `posting_date`, 금액                 |
| C02 | 주말 전기     | `WeekendPosting`              | 2   | 240-A49(c), FSS비정상시점         | `weekday() >= 5`                        | `posting_date`                       |
| C03 | 심야 전기     | `AfterHoursPosting`           | 2   | 240-A49(c), FSS비정상시점         | 22시~06시                               | `posting_date` (시간)                |
| C04 | 소급 전기     | `BackdatedEntry`              | 3   | 240-A49(c), FSS횡령은폐          | `posting_date < document_date - N일`    | `posting_date`, `document_date`      |
| C05 | 기간 불일치   | `WrongPeriod`                 | 4   | 240§32(b)                        | `fiscal_period ≠ month(posting_date)`   | `fiscal_period`, `posting_date`      |
| C06 | 위험 적요     | `VagueDescription`            | 1   | 240-A49(c), SOX전표기록           | `line_text` 공백·위험키워드              | `line_text`, `header_text`           |
| C07 | Benford 위반  | `BenfordViolation`            | 2   | **520호**, 240-A49(e)             | MAD > 0.012 or KS p < 0.05             | `debit_amount`, `credit_amount`      |
| C08 | 이상 고액     | `UnusuallyHighAmount`         | 3   | 240§33(b), 315                   | Z-score > 3                             | `debit_amount`, `credit_amount`      |
| C09 | 비정상 계정조합 | `UnusualAccountPair`         | 2   | 240-A49(a), 315                  | 차변-대변 계정 쌍 빈도 하위 1%           | `gl_account`                         |

**Phase 1 합계: A(3) + B(10) + C(9) = 22개 룰, §4 Tier 1의 20개 DataSynth 유형 커버**
(B02↔B03이 JustBelowThreshold/ExceededApprovalLimit 쌍, C07이 BenfordViolation 세부 구현)

### Phase 2: ML 학습 레이블 — 추가 16개 유형

Phase 1의 22개 룰 결과를 pseudo-label로, DataSynth `is_fraud`/`is_anomaly`를 ground truth로.

#### ML 모델 전략

- **지도학습 (분류)**: 다수 모델 후보군 조사 → GridSearchCV로 최적 모델·하이퍼파라미터 선택 (모델 후보는 Phase 2 착수 시 확정)
- **비지도학습 (이상탐지)**: VAE (+ Isolation Forest 앙상블)
- **별도 로직**: DuplicateDetector, 시계열 분석, 내부거래 매칭 등은 전용 로직 유지

| DataSynth 유형           | 카테고리    | Sev | ML 활용 방식                                       |
|--------------------------|------------|-----|----------------------------------------------------|
| ImproperCapitalization   | Fraud      | 4   | GridSearch 지도학습 (비용→자산 계정 전환 패턴)       |
| FictitiousEntry          | Fraud      | 4   | VAE 이상탐지 (비경상 패턴)                           |
| FictitiousVendor         | Fraud      | 5   | GridSearch 지도학습 (마스터 데이터 교차 검증)         |
| RoundDollarManipulation  | Fraud      | 2   | GridSearch 지도학습 (금액 끝자리 분포)               |
| MisclassifiedAccount     | Error      | 3   | GridSearch 지도학습 (계정-프로세스 불일치)            |
| ReversedAmount           | Error      | 3   | VAE (차대 반전 쌍)                                   |
| TransposedDigits         | Error      | 2   | VAE (금액 자릿수 이상)                               |
| FutureDatedEntry         | Error      | 3   | GridSearch 지도학습 (날짜 이상)                      |
| CurrencyError            | Error      | 4   | GridSearch 지도학습 (환율 불일치)                     |
| StatisticalOutlier       | Statistical | 3  | VAE + IF 앙상블                                      |
| ExactDuplicateAmount     | Statistical | 3  | DuplicateDetector                                    |
| TransactionBurst         | Statistical | 4  | 시계열 밀도 분석                                     |
| UnusualFrequency         | Statistical | 2  | 시계열 분석                                          |
| DormantAccountActivity   | Relational | 2   | GridSearch 지도학습 (계정 사용 이력)                  |
| NewCounterparty          | Relational | 1   | GridSearch 지도학습 (신규 거래처 패턴)                |
| UnmatchedIntercompany    | Relational | 3   | 내부거래 매칭 로직                                   |

**Phase 2 누적: §4 Tier 1(20) + Tier 2(16) = 36개 유형 커버**

### Phase 3: NLP + 그래프 — 추가 5개 유형

| DataSynth 유형          | 카테고리    | Sev | 방법               |
|-------------------------|------------|-----|--------------------|
| LatePosting             | ProcessIssue | 2 | 시계열 NLP 복합     |
| MissingDocumentation    | ProcessIssue | 3 | NLP (적요 분석)     |
| CircularTransaction     | Relational  | 4  | 그래프 순환 탐지    |
| TransferPricingAnomaly  | Relational  | 4  | 그래프 + 금액       |
| TrendBreak              | Statistical | 3  | 시계열 추세 분석    |

**Phase 3 누적: §4 Tier 1(20) + Tier 2(16) + Tier 3(5) = 41개 유형 커버**

### 제외 — 13개 유형

| 유형                     | 사유                                         |
|--------------------------|----------------------------------------------|
| RoundingError (sev 1)    | 실무 중요성 낮음, false positive 과다          |
| WrongCostCenter (sev 3)  | 코스트센터 마스터 없이 정합성 판단 불가        |
| DecimalError (sev 3)     | 소수점 오류는 시스템 레벨에서 방지             |
| LateApproval (sev 3)     | 승인 로그 데이터 없음                         |
| IncompleteApprovalChain  | 승인 체인 데이터 없음                         |
| UnusualTiming (sev 1)    | C02/C03과 중복, severity 낮음                 |
| RepeatingAmount (sev 3)  | ExactDuplicateAmount와 중복                   |
| UnusuallyLowAmount       | false positive 과다                           |
| MissingRelationship      | document_flows 데이터 의존                    |
| CentralityAnomaly        | 그래프 분석 범위 초과                         |
| 나머지 3개               | Phase 3 이후 확장 가능                        |

---

## 6. Benford's Law 판정 기준

| 지표       | 적합     | 한계적 적합   | 부적합       | 부적합(강)  |
|------------|---------|--------------|-------------|------------|
| MAD        | < 0.006 | 0.006~0.012  | 0.012~0.015 | > 0.015    |
| KS p-value | > 0.05  | 0.01~0.05    | < 0.01      | —          |

> **근거:**
> - MAD 임계값: Mark Nigrini, *Benford's Law: Applications for Forensic Accounting, Auditing, and Fraud Detection* (Wiley, 2012). 감사/포렌식 분야에서 사실상 표준으로 통용되는 수치.
> - KS p-value: 통계학 일반 유의수준 (0.05, 0.01). 별도 출처 불필요.

추가 검정 (Phase 2): Chi-square, Anderson-Darling

---

## 7. 점수 체계

> **⚠️ 근거 없음 — 프로젝트 자체 설계안.**
> 아래 가중치와 임계값은 공식 기준서·학술 논문 근거가 아닌 초기 설계값이다.
> 실제 데이터 기반 튜닝(Phase 1 완료 후 back-testing)을 거쳐 조정될 예정.

### Phase 1 (3레이어 + Benford)

```
anomaly_score = Layer_A × W_A + Layer_B × W_B + Layer_C × W_C + Benford × W_Benford

기본 가중치 (초기값, 튜닝 대상):
  W_A (무결성) = 0.15    ← 위반 시 다른 점수의 신뢰도 자체가 떨어짐
  W_B (부정)   = 0.45    ← 핵심 탐지 레이어
  W_C (징후)   = 0.25    ← 보조 징후
  W_Benford    = 0.15    ← 통계적 배경

위험 등급 (초기값, 튜닝 대상):
  High:   anomaly_score > 0.7  또는  Layer_A 위반 + Layer_B 2개 이상
  Medium: anomaly_score > 0.4
  Low:    anomaly_score > 0.2
  Normal: anomaly_score ≤ 0.2
```

### Phase 2 (5트랙)

```
rule(0.20) + xgboost(0.25) + vae(0.20) + benford(0.15) + duplicate(0.20)
```

### Phase 3 (7트랙)

```
rule(0.15) + xgboost(0.20) + vae(0.15) + benford(0.10) + duplicate(0.15) + nlp(0.10) + graph(0.15)
```

### 점수 스케일 통일 (Phase 2+)

각 모델의 원시 점수 단위가 다르므로, 가중합 전 Percentile Ranking으로 0~1 정규화.

```
원시 점수 범위:
  XGBoost predict_proba:     0.0 ~ 1.0     (확률)
  Isolation Forest:         -0.5 ~ 0.5     (고립도)
  VAE reconstruction error:  0.0 ~ ∞       (오차)
  룰 기반:                   0.0 ~ 1.0     (정규화 완료)

정규화: scipy.stats.rankdata → 백분위수 0~1 변환
  → 분포 무관, 극단값에 강건 (Min-Max/Z-score 대비 우수)
```

### 성능 평가 지표 체계

| 계층           | 지표            | 용도                                          |
|:---------------|:----------------|:----------------------------------------------|
| 1차 (메인)     | AUPRC (PR-AUC)  | threshold-free, 불균형에 강건. 지도/비지도 공통 |
| 1차 (메인)     | F2-score        | Recall 가중 (부정 놓치는 비용 > 오탐 비용)     |
| 2차 (보조)     | MCC             | 불균형에서도 신뢰할 수 있는 단일 지표           |
| 2차 (보조)     | DR@FAR=5%       | "오탐 5% 허용 시 탐지율" — 실무 의사결정용      |
| 3차 (참고)     | ROC-AUC         | 모델 간 비교용 (불균형 caveat 명시)             |
| 보고용         | Precision/Recall/F1 | 대시보드 표시 + 감사인 소통용               |

F2를 사용하는 이유: 감사에서 부정을 놓치는 비용(FN)이 오탐 비용(FP)보다 크므로
Recall에 2배 가중하는 F2가 F1보다 적합.

---

## 8. 표준 컬럼 스키마

DataSynth `journal_entries.csv` 29개 컬럼 기준.

### 필수 컬럼 (9개)

| 컬럼명           | 타입   | ACDOCA  | 설명             | 탐지 활용              |
|------------------|--------|---------|------------------|------------------------|
| `document_id`    | str    | `belnr` | 전표 ID (UUID)    | A01, B04, B05          |
| `company_code`   | str    | `rbukrs`| 회사코드          | B10                    |
| `fiscal_year`    | int    | `gjahr` | 회계연도          | C05                    |
| `posting_date`   | date   | `budat` | 전기일            | C01~C05                |
| `document_date`  | date   | `bldat` | 전표일            | C04                    |
| `gl_account`     | int    | `racct` | G/L 계정코드      | A03, B01, C09          |
| `debit_amount`   | float  | `wsl(S)`| 차변 금액         | A01, B02~B05, C07~C08  |
| `credit_amount`  | float  | `wsl(H)`| 대변 금액         | A01, B02~B05, C07~C08  |
| `document_type`  | str    | `blart` | 전표유형          | B01                    |

### 권장 컬럼 (10개)

| 컬럼명             | 타입   | ACDOCA  | 설명              | 탐지 활용   |
|--------------------|--------|---------|--------------------|------------|
| `created_by`       | str    | `usnam` | 입력자             | B06~B09    |
| `source`           | str    | —       | 입력소스           | B08, B09   |
| `business_process` | str    | —       | 비즈니스 프로세스   | B07        |
| `line_number`      | int    | `docln` | 라인번호           | A01        |
| `local_amount`     | float  | `hsl`   | 현지통화 금액      | 환율 검증   |
| `currency`         | str    | `rwcur` | 통화               | 환율 검증   |
| `cost_center`      | str    | `rcntr` | 코스트센터         | —          |
| `profit_center`    | str    | `prctr` | 손익센터           | —          |
| `line_text`        | str    | `sgtxt` | 적요               | C06        |
| `header_text`      | str    | `bktxt` | 헤더 텍스트        | C06        |

### 레이블 컬럼 (2개)

| 컬럼명       | 타입 | 설명          | 분포                    |
|-------------|------|---------------|-------------------------|
| `is_fraud`  | bool | fraud 여부     | True 1.3%, False 98.7%  |
| `is_anomaly`| bool | anomaly 여부   | True 2.5%, False 97.5%  |

---

## 9. 도메인 용어 ↔ 코드 매핑

| 감사 용어      | 영문              | DataSynth 컬럼         | 코드 변수              |
|---------------|-------------------|------------------------|------------------------|
| 전표          | Journal Entry      | `document_id`          | `journal_entry`, `je`  |
| 전기일        | Posting Date       | `posting_date`         | `posting_date`         |
| 전표일        | Document Date      | `document_date`        | `document_date`        |
| 적요          | Line Text          | `line_text`            | `line_text`            |
| 차변          | Debit              | `debit_amount`         | `debit_amount`         |
| 대변          | Credit             | `credit_amount`        | `credit_amount`        |
| 역분개        | Reversal           | `xstov` flag           | `is_reversal`          |
| 수기전표      | Manual JE          | `source='manual'`      | `is_manual_je`         |
| 관계사 거래   | Intercompany       | `company_code` 쌍      | `is_intercompany`      |
| 총계정원장    | General Ledger     | `gl_account`           | `gl_account`           |
| 이상징후      | Anomaly            | `is_anomaly`           | `anomaly`              |
| 입력자        | Created By         | `created_by`           | `created_by`           |
| 전표유형      | Document Type      | `document_type`        | `document_type`        |

---

## 10. Fraud Red Flags (참고)

정상 전표에 부여된 의심 징후 (211건, 전부 is_fraudulent=False).
Phase 2 ML에서 **False Positive 내성 훈련**에 활용.

| pattern_name                      | 건수 | category    | strength | confidence |
|-----------------------------------|------|-------------|----------|------------|
| month_end_timing                  | 32   | Timing      | Weak     | 0.10       |
| round_dollar_amount               | 31   | Transaction | Weak     | 0.15       |
| vague_description                 | 20   | Document    | Weak     | 0.15       |
| after_hours_posting               | 18   | Timing      | Weak     | 0.15       |
| repeat_amount_pattern             | 15   | Transaction | Weak     | 0.18       |
| benford_first_digit_deviation     | 12   | Transaction | Weak     | 0.12       |
| weekend_transaction               | 12   | Timing      | Weak     | 0.12       |
| unusual_account_combination       | 11   | Account     | Weak     | 0.20       |
| invoice_without_purchase_order    | 11   | Document    | Moderate | 0.30       |
| employee_vacation_fraud_pattern   | 10   | Employee    | Moderate | 0.45       |
| amount_just_below_threshold       | 10   | Transaction | Moderate | 0.35       |
| missing_supporting_documentation  | 9    | Document    | Moderate | 0.30       |
| dormant_vendor_reactivation       | 7    | Vendor      | Moderate | 0.35       |
| new_vendor_large_first_payment    | 5    | Vendor      | Moderate | 0.40       |
| unusual_vendor_payment_pattern    | 4    | Vendor      | Moderate | 0.30       |
| vendor_no_physical_address        | 2    | Vendor      | Strong   | 0.15       |
| po_box_only_vendor                | 2    | Vendor      | Strong   | —          |

---

## 부록: 참조 출처

### 한국 감사기준서

- [삼일 회계감사기준서 240호 (2023 개정)](https://www.samili.com/acc/JoList.asp?op=4&op2=1&code=413-240)
- [KIFRS 감사기준서 240 - 경영진 통제무력화](https://www.kifrs.com/s/240/41ee67)
- [회계도움e 기준서](https://accounting.krx.co.kr/accounting/standard/view)

### 금감원 감리

- [2023년 회계심사·감리 주요 지적사례 (KDI)](https://eiec.kdi.re.kr/policy/materialView.do?num=251132)
- [최근 3년간 주요 지적사례 (법률신문)](https://www.lawtimes.co.kr/LawFirm-NewsLetter/208508)
- [2025년 감리업무 운영계획 (김앤장)](https://www.kimchang.com/ko/insights/detail.kc?sch_section=4&idx=32034)
- [2024년 상반기 지적사례 (한울회계법인)](https://www.crowe.com/kr/news/news20240924_kr)
- [금감원 2023년 지적사례 공개 (일간NTN)](https://www.intn.co.kr/news/articleView.html?idxno=2035460)

### 내부회계관리제도

- [외감법 제8조](https://casenote.kr/%EB%B2%95%EB%A0%B9/%EC%A3%BC%EC%8B%9D%ED%9A%8C%EC%82%AC_%EB%93%B1%EC%9D%98_%EC%99%B8%EB%B6%80%EA%B0%90%EC%82%AC%EC%97%90_%EA%B4%80%ED%95%9C_%EB%B2%95%EB%A5%A0/%EC%A0%9C8%EC%A1%B0)
- [내부회계관리제도 모범규준 (CGS)](https://www.cgs.or.kr/CGSDownload/eBook/REV/C200501002.pdf)

### 실무 참조

- [Joy Accounting - 전표테스트 시나리오](https://joy-accounting.netlify.app/2021-02-23-journal-entry-test/)
- [ISA 240 원문 (IAASB)](https://www.iaasb.org/publications/isa-240-revised-auditor-s-responsibilities-relating-fraud-audit-financial-statements)

### DataSynth

- GitHub: `mivertowski/SyntheticData` (구 `ey-asu-rnd/SyntheticData`)
- 근거 파일: `crates/datasynth-core/src/models/anomaly.rs`
