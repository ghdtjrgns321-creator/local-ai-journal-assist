"""WU-30 RuleFeedbackEngine 단위 테스트 — DuckDB :memory: + mock ChatClient.

검증 범위:
1. 제안 생성 해피패스 (LLM JSON → RuleFeedbackReport 파싱)
2. 전역 중복 제안 필터링 (코드 레벨 이중 방어)
3. 회사별 오버라이드만 저장 + 전역 yaml 불변 + lru_cache 무효화
4. IntercompanyPair 중첩 JSON 왕복
5. 기존 회사 override 리스트 보존 (deep_merge replace 대응)
6. 감사 로그 append
7. LLM 비가용 시 예외 전파 (graceful degradation은 UI 레이어 책임)
"""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import duckdb
import pytest
import yaml

from src.company.models import CompanyProfile
from src.company.repository import CompanyRepository
from src.llm.models import (
    EvidenceSample,
    IntercompanyPair,
    RuleCategory,
    RuleFeedbackReport,
    RuleSuggestion,
)
from src.llm.rule_feedback import RuleFeedbackEngine

# ── Fixtures ────────────────────────────────────────────────────


@pytest.fixture()
def conn() -> duckdb.DuckDBPyConnection:
    """가공된 general_ledger — Manual/Adjustment/Custom 등 source 다양성 보장."""
    c = duckdb.connect(":memory:")
    c.execute(
        """
        CREATE TABLE general_ledger (
            document_id VARCHAR,
            gl_account VARCHAR,
            header_text VARCHAR,
            line_text VARCHAR,
            source VARCHAR,
            debit_amount DOUBLE,
            credit_amount DOUBLE
        )
        """
    )
    c.execute("CREATE SEQUENCE feedback_event_id_seq START 1")
    c.execute(
        """
        CREATE TABLE feedback_events (
            id BIGINT DEFAULT nextval('feedback_event_id_seq') PRIMARY KEY,
            company_id VARCHAR,
            engagement_id VARCHAR,
            batch_id VARCHAR,
            document_id VARCHAR,
            track_name VARCHAR,
            rule_code VARCHAR,
            event_type VARCHAR NOT NULL,
            decision VARCHAR NOT NULL,
            reason VARCHAR,
            payload_json JSON,
            created_by VARCHAR DEFAULT 'auditor',
            created_at TIMESTAMP DEFAULT current_timestamp
        )
        """
    )
    rows = [
        # Manual 전표 (기존 룰) + 신규 source 'CustomManual'
        ("D001", "5100", "Office Rent", None, "Manual", 1_000_000, 0),
        ("D002", "5100", "Office Rent", None, "Manual", 1_000_000, 0),
        ("D003", "5100", "Utility",    None, "CustomManual", 500_000, 0),
        ("D004", "5100", "Utility",    None, "CustomManual", 500_000, 0),
        ("D005", "5100", "Utility",    None, "CustomManual", 500_000, 0),
        # 가계정 후보 gl_account='9900' — suspense 키워드 비율 100%
        ("D006", "9900", "Temporary clearing", None, "Manual", 200_000, 0),
        ("D007", "9900", "Temporary clearing", None, "Manual", 200_000, 0),
        ("D008", "9900", "Temporary clearing", None, "Manual", 200_000, 0),
        # 매출 prefix '7' (새로움) — 기존 revenue_account_prefixes=['4']
        ("D009", "7100", "Service Revenue", None, "Automated", 0, 5_000_000),
        ("D010", "7100", "Service Revenue", None, "Automated", 0, 5_000_000),
        # IC 쌍: document D100 의 debit=1160 credit=2060
        ("D100", "1160", "Intercompany Settlement", None, "Automated", 3_000_000, 0),
        ("D100", "2060", "Intercompany Settlement", None, "Automated", 0, 3_000_000),
        ("D101", "1160", "IC settlement", None, "Automated", 1_000_000, 0),
        ("D101", "2060", "IC settlement", None, "Automated", 0, 1_000_000),
    ]
    c.executemany(
        "INSERT INTO general_ledger VALUES (?,?,?,?,?,?,?)", rows,
    )
    return c


@pytest.fixture()
def existing_rules() -> dict:
    """기존 전역 룰 시뮬레이션 (audit_rules.yaml 부분 미러)."""
    return {
        "patterns": {
            "manual_source_codes": ["Manual", "Adjustment"],
            "suspense_keywords": ["가수금"],
            "suspense_account_codes": ["1190", "2190"],
            "revenue_account_prefixes": ["4"],
            "intercompany": {
                "pairs": [{"receivable": "1150", "payable": "2050"}],
            },
        },
    }


