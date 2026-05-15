# Project Overview

> **🔄 Phase 3 v2 Rescope 안내 (2026-05-14) ✅ 구현 완료 (Sprint A~G, 2026-05-15)**: 본 문서의 Phase 3 관련 기술 스택 표·디렉토리 구조·pre-plan 인덱스(8/9번)는 v1 시점 정의(Ollama/Vanna/Text-to-SQL/Export)다. Phase 3 v2 단일 목표는 **Review Queue Narrator** — PHASE1 룰 히트 + PHASE2 ML 스코어 + 전표 메타를 LLM이 읽고 감사 후보 Top-N 재정렬 + 의심 근거 서술 + 다음 행동 제안. Text-to-SQL/Vanna/ChromaDB/fpdf2/Export 탭/Chat 탭은 비범위(구현 보존, 신규 작업 없음). 단일 출처: [PHASE3_REVIEW_NARRATOR_SPEC.md](PHASE3_REVIEW_NARRATOR_SPEC.md), [PHASE3_REWORK_PLAN.md](PHASE3_REWORK_PLAN.md), [DECISION.md §D041 / §D043](DECISION.md), 완료 리포트 [completed/phase3_review_narrator_completion.md](completed/phase3_review_narrator_completion.md). 본 문서 본문 라인은 historical reference로 보존한다.

> **PHASE1 역할 원칙**: PHASE1은 `fraud`를 확정하거나 정답 라벨을 맞히는 단계가 아니다. PHASE1의 목적은 전수 모집단에서 규칙 위반, 정책 위반, 이상 징후, 분석적 검토 신호를 넓게 올려 **감사인이 봐야 할 항목과 우선순위**를 만드는 것이다. DataSynth의 `is_fraud`/`is_anomaly`와 precision/recall은 개발 검증 보조 지표이며, 운영 해석은 예외 처리 대상, 감사인 리뷰 대상, 고위험 후보를 구분하는 review queue 기준으로 한다.

> PHASE1 operating role: PHASE1 is a rule-based full-population screening layer, not a final fraud classifier. Its first job is to surface all records, groups, and macro signals that violate configured rules or deserve review. The second step classifies those hits into normal exceptions, auditor review queues, and high-risk candidates using materiality, evidence strength, case priority, company exception policy, and rule combinations.

> Current DataSynth baseline: `data/journal/primary/datasynth/` freeze `v126` as of 2026-05-02. Dataset size is `1,109,435` rows / `319,193` documents / `52` columns. Main label sidecar: `labels/anomaly_labels.csv` `3,149` rows.

> PHASE1 scoring baseline: rule results are normalized through `src/detection/rule_scoring.py` before case aggregation. Dashboard/report priority is case-level `priority_score`, not a direct sum of raw rule labels or row-level `anomaly_score`. Case priority uses control, amount, logic, timing, and behavior axes; timing keeps closing/cutoff signals such as L3-11 visible in the review queue.

> Current PHASE1 rule scope: 32 L1~L4 implemented rules. L3-12 is an `access_scope_review` work-scope review signal, separated from L1-06 direct SoD violations and promoted only through `work_scope_combo_score` when corroborating rule groups are present.

## ?꾨줈?앺듃 ?뺤쓽

Local AI Audit Assistant v2.0 ??媛먯궗 ?ㅼ쬆?덉감 ?꾪몴 ?뚯뒪???먮룞???꾧뎄.
MindBridge, KPMG Clara???듭떖 濡쒖쭅???ㅽ뵂?뚯뒪(Python)濡??ы쁽?섎뒗 ?ы듃?대━??

## 湲곗닠 ?ㅽ깮

