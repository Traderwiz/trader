"""Process entrypoint for the Phase 1 control-plane service."""

from __future__ import annotations

import argparse
import signal
import threading
from pathlib import Path

from platform.bootstrap import bootstrap_service


def main() -> int:
    """Start the service and block until SIGINT or SIGTERM."""

    parser = argparse.ArgumentParser(description="Phase 1 control-plane service")
    parser.add_argument(
        "--config",
        default="config/service.yaml",
        help="Path to the service configuration file.",
    )
    args = parser.parse_args()

    shutdown_event = threading.Event()
    context = bootstrap_service(Path(args.config))

    def _handle_signal(_signum: int, _frame: object) -> None:
        shutdown_event.set()

    for signum_name in ("SIGINT", "SIGTERM"):
        if hasattr(signal, signum_name):
            signal.signal(getattr(signal, signum_name), _handle_signal)

    try:
        shutdown_event.wait()
    finally:
        context.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
