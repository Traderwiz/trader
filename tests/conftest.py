"""Pytest bootstrap for the local ``platform`` package.

The repository follows the architecture spec's ``platform/`` layout, which
collides with Python's standard-library ``platform`` module during fresh test
collection. Load the repo package first so imports like ``platform.backtest``
resolve to the project package while still preserving stdlib platform helpers
re-exported by ``platform/__init__.py``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = REPO_ROOT / "platform"


def _bootstrap_repo_platform_package() -> None:
    existing = sys.modules.get("platform")
    if existing is not None and getattr(existing, "__path__", None):
        return

    spec = importlib.util.spec_from_file_location(
        "platform",
        PACKAGE_ROOT / "__init__.py",
        submodule_search_locations=[str(PACKAGE_ROOT)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load repo platform package from {PACKAGE_ROOT}")

    module = importlib.util.module_from_spec(spec)
    sys.modules["platform"] = module
    spec.loader.exec_module(module)


_bootstrap_repo_platform_package()

