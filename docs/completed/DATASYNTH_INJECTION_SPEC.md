# DataSynth Anomaly Injection ?섏젙 紐낆꽭??

> **PHASE1 역할 원칙**: PHASE1은 `fraud`를 확정하거나 정답 라벨을 맞히는 단계가 아니다. PHASE1의 목적은 전수 모집단에서 규칙 위반, 정책 위반, 이상 징후, 분석적 검토 신호를 넓게 올려 **감사인이 봐야 할 항목과 우선순위**를 만드는 것이다. DataSynth의 `is_fraud`/`is_anomaly`와 precision/recall은 개발 검증 보조 지표이며, 운영 해석은 예외 처리 대상, 감사인 리뷰 대상, 고위험 후보를 구분하는 review queue 기준으로 한다.> ?묒꽦?? 2026-03-27
> 紐⑹쟻: DataSynth Rust 肄붾뱶??anomaly injection ?꾨왂 ?꾨㈃ ?섏젙 ?ㅽ럺
> 洹쇨굅: ?꾩닔議곗궗 寃곌낵 53媛?anomaly_type 以?41媛쒓? default fallback(湲덉븸횞2~10諛??쇰줈 泥섎━?섏뼱
>       ?쇰꺼怨??ㅼ젣 ?곗씠?곌? 遺덉씪移? ML/DL ?숈뒿???ъ슜 遺덇?.

## 1. ?꾪솴: strategies.rs 援ъ“??臾몄젣

```rust
// tools/datasynth/crates/datasynth-generators/src/anomaly/strategies.rs
fn apply_strategy(&self, entry: &mut JournalEntry, anomaly_type: AnomalyType, rng: &mut impl Rng) -> InjectionResult {
    match anomaly_type {
        // === 12媛쒕쭔 ?꾩슜 ?꾨왂 ===
        UnusuallyHighAmount    => self.amount_modification.apply(...),
        BackdatedEntry         => self.date_modification.apply(...),
        FutureDatedEntry       => self.date_modification.apply(...),
        WrongPeriod            => self.date_modification.apply(...),
        LatePosting            => self.date_modification.apply(...),
        JustBelowThreshold     => self.approval_anomaly.apply(...),
        ExceededApprovalLimit  => self.approval_anomaly.apply(...),
        VagueDescription       => self.description_anomaly.apply(...),
        BenfordViolation       => self.benford_violation.apply(...),
        SplitTransaction       => self.split_transaction.apply(...),
        SkippedApproval        => self.skipped_approval.apply(...),
        WeekendPosting         => self.weekend_posting.apply(...),

        // === 41媛? ?꾨? 湲덉븸 蹂寃쎌쑝濡?鍮좎쭚 ===
        _ => self.amount_modification.apply(entry, anomaly_type, rng),
    }
}
```

## 2. ?꾩닔議곗궗 寃곌낵 (audit_labels.py, 2026-03-27)

### OK (15媛? ???쇰꺼 = ?곗씠???쇱튂

?꾩옱 ?뺤긽 ?묐룞 以? ?섏젙 遺덊븘??

```
BackdatedEntry           9/9     diff>30d
ExceededApprovalLimit   historical threshold_match

> 2026-05-02 ?댁쁺 湲곗?蹂?`v126`)?먯꽌??`ExceededApprovalLimit`??threshold 湲곕컲???꾨땲??`document amount > approved_by.approval_limit` 湲곗????좎??쒕떎. `v23`? ???뺤젙??泥섏쓬 ?댁쁺 湲곗??쇰줈 ?밴꺽??怨쇨굅 freeze??
> `v126`?먯꽌??`MisclassifiedAccount`媛 CoA 諛?GL???곗? ?딅룄濡?異붽? 蹂댁젙?덈떎. CoA 諛?GL? `InvalidAccount`留??뚯쑀?섍퀬, `MisclassifiedAccount`???좏슚 怨꾩젙???낅Т ?꾨줈?몄뒪 遺덉씪移섎쭔 ?쒗쁽?쒕떎.
> ?먰븳 `DuplicatePayment`??`TRE-only` 蹂듭젣 臾몄꽌媛 ?꾨땲??`P2P + KZ` 吏湲됱뙇 湲곗??쇰줈 ?ш뎄?깅릺?덇퀬, pair lineage / negative control sidecar媛 ?④퍡 ?쒓났?쒕떎.
ImproperCapitalization  11/11    15xx+6xx (Python ?꾩쿂由щ줈 ?섏젙???곹깭 ??Rust?먯꽌 ?닿껐 ?꾩슂)
InvalidAccount           2/2     invalid_gl (Python ?꾩쿂由???Rust)
JustBelowThreshold      29/29    threshold_match
LatePosting             10/10    diff>30d
ManualOverride           3/3     manual+high
RevenueManipulation      7/7     4xxx+high (Python ?꾩쿂由???Rust)
ReversedAmount          11/11    reversal_pair (Python ?꾩쿂由???Rust)
SkippedApproval          6/6     no_approver (Python ?꾩쿂由???Rust)
UnbalancedEntry          2/2     imbalanced (Python ?꾩쿂由???Rust)
WeekendPosting           3/3     weekend
WrongPeriod              7/7     wrong_period
DormantAccountActivity 811/826   dormant_gl (15嫄?誘몄씪移?
```

**二쇱쓽**: 湲곗〈 Python ?꾩쿂由?fix_datasynth_anomalies.py)????젣??
紐⑤뱺 ?섏젙??Rust ?꾨왂(strategies.rs)??援ы쁽 ?꾨즺.

