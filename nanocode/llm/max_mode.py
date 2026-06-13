"""Max Mode - Parallel best-of-N with judge selection.

Ported from MiMo-Code's session/max-mode.ts.
Runs N parallel completions and uses a judge model to select the best response.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class MaxModeConfig:
    """Configuration for Max Mode."""

    enabled: bool = False
    n: int = 3  # Number of parallel completions
    judge_model: str | None = None  # Model to use for judging (None = use default)
    timeout: float = 60.0  # Timeout per completion in seconds


@dataclass
class CompletionResult:
    """Result from a single completion."""

    content: str
    model: str
    tokens: int = 0
    latency: float = 0.0
    error: str | None = None


@dataclass
class MaxModeResult:
    """Result from Max Mode selection."""

    best: CompletionResult
    all_results: list[CompletionResult] = field(default_factory=list)
    judge_reasoning: str = ""


JUDGE_PROMPT = """You are a judge evaluating multiple AI responses to the same prompt.

Select the BEST response based on these criteria:
1. Correctness - Is the answer accurate?
2. Completeness - Does it fully address the question?
3. Clarity - Is it well-organized and easy to understand?
4. Code quality - If code is included, is it clean and idiomatic?

Here are the responses to evaluate:

{responses}

Respond with ONLY a JSON object in this exact format:
{{"best_index": <0-based index>, "reasoning": "<brief explanation>"}}

Do not include any other text."""


async def run_single_completion(
    llm: Any,
    messages: list[dict[str, Any]],
    temperature: float = 0.7,
    timeout: float = 60.0,
) -> CompletionResult:
    """Run a single LLM completion.

    Args:
        llm: LLM instance
        messages: Message list
        temperature: Sampling temperature
        timeout: Timeout in seconds

    Returns:
        CompletionResult
    """
    import time
    from nanocode.llm import Message

    start = time.monotonic()

    try:
        llm_messages = [
            Message(role=m["role"], content=m.get("content", ""))
            for m in messages
        ]

        response = await asyncio.wait_for(
            llm.chat(llm_messages, temperature=temperature),
            timeout=timeout,
        )

        latency = time.monotonic() - start
        content = response.content or ""

        return CompletionResult(
            content=content,
            model=getattr(llm, "model", "unknown"),
            tokens=len(content.split()),
            latency=latency,
        )

    except asyncio.TimeoutError:
        return CompletionResult(
            content="",
            model=getattr(llm, "model", "unknown"),
            error="timeout",
            latency=time.monotonic() - start,
        )
    except Exception as e:
        return CompletionResult(
            content="",
            model=getattr(llm, "model", "unknown"),
            error=str(e),
            latency=time.monotonic() - start,
        )


async def judge_responses(
    judge_llm: Any,
    responses: list[CompletionResult],
) -> tuple[int, str]:
    """Use a judge model to select the best response.

    Args:
        judge_llm: LLM instance for judging
        responses: List of CompletionResult to judge

    Returns:
        Tuple of (best_index, reasoning)
    """
    from nanocode.llm import Message

    valid_responses = [r for r in responses if r.content and not r.error]
    if not valid_responses:
        return 0, "No valid responses to judge"
    if len(valid_responses) == 1:
        return 0, "Only one valid response"

    formatted = []
    for i, r in enumerate(valid_responses):
        formatted.append(f"Response {i}:\n{r.content}")

    prompt = JUDGE_PROMPT.format(responses="\n\n".join(formatted))

    try:
        response = await judge_llm.chat([Message("user", prompt)])
        result_text = response.content.strip()

        import json

        if result_text.startswith("```"):
            result_text = result_text.split("\n", 1)[1]
            if result_text.endswith("```"):
                result_text = result_text[:-3]

        result = json.loads(result_text)
        best_index = result.get("best_index", 0)
        reasoning = result.get("reasoning", "")

        best_index = max(0, min(best_index, len(valid_responses) - 1))
        return best_index, reasoning

    except Exception as e:
        logger.warning(f"Judge failed: {e}, selecting first response")
        return 0, f"Judge failed: {e}"


async def max_mode_completion(
    llm: Any,
    messages: list[dict[str, Any]],
    config: MaxModeConfig | None = None,
    judge_llm: Any | None = None,
) -> MaxModeResult:
    """Run Max Mode - N parallel completions with judge selection.

    Args:
        llm: LLM instance for completions
        messages: Message list
        config: Max Mode configuration
        judge_llm: Optional separate judge LLM (defaults to same llm)

    Returns:
        MaxModeResult with best response and all results
    """
    if config is None:
        config = MaxModeConfig()

    if not config.enabled:
        result = await run_single_completion(llm, messages)
        return MaxModeResult(best=result, all_results=[result])

    n = max(1, config.n)
    judge = judge_llm or llm

    tasks = [
        run_single_completion(llm, messages, temperature=0.7 + i * 0.1, timeout=config.timeout)
        for i in range(n)
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    completion_results = []
    for r in results:
        if isinstance(r, Exception):
            completion_results.append(CompletionResult(content="", model="unknown", error=str(r)))
        else:
            completion_results.append(r)

    valid = [r for r in completion_results if r.content and not r.error]
    if not valid:
        return MaxModeResult(
            best=completion_results[0] if completion_results else CompletionResult(content="", model="unknown"),
            all_results=completion_results,
            judge_reasoning="All completions failed",
        )

    best_index, reasoning = await judge_responses(judge, valid)

    best = valid[best_index] if best_index < len(valid) else valid[0]

    return MaxModeResult(
        best=best,
        all_results=completion_results,
        judge_reasoning=reasoning,
    )
