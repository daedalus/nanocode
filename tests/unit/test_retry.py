"""Tests for retry logic."""

import pytest

from nanocode.retry import (
    RetryConfig,
    RetryState,
    RetryError,
    RateLimitError,
    ProviderOverloadedError,
    ContextOverflowError,
    FreeUsageLimitError,
    retry_with_backoff,
    is_retryable_error,
    calculate_retry_delay,
    parse_error_type,
    create_error_from_response,
)


class TestRetryConfig:
    """Test retry config."""

    def test_default_config(self):
        """Test default config values."""
        config = RetryConfig.default()

        assert config.max_retries == 5
        assert config.initial_delay == 2.0
        assert config.backoff_factor == 2.0
        assert config.max_delay == 60.0

    def test_no_retries_config(self):
        """Test config with no retries."""
        config = RetryConfig.no_retries()

        assert config.max_retries == 0


class TestRetryState:
    """Test retry state."""

    def test_initial_state(self):
        """Test initial state."""
        state = RetryState()

        assert state.attempt == 0
        assert state.total_delay == 0.0

    def test_increment(self):
        """Test incrementing attempt."""
        state = RetryState()

        state.increment(RateLimitError("rate limited"))

        assert state.attempt == 1
        assert len(state.errors) == 1

    def test_can_retry(self):
        """Test can_retry logic."""
        config = RetryConfig(max_retries=3)
        state = RetryState(config)

        assert state.can_retry() is True

        state.attempt = 3
        assert state.can_retry() is False

    def test_get_delay(self):
        """Test delay calculation."""
        config = RetryConfig(initial_delay=2.0, backoff_factor=2.0, max_delay=30.0)
        state = RetryState(config)

        state.attempt = 1
        delay = state.get_delay()

        assert delay == 2.0

        state.attempt = 2
        delay = state.get_delay()

        assert delay == 4.0


class TestCalculateRetryDelay:
    """Test retry delay calculation."""

    def test_exponential_backoff(self):
        """Test exponential backoff."""
        delay = calculate_retry_delay(1, initial_delay=2.0, backoff_factor=2.0)
        assert delay == 2.0

        delay = calculate_retry_delay(2, initial_delay=2.0, backoff_factor=2.0)
        assert delay == 4.0

        delay = calculate_retry_delay(3, initial_delay=2.0, backoff_factor=2.0)
        assert delay == 8.0

    def test_max_delay(self):
        """Test max delay cap."""
        delay = calculate_retry_delay(10, initial_delay=2.0, backoff_factor=2.0, max_delay=30.0)
        assert delay == 30.0

    def test_retry_after_header(self):
        """Test retry-after header parsing."""
        headers = {"retry-after": "5"}
        delay = calculate_retry_delay(
            1, response_headers=headers, initial_delay=2.0, max_delay=120.0
        )

        assert delay > 2.0

    def test_retry_after_ms_header(self):
        """Test retry-after-ms header parsing."""
        headers = {"retry-after-ms": "1000"}
        delay = calculate_retry_delay(
            1, response_headers=headers, initial_delay=2.0, max_delay=120.0
        )

        assert delay > 2.0


class TestIsRetryableError:
    """Test retryable error detection."""

    def test_context_overflow_not_retryable(self):
        """Test context overflow is not retryable."""
        error = ContextOverflowError("context overflow")
        result = is_retryable_error(error)

        assert result is None

    def test_rate_limit_retryable(self):
        """Test rate limit is retryable."""
        error = RateLimitError("rate limited")
        result = is_retryable_error(error)

        assert result is not None
        assert "rate" in result.lower()

    def test_provider_overloaded_retryable(self):
        """Test provider overloaded is retryable."""
        error = ProviderOverloadedError("provider overloaded")
        result = is_retryable_error(error)

        assert result is not None

    def test_free_limit_error(self):
        """Test free limit error is now retryable."""
        error = FreeUsageLimitError("free limit exceeded")
        result = is_retryable_error(error)

        assert result is None  # Now retryable

    def test_free_limit_error_message(self):
        """Test free limit error in message is retryable."""
        error = RetryError("free_usage exceeded")
        result = is_retryable_error(error)

        assert result is None  # Now retryable

    def test_rate_limit_error_message(self):
        """Test rate limit error in message is retryable."""
        error = RetryError("Rate limit exceeded. Please try again later.")
        result = is_retryable_error(error)

        assert result is not None  # Retryable

    def test_generic_error_not_retryable(self):
        """Test generic errors are not retryable."""
        error = ValueError("some error")
        result = is_retryable_error(error)

        assert result is None


class TestParseErrorType:
    """Test error type parsing."""

    def test_parse_rate_limit(self):
        """Test parsing rate limit error."""
        error = ValueError("rate_limit exceeded")
        error_type, _ = parse_error_type(error)

        assert error_type == RateLimitError

    def test_parse_overloaded(self):
        """Test parsing overloaded error."""
        error = ValueError("provider overloaded")
        error_type, _ = parse_error_type(error)

        assert error_type == ProviderOverloadedError


class TestCreateErrorFromResponse:
    """Test creating errors from API responses."""

    def test_rate_limit_response(self):
        """Test creating rate limit error from response."""
        response = {"error": {"type": "rate_limit_error", "message": "Rate limited"}}
        error = create_error_from_response(response)

        assert error is not None

    def test_overloaded_response(self):
        """Test creating overloaded error from response."""
        response = {"error": {"type": "error", "message": "Service overloaded"}}
        error = create_error_from_response(response)

        assert error is not None

    def test_invalid_response(self):
        """Test handling invalid response."""
        error = create_error_from_response({"message": "test"})

        assert isinstance(error, RetryError)


class TestRetryWithBackoff:
    """Test retry with backoff."""

    @pytest.mark.asyncio
    async def test_successful_call(self):
        """Test successful call without retry."""
        call_count = 0

        async def func():
            nonlocal call_count
            call_count += 1
            return "success"

        result = await retry_with_backoff(func, RetryConfig(max_retries=3))

        assert result == "success"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retry_on_error(self):
        """Test retry on error."""
        call_count = 0

        async def func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RateLimitError("rate limited")
            return "success"

        result = await retry_with_backoff(func, RetryConfig(max_retries=3, initial_delay=0.01))

        assert result == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_max_retries_exceeded(self):
        """Test max retries exceeded."""
        call_count = 0

        async def func():
            nonlocal call_count
            call_count += 1
            raise RateLimitError("rate limited")

        with pytest.raises(RetryError):
            await retry_with_backoff(func, RetryConfig(max_retries=2, initial_delay=0.01))

        assert call_count == 3

    @pytest.mark.asyncio
    async def test_non_retryable_error(self):
        """Test non-retryable error raises immediately."""
        call_count = 0

        async def func():
            nonlocal call_count
            call_count += 1
            raise ContextOverflowError("context overflow")

        with pytest.raises(ContextOverflowError):
            await retry_with_backoff(func, RetryConfig(max_retries=3))

        assert call_count == 1

    @pytest.mark.asyncio
    async def test_on_retry_callback(self):
        """Test on_retry callback is called."""
        call_count = 0
        retry_attempts = []

        async def func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RateLimitError("rate limited")
            return "success"

        def on_retry(error, attempt):
            retry_attempts.append(attempt)

        await retry_with_backoff(
            func,
            RetryConfig(max_retries=3, initial_delay=0.01),
            on_retry=on_retry,
        )

        assert retry_attempts == [1, 2]