### ALL_MISMATCH (6媛? ???꾩닔 ?섏젙 ?꾩슂

| Type | 臾몄꽌??| ?쇱튂 | 臾몄젣 | Rust ?섏젙 諛⑸쾿 |
|------|-------:|-----:|------|----------------|
| AfterHoursPosting | 12 | 0 | posting_time???낅Т?쒓컙 ??| posting_date ?쒓컙??22:00~05:00 遺꾪룷濡??섑뵆留?(LogNormal ?먮뒗 Uniform) |
| DuplicateEntry | 10 | 0 | ?숈씪 GL+湲덉븸+?좎쭨 ???놁쓬 | DuplicationStrategy ?쒖꽦?? 媛숈? GL+湲덉븸+posting_date濡?2踰덉㎏ entry ?앹꽦 |
| DuplicatePayment | 30 | 0 | vendor+湲덉븸 ???놁쓬 | 媛숈? vendor + 媛숈? 湲덉븸 + posting_date 짹1~15??entry ???앹꽦, business_process=P2P 蹂댁옣 |
| ExactDuplicateAmount | 134 | 0 | 媛숈? 湲덉븸 ???놁쓬 | 媛숈? GL+湲덉븸?쇰줈 2踰덉㎏ entry ?앹꽦 (?좎쭨???ㅻ? ???덉쓬) |
| FutureDatedEntry | 4 | 0 | document_date < posting_date | document_date瑜?posting_date蹂대떎 3~7???ㅻ줈 ?ㅼ젙 |
| VagueDescription | 14 | 0 | line_text???꾪뿕 ?ㅼ썙???놁쓬 | DescriptionAnomalyStrategy???쒓뎅???ㅼ썙??異붽?: "湲고?", "?뺤씤以?, "?꾩떆", "?뚯뒪??, "異뷀썑?뺣━" |

### PARTIAL (7媛? ??誘몄씪移섎텇 ?섏젙 ?꾩슂

| Type | 臾몄꽌??| ?쇱튂 | 誘몄씪移?| Rust ?섏젙 諛⑸쾿 |
|------|-------:|-----:|-------:|----------------|
| SelfApproval | 19 | 4 | 15 | approved_by = created_by 媛뺤젣 ?ㅼ젙. approval_date??posting_date? ?숈씪 |
| SegregationOfDutiesViolation | 10 | 3 | 7 | sod_violation=true, sod_conflict_type??preparer_approver ?깆쑝濡??ㅼ젙 |
| MissingField | 28 | 6 | 22 | ?꾩닔?꾨뱶(gl_account ?먮뒗 reference) 以??섎굹瑜?NULL濡??ㅼ젙. posting_date, document_id??蹂댁〈 |
| RushedPeriodEnd | 9 | 4 | 5 | posting_date瑜??대떦 ??26~31?쇰줈 蹂寃? month_end_spike 濡쒖쭅怨??곕룞 |
| UnusuallyHighAmount | 110 | 6 | 104 | 湲덉븸???대떦 GL 洹몃９??mean + Uniform(3?, 6?)濡??ㅼ젙. ???gl_account蹂??ㅼ젣 std ?ъ슜 |
| StatisticalOutlier | 129 | 1 | 128 | UnusuallyHighAmount? ?숈씪 濡쒖쭅 |
| UnusualTiming | 183 | 1 | 182 | AfterHoursPosting怨??숈씪: ?쒓컙??22:00~05:00?쇰줈 ?ㅼ젙 |

