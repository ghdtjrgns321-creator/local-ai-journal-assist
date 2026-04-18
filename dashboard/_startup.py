"""Streamlit 앱 시작 시 이전 프로세스 자동 종료 + 종료 시 커넥션 정리.

Why: DuckDB는 단일 writer만 허용하므로, 이전 Streamlit 프로세스가
     남아 있으면 파일 잠금 에러가 발생한다.
     현재 프로세스의 부모(streamlit parent)를 제외한 모든 streamlit python
     프로세스를 종료하여 잠금 충돌을 방지한다.
"""

from __future__ import annotations

import atexit
import logging
import os
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_PID_FILE = Path("data/.streamlit.pid")


def kill_previous_instance() -> None:
    """이전 Streamlit 프로세스를 모두 종료한다.

    1단계: PID 파일에 기록된 이전 프로세스 kill
    2단계: 8501/8502 포트를 잡고 있는 python 프로세스 kill (PID 파일 누락 대비)
    3단계: WAL 잠금 파일 정리
    """
    my_pid = os.getpid()
    # Streamlit은 자식 python 프로세스를 fork하므로 부모 PID도 보호
    my_ppid = os.getppid()

    killed_pids: set[int] = set()

    # 1단계: PID 파일 기반 kill
    if _PID_FILE.exists():
        try:
            old_pid = int(_PID_FILE.read_text().strip())
            if old_pid not in (my_pid, my_ppid):
                _kill_pid(old_pid)
                killed_pids.add(old_pid)
        except (ValueError, OSError):
            pass

    # 2단계: 포트 기반 kill (Windows netstat)
    if sys.platform == "win32":
        for port in (8501, 8502):
            for pid in _find_pids_on_port(port):
                if pid not in (my_pid, my_ppid) and pid not in killed_pids:
                    _kill_pid(pid)
                    killed_pids.add(pid)

    # 3단계: WAL 잠금 파일 정리
    for wal in Path("data/companies").rglob("*.duckdb.wal"):
        try:
            wal.unlink()
            logger.info("WAL 파일 삭제: %s", wal)
        except OSError:
            pass

    _write_pid()


def _kill_pid(pid: int) -> None:
    """PID를 강제 종료한다."""
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                capture_output=True, timeout=5,
            )
        else:
            import signal
            os.kill(pid, signal.SIGTERM)
        logger.info("이전 프로세스 종료: PID %d", pid)
    except (ProcessLookupError, PermissionError, subprocess.TimeoutExpired):
        pass
    except Exception:
        logger.warning("PID %d 종료 실패", pid, exc_info=True)


def _find_pids_on_port(port: int) -> list[int]:
    """Windows netstat로 특정 포트를 LISTENING 중인 PID를 찾는다."""
    try:
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True, text=True, timeout=5,
        )
        pids: list[int] = []
        for line in result.stdout.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                parts = line.split()
                if parts:
                    try:
                        pids.append(int(parts[-1]))
                    except ValueError:
                        pass
        return pids
    except Exception:
        return []


def _write_pid() -> None:
    """현재 프로세스 PID를 파일에 기록."""
    _PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PID_FILE.write_text(str(os.getpid()))


def register_cleanup(conn_mgr) -> None:  # noqa: ANN001
    """프로세스 종료 시 커넥션 정리 + PID 파일 삭제."""

    def _cleanup() -> None:
        conn_mgr.close_all()
        try:
            _PID_FILE.unlink(missing_ok=True)
        except OSError:
            pass

    atexit.register(_cleanup)
