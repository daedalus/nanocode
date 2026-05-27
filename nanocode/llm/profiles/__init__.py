"""Provider profile registry.

Provider profiles live in ``providers/`` as self-registering modules.
Each module calls ``register_provider(profile)`` at import time.

Discovery is lazy: the first call to ``get_provider_profile()`` or
``list_providers()`` scans the ``providers/`` directory.

For backward compatibility, users can also drop a single-file profile
at ``profiles/providers/<name>.py`` (not a subpackage) and it will be
discovered via ``pkgutil.iter_modules``.

Usage::

    from nanocode.llm.profiles import get_provider_profile
    profile = get_provider_profile("opencode-zen")
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
import sys
from pathlib import Path

from nanocode.llm.profiles.base import OMIT_TEMPERATURE, ProviderProfile  # noqa: TC001

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, ProviderProfile] = {}
_ALIASES: dict[str, str] = {}
_discovered = False

_PROVIDERS_PKG_DIR = Path(__file__).resolve().parent / "providers"


def register_provider(profile: ProviderProfile) -> None:
    _REGISTRY[profile.name] = profile
    for alias in profile.aliases:
        _ALIASES[alias] = profile.name


def get_provider_profile(name: str) -> ProviderProfile | None:
    if not _discovered:
        _discover_providers()
    canonical = _ALIASES.get(name, name)
    return _REGISTRY.get(canonical)


def list_providers() -> list[ProviderProfile]:
    if not _discovered:
        _discover_providers()
    seen: set[int] = set()
    result: list[ProviderProfile] = []
    for profile in _REGISTRY.values():
        pid = id(profile)
        if pid not in seen:
            seen.add(pid)
            result.append(profile)
    return result


def _import_profile_module(module_name: str, source: str = "bundled") -> None:
    if module_name in sys.modules:
        return
    try:
        importlib.import_module(module_name)
    except Exception as exc:
        logger.debug("Failed to import profile module %s: %s", module_name, exc)


def _discover_providers() -> None:
    global _discovered
    if _discovered:
        return
    _discovered = True

    # 1. Subpackage providers (providers/<name>/__init__.py)
    if _PROVIDERS_PKG_DIR.is_dir():
        for child in sorted(_PROVIDERS_PKG_DIR.iterdir()):
            if not child.is_dir() or child.name.startswith(("_", ".")):
                continue
            init_file = child / "__init__.py"
            if not init_file.exists():
                continue
            module_name = f"nanocode.llm.profiles.providers.{child.name}"
            _import_profile_module(module_name, "subpackage")

    # 2. Single-file legacy profiles (providers/<name>.py)
    try:
        import nanocode.llm.profiles.providers as _pkg
        for _importer, modname, _ispkg in pkgutil.iter_modules(_pkg.__path__):
            if modname.startswith("_") or modname == "base":
                continue
            module_name = f"nanocode.llm.profiles.providers.{modname}"
            _import_profile_module(module_name, "single-file")
    except Exception:
        pass
