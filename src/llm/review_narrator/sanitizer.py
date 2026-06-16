"""Phase 3 v2 Review Narrator — PII Sanitizer.

LLM(상용 API) 전송 전에 PII 식별자를 비식별 처리한다. CONSTRAINTS.md §데이터
비식별화 표의 4계층 중 본 프로젝트 범위는 다음 3가지로 한정한다.

- 고유명사 마스킹: 거래처명·임직원명·적요 내 이름 → `MASKED_NAME_<hash8>`
- 식별자 해싱: 계좌번호 / 사업자번호 → `ACCT_<hash8>` / `BIZ_<hash8>` (단방향 SHA-256)
- 금액 범위화: 실 금액(KRW) → 한국 회계 일반 범위 라벨 ("1억~10억" 등)

설계:
- 해시는 salt + SHA-256 8자 prefix. salt를 명시적 인자로 받아 테스트 결정성 확보.
- None / "" / NaN 모든 결측 입력은 빈 문자열 반환 (회귀 안전).
- 적요 내 패턴(이름·계좌·사업자번호)은 정규식 기반 단순 마스킹. 본격 NER는 비범위.

단일 출처: docs/spec/CONSTRAINTS.md §데이터 비식별화 + docs/archive/abandoned/PHASE3_REVIEW_NARRATOR_SPEC.md.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass

# Why: 한국 사업자번호 표준 형식 (10자리, 하이픈 위치 고정)
_BIZ_ID_PATTERN = re.compile(r"\d{3}-\d{2}-\d{5}")
# Why: 계좌번호는 자릿수 변동(은행별) → 8자리 이상 연속 숫자 + 선택적 하이픈.
#      `\b` 단어경계가 `BIZ_<hash>` / `ACCT_<hash>` 마스킹 결과 재매칭을 차단한다
#      (밑줄·문자는 word char, 단어경계가 생기지 않음). 패턴 변경 시 회귀 테스트
#      `TestMaskDescription::test_masked_tokens_not_rematched`에서 즉시 감지.
_ACCOUNT_PATTERN = re.compile(r"\b\d{2,4}-?\d{2,6}-?\d{2,8}\b")


@dataclass(frozen=True)
class AmountBucket:
    """금액 범위 1개의 (하한 inclusive, 라벨)."""

    threshold_won: float
    label: str


# Why: 한국 중견 제조업 감사 실무에서 흔히 쓰이는 7단계 분류.
#      재무중요성(performance materiality) 구간과 거의 일치.
_AMOUNT_BUCKETS: tuple[AmountBucket, ...] = (
    AmountBucket(0, "100만 미만"),
    AmountBucket(1_000_000, "100만~1천만"),
    AmountBucket(10_000_000, "1천만~1억"),
    AmountBucket(100_000_000, "1억~10억"),
    AmountBucket(1_000_000_000, "10억~100억"),
    AmountBucket(10_000_000_000, "100억~1천억"),
    AmountBucket(100_000_000_000, "1천억 이상"),
)


def _hash8(raw: str, salt: str) -> str:
    """SHA-256 hex 앞 8자 — 결정론적·역추적 불가."""
    digest = hashlib.sha256(f"{salt}|{raw}".encode()).hexdigest()
    return digest[:8]


def _is_blank(value: object) -> bool:
    """None / 빈 문자열 / NaN 결측 판정."""
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


class Sanitizer:
    """결정론적 PII 마스킹기.

    동일 입력 + 동일 salt → 동일 마스킹 출력. 테스트와 운영에서 salt를 다르게 두면
    동일 원본도 다른 해시가 되므로, 운영에서는 환경변수 기반 salt를 권장한다.
    """

    def __init__(self, *, salt: str = "review-narrator-v1") -> None:
        self._salt = salt

    # ── 식별자 마스킹 ──

    def mask_name(self, name: object) -> str:
        """거래처명·임직원명 — 결측은 빈 문자열, 그 외는 MASKED_NAME_<hash8>."""
        if _is_blank(name):
            return ""
        return f"MASKED_NAME_{_hash8(str(name), self._salt)}"

    def mask_account(self, account: object) -> str:
        """계좌번호 — 결측은 빈 문자열, 그 외는 ACCT_<hash8>."""
        if _is_blank(account):
            return ""
        return f"ACCT_{_hash8(str(account), self._salt)}"

    def mask_business_id(self, business_id: object) -> str:
        """사업자번호 — 결측은 빈 문자열, 그 외는 BIZ_<hash8>."""
        if _is_blank(business_id):
            return ""
        return f"BIZ_{_hash8(str(business_id), self._salt)}"

    # ── 금액 범위화 ──

    def bucket_amount(self, amount: object) -> str:
        """금액 → 범위 라벨. 결측은 "미상", 음수는 절댓값으로 처리."""
        if _is_blank(amount):
            return "미상"
        try:
            value = abs(float(amount))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return "미상"
        chosen = _AMOUNT_BUCKETS[0].label
        for bucket in _AMOUNT_BUCKETS:
            if value >= bucket.threshold_won:
                chosen = bucket.label
        return chosen

    # ── 적요 마스킹 ──

    def mask_description(self, text: object) -> str:
        """적요 내 사업자번호·계좌번호 패턴만 단순 마스킹. 일반 한국어는 보존.

        NER 기반 인명 추출은 비범위 — 운영 투입 시 보완.
        """
        if _is_blank(text):
            return ""
        masked = str(text)
        masked = _BIZ_ID_PATTERN.sub(lambda m: self.mask_business_id(m.group(0)), masked)
        masked = _ACCOUNT_PATTERN.sub(lambda m: self.mask_account(m.group(0)), masked)
        return masked

    # ── 복합 처리 ──

    def sanitize_journal_meta(self, meta: dict) -> dict:
        """전표 메타 dict 1건 통째로 비식별화.

        스펙 §입력 계약 `journal_meta`: 금액·계정·거래처·승인자·적요 요약.
        amount → 범위, counterparty/approver → 이름 마스킹, description → 패턴 마스킹.
        gl_account는 회계 코드라 비식별 대상 아님 (보존).
        """
        return {
            "amount_bucket": self.bucket_amount(meta.get("amount")),
            "gl_account": meta.get("gl_account") or "",
            "counterparty_masked": self.mask_name(meta.get("counterparty")),
            "approver_masked": self.mask_name(meta.get("approver")),
            "description_masked": self.mask_description(meta.get("description")),
        }
