# 엔진 전수 감사 — 기존 부정 주입 엔진이 올바른가

작성 2026-06-30. 방법: 병렬 서브에이전트 3갈래 + 결정적 주장 main 재검증(§9). 도구 주의: `tools/datasynth/`가 `.gitignore:68`에 있어 Grep(ripgrep) 검색 불가 → `grep -rn`/Read로 검증.

## 결론 한 줄

**기존 엔진은 이 벤치마크에 거의 부적합하다.** 우리가 기대한 기전 엔진은 dead code이고, 실제 가동 경로는 얕고(텍스트 1종 덮어쓰기) 상태 비인지이며 6대 패턴을 거의 못 만든다. 단 **배선·provenance·firewall은 재사용 가능**.

## 1. 흐름 배선 — 정상 (메인 체인 완결)

`orchestrator → injector.process_entries → inject_anomaly → strategies.apply_strategy → 배열 회수 → 스트림 직렬화 → journal_entries.csv`. 끊김 없음.
- 증거: `streaming_orchestrator.rs:706/709/722`, `injector.rs:1063/1132`.

## 2. schemes/ (embezzlement·revenue·kickback) — **dead code 확정**

기전 기반 multi-stage scheme 엔진은 production 경로 0건.
- 플래그 `multi_stage_schemes_enabled` true 세팅은 빌더 본체 `injector.rs:1695/1746`뿐, **그 빌더 호출처 0건**(grep -rn).
- `advance_schemes`/`maybe_start_scheme` 외부 호출은 injector 내부(:1567)와 `#[cfg(test)]`(scheme_advancer.rs:415~481)뿐, **orchestrator 호출 0건**.
- `SchemeAction → JournalEntry` 변환 코드 부재 → 켜도 CSV 미materialize.
- **함의**: 앞서 읽고 감탄한 `embezzlement.rs` 단계전개(testing→desperation) 로직은 데이터에 안 들어간다. 기전 기반 생성은 **사실상 미보유**.

## 3. 가동 부정 경로 — 얕음, 이원화

부정은 두 분리된 taxonomy로 주입되며 둘 다 얕다:
- **(가) AnomalyMutator(의미 불일치)**: `AnomalyMutationType` 11종 정의되나 **구현 3종**(DocumentTextMismatch·ProcessTextMismatch·AccountTextFamilyMismatch), 나머지 8종 `UnsupportedMutation`. 그 3종도 **전부 동일 동작 — 차변 line_text를 "direct labor payroll accrual"로 덮어쓰기**(injector.rs:138-200). 2종(WrongBusinessProcess·WrongAccountSubtype)은 시나리오 미연결 dead.
- **(나) strategies.rs(FraudType weighted)**: in-place 필드 덮어쓰기. 예 `DormantAccountStrategy`는 하드코딩 계정 `["199999","299999","399999","999999"]` 중 무작위로 `gl_account` 치환(strategies.rs:1330-1366).

## 4. 상태 인지 — **문제 (state-blind)**

가동 경로는 장부 상태(잔액·열린 AR/AP·문서체인)를 조회하지 않는다.
- anomaly 모듈에 `amount_open|is_cleared|outstanding|open_ar|account_balance` 참조 0건(서브에이전트 grep, datasynth subtree).
- 변이는 무작위 line을 하드코딩/분포값으로 덮어씀(strategies.rs:1366). 유일한 데이터 인지는 분포 Z-score(injector.rs:246/318)이지 상태 아님.
- **함의**: "없는 매출채권 갚기" 위험이 **현재 실재**. 우리 설계 ⑥D(상태의존)·⑦(3층 오라클)이 막으려던 결함이 기존 엔진에 그대로 있음.

## 5. 정합 검증기 SemanticValidator — **1층만, 2·3층 0**

`validate(entry, coa)` — 단일 전표 + 정적 COA만 입력(semantic_validator.rs:52). 11규칙(SEM001~011) 전부 한 전표 내부(텍스트·계정 sub_type·차대 role·거래처).
- 2층(참조 무결성) 0종 / 3층(잔액 상태) 0종.
- 단, **유용한 패턴 발견**: AnomalyMutator는 변이 후 SemanticValidator 위반이 없으면 에러(injector.rs:156-161) — 우리 설계 ⑦의 "spec이 선언한 위반만 깬다"가 1층 한정으로 이미 부분 구현됨.

## 6. firewall — **양호 (재사용 가능)**

라벨·mutation·surface_hints 9개 필드가 detector 입력으로 새지 않음. 3중 방어:
1. hidden 모드 라벨 drop(`ingest/datasynth_labels.py:146-152`) — 라벨 6종.
2. forbidden strip(`validation/schema_validator.py:42-55`, pipeline.py:1331) — mutation/hint 8종, feature/detection보다 먼저.
3. AST 회귀 가드(`tests/.../test_schema_validator.py:286-311`) — mutation 8종 detection 참조 0 단언.
- detection·feature 전수 grep read 0건.
- **비대칭 1건(부채)**: truth 라벨 4종(is_fraud 등)은 hidden-drop + 경험적 read0에만 의존, **AST 가드 없음**. visible 모드/신규 룰이면 회귀 위험(현재 무해).
- **미측정**: `is_fraud`↔`fraud_type` 행 단위 fill 정합은 데이터 미로드.

## 7. 종합 — 재사용 가능 / 신축 필요

| 구성요소                               | 상태       | 벤치마크 활용                          |
| -------------------------------------- | ---------- | -------------------------------------- |
| 주입 배선(process_entries→serialize)   | 정상       | **재사용**                             |
| provenance→header + 자가검증(위반필수) | 정상(1층)  | **재사용**(3층으로 확장)               |
| firewall(라벨 누수 차단)               | 양호       | **재사용**(truth 라벨 AST 가드만 추가) |
| schemes/ 기전 엔진                     | dead       | 폐기 또는 배선 신설                    |
| AnomalyMutator 변이 11종               | 3종/얕음   | **신축**(6대 패턴 기전)                |
| 상태 인지                              | 없음       | **신축**(⑥D 상태의존)                  |
| SemanticValidator 2·3층                | 없음       | **신축**(⑦ 참조·잔액 오라클)           |
| 6대 패턴 커버                          | 1~2개 부분 | **신축**                               |

## 8. 검증 경계(정직)

- 타 크레이트(banking 등)의 schemes 사용 미전수(generators 내부 `super::schemes` 노출이라 가능성 낮음, 미검증).
- 35+ strategies 전수 본문 미열람(대표 5~6개 + 모듈 grep 0건이 방증).
- 라벨 행 단위 fill 정합 데이터 미측정.