@pytest.fixture()
def mock_report() -> RuleFeedbackReport:
    """LLM이 반환할 가짜 리포트 — 카테고리별 신규 1건씩 + 중복 1건."""
    return RuleFeedbackReport(
        suggestions=[
            RuleSuggestion(
                category=RuleCategory.MANUAL_SOURCE_CODES,
                proposed_value="CustomManual",
                rationale="3회 이상 반복되는 신규 수기 전표 소스",
                evidence_samples=[
                    EvidenceSample(document_id="D003", gl_account="5100",
                                   description="Utility", debit_amount=500_000),
                ],
                confidence="high",
            ),
            # 중복 제안 (Manual은 이미 기존에 있음) — 필터 대상
            RuleSuggestion(
                category=RuleCategory.MANUAL_SOURCE_CODES,
                proposed_value="Manual",
                rationale="duplicate",
                evidence_samples=[
                    EvidenceSample(document_id="D001", gl_account="5100",
                                   description="Office Rent"),
                ],
                confidence="low",
            ),
            RuleSuggestion(
                category=RuleCategory.SUSPENSE_ACCOUNT_CODES,
                proposed_value="9900",
                rationale="적요 100%가 Temporary/Clearing 계정",
                evidence_samples=[
                    EvidenceSample(document_id="D006", gl_account="9900",
                                   description="Temporary clearing"),
                ],
                confidence="high",
            ),
            RuleSuggestion(
                category=RuleCategory.REVENUE_ACCOUNT_PREFIXES,
                proposed_value="7",
                rationale="서비스 매출 계정 군집",
                evidence_samples=[
                    EvidenceSample(document_id="D009", gl_account="7100",
                                   description="Service Revenue",
                                   credit_amount=5_000_000),
                ],
                confidence="medium",
            ),
            RuleSuggestion(
                category=RuleCategory.INTERCOMPANY_IDENTIFIERS,
                proposed_value="",
                intercompany_pair=IntercompanyPair(receivable="1160", payable="2060"),
                rationale="IC Settlement 전표 2건 공출현",
                evidence_samples=[
                    EvidenceSample(document_id="D100", gl_account="1160",
                                   description="Intercompany Settlement"),
                ],
                confidence="high",
            ),
        ],
    )


@pytest.fixture()
def mock_client(mock_report: RuleFeedbackReport) -> MagicMock:
    client = MagicMock()
    client.chat.return_value = mock_report.model_dump_json()
    return client


@pytest.fixture()
def repo() -> CompanyRepository:
    """임시 회사 디렉토리 + 'TEST' 회사 프로파일 생성."""
    base_dir = Path("tmp_test_rule_feedback") / str(uuid.uuid4())
    base_dir.mkdir(parents=True, exist_ok=True)
    try:
        r = CompanyRepository(base_dir)
        r.create_company(CompanyProfile(
        company_id="test",
        display_name="Test Co",
        industry="Manufacturing",
        ))
        yield r
    finally:
        shutil.rmtree(base_dir, ignore_errors=True)


# ── 테스트 ──────────────────────────────────────────────────────


def test_propose_generates_valid_report(conn, existing_rules, mock_client):
    """해피패스: LLM 응답을 RuleFeedbackReport로 파싱 + 메타 주입."""
    engine = RuleFeedbackEngine(conn, existing_rules, client=mock_client)
    report = engine.propose()

    assert isinstance(report, RuleFeedbackReport)
    assert report.generated_at.endswith("Z")
    # 5개 카테고리 모두 샘플이 수집되었는지
    assert set(report.sample_summary.keys()) == {c.value for c in RuleCategory}
    assert mock_client.chat.called

    # sample_summary에 제안용 후보가 들어있어야 함
    assert report.sample_summary["manual_source_codes"] >= 1
    assert report.sample_summary["intercompany_identifiers"] >= 1


def test_duplicates_filtered_out(conn, existing_rules, mock_client):
    """기존 'Manual' 재제안은 _filter_duplicates에서 제거."""
    engine = RuleFeedbackEngine(conn, existing_rules, client=mock_client)
    report = engine.propose()

    manual_suggestions = [
        s for s in report.suggestions
        if s.category == RuleCategory.MANUAL_SOURCE_CODES
    ]
    values = [s.proposed_value for s in manual_suggestions]
    assert "Manual" not in values
    assert "CustomManual" in values  # 신규는 유지


