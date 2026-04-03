from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
import warnings


CANONICAL_RUNTIME_ENTRYPOINT = "app.py -> highlight_manager.app.bot.main"


class LegacyRuntimeRegistry:
    def __init__(self) -> None:
        self._lock = Lock()
        self._imports: dict[str, str] = {}

    def register(self, package_name: str) -> None:
        with self._lock:
            if package_name in self._imports:
                return
            self._imports[package_name] = datetime.now(timezone.utc).isoformat()
        warnings.warn(
            (
                f"{package_name} is part of the legacy Highlight Manger runtime tree. "
                f"Use {CANONICAL_RUNTIME_ENTRYPOINT} with highlight_manager.app / db / modules / tasks / ui instead."
            ),
            DeprecationWarning,
            stacklevel=2,
        )

    def snapshot(self) -> dict[str, str]:
        with self._lock:
            return dict(self._imports)

    def clear(self) -> None:
        with self._lock:
            self._imports.clear()


_REGISTRY = LegacyRuntimeRegistry()


def register_legacy_import(package_name: str) -> None:
    _REGISTRY.register(package_name)


def get_legacy_runtime_summary() -> dict[str, object]:
    imports = _REGISTRY.snapshot()
    return {
        "canonical_entrypoint": CANONICAL_RUNTIME_ENTRYPOINT,
        "legacy_import_count": len(imports),
        "legacy_packages": sorted(imports.keys()),
        "first_seen_by_package": imports,
    }


def clear_legacy_runtime_registry() -> None:
    _REGISTRY.clear()
