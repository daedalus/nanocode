"""Retry logic with exponential backoff for API calls."""

import asyncio
import logging
import time
from typing import Any, Callable, Optional, TypeVar
from functools import wraps

logger = logging.getLogger(__name__)


class RetryError(Exception):
    """Base exception for retry errors."""

    def __init__(self, message: str, last_error: Exception = None, attempt: int = 0):
        super().__init__(message)
        self.last_error = last_error
        self.attempt = attempt


class RateLimitError(RetryError):
    """Rate limit exceeded error."""

    def __init__(
        self,
        message: str,
        retry_after: float = None,
        last_error: Exception = None,
        attempt: int = 0,
    ):
        super().__init__(message, last_error, attempt)
        self.retry_after = retry_after


class ContextOverflowError(RetryError):
    """Context overflow error - should not retry."""

    pass


class ProviderOverloadedError(RetryError):
    """Provider is overloaded."""

    pass


class FreeUsageLimitError(RetryError):
    """Free usage limit exceeded."""

    def __init__(
        self,
        message: str = "Free usage exceeded, add credits",
        last_error: Exception = None,
        attempt: int = 0,
    ):
        super().__init__(message, last_error, attempt)


class RetryConfig:
    """Configuration for retry behavior."""

    def __init__(
        self,
        max_retries: int = 5,
        initial_delay: float = 2.0,
        backoff_factor: float = 2.0,
        max_delay: float = 60.0,
        retryable_errors: tuple = (RateLimitError, ProviderOverloadedError),
        non_retryable_errors: tuple = (ContextOverflowError,),
    ):
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self.backoff_factor = backoff_factor
        self.max_delay = max_delay
        self.retryable_errors = retryable_errors
        self.non_retryable_errors = non_retryable_errors

    @classmethod
    def default(cls) -> "RetryConfig":
        """Get default retry config."""
        return cls()

    @classmethod
    def no_retries(cls) -> "RetryConfig":
        """Get config with no retries."""
        return cls(max_retries=0)


class RetryState:
    """State for tracking retry attempts."""

    def __init__(self, config: RetryConfig = None):
        self.config = config or RetryConfig.default()
        self.attempt = 0
        self.total_delay = 0.0
        self.errors: list[Exception] = []

    def reset(self):
        """Reset state for new retry sequence."""
        self.attempt = 0
        self.total_delay = 0.0
        self.errors.clear()

    def increment(self, error: Exception):
        """Increment attempt and record error."""
        self.attempt += 1
        self.errors.append(error)

    def can_retry(self) -> bool:
        """Check if more retries are allowed."""
        return self.attempt < self.config.max_retries

    def get_delay(self, error: Exception = None) -> float:
        """Calculate delay for next retry with exponential backoff."""
        delay = self.config.initial_delay * (self.config.backoff_factor ** (self.attempt - 1))

        if isinstance(error, RateLimitError) and error.retry_after:
            delay = min(error.retry_after, self.config.max_delay)

        delay = min(delay, self.config.max_delay)

        self.total_delay += delay
        return delay


async def sleep_with_abort(ms: float, abort_signal: asyncio.Event = None):
    """Sleep with abort support."""
    try:
        if abort_signal:
            await asyncio.wait_for(asyncio.sleep(ms / 1000), timeout=ms / 1000)
        else:
            await asyncio.sleep(ms / 1000)
    except asyncio.TimeoutError:
        pass


def calculate_retry_delay(
    attempt: int,
    error: Exception = None,
    initial_delay: float = 2.0,
    backoff_factor: float = 2.0,
    max_delay: float = 30.0,
    response_headers: dict = None,
) -> float:
    """Calculate retry delay from error and attempt number."""
    delay = initial_delay * (backoff_factor ** (attempt - 1))

    if response_headers:
        retry_after_ms = response_headers.get("retry-after-ms")
        if retry_after_ms:
            try:
                return min(float(retry_after_ms), max_delay)
            except ValueError:
                pass

        retry_after = response_headers.get("retry-after")
        if retry_after:
            try:
                seconds = float(retry_after)
                return min(seconds * 1000, max_delay)
            except ValueError:
                pass

            try:
                http_date_delay = (
                    time.mktime(time.strptime(retry_after, "%a, %d %b %Y %H:%M:%S GMT"))
                    - time.time()
                ) * 1000
                if http_date_delay > 0:
                    return min(http_date_delay, max_delay)
            except (ValueError, OSError):
                pass

    return min(delay, max_delay)