def test_apply_writes_only_company_override(
    conn, existing_rules, mock_client, repo, monkeypatch,
):
    """전역 config/audit_rules.yaml은 불변, 회사 override만 기록됨 + cache_clear 호출."""
    # Why: MagicMock으로 get_audit_rules를 교체하면 cache_clear 속성이 자동 생성되어
    #      호출 여부를 spy할 수 있다.
    mock_get = MagicMock(return_value=existing_rules)
    monkeypatch.setattr("src.llm.rule_feedback.get_audit_rules", mock_get)

    engine = RuleFeedbackEngine(conn, existing_rules, client=mock_client)
    report = engine.propose()
    result = engine.apply(report.suggestions, "test", repo)

    # 1) 회사 override 파일 생성 확인 (해당 회사 디렉토리 하위)
    assert result.path.exists()
    assert result.path.name == "audit_rules.yaml"
    assert result.path.parent == repo.company_dir("test")

    # 2) applied/skipped 카운트 — 중복 1건(Manual)은 propose에서 이미 제거되므로 skipped=0
    assert result.applied == len(report.suggestions)
    assert result.skipped == 0

    # 3) 캐시 무효화 호출 확인
    assert mock_get.cache_clear.called

    # 4) 저장된 내용에 신규 값 포함
    with open(result.path, encoding="utf-8") as f:
        saved = yaml.safe_load(f)
    patterns = saved["patterns"]
    assert "CustomManual" in patterns["manual_source_codes"]
    assert "9900" in patterns["suspense_account_codes"]
    assert "7" in patterns["revenue_account_prefixes"]


def test_intercompany_pair_roundtrip(
    conn, existing_rules, mock_client, repo, monkeypatch,
):
    """IntercompanyPair → yaml {receivable, payable} dict 왕복."""
    monkeypatch.setattr(
        "src.llm.rule_feedback.get_audit_rules", lambda: existing_rules,
    )
    engine = RuleFeedbackEngine(conn, existing_rules, client=mock_client)
    report = engine.propose()
    result = engine.apply(report.suggestions, "test", repo)

    with open(result.path, encoding="utf-8") as f:
        saved = yaml.safe_load(f)
    pairs = saved["patterns"]["intercompany"]["pairs"]

    # 기존 1150/2050 + 신규 1160/2060
    pair_set = {(p["receivable"], p["payable"]) for p in pairs}
    assert ("1150", "2050") in pair_set
    assert ("1160", "2060") in pair_set


def test_apply_preserves_existing_company_override(
    conn, existing_rules, mock_client, repo, monkeypatch,
):
    """회사 override에 'LegacyManual'이 이미 있으면 새 제안 추가 후에도 보존."""
    # 기존 회사 override 파일 배치
    existing_company = {
        "patterns": {
            "manual_source_codes": ["Manual", "Adjustment", "LegacyManual"],
        },
    }
    repo.save_company_yaml("test", "audit_rules.yaml", existing_company)

    monkeypatch.setattr(
        "src.llm.rule_feedback.get_audit_rules", lambda: existing_rules,
    )
    engine = RuleFeedbackEngine(conn, existing_rules, client=mock_client)
    report = engine.propose()
    result = engine.apply(report.suggestions, "test", repo)

    with open(result.path, encoding="utf-8") as f:
        saved = yaml.safe_load(f)
    manual = saved["patterns"]["manual_source_codes"]

    assert "LegacyManual" in manual, "기존 회사 override 리스트가 덮어써지면 안 됨"
    assert "CustomManual" in manual  # 신규 추가
    assert manual.count("Manual") == 1  # 중복 없음


def test_apply_skips_global_duplicates(
    conn, existing_rules, repo, monkeypatch,
):
    """LLM이 전역에 이미 있는 값을 재제안해도 yaml에 중복 기록되지 않음."""
    dup_report = RuleFeedbackReport(suggestions=[
        RuleSuggestion(
            category=RuleCategory.MANUAL_SOURCE_CODES,
            proposed_value="Adjustment",  # 기존 전역에 이미 존재
            rationale="duplicate",
            evidence_samples=[EvidenceSample(
                document_id="D001", gl_account="5100", description="x")],
            confidence="low",
        ),
    ])
    client = MagicMock()
    client.chat.return_value = dup_report.model_dump_json()

    monkeypatch.setattr(
        "src.llm.rule_feedback.get_audit_rules", lambda: existing_rules,
    )
    engine = RuleFeedbackEngine(conn, existing_rules, client=client)
    report = engine.propose()
    # _filter_duplicates가 이미 제거함
    assert report.suggestions == []

    result = engine.apply(report.suggestions, "test", repo)
    # 빈 suggestions면 파일 쓰지 않고 경로만 반환, applied/skipped=0
    assert not result.path.exists()
    assert result.applied == 0
    assert result.skipped == 0


