#!/home/gabernardi/trader/.venv/bin/python
"""Cron-safe daily bar trigger wrapper with overlap protection."""

from __future__ import annotations

import fcntl
import subprocess
from pathlib import Path

from openclaw_env import LOG_DIR, PROJECT_ROOT, STATE_DIR, TRADERD_PYTHON


LOCK_FILE = STATE_DIR / "daily_bars.lock"
RUN_LOG = LOG_DIR / "daily_runner.log"
RUNNER = PROJECT_ROOT / "scripts" / "run_daily_bars.py"


def main() -> int:
    """Run one daily-bar delivery attempt if another is not already in flight."""

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    with LOCK_FILE.open("w", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0

        with RUN_LOG.open("a", encoding="utf-8") as log_handle:
            result = subprocess.run(
                [str(TRADERD_PYTHON), str(RUNNER), "--issued-by", "scheduler"],
                cwd=str(PROJECT_ROOT),
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                check=False,
            )
        return int(result.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