def is_retryable_error(error: Exception) -> Optional[str]:
    """Check if an error is retryable and return reason if not."""
    if isinstance(error, ContextOverflowError):
        return None

    error_msg = str(error).lower()

    if "rate_limit" in error_msg or "too many requests" in error_msg or "rate limit" in error_msg:
        return "Rate Limited"

    if "overloaded" in error_msg:
        return "Provider is overloaded"

    if "exhausted" in error_msg or "unavailable" in error_msg:
        return "Provider is overloaded"

    if isinstance(error, FreeUsageLimitError):
        return None  # Retry free usage errors too, user might add credits

    if "free_usage" in error_msg or "free limit" in error_msg:
        return None  # Retry free usage errors too

    return None

    if isinstance(error, FreeUsageLimitError):
        return str(error)

    if isinstance(error, RateLimitError):
        return str(error)

    if isinstance(error, ProviderOverloadedError):
        return str(error)

    error_msg = str(error).lower()

    if "rate_limit" in error_msg or "too many requests" in error_msg:
        return "Rate Limited"

    if "overloaded" in error_msg:
        return "Provider is overloaded"

    if "exhausted" in error_msg or "unavailable" in error_msg:
        return "Provider is overloaded"

    if "free_usage" in error_msg or "free limit" in error_msg:
        return "Free usage exceeded"

    return None


async def retry_with_backoff(
    func: Callable,
    config: RetryConfig = None,
    abort_signal: asyncio.Event = None,
    on_retry: Callable[[Exception, int], None] = None,
) -> Any:
    """Retry a function with exponential backoff."""
    config = config or RetryConfig.default()
    state = RetryState(config)

    while True:
        try:
            return await func()
        except Exception as e:
            retry_reason = is_retryable_error(e)

            if retry_reason is None:
                raise

            if not state.can_retry():
                raise RetryError(
                    f"Max retries ({config.max_retries}) exceeded: {retry_reason}",
                    last_error=e,
                    attempt=state.attempt,
                )

            delay = state.get_delay(e)

            logger.debug(
                f"Retrying (attempt {state.attempt + 1}/{config.max_retries}) due to: {retry_reason}"
            )

            if on_retry:
                on_retry(e, state.attempt + 1)

            state.increment(e)

            await sleep_with_abort(delay * 1000, abort_signal)


T = TypeVar("T")


def with_retry(config: RetryConfig = None):
    """Decorator for adding retry logic to async functions."""

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            async def call():
                return await func(*args, **kwargs)

            return await retry_with_backoff(call, config)

        return wrapper

    return decorator


def parse_error_type(error: Exception) -> tuple[type, dict]:
    """Parse error to determine type and details."""
    error_str = str(error)
    error_lower = error_str.lower()

    if "rate_limit" in error_lower or "too many requests" in error_lower:
        return RateLimitError, {"message": error_str}

    if "overloaded" in error_lower:
        return ProviderOverloadedError, {"message": error_str}

    if "context" in error_lower and ("overflow" in error_lower or "limit" in error_lower):
        return ContextOverflowError, {"message": error_str}

    if "free" in error_lower and ("limit" in error_lower or "exceeded" in error_lower):
        return FreeUsageLimitError, {"message": error_str}

    return RetryError, {"message": error_str}


def create_error_from_response(response_data: dict) -> Exception:
    """Create appropriate error from API response data."""
    if not isinstance(response_data, dict):
        return RetryError(str(response_data))

    message = response_data.get("message", "")
    error_type = response_data.get("type", "")
    error_code = response_data.get("code", "")

    if error_type == "error":
        if "rate_limit" in str(error_code).lower():
            return RateLimitError(message)
        if "too_many_requests" in str(error_code).lower():
            return RateLimitError(message)
        if "overloaded" in message.lower():
            return ProviderOverloadedError(message)
        if "free" in message.lower() and "limit" in message.lower():
            return FreeUsageLimitError(message)

    if "exhausted" in str(error_code).lower() or "unavailable" in str(error_code).lower():
        return ProviderOverloadedError(message)

    return RetryError(message)
