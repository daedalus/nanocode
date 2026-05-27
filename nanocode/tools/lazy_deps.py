"""Lazy dependency installer for opt-in nanocode backends.

Many nanocode features (Anthropic SDK, Bedrock, web search, TTS, messaging
platforms) require Python packages that not every user needs. The historical
approach was to bundle them all under ``pyproject.toml`` extras and install
them eagerly at setup time. That has two problems:

1. **Fragility.** When one extra's transitive dependency becomes unavailable
   on PyPI, the *entire* extras resolve fails.
2. **Bloat.** A user who only uses one provider pulls hundreds of packages
   they will never import.

The lazy-install pattern fixes both. Backends call :func:`ensure` at the
top of their first-import path. If deps are missing, ``ensure`` checks the
``security.allow_lazy_installs`` config flag and runs a venv-scoped pip
install. If disabled, ``ensure`` raises :class:`FeatureUnavailable`.

Security model:
* **Venv-scoped only.** Installs target ``sys.executable`` in the active venv.
* **PyPI by package name only.** No ``--index-url``, ``git+https://``, or files.
* **Allowlist.** Only specs in :data:`LAZY_DEPS` can be installed.
* **Opt-out.** ``security.allow_lazy_installs: false`` in config.
* **Offline detection.** Surfaces actual pip stderr on failure.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


LAZY_DEPS: dict[str, tuple[str, ...]] = {
    "provider.anthropic": ("anthropic>=0.80.0",),
    "provider.bedrock": ("boto3>=1.35.0",),
    "provider.ollama": ("ollama>=0.4.0",),
    "search.exa": ("exa-py>=2.0.0",),
    "search.firecrawl": ("firecrawl-py>=4.0.0",),
    "tts.edge": ("edge-tts>=7.0.0",),
    "tts.elevenlabs": ("elevenlabs>=1.0.0",),
    "stt.faster_whisper": ("faster-whisper>=1.0.0", "sounddevice>=0.5.0"),
    "image.fal": ("fal-client>=0.10.0",),
    "platform.telegram": ("python-telegram-bot[webhooks]>=22.0",),
    "platform.discord": ("discord.py[voice]>=2.7.0",),
    "platform.slack": ("slack-bolt>=1.27.0", "slack-sdk>=3.40.0"),
    "tool.acp": ("agent-client-protocol>=0.9.0",),
    "tool.dashboard": ("fastapi>=0.130.0", "uvicorn[standard]>=0.40.0"),
}

_SAFE_SPEC = re.compile(
    r"^[A-Za-z0-9_][A-Za-z0-9_.\-]*"
    r"(?:\[[A-Za-z0-9_,\-]+\])?"
    r"(?:[<>=!~]=?[A-Za-z0-9_.\-+,*<>=!~]+)?"
    r"$"
)


class FeatureUnavailable(RuntimeError):
    """A lazily-installable feature is missing and cannot be made available."""

    def __init__(self, feature: str, missing: tuple[str, ...], reason: str):
        self.feature = feature
        self.missing = missing
        self.reason = reason
        super().__init__(self._format())

    def _format(self) -> str:
        spec_list = " ".join(repr(s) for s in self.missing)
        return (
            f"Feature {self.feature!r} unavailable: {self.reason}. "
            f"To enable manually: pip install {spec_list}"
        )


@dataclass(frozen=True)
class _InstallResult:
    success: bool
    stdout: str
    stderr: str


def _allow_lazy_installs() -> bool:
    if os.environ.get("NANOCODE_DISABLE_LAZY_INSTALLS") == "1":
        return False
    try:
        import nanocode.config as _nc_config
        cfg = _nc_config.get_config()
    except Exception:
        return True
    sec = cfg.get("security") or {}
    val = sec.get("allow_lazy_installs", True)
    return bool(val)


def _spec_is_safe(spec: str) -> bool:
    if not spec or len(spec) > 200:
        return False
    if any(ch in spec for ch in (";", "|", "&", "`", "$", "\n", "\r", "\t", "\\")):
        return False
    if spec.startswith(("-", "/", ".")) or "://" in spec or "@" in spec:
        return False
    return bool(_SAFE_SPEC.match(spec))


def _pkg_name_from_spec(spec: str) -> str:
    m = re.match(r"^([A-Za-z0-9_][A-Za-z0-9_.\-]*)", spec)
    return m.group(1) if m else spec


def _specifier_from_spec(spec: str) -> str:
    m = re.match(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]*(?:\[[A-Za-z0-9_,\-]+\])?", spec)
    if not m:
        return ""
    return spec[m.end():]


def _is_satisfied(spec: str) -> bool:
    pkg = _pkg_name_from_spec(spec)
    try:
        from importlib.metadata import PackageNotFoundError, version
    except ImportError:
        return False
    try:
        installed = version(pkg)
    except PackageNotFoundError:
        return False
    except Exception:
        return False

    spec_tail = _specifier_from_spec(spec)
    if not spec_tail:
        return True

    try:
        from packaging.specifiers import InvalidSpecifier, SpecifierSet
        from packaging.version import InvalidVersion, Version
    except ImportError:
        return True

    try:
        return Version(installed) in SpecifierSet(spec_tail)
    except (InvalidSpecifier, InvalidVersion, Exception):
        return True


def _is_present(spec: str) -> bool:
    pkg = _pkg_name_from_spec(spec)
    try:
        from importlib.metadata import PackageNotFoundError, version
    except ImportError:
        return False
    try:
        version(pkg)
        return True
    except PackageNotFoundError:
        return False
    except Exception:
        return False


def _venv_pip_install(specs: tuple[str, ...], *, timeout: int = 300) -> _InstallResult:
    if not specs:
        return _InstallResult(True, "", "")

    venv_root = Path(sys.executable).parent.parent
    uv_env = {**os.environ, "VIRTUAL_ENV": str(venv_root)}

    uv_bin = shutil.which("uv")
    if uv_bin:
        try:
            r = subprocess.run(
                [uv_bin, "pip", "install", *specs],
                capture_output=True, text=True, timeout=timeout, env=uv_env,
            )
            if r.returncode == 0:
                return _InstallResult(True, r.stdout or "", r.stderr or "")
            logger.debug("uv pip install failed: %s", r.stderr)
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            logger.debug("uv invocation failed: %s", e)

    pip_cmd = [sys.executable, "-m", "pip"]
    try:
        probe = subprocess.run(
            pip_cmd + ["--version"],
            capture_output=True, text=True, timeout=15,
        )
        if probe.returncode != 0:
            raise FileNotFoundError("pip not in venv")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        try:
            subprocess.run(
                [sys.executable, "-m", "ensurepip", "--upgrade", "--default-pip"],
                capture_output=True, text=True, timeout=120, check=True,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            return _InstallResult(False, "", f"pip not available and ensurepip failed: {e}")

    try:
        r = subprocess.run(
            pip_cmd + ["install", *specs],
            capture_output=True, text=True, timeout=timeout,
        )
        return _InstallResult(r.returncode == 0, r.stdout or "", r.stderr or "")
    except subprocess.TimeoutExpired as e:
        return _InstallResult(False, "", f"pip install timed out: {e}")
    except Exception as e:
        return _InstallResult(False, "", f"pip install failed: {e}")


def feature_specs(feature: str) -> tuple[str, ...]:
    if feature not in LAZY_DEPS:
        raise KeyError(f"Unknown lazy feature: {feature!r}")
    return LAZY_DEPS[feature]


def feature_missing(feature: str) -> tuple[str, ...]:
    return tuple(s for s in feature_specs(feature) if not _is_satisfied(s))


def ensure(feature: str, *, prompt: bool = True) -> None:
    if feature not in LAZY_DEPS:
        raise FeatureUnavailable(
            feature, (), f"feature {feature!r} not in LAZY_DEPS allowlist"
        )

    missing = feature_missing(feature)
    if not missing:
        return

    for spec in missing:
        if not _spec_is_safe(spec):
            raise FeatureUnavailable(
                feature, missing, f"refusing to install unsafe spec {spec!r}"
            )

    if not _allow_lazy_installs():
        raise FeatureUnavailable(
            feature, missing,
            "lazy installs disabled (security.allow_lazy_installs=false)"
        )

    if prompt and sys.stdin.isatty() and sys.stdout.isatty():
        spec_list = ", ".join(missing)
        try:
            answer = input(
                f"\nFeature {feature!r} requires: {spec_list}\n"
                f"Install into the active venv now? [Y/n] "
            ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"
        if answer and answer not in {"y", "yes"}:
            raise FeatureUnavailable(
                feature, missing, "user declined install at prompt"
            )

    logger.info("Lazy-installing %s for feature %r", " ".join(missing), feature)
    result = _venv_pip_install(missing)
    if not result.success:
        snippet = (result.stderr or result.stdout or "").strip()
        if snippet:
            snippet = snippet[-2000:]
        raise FeatureUnavailable(
            feature, missing,
            f"pip install failed: {snippet or 'no error output'}"
        )

    try:
        import importlib.metadata as _md
        if hasattr(_md, "_cache_clear"):
            _md._cache_clear()
    except Exception:
        pass

    still_missing = feature_missing(feature)
    if still_missing:
        raise FeatureUnavailable(
            feature, still_missing,
            "install reported success but packages still not importable "
            "(may require Python restart)"
        )

    logger.info("Lazy install complete for feature %r", feature)


def is_available(feature: str) -> bool:
    if feature not in LAZY_DEPS:
        return False
    return not feature_missing(feature)


def feature_install_command(feature: str) -> str | None:
    if feature not in LAZY_DEPS:
        return None
    specs = LAZY_DEPS[feature]
    return "pip install " + " ".join(repr(s) for s in specs)


def active_features() -> list[str]:
    active = []
    for feature, specs in LAZY_DEPS.items():
        if any(_is_present(s) for s in specs):
            active.append(feature)
    return active


def refresh_active_features(*, prompt: bool = False) -> dict[str, str]:
    results: dict[str, str] = {}
    for feature in active_features():
        missing = feature_missing(feature)
        if not missing:
            results[feature] = "current"
            continue
        try:
            ensure(feature, prompt=prompt)
            results[feature] = "refreshed"
        except FeatureUnavailable as e:
            if "lazy installs disabled" in str(e) or "declined" in str(e):
                results[feature] = f"skipped: {e.reason}"
            else:
                results[feature] = f"failed: {e.reason}"
        except Exception as e:
            results[feature] = f"failed: {e}"
    return results


def ensure_and_bind(
    feature: str,
    importer: Callable[[], dict[str, Any]],
    target_globals: dict,
    *,
    prompt: bool = False,
) -> bool:
    try:
        ensure(feature, prompt=prompt)
    except (FeatureUnavailable, Exception):
        return False

    try:
        bindings = importer()
    except ImportError:
        return False

    target_globals.update(bindings)
    return True
