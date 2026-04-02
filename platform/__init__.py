"""Phase 1 control-plane package for the trading service.

This package intentionally matches the architecture spec's `platform/` path.
To avoid breaking tools that import the standard library `platform` module,
it re-exports the stdlib module's public API alongside the package namespace.
"""

from __future__ import annotations

import importlib.util
import sysconfig
from pathlib import Path


_STDLIB_PLATFORM_PATH = Path(sysconfig.get_path("stdlib")) / "platform.py"
_STDLIB_PLATFORM_SPEC = importlib.util.spec_from_file_location(
    "_stdlib_platform",
    _STDLIB_PLATFORM_PATH,
)
if _STDLIB_PLATFORM_SPEC is None or _STDLIB_PLATFORM_SPEC.loader is None:
    raise RuntimeError(f"Unable to load standard library platform module from {_STDLIB_PLATFORM_PATH}")
_STDLIB_PLATFORM_MODULE = importlib.util.module_from_spec(_STDLIB_PLATFORM_SPEC)
_STDLIB_PLATFORM_SPEC.loader.exec_module(_STDLIB_PLATFORM_MODULE)

for _name in dir(_STDLIB_PLATFORM_MODULE):
    if _name.startswith("__") and _name not in {"__all__", "__doc__"}:
        continue
    globals().setdefault(_name, getattr(_STDLIB_PLATFORM_MODULE, _name))
