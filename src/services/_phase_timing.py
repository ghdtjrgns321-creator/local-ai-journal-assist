"""Phase timing helpers — 시작 시각 + tag + elapsed 일관 포맷.

Why: phase1/phase2 단계별 병목 분석용. 모든 timing log를 동일 포맷으로 통일하면
- 같은 stage의 start_ts만 grep 해 호출 순서/대기 시간 파악 가능
- elapsed 와 (다음 stage start_ts - 현재 stage start_ts) 차이로 idle/IO 추정 가능
- 한 줄에 시작시각 + tag + elapsed 가 모두 보여 외부 분석 도구로 파싱 쉬움

포맷: ``[TIMING] HH:MM:SS.fff <tag>: <elapsed>s``
"""

from __future__ import annotations

import logging
import time
from datetime import datetime

_logger = logging.getLogger(__name__)


def now_str() -> str:
    """HH:MM:SS.fff (millisecond) 시작시각 prefix."""
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def log_timing(tag: str, elapsed: float, *, start_ts: str | None = None) -> None:
    """단일 timing 레코드 출력.

    start_ts 가 None이면 호출 시점을 사용. elapsed 단위는 초.
    """
    if start_ts is None:
        start_ts = now_str()
    _logger.warning("[TIMING] %s %s: %.2fs", start_ts, tag, elapsed)


class TimingBlock:
    """``with TimingBlock(tag):`` 블록의 시작/종료 시각 + elapsed 자동 로그.

    Why: try/finally + perf_counter() 반복을 줄이고, exception 경로에서도
    elapsed가 누락되지 않도록 보장한다.
    """

    def __init__(self, tag: str) -> None:
        self.tag = tag
        self.start_ts = ""
        self._start = 0.0
        self.elapsed = 0.0

    def __enter__(self) -> TimingBlock:
        self.start_ts = now_str()
        self._start = time.perf_counter()
        return self

    def __exit__(self, *_exc) -> None:
        self.elapsed = time.perf_counter() - self._start
        log_timing(self.tag, self.elapsed, start_ts=self.start_ts)