### SKIP ??Rust ?섏젙 ?꾩슂 (13媛?

| Type | 臾몄꽌??| ?꾩떎 ?쒕굹由ъ삤 | Rust ?섏젙 諛⑸쾿 |
|------|-------:|---------------|----------------|
| TransposedDigits | 27 | 寃쎈━ ?섍린?낅젰 ???몄젒 ?먮┸??swap (123,456??32,456) | amount???몄젒 2?먮━ swap. TransposedDigitsStrategy ?대? 議댁옱 ??apply_strategy match??異붽? |
| DecimalError | 9 | ?먮┸??李⑹삤 (留뚯썝??泥쒖썝?쇰줈, 횞10 or 첨10) | amount瑜?횞10 ?먮뒗 첨10. rebalance_entry=false (李⑤?蹂 遺덉씪移??좊컻???꾩떎?? |
| RoundingError | 29 | 諛섏삱由??ㅻ쪟 (?앹옄由?1~9??異붽?/李④컧) | amount 짹 Uniform(1, 9). ?뚯븸?대?濡?李⑤?蹂 1~9??李⑥씠 ?덉슜 |
| CurrencyError | 7 | ?먰솕?붾떖???섏궛 ?ㅼ닔 (첨1,100~1,300 ?먮뒗 횞1,100~1,300) | amount瑜?첨 Uniform(1100, 1300). ?섏쑉 ?곸슜 ?ㅻ쪟 ?쒕??덉씠??|
| MisclassifiedAccount | 6 | 怨꾩젙 遺꾨쪟 ?ㅻ쪟 ?먮뒗 ?낅Т ?꾨줈?몄뒪? 留욎? ?딅뒗 ?좏슚 怨꾩젙 ?ъ슜 | gl_account瑜?CoA??議댁옱?섎뒗 ?ㅻⅨ ?좏슚 怨꾩젙?쇰줈 援먯껜. CoA 諛?怨꾩젙? InvalidAccount ?꾩슜?대?濡??ъ슜 湲덉? |
| WrongCostCenter | 18 | ?ㅻⅨ 踰뺤씤/遺??肄붿뒪?몄꽱???낅젰 | cost_center瑜??ㅻⅨ company_code??CC濡?援먯껜 (?? CC-C001 ??CC-C002) |
| RoundDollarManipulation | 28 | 媛怨??꾪몴 ?뱀쑀???뺥솗??round number (100留? 500留? 1?? | amount瑜?round_number_unit(100留????뺥솗??諛곗닔濡??ㅼ젙. ?앹옄由?000,000 蹂댁옣 |
| UnusuallyLowAmount | 87 | ?먯깋???뚯븸 ?꾧린 (100~1,000??, ?뚯뒪???꾪몴 | amount瑜?Uniform(100, 1000)?쇰줈 ?ㅼ젙 |
| IncompleteApprovalChain | 4 | ?뱀씤 泥댁씤 遺덉셿??(以묎컙 ?뱀씤???꾨씫) | approved_by=NULL, source='manual'. approval_date 誘몄꽕??|
| LateApproval | 5 | ?꾧린 ??14~30???ㅼ뿉???뱀씤 | approval_date = posting_date + Uniform(14, 30)??|
| MissingDocumentation | 12 | 利앸튃 誘몄꺼遺 (reference, header_text 鍮꾩뼱?덉쓬) | reference=NULL, header_text=NULL. line_text???좎? |
| BenfordViolation | 157 | 媛怨?湲덉븸??泥レ㎏?먮┸??遺꾪룷 ?꾨컲 (5~9 ?몄쨷) | BenfordViolationStrategy ?대? 議댁옱 ??apply_strategy match??異붽?. 泥レ㎏?먮┸?섎? Categorical([5,6,7,8,9], equal_weight)濡?媛뺤젣 |
| UnusualAccountPair | 30 | ?낅Т??留뚮궇 ???녿뒗 怨꾩젙 議고빀 (P2P 留ㅼ엯怨꾩젙?봈2R 湲됱뿬怨꾩젙) | cross-process GL ??媛뺤젣 諛곗젙. ?대떦 議고빀???꾩껜 鍮덈룄 ?섏쐞 1%媛 ?섎룄濡?蹂댁옣 |

### Phase 2/3 ??DataSynth 援ъ“???뺤옣 ?꾩슂 (12媛? 4,888嫄?

CSV ?꾩쿂由щ줈 遺덇??ν븳 寃껋씠 ?꾨땲?? **?대떦 Phase???먯? 紐⑤뱢怨??④퍡 ?ㅺ퀎?댁빞 ?섎? ?덈뒗 寃껊뱾.**

| Type | 臾몄꽌??| ?꾩슂???명봽??| 援ы쁽 ?쒖젏 |
|------|-------:|---------------|-----------|
| NewCounterparty | 1,312 | auxiliary_account_number媛 ?곗씠?곗뿉 1?뚮쭔 ?깆옣?섎룄濡?蹂댁옣 | Phase 2c |
| MissingRelationship | 896 | document flow 泥댁씤(PO?묰R?묲nvoice?뭁ayment)?먯꽌 ???④퀎 ?꾨씫 | Phase 2c |
| CentralityAnomaly | 444 | ?뱀젙 entity媛 鍮꾩젙?곸쟻?쇰줈 留롮? 嫄곕옒??愿??| Phase 2c (GNN) |
| CircularTransaction | 416 | trading_partner濡?A?묪?묬?묨 ?쒗솚 泥댁씤 ?앹꽦 | Phase 2c (洹몃옒?? |
| CircularIntercompany | 233 | company_code 媛?IC ?쒗솚 ?앹꽦 + trading_partner 梨꾩? | Phase 2c |
| TransferPricingAnomaly | 472 | IC ???앹꽦 + arm's length ?鍮?20~30% ?댄깉 湲덉븸 | Phase 2c |
| UnmatchedIntercompany | 704 | IC ?쒖そ留??앹꽦, ?곷? ?꾪몴 ?놁쓬 | Phase 2c |
| RepeatingAmount | 90 | ?숈씪 vendor + ?숈씪 湲덉븸??5?? 諛섎났 | Phase 2 (?쒓퀎?? |
| UnusualFrequency | 131 | ?숈씪 vendor 嫄곕옒媛 ?④린媛?1二???吏묒쨷 | Phase 2 |
| TransactionBurst | 104 | ?뱀젙 湲곌컙??嫄곕옒??湲됱쬆 (?됱냼 ?鍮?3?+) | Phase 2 |
| TrendBreak | 77 | ?붾퀎 異붿꽭 ?鍮??댄깉 (?? 留ㅼ텧 湲됰벑/湲됰씫) | Phase 2 |
| FictitiousEntry | 7 | ?ㅻЪ 嫄곕옒 ?녿뒗 媛怨??꾪몴 (vendor 誘몄〈?? | Phase 2 (ML) |
| FictitiousVendor | 2 | 媛吏?嫄곕옒泥?(vendor master???녿뒗 ID) | Phase 2 (ML) |

## 3. 湲濡쒕쾶 ?곗씠??踰꾧렇

?꾩닔議곗궗?먯꽌 諛쒓껄??anomaly injection ???곗씠??臾닿껐??臾몄젣.

| # | ??ぉ | 嫄댁닔 | ?먯씤 | Rust ?섏젙 |
|---|------|-----:|------|-----------|
| 1 | Negative credit_amount | 2 | 湲덉븸 ?앹꽦 踰꾧렇 | abs() 蹂댁옣 ?먮뒗 ?뚯닔 諛⑹? validation |
| 2 | fiscal_period ??posting_month | 174 | WrongPeriod 7嫄댁? ?섎룄?? ?섎㉧吏 167嫄댁? ?좎쭨 蹂??踰꾧렇 | posting_date.month() == fiscal_period 蹂댁옣 (WrongPeriod ?쒖쇅) |
| 3 | trading_partner 99.9% NULL | ~1.1M | IC 紐⑤뱢??trading_partner 誘몄깮??| IC 嫄곕옒(intercompany.enabled=true) ??trading_partner 梨꾩? |
| 4 | DormantAccountActivity 15嫄?誘몄씪移?| 15 | dormant GL 援먯껜 ?꾨씫 | DormantAccountStrategy ?곸슜 ?뺤씤 |

## 4. ?꾩떎 ?쒕굹由ъ삤 留ㅽ븨 (DETECTION_REFERENCE.md 湲곕컲)

媛?anomaly_type???ㅼ젣 媛먯궗?먯꽌 ?대뼡 遺???ㅻ쪟 ?⑦꽩????묓븯?붿?.

### 媛怨??꾪몴 (FSS 50嫄? 53%)

```
FictitiousEntry          ???ㅻЪ ?놁씠 ?멸툑怨꾩궛???꾩“ ??留ㅼ텧/?먯궛 遺꾧컻 ?앹꽦
DuplicatePayment         ???숈씪 嫄??댁쨷 吏湲?(?〓졊 ?섎떒)
DuplicateEntry           ??媛숈? ?꾪몴 諛섎났 ?꾧린 (?쒖뒪???ㅻ쪟 ?먮뒗 ?섎룄??
ExactDuplicateAmount     ???뺥솗??媛숈? 湲덉븸 諛섎났 (?쇱슫?쒗듃由? ?섏씠?쇱뺨?쇰땲)
RevenueManipulation      ??留ㅼ텧 怨꾩젙??鍮꾩젙??怨좎븸 湲곗옣 (?ㅻЪ ?녿뒗 媛怨듬ℓ異?
```

### 寃곗궛 ?섏젙 議곗옉 (FSS 27嫄? 29%)

```
RushedPeriodEnd          ???붾쭚 留덇컧 吏곸쟾 ????꾧린 (諛?대궡湲?
ImproperCapitalization   ??鍮꾩슜???먯궛?쇰줈 ?댁쟾 (?댁씡 遺?由ш린)
UnusuallyHighAmount      ??鍮꾩젙??怨좎븸 寃곗궛 議곗젙
StatisticalOutlier       ???듦퀎?곸쑝濡??댁긽??湲덉븸 (Z-score > 3?)
BenfordViolation         ??媛怨?湲덉븸??泥レ㎏?먮┸??遺꾪룷 ?꾨컲
```

### ?〓졊 ???(FSS 24嫄? 26%)

```
SelfApproval             ???먭린 寃곗옱 (?대??듭젣 ?고쉶, ?ㅼ뒪?쒖엫?뚮????щ?)
SegregationOfDutiesViolation ??1???낅젰쨌?뱀씤쨌?ㅽ뻾 (吏곷Т遺꾨━ ?꾨컲)
SkippedApproval          ???뱀씤 ?놁씠 ?쒕룄 珥덇낵 ?꾪몴 泥섎━
ManualOverride           ???먮룞 ?꾨줈?몄뒪 ?고쉶?섏뿬 ?섍린 ?꾧린 (source='manual' + 怨좎븸)
IncompleteApprovalChain  ???뱀씤 泥댁씤 遺덉셿??(以묎컙 ?뱀씤???꾨씫)
```

### ?쒗솚嫄곕옒 (FSS 10嫄? 11%)

```
CircularTransaction      ??A?묪?묬?묨 媛怨듬ℓ異??쒗솚 (?섏씠?쇱뺨?쇰땲)
CircularIntercompany     ??洹몃９??媛??쒗솚 ?대?嫄곕옒
TransferPricingAnomaly   ??arm's length ?鍮??댁쟾媛寃??댄깉
UnmatchedIntercompany    ??IC ?쒖そ留?議댁옱 (?곷? ?꾪몴 誘몄깮??
```

### 鍮꾩젙???쒖젏 (FSS 4嫄? 4%)

```
AfterHoursPosting        ???ъ빞(22:00~06:00) ?꾧린 (?닿렐 ??紐곕옒 ?꾧린)
UnusualTiming            ??鍮꾩젙???쒓컙? ?꾧린
WeekendPosting           ??二쇰쭚 ?꾧린
BackdatedEntry           ???뚭툒 ?꾧린 (30?? ?댁쟾 ?좎쭨濡?湲곕줉)
FutureDatedEntry         ???좎씪??利앸튃 (?꾩쭅 ?????멸툑怨꾩궛???좎쭨)
LatePosting              ??嫄곕옒 諛쒖깮 ??30?? 吏???꾧린
```

### ?곗씠???ㅻ쪟

```
MissingField             ??ERP 誘몄셿猷??꾧린 (?꾩닔?꾨뱶 NULL)
InvalidAccount           ??CoA???녿뒗 GL 肄붾뱶 ?ъ슜
TransposedDigits         ???섍린 ?낅젰 ?먮┸??swap (123,456??32,456)
DecimalError             ???먮┸??李⑹삤 (留뚯썝?붿쿇?? 횞10/첨10)
RoundingError            ??諛섏삱由??ㅻ쪟 (?앹옄由?1~9??
CurrencyError            ???먰솕?붾떖???섏궛 ?ㅼ닔 (첨1,100~1,300)
MisclassifiedAccount     ??怨꾩젙 遺꾨쪟 ?ㅻ쪟 (?щ퉬?믪젒?鍮?
WrongCostCenter          ??CC ?섎せ ?낅젰 (?ㅻⅨ 踰뺤씤/遺??
WrongPeriod              ???뚭퀎湲곌컙 遺덉씪移?UnbalancedEntry          ??李⑤?蹂 遺덉씪移?MissingDocumentation     ??利앸튃 誘몄꺼遺 (reference, header_text ?놁쓬)
VagueDescription         ??紐⑦샇???곸슂 ("湲고?", "?뺤씤以?, "?꾩떆")
```

### ?듦퀎???댁긽

```
UnusualAccountPair       ???낅Т??留뚮궇 ???녿뒗 怨꾩젙 議고빀 (P2P?봈2R GL ??
RoundDollarManipulation  ??媛怨??꾪몴 ?뱀쑀???뺥솗??round number
UnusuallyLowAmount       ???먯깋???뚯븸 ?꾧린 (100~1,000?? ?뚯뒪???꾪몴)
LateApproval             ???꾧린 ??14~30??吏???뱀씤
```

## 5. Rust ?섏젙 ?곗꽑?쒖쐞

### P0: 湲곗〈 ?꾨왂 match臾??꾨씫 (?대? Strategy 議댁옱)

strategies.rs??match臾몄뿉 異붽?留??섎㈃ ?? 肄붾뱶 蹂寃?理쒖냼.

```
TransposedDigits  ??TransposedDigitsStrategy (?대? 援ы쁽)
BenfordViolation  ??BenfordViolationStrategy (?대? 援ы쁽)
AfterHoursPosting ??WeekendPostingStrategy ?뺤옣 (?쒓컙 蹂寃?濡쒖쭅 異붽?)
UnusualTiming     ???꾩? ?숈씪
```

### P1: ?좉퇋 ?꾨왂 援ы쁽 ?꾩슂

| ?꾨왂 | ??????| ?덉긽 LOC | ?듭떖 濡쒖쭅 |
|------|-----------|:--------:|-----------|
| SelfApprovalStrategy | SelfApproval | ~50 | approved_by = created_by |
| MissingFieldStrategy | MissingField | ~40 | ?꾩닔?꾨뱶 1媛쒕? NULL |
| DuplicateEntryStrategy | DuplicateEntry, ExactDuplicateAmount, DuplicatePayment | ~150 | entry 蹂듭젣 + new doc_id + date offset |
| FutureDateStrategy | FutureDatedEntry | ~40 | document_date = posting + 3~7??|
| SoDViolationStrategy | SegregationOfDutiesViolation | ~60 | sod_violation=true + conflict_type |
| RushedPeriodEndStrategy | RushedPeriodEnd | ~40 | posting_date.day瑜?26~31濡?|
| HighAmountStrategy | UnusuallyHighAmount, StatisticalOutlier | ~80 | amount = gl_mean + Uniform(3?, 6?) |
| LowAmountStrategy | UnusuallyLowAmount | ~30 | amount = Uniform(100, 1000) |
| FormatErrorStrategy | DecimalError, RoundingError, CurrencyError | ~80 | 횞10/첨10, 짹1~9, 첨1200 |
| AccountSwapStrategy | MisclassifiedAccount, WrongCostCenter | ~60 | GL/CC瑜?媛숈? 洹몃９ ???ㅻⅨ 媛믪쑝濡?援먯껜 |
| RoundDollarStrategy | RoundDollarManipulation | ~30 | amount瑜?round_unit???뺥솗??諛곗닔濡?|
| DocumentationStrategy | MissingDocumentation, IncompleteApprovalChain, LateApproval | ~60 | reference/header_text NULL, approval_date 吏??|
| RarePairStrategy | UnusualAccountPair | ~100 | cross-process GL ??媛뺤젣 諛곗젙 + 鍮덈룄 ?섏쐞 1% 蹂댁옣 |

### P2: 湲濡쒕쾶 踰꾧렇 ?섏젙

```
1. negative credit 諛⑹?: amount ?앹꽦 ??abs() 蹂댁옣
2. fiscal_period ?뺥빀?? posting_date.month() ?숆린??3. trading_partner 梨꾩?: IC 嫄곕옒???쒗빐 counterparty company_code ?ㅼ젙
4. DormantAccount 15嫄?誘몄씪移? strategy ?곸슜 ?뺤씤
```

### P3: Phase 2/3 ?꾩슜 (?먯? 紐⑤뱢怨??④퍡 援ы쁽)

```
CircularTransaction, CircularIntercompany ??洹몃옒??紐⑤뱢
TransferPricingAnomaly, UnmatchedIntercompany ??IC 紐⑤뱢
NewCounterparty, MissingRelationship, CentralityAnomaly ??愿怨?紐⑤뱢
RepeatingAmount, UnusualFrequency, TransactionBurst, TrendBreak ???쒓퀎??紐⑤뱢
FictitiousEntry, FictitiousVendor ??ML 遺꾨쪟湲?```

## 6. ?듭떖 遺꾪룷 ?뚮씪誘명꽣 (?꾩떎??遺꾩궛 蹂댁옣)

?섎뱶肄붾뵫 湲덉?. 紐⑤뱺 ?섏튂??遺꾪룷?먯꽌 ?섑뵆留?

| ??ぉ | 遺꾪룷 | ?뚮씪誘명꽣 | 洹쇨굅 |
|------|------|----------|------|
| ?뱀씤?쒕룄 吏곹븯 鍮꾩쑉 | Uniform | (0.88, 0.99) | ?〓졊踰붿? ?쒕룄??88~99%?먯꽌 遺꾩궛 |
| ?뚭툒 ?쇱닔 | LogNormal | mu=3.5, sigma=0.5 ??以묒븰媛?33?? 踰붿쐞 20~90??| ?ㅻТ ?뚭툒? 1~3媛쒖썡 ?ㅼ뼇 |
| ?ъ빞 ?쒓컙 | Uniform | (22.0, 29.0) mod 24 ??22:00~05:00 | ?ъ빞 ?꾧린 遺꾪룷 |
| 李⑤?蹂 遺덉씪移?| LogNormal | mu=4, sigma=2 ??以묒븰媛?55?? 踰붿쐞 1???섏쿇??| 諛섏삱由??낅젰 ?ㅻ쪟 |
| 怨좎븸 Z-score | Uniform | (3.0, 6.0) 횞 ? | ?듦퀎???댁긽移?湲곗? |
| ?먮┸???ㅻ쪟 諛곗닔 | Choice | [0.1, 10.0] equal weight | ???먮┸??李⑹삤 |
| ??텇媛??쒖감 | Uniform | (0, 1)??| SAP ??텇媛쒕뒗 ?뱀씪~?듭씪 |
| 以묐났 吏湲??쒖감 | Uniform | (1, 15)??| ?숈씪 泥?뎄???댁쨷 泥섎━ |

## 7. 寃利?諛⑸쾿

Rust ?섏젙 ???ъ깮????

```bash
# 1. ?꾩닔議곗궗 ?ㅽ뻾
PYTHONPATH=. uv run python tools/audit_labels.py
# 紐⑺몴: ALL_MISMATCH=0, PARTIAL??誘몄씪移?0

# 2. E2E ?쇰꺼 寃利?PYTHONPATH=. uv run python tests/phase1_rulebase/test_e2e_label_validation.py
# 紐⑺몴: Phase 1 Recall > 95%

# 3. 遺꾩궛 寃利????숈씪 媛??대윭?ㅽ꽣留??녿뒗吏 ?뺤씤
# L2-01 amounts媛 ?꾨? 媛숈? 鍮꾩쑉?대㈃ ?ㅽ뙣
# L3-07 date diff媛 ?꾨? 媛숈? ?쇱닔?대㈃ ?ㅽ뙣

# 4. 湲곗〈 ?뚯뒪???뚭?
uv run pytest tests/ -v --timeout=120
```

## 8. ?먭린 ???
| ?뚯씪 | ?ъ쑀 |
|------|------|
| `tools/fix_datasynth_anomalies.py` | **??젣??* ??Rust strategies.rs??紐⑤뱺 ?꾨왂 援ы쁽 ?꾨즺 |
| `data/journal/primary/datasynth/journal_entries.csv.bak` | ?먮낯?쇰줈 蹂듭썝 ?꾨즺. bak ??젣 媛??|


