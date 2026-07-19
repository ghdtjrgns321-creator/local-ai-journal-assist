"""Sanitizer — 스펙 §6.1 표 sanitizer 5 케이스 + 결정성/적요 회귀."""

from __future__ import annotations

import math

import pytest

from src.llm.review_narrator.sanitizer import Sanitizer


@pytest.fixture()
def rn_sanitizer() -> Sanitizer:
    """결정성 보장을 위한 고정 salt sanitizer."""
    return Sanitizer(salt="test-salt-v1")


# ── (1) 거래처명 마스킹 ──


class TestMaskName:
    def test_corporate_name_masked(self, rn_sanitizer):
        out = rn_sanitizer.mask_name("주식회사 ABC상사")
        assert out.startswith("MASKED_NAME_")
        assert "ABC" not in out
        assert "주식회사" not in out

    def test_employee_name_masked(self, rn_sanitizer):
        out = rn_sanitizer.mask_name("홍길동")
        assert out.startswith("MASKED_NAME_")
        assert "홍길동" not in out

    def test_deterministic(self, rn_sanitizer):
        """동일 입력 + 동일 salt → 동일 출력."""
        assert rn_sanitizer.mask_name("홍길동") == rn_sanitizer.mask_name("홍길동")

    def test_different_inputs_different_hashes(self, rn_sanitizer):
        assert rn_sanitizer.mask_name("홍길동") != rn_sanitizer.mask_name("김철수")

    def test_salt_changes_output(self):
        a = Sanitizer(salt="A").mask_name("홍길동")
        b = Sanitizer(salt="B").mask_name("홍길동")
        assert a != b


# ── (2) 임직원명 마스킹 — mask_name이 동일 메서드를 사용하므로 위와 통합되어 있다 ──
# 별도 라운드: 결측 안전성만 추가 검증


# ── (3) 사업자번호 마스킹 ──


class TestMaskBusinessId:
    def test_standard_format_masked(self, rn_sanitizer):
        out = rn_sanitizer.mask_business_id("123-45-67890")
        assert out.startswith("BIZ_")
        assert "123" not in out
        assert "67890" not in out

    def test_deterministic(self, rn_sanitizer):
        assert rn_sanitizer.mask_business_id("123-45-67890") == rn_sanitizer.mask_business_id(
            "123-45-67890"
        )


class TestMaskAccount:
    def test_account_masked(self, rn_sanitizer):
        out = rn_sanitizer.mask_account("110-456-7890123")
        assert out.startswith("ACCT_")
        assert "110" not in out


# ── (4) 금액 범위화 ──


class TestBucketAmount:
    @pytest.mark.parametrize(
        "amount, expected_bucket",
        [
            (500_000, "100만 미만"),
            (1_000_000, "100만~1천만"),
            (9_999_999, "100만~1천만"),
            (10_000_000, "1천만~1억"),
            (99_999_999, "1천만~1억"),
            (100_000_000, "1억~10억"),
            (5_200_000_000, "10억~100억"),  # 52억
            (50_000_000_000, "100억~1천억"),  # 500억
            (200_000_000_000, "1천억 이상"),  # 2000억
        ],
    )
    def test_boundary_buckets(self, rn_sanitizer, amount, expected_bucket):
        assert rn_sanitizer.bucket_amount(amount) == expected_bucket

    def test_negative_amount_uses_absolute(self, rn_sanitizer):
        """음수 금액(차변/대변 분개)은 절댓값으로 범위 산정."""
        assert rn_sanitizer.bucket_amount(-5_200_000_000) == "10억~100억"

    def test_zero_returns_lowest_bucket(self, rn_sanitizer):
        assert rn_sanitizer.bucket_amount(0) == "100만 미만"


# ── (5) PII 결측 안전 처리 ──