def test_log_file_append(conn, existing_rules, mock_client, repo, monkeypatch):
    """승인 이벤트가 rule_feedback_log.jsonl에 실제 applied 건수만큼 append된다."""
    monkeypatch.setattr(
        "src.llm.rule_feedback.get_audit_rules", lambda: existing_rules,
    )
    engine = RuleFeedbackEngine(conn, existing_rules, client=mock_client)
    report = engine.propose()
    result = engine.apply(report.suggestions, "test", repo, actor="alice")

    log_path = repo.company_dir("test") / "rule_feedback_log.jsonl"
    assert log_path.exists()
    lines = log_path.read_text(encoding="utf-8").strip().split("\n")
    # Why: 로그는 실제 yaml에 반영된 건(applied)만 기록 — skipped는 로그에 남기지 않음
    assert len(lines) == result.applied
    first = json.loads(lines[0])
    assert first["actor"] == "alice"
    assert first["action"] == "approved"
    events = conn.execute(
        "SELECT decision FROM feedback_events WHERE event_type = 'rule_feedback'"
    ).fetchall()
    assert len(events) == result.applied
    assert all(row[0] == "approved" for row in events)


def test_invalid_actor_rejected(conn, existing_rules, mock_client, repo, monkeypatch):
    """actor 포맷 불일치 시 apply/log_rejections 모두 ValueError."""
    monkeypatch.setattr(
        "src.llm.rule_feedback.get_audit_rules", lambda: existing_rules,
    )
    engine = RuleFeedbackEngine(conn, existing_rules, client=mock_client)
    report = engine.propose()

    # 줄바꿈 + 중괄호 = 감사로그 위변조 시도 패턴
    bad_actor = "alice\n{\"action\":\"forged\"}"
    with pytest.raises(ValueError, match="actor 포맷 불일치"):
        engine.apply(report.suggestions, "test", repo, actor=bad_actor)
    with pytest.raises(ValueError, match="actor 포맷 불일치"):
        RuleFeedbackEngine.log_rejections(
            report.suggestions, "test", repo, actor=bad_actor,
        )


def test_topk_out_of_range_rejected(conn, existing_rules, mock_client):
    """topk 범위 밖(음수/과대/비정수) → ValueError."""
    for bad in [0, -1, 1001, "10"]:
        with pytest.raises(ValueError, match="topk must be int"):
            RuleFeedbackEngine(conn, existing_rules, client=mock_client, topk=bad)


def test_log_rejections_without_engine(conn, existing_rules, repo):
    """log_rejections는 staticmethod — LLM client 불필요."""
    sugg = [RuleSuggestion(
        category=RuleCategory.MANUAL_SOURCE_CODES,
        proposed_value="CustomManual",
        rationale="rejected by auditor",
        evidence_samples=[EvidenceSample(
            document_id="D001", gl_account="5100", description="x")],
        confidence="high",
    )]
    # 엔진 인스턴스 없이 바로 호출 가능해야 함
    RuleFeedbackEngine.log_rejections(
        sugg, "test", repo, actor="bob", conn=conn, engagement_id="2026",
    )

    log_path = repo.company_dir("test") / "rule_feedback_log.jsonl"
    assert log_path.exists()
    record = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert record["action"] == "rejected"
    assert record["actor"] == "bob"
    events = conn.execute(
        "SELECT decision, engagement_id FROM feedback_events WHERE event_type = 'rule_feedback'"
    ).fetchall()
    assert events == [("rejected", "2026")]


def test_llm_unavailable_propagates(conn, existing_rules, monkeypatch):
    """get_chat_client가 RuntimeError를 내면 엔진 생성 시 예외 전파."""
    def raise_runtime(tier):
        raise RuntimeError("OpenAI unavailable")

    monkeypatch.setattr(
        "src.llm.rule_feedback.get_chat_client", raise_runtime,
    )
    with pytest.raises(RuntimeError, match="OpenAI unavailable"):
        RuleFeedbackEngine(conn, existing_rules)
