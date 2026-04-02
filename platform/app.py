"""Process entrypoint for the traderd service."""
from __future__ import annotations
import sys as _sys
import importlib

for _mod in list(_sys.modules):
    _f = getattr(_sys.modules.get(_mod), "__file__", "") or ""
    if _mod in ("operator","enum","re") and "trader" in _f:
        del _sys.modules[_mod]

import argparse, signal, threading
from pathlib import Path
from platform.bootstrap import bootstrap_service

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/service.yaml")
    args = parser.parse_args()
    shutdown_event = threading.Event()
    context = bootstrap_service(Path(args.config))
    def _sig(_n, _f): shutdown_event.set()
    for s in ("SIGINT","SIGTERM"):
        if hasattr(signal, s): signal.signal(getattr(signal, s), _sig)
    try: shutdown_event.wait()
    finally: context.shutdown()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
