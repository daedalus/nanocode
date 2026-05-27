"""Cross-session rate limit guard.

Writes rate limit state to a shared file on disk so all sessions
(CLI, gateway, cron, auxiliary) can check whether a provider is
currently rate-limited before making requests.

Prevents retry amplification: each 429 from a provider can trigger
multiple retry attempts per call, and every one counts against the
rate limit.  By recording the state on first 429 and checking before
subsequent attempts, we eliminate the amplification effect.
"""

import json
import logging
import os
import tempfile
import time
from collections.abc import Mapping

logger = logging.getLogger(__name__)

_STATE_DIR = "rate_limits"


def _nanocode_home() -> str:
    return os.path.join(os.path.expanduser("~"), ".nanocode")


def _state_path(provider: str) -> str:
    sanitized = provider.replace("/", "_").replace(" ", "_")
    return os.path.join(_nanocode_home(), _STATE_DIR, f"{sanitized}.json")


def _parse_reset_seconds(headers: Mapping[str, str] | None) -> float | None:
    if not headers:
        return None

    lowered = {k.lower(): v for k, v in headers.items()}

    for key in (
        "x-ratelimit-reset-requests-1h",
        "x-ratelimit-reset-requests",
        "retry-after",
    ):
        raw = lowered.get(key)
        if raw is not None:
            try:
                val = float(raw)
                if val > 0:
                    return val
            except (TypeError, ValueError):
                pass

    return None


def record_rate_limit(
    provider: str,
    *,
    headers: Mapping[str, str] | None = None,
    default_cooldown: float = 300.0,
) -> None:
    now = time.time()
    reset_at: float | None = None

    header_seconds = _parse_reset_seconds(headers)
    if header_seconds is not None:
        reset_at = now + header_seconds

    if reset_at is None:
        reset_at = now + default_cooldown

    path = _state_path(provider)
    try:
        state_dir = os.path.dirname(path)
        os.makedirs(state_dir, exist_ok=True)

        state = {
            "reset_at": reset_at,
            "recorded_at": now,
            "reset_seconds": reset_at - now,
            "provider": provider,
        }

        fd, tmp_path = tempfile.mkstemp(dir=state_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(state, f)
            os.replace(tmp_path, path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        logger.info(
            "Rate limit recorded for %s: resets in %.0fs (at %.0f)",
            provider, reset_at - now, reset_at,
        )
    except Exception as exc:
        logger.debug("Failed to write rate limit state for %s: %s", provider, exc)


def check_rate_limit(provider: str) -> float | None:
    path = _state_path(provider)
    try:
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
        reset_at = float(state.get("reset_at", 0))
        remaining = reset_at - time.time()
        if remaining > 0:
            return remaining
        try:
            os.unlink(path)
        except OSError:
            pass
        return None
    except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError):
        return None


def clear_rate_limit(provider: str) -> None:
    try:
        os.unlink(_state_path(provider))
    except FileNotFoundError:
        pass
    except OSError as exc:
        logger.debug("Failed to clear rate limit state for %s: %s", provider, exc)


def format_remaining(seconds: float) -> str:
    s = max(0, int(seconds))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        m, sec = divmod(s, 60)
        return f"{m}m {sec}s" if sec else f"{m}m"
    h, remainder = divmod(s, 3600)
    m = remainder // 60
    return f"{h}h {m}m" if m else f"{h}h"
