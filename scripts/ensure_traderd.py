#!/home/gabernardi/trader/.venv/bin/python
"""Ensure traderd is running with the secure OpenClaw environment loaded."""

from __future__ import annotations

import fcntl
import os
import subprocess
import sys
from pathlib import Path

from openclaw_env import LOG_DIR, PROJECT_ROOT, STATE_DIR, TRADERD_CONFIG, TRADERD_LOG, TRADERD_PYTHON, merged_env


LOCK_FILE = STATE_DIR / "traderd_supervisor.lock"
PID_FILE = STATE_DIR / "traderd.pid"
TRADERD_SCRIPT = PROJECT_ROOT / "traderd.py"
PROCESS_PATTERN = "traderd.py --config config/service.yaml"


def _matching_traderd_pids() -> list[int]:
    """Return live traderd process ids if the service is already running."""

    result = subprocess.run(
        ["pgrep", "-af", PROCESS_PATTERN],
        capture_output=True,
        text=True,
        check=False,
    )
    pids: list[int] = []
    for line in result.stdout.splitlines():
        if "pgrep" in line:
            continue
        fields = line.strip().split(maxsplit=1)
        if not fields:
            continue
        try:
            pids.append(int(fields[0]))
        except ValueError:
            continue
    return pids


def main() -> int:
    """Start traderd if it is not already running."""

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    with LOCK_FILE.open("w", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0

        existing = _matching_traderd_pids()
        if existing:
            PID_FILE.write_text(f"{existing[0]}\n", encoding="utf-8")
            return 0

        env = merged_env()
        env["PYTHONUNBUFFERED"] = "1"
        log_handle = TRADERD_LOG.open("a", encoding="utf-8")
        process = subprocess.Popen(
            [str(TRADERD_PYTHON), str(TRADERD_SCRIPT), "--config", "config/service.yaml"],
            cwd=str(PROJECT_ROOT),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        PID_FILE.write_text(f"{process.pid}\n", encoding="utf-8")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