class TestBlankSafety:
    @pytest.mark.parametrize("value", [None, "", "   ", math.nan])
    def test_mask_name_blank_returns_empty(self, rn_sanitizer, value):
        assert rn_sanitizer.mask_name(value) == ""

    @pytest.mark.parametrize("value", [None, "", math.nan])
    def test_mask_account_blank_returns_empty(self, rn_sanitizer, value):
        assert rn_sanitizer.mask_account(value) == ""

    @pytest.mark.parametrize("value", [None, "", math.nan])
    def test_mask_business_id_blank_returns_empty(self, rn_sanitizer, value):
        assert rn_sanitizer.mask_business_id(value) == ""

    def test_bucket_amount_none_returns_misang(self, rn_sanitizer):
        assert rn_sanitizer.bucket_amount(None) == "미상"

    def test_bucket_amount_non_numeric_returns_misang(self, rn_sanitizer):
        assert rn_sanitizer.bucket_amount("abc") == "미상"

    def test_bucket_amount_nan_returns_misang(self, rn_sanitizer):
        assert rn_sanitizer.bucket_amount(math.nan) == "미상"


# ── 적요 마스킹 회귀 ──


class TestMaskDescription:
    def test_business_id_in_text_masked(self, rn_sanitizer):
        text = "공급가액 청구 — 사업자번호 123-45-67890"
        out = rn_sanitizer.mask_description(text)
        assert "123-45-67890" not in out
        assert "BIZ_" in out
        assert "공급가액 청구" in out  # 일반 텍스트 보존

    def test_account_in_text_masked(self, rn_sanitizer):
        text = "송금 110-456-7890123 처리"
        out = rn_sanitizer.mask_description(text)
        assert "110-456-7890123" not in out
        assert "ACCT_" in out

    def test_blank_description_safe(self, rn_sanitizer):
        assert rn_sanitizer.mask_description(None) == ""
        assert rn_sanitizer.mask_description("") == ""

    def test_masked_tokens_not_rematched(self, rn_sanitizer):
        """BIZ_<hash> / ACCT_<hash> 토큰이 계좌 패턴에 재매칭되지 않아야 한다.

        regex `\\b\\d{2,4}` 의 단어경계가 `_<digit>` 전이를 차단함에 의존.
        패턴이 변경되면 이 회귀가 깨져 재마스킹 사고를 즉시 알린다.
        """
        # 사업자번호 마스킹 후 hash가 모두 숫자인 케이스를 강제로 만든다
        text = "BIZ_12345678 처리 + ACCT_87654321 송금"
        out = rn_sanitizer.mask_description(text)
        # 원본 마스킹 토큰이 그대로 보존 (이중 마스킹 없음)
        assert "BIZ_12345678" in out
        assert "ACCT_87654321" in out
        # 새로운 ACCT_ 마스킹이 추가되지 않음
        assert out.count("ACCT_") == 1


# ── 복합 처리 ──


class TestSanitizeJournalMeta:
    def test_full_meta_masked(self, rn_sanitizer):
        meta = {
            "amount": 5_200_000_000,
            "gl_account": "1100",
            "counterparty": "주식회사 ABC상사",
            "approver": "홍길동",
            "description": "정상 매출 — 사업자번호 123-45-67890",
        }
        out = rn_sanitizer.sanitize_journal_meta(meta)
        assert out["amount_bucket"] == "10억~100억"
        assert out["gl_account"] == "1100"
        assert out["counterparty_masked"].startswith("MASKED_NAME_")
        assert out["approver_masked"].startswith("MASKED_NAME_")
        assert "123-45-67890" not in out["description_masked"]
        assert "BIZ_" in out["description_masked"]

    def test_partial_meta_safe(self, rn_sanitizer):
        """일부 필드 누락 → 빈 문자열/미상 채움, 예외 발생 없음."""
        out = rn_sanitizer.sanitize_journal_meta({"amount": None})
        assert out["amount_bucket"] == "미상"
        assert out["gl_account"] == ""
        assert out["counterparty_masked"] == ""
        assert out["approver_masked"] == ""
        assert out["description_masked"] == ""