| ?곸뿭        | 湲곗닠                               | 鍮꾧퀬                                        |
|-------------|------------------------------------|---------------------------------------------|
| ?몄뼱        | Python 3.11+                       |                                             |
| ?⑦궎吏      | uv + pyproject.toml                | dependency-groups濡?core/ml/llm/dashboard 遺꾨━ |
| ?꾩쿂由?     | openpyxl, pandas 2.x, pandera      | pandera: ?ㅽ궎留?湲곕컲 ?덉쭏 寃뚯씠??           |
| 而щ읆 留ㅽ븨   | rapidfuzz                          | fuzzy string matching                       |
| ?ㅼ젙        | pydantic-settings, pyyaml          | ?섍꼍蹂??+ YAML                             |
| ?듦퀎        | scipy.stats, numpy                 | Benford, KS 寃?? Runs test                |
| 吏?꾪븰??   | xgboost, lightgbm, scikit-learn, shap | ?뚯씠?꾨씪???명봽??(怨좉컼???ㅻ뜲?댄꽣 fine-tuning?? Phase 2) |
| 鍮꾩??꾪븰?? | pytorch (VAE), scikit-learn (IF)   | **?듭떖 ?먯?湲?* ???⑹꽦 ?곗씠???곹빀???믪쓬 (Phase 2)  |
| ?쒓뎅??NLP  | kiwipiepy                          | JVM ?섏〈???놁쓬 (Phase 3)                  |
| DB          | duckdb                             | OLAP 理쒖쟻??                                |
| LLM         | ?곸슜 API (Gemini, Claude ??       | Phase 3 ??濡쒖뺄 LLM ????곸슜 API ?ъ슜      |
| Text-to-SQL | ?곸슜 LLM API 湲곕컲                  | Phase 3                                     |
| 踰≫꽣 DB     | ChromaDB                           | RAG ?ㅽ넗由ъ? (Phase 3)                     |
| ??쒕낫??   | streamlit, plotly, streamlit-aggrid |                                             |
| PDF         | fpdf2                              | Phase 3                                     |

## ?붾젆?좊━ 援ъ“

> **?꾪궎?띿쿂 ?꾪솚 (2026-04-02)**: Company-Centric ?ъ꽕怨?吏꾪뻾 以? [NEW_TASKS.MD](NEW_TASKS.MD) 李몄“.

```
local-ai-assist/
?쒋?? pyproject.toml
?쒋?? CLAUDE.md
?쒋?? config/                     # 湲濡쒕쾶 湲곕낯 ?ㅼ젙 (?뚯궗蹂??ㅻ쾭?쇱씠?쒖쓽 ?대갚)
??  ?쒋?? settings.py             # AuditSettings + ContextFactory
??  ?쒋?? datasynth.yaml          # DataSynth ?앹꽦 ?ㅼ젙
??  ?쒋?? schema.yaml             # ?쒖? 46而щ읆 ?ㅽ궎留?(?꾩궗 怨듯넻)
??  ?쒋?? keywords.yaml           # 湲곕낯 ERP蹂??ㅻ뜑 ?ㅼ썙????  ?쒋?? audit_rules.yaml        # 湲곕낯 媛먯궗 猷???  ?쒋?? risk_keywords.yaml      # 湲곕낯 ?꾪뿕 ?곸슂 ?ㅼ썙????  ?쒋?? cleaning.yaml           # ???罹먯뒪??洹쒖튃 (?꾩궗 怨듯넻)
??  ?쒋?? chart_of_accounts.csv   # 踰붿슜 CoA (湲濡쒕쾶 ?대갚)
??  ?붴?? presets/                # ?곗뾽蹂??꾨━??(?고????ㅻ쾭?덉씠)
?쒋?? src/
??  ?쒋?? context.py              # CompanyContext + ContextFactory (RC-0)
??  ?쒋?? pipeline.py             # AuditPipeline(context=) ?ㅼ??ㅽ듃?덉씠????  ?쒋?? company/                # ?뚯궗/Engagement CRUD (RC-0)
??  ??  ?쒋?? models.py           # CompanyProfile, EngagementProfile
??  ??  ?쒋?? repository.py       # YAML CRUD, ?붾젆?좊━ 愿由???  ??  ?쒋?? merger.py           # 3怨꾩링 deep_merge
??  ??  ?붴?? migration.py        # ?덇굅??DB 留덉씠洹몃젅?댁뀡
??  ?쒋?? ingest/                 # ?섏쭛쨌?됲깂????  ?쒋?? feature/                # 媛먯궗 ?뚯깮蹂??19媛???  ?쒋?? eda/                    # EDA ?꾨줈?뚯씪留???  ?쒋?? validation/             # 怨꾩링??寃利?(L1~L3)
??  ?쒋?? preprocessing/          # ML ?꾩쿂由??뚯씠?꾨씪??(Phase 2)
??  ?쒋?? detection/              # PHASE1 L1~L4 32媛?猷?+ 蹂댁“ findings
??  ?쒋?? db/                     # DuckDB (ConnectionManager)
??  ?쒋?? llm/                    # LLM ?곕룞 (Phase 3)
??  ?붴?? export/                 # ?대낫?닿린 (Phase 3)
?쒋?? dashboard/                  # Streamlit
??  ?쒋?? app.py                  # 硫붿씤 ??(?뚯궗 ?좏깮 ??遺꾩꽍 ?뚮줈??
??  ?쒋?? page_company.py         # ?뚯궗 ?좏깮/?앹꽦 ?붾㈃ (RC-4)
??  ?쒋?? _state.py               # session_state ??(company_id, engagement_id ?ы븿)
??  ?쒋?? _kpi.py                 # KPI 6媛???  ?쒋?? tab_eda.py              # Tab 0: EDA ?꾨줈?뚯씪
??  ?쒋?? tab_summary.py          # Tab 1: Executive Summary
??  ?쒋?? tab_benford.py          # Tab 2: Benford Analysis
??  ?쒋?? tab_explorer.py         # Tab 3: Anomaly Explorer
??  ?쒋?? tab_comparison.py       # Tab 4: ?곕룄 鍮꾧탳 (RC-4)
??  ?쒋?? tab_chat.py             # Tab 5: Text-to-SQL (Phase 3)
??  ?붴?? components/
??      ?쒋?? company_manager.py  # ?뚯궗 CRUD 而댄룷?뚰듃 (RC-4)
??      ?쒋?? engagement_selector.py # ?곕룄 ?좏깮 (RC-4)
??      ?쒋?? data_uploader.py    # ?뚯씪 ?낅줈??+ ?뚯씠?꾨씪???ㅽ뻾
??      ?쒋?? filters.py          # ?ъ씠?쒕컮 ?꾪꽣 12媛???      ?쒋?? mapping_review.py   # 留ㅽ븨 由щ럭 3-tier UI
??      ?쒋?? preset_selector.py  # ?꾨━??+ ?뚯궗蹂??ㅼ젙 ?듯빀
??      ?쒋?? threshold_sidebar.py # ?꾧퀎媛??쒕떇 ?щ씪?대뜑
??      ?쒋?? rule_panel.py       # 猷?而⑦듃濡??⑤꼸
??      ?쒋?? _redetect.py        # ?ы깘吏 ?ы띁
??      ?쒋?? explorer_*.py       # ?먯깋湲??쒕툕 而댄룷?뚰듃 3醫???      ?붴?? charts/             # Plotly 李⑦듃 ?섑띁 17醫??쒋?? data/
??  ?쒋?? companies/              # ?뚯궗蹂??곗씠??(Company-Centric)
??  ??  ?붴?? {company_id}/
??  ??      ?쒋?? company.yaml    # 硫뷀? + settings_overrides
??  ??      ?쒋?? chart_of_accounts.csv
??  ??      ?쒋?? keywords.yaml   # ERP 蹂꾩묶 ?ㅻ쾭?쇱씠????  ??      ?쒋?? audit_rules.yaml
??  ??      ?쒋?? profiles/       # 留ㅽ븨 ?꾨줈?뚯씪
??  ??      ?붴?? engagements/{year}/
??  ??          ?쒋?? engagement.yaml
??  ??          ?쒋?? audit.duckdb  # Engagement蹂?寃⑸━ DB
??  ??          ?붴?? models/       # ML 紐⑤뜽 ?꾪떚?⑺듃
??  ?붴?? journal/                # ?꾪몴 ?먮낯 (.gitignore)
?쒋?? tools/datasynth/            # EY-ASU DataSynth (Rust)
?쒋?? tests/
?붴?? docs/
```

## 援ы쁽 媛?대뱶 (docs/pre-plan/)

媛쒖슂?쒕? 湲곕뒫 ?곸뿭蹂꾨줈 遺꾨━??援ы쁽 ?덊띁?곗뒪. 媛??뚯씪? 紐⑹쟻/愿???뚯씪/?듭떖 ?대옒???곗씠???먮쫫/援ы쁽 ?쒖꽌/?뚯뒪???꾨왂???ы븿.

| #  | ?뚯씪                                                     | ?댁슜                                                          | Phase  |
|----|----------------------------------------------------------|---------------------------------------------------------------|--------|
| 0  | [00-dataset.md](pre-plan/00-dataset.md)                  | ?곗씠?곗뀑 ?섏쭛쨌?좎젙쨌?곹빀?꽷텾hase蹂??쒖슜 ?꾨왂                   | ?ъ쟾   |
| 1  | [01-project-setup.md](pre-plan/01-project-setup.md)      | pyproject.toml, uv, AuditSettings, YAML ?ㅼ젙                 | MVP    |
| 2  | [02-ingest.md](pre-plan/02-ingest.md)                    | ?뚯씪 寃利? Excel ?쎄린, ?ㅻ뜑 ?먯?, 而щ읆 留ㅽ븨, ???罹먯뒪??    | MVP    |
| 3  | [03-feature.md](pre-plan/03-feature.md)                  | 媛먯궗 ?뚯깮蹂??11媛?(time/amount/pattern/text)                 | MVP    |
| 3a | [03a-preprocessing.md](pre-plan/03a-preprocessing.md)    | ML ?꾩쿂由??뚯씠?꾨씪?? VAE ?섑띁, ?쇰꺼 ?꾨왂                     | P2     |
| 4  | [04-validation.md](pre-plan/04-validation.md)            | L1 Pandera + L2 ?뚭퀎 + L3 ?듦퀎 寃利?+ 由ы룷??                | MVP+P2 |
| 5  | [05-detection.md](pre-plan/05-detection.md)              | 珥덇린 24媛?猷??ㅺ퀎 湲곕줉. ?꾪뻾 湲곗?? L1/L2/L3/L4 32媛?猷? Benford(L4-02), L3-12 work-scope review, ML 16媛? NLP 5媛?| MVP~P3 |
| 6  | [06-db.md](pre-plan/06-db.md)                            | DuckDB 而ㅻ꽖?? ?ㅽ궎留? 濡쒕뜑, ?꾨━??荑쇰━                     | MVP    |
| 7  | [07-dashboard.md](pre-plan/07-dashboard.md)              | Streamlit 5?? 而댄룷?뚰듃, 李⑦듃, ?꾪꽣                          | MVP+P3 |
| 8  | [08-llm.md](pre-plan/08-llm.md)                          | Ollama, Vanna AI 2.0, SQL 寃利? ?꾨━?? ?몄궗?댄듃             | P3     |
| 9  | [09-export.md](pre-plan/09-export.md)                    | Excel/PDF 媛먯궗議곗꽌, Audit Trail                               | P3     |
| 10 | [10-sample-data.md](pre-plan/10-sample-data.md)          | 媛??GL ?곗씠???앹꽦湲???DataSynth濡??泥대맖                    | MVP    |
| UX | [ux-flow.md](pre-plan/ux-flow.md)                        | UX 3?④퀎 ?먮쫫?? 媛먯궗???щ━, 3媛吏 ?붿옄???먯튃               | ?꾩껜   |

**援ы쁽 ?섏〈 洹몃옒??**
```
00-dataset ??01-project-setup ??10-sample-data ??02-ingest ??03-feature ??04-validation
                                                                    ??                                                              05-detection ??03a-preprocessing ??ML ?먯?
                                                                                                    ??                                                                                                  06-db
                                                                                                    ??                                                                                              07-dashboard
                                                                                                    ??                                                                                         08-llm ??09-export
```

## ?⑹꽦 ?곗씠??(DataSynth)

EY-ASU DataSynth(Rust)濡??앹꽦??K-IFRS ?곸슜 ?쒓뎅 以묎껄 ?쒖“ 洹몃９???쒕??덉씠??

| ??ぉ           | 媛?                                                   |
|----------------|-------------------------------------------------------|
| 踰뺤씤           | C001 蹂몄궗(?쒖슱), C002 ?몄궛怨듭옣, C003 泥쒖븞怨듭옣 ???꾩껜 KRW |
| ?뚭퀎?곕룄       | 2022-01 ~ 2024-12 (3媛쒕뀈)                             |
| ?꾪몴 洹쒕え      | 319,226嫄?/ 1,109,221 ?쇱씤?꾩씠??(?꾪몴????3.47??      |
| 湲덉븸 遺꾪룷      | LogNormal(14.0, 2.5) ???쇱씤 以묒븰媛?~33.6留뚯썝, ?됯퇏 ~1,706留뚯썝 |
| ?뱀씤 ?쒕룄      | 6?④퀎 ?꾧껐洹쒖젙 (?먮룞?믩떞?뱀옄?믫??β넂蹂몃??β넂CFO?믪씠?ы쉶)    |
| ?ъ슜???      | 吏곸썝 留덉뒪??246紐?湲곕낯 204 + JE actor 42), `created_by 42/42` 諛?`approved_by 14/14` 吏곸젒 議곗씤 |
| ?쒓컙 ?⑦꽩      | ?쒓뎅 洹쇰Т 臾명솕 諛섏쁺 (?ъ빞 1.5%, ?ㅼ쟾 ?쇳겕 29.7%, ?쇨렐 13.1%) |
| ?댁긽 二쇱엯      | fraud 1.35% (15,008?? + anomaly 0.57% (6,270?? + SoD 2.75% (30,488?? + anomaly_labels.csv 1,912嫄?(5媛?移댄뀒怨좊━) |
| Benford        | 泥レ㎏ ?먮┸???곹빀 (tolerance 5%, payroll/recurring ?쒖쇅) |

## ML ?숈뒿 ?꾨왂

鍮꾩??꾪븰??以묒떖 + 吏?꾪븰???뚯씠?꾨씪???명봽??援ъ텞.

| ?묎렐踰?| 紐⑤뜽 | ??븷 | ?⑹꽦 ?곗씠???곹빀??|
|:-------|:-----|:-----|:-----------------:|
| 鍮꾩??꾪븰??| VAE + Isolation Forest | **?듭떖 ?먯?湲?* ???뺤긽 遺꾪룷 ?댄깉 ?먯? | ?믪쓬 |
| 吏?꾪븰??| XGBoost, FT-Transformer, BiLSTM | ?뚯씠?꾨씪???명봽????怨좉컼???ㅻ뜲?댄꽣 ?좎엯 ???쒖꽦??| 以묎컙 |
| ?숈긽釉?| Stacking Meta-Learner (LR Ridge) | 6媛?紐⑤뜽 異쒕젰 寃고빀 | ?믪쓬 |

**諛곌꼍**: DataSynth ?⑹꽦 ?곗씠?곗쓽 ?댁긽移섎뒗 猷?湲곕컲?쇰줈 二쇱엯?섎?濡? 吏?꾪븰?????쒗솚 ?숈뒿(Circular Learning) 臾몄젣 諛쒖깮.
鍮꾩??꾪븰??VAE+IF)? ?뺤긽 遺꾪룷瑜??숈뒿?섎?濡??⑹꽦 ?곗씠?곗뿉?쒕룄 ?좏슚.
吏?꾪븰???뚯씠?꾨씪??cv_selector, SMOTE-ENN, PR-AUC ?됯?)? ?명봽?쇰줈 援ъ텞?섏뿬,
?ν썑 怨좉컼?щ퀎 ?ㅻ뜲?댄꽣 ?좎엯 ??fine-tuning?쇰줈 利됱떆 ?쒖꽦??媛??

?곸꽭: [CONSTRAINTS.md 짠ML ?숈뒿 ?꾨왂](CONSTRAINTS.md) | [TROUBLESHOOT.md 짠TS-3](TROUBLESHOOT.md)

## ?곗씠???먮쫫

> **Company-Centric ?ъ꽕怨?諛섏쁺 (2026-04-02)**

```
[??쒕낫??吏꾩엯]
  ???뚯궗 ?좏깮/?앹꽦 ??Engagement(?곕룄) ?좏깮 ??CompanyContext ?앹꽦
  ??(ContextFactory: 湲濡쒕쾶 ???뚯궗 ???곕룄 3怨꾩링 ?ㅼ젙 ?댁냼)

[?곗씠???낅줈??
  Excel/CSV ??file_validator ??reader ??header_detector
  ??column_mapper(?릀tx.keywords) ??type_caster(?릀leaning.yaml)
  ??留ㅽ븨 ?꾨줈?뚯씪 ???(ctx.profile_dir)
  ??UX 1?④퀎: ?먮룞 ?ㅻ뜑/留ㅽ븨 + ?ъ슜???꾩엫 + ?먮떒 洹쇨굅 ?щ챸 ?몄텧

[?뚯씠?꾨씪???ㅽ뻾] ??AuditPipeline(context=ctx).run(path)
  ???쒖? DataFrame ??feature/engine(?릀tx.settings, ctx.audit_rules) ???뚯깮蹂??19媛?  ??validation (L1 援ъ“ + L2 ?뚭퀎 + L3 ?듦퀎)
  ??detection (L1~L4 32媛?猷?+ 蹂댁“ findings, ?릀tx.settings, ctx.chart_of_accounts)
  ??score_aggregator (媛以묓빀 + risk_level + L2-05)
  ??DuckDB ?곸옱 (ctx.db_path ??Engagement蹂?寃⑸━ DB)
  ??UX 2?④퀎: 猷?而⑦듃濡??⑤꼸 + ?ы깘吏

[遺꾩꽍]
  ??Streamlit 4??(EDA / Summary / Benford / Explorer)
  ???곕룄 鍮꾧탳 ??(ATTACH 援먯감 荑쇰━)
  ??UX 3?④퀎: EDA ?꾨줈?뚯씪留?+ ?꾩쿂由??щ챸??
[Phase 2: ML/DL ??濡쒖뺄 ?ㅽ뻾]
  ??preprocessing (pipeline_builder ??cv_selector)
  ??ML ?먯? (VAE+IF + Stacking) ??紐⑤뜽 ??? ctx.model_dir

[Phase 3: LLM ???곸슜 API (?섏씠釉뚮━??]
  ??濡쒖뺄: ?꾪뿕 ?ㅼ퐫?는룻넻怨?吏??異붿텧
  ??API: Text-to-SQL, NLP ?섎? 遺꾩꽍, ?몄궗?댄듃 ?앹꽦, Export
  ??鍮꾩떇蹂꾪솕 ?덉씠?? ?꾩옱 踰붿쐞 ?? ?꾩슂???몄? (CONSTRAINTS.md 李몄“)
```
> Historical note. Current DataSynth production baseline is `data/journal/primary/datasynth/` freeze `v126` as of 2026-05-02. This section originally referenced `v23` freeze (2026-04-22).
> `B04 DuplicatePayment`??`P2P + KZ` pair/negative-control 援ъ“濡??밴꺽?섏뿀怨? `v20.4`??諛깆뾽蹂?`datasynth_backup_v20_4_20260422`濡?蹂댁〈?쒕떎.
> Historical sub-note. This section originally referenced `v23` as of 2026-04-22; current production is `v126`.

