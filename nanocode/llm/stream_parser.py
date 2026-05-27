"""Streaming tool call parser that handles SSE-delimited JSON chunks.

This implements the same logic as the Vercel AI SDK for parsing tool calls
from streaming LLM responses.
"""

from dataclasses import dataclass
from typing import AsyncIterator

from nanocode.tools import ToolCall


@dataclass
class ToolCallChunk:
    """Accumulated tool call during streaming."""

    id: str
    name: str
    arguments: str = ""
    has_finished: bool = False


@dataclass
class StreamChunk:
    """Represents a parsed chunk from the stream."""

    text: str | None = None
    tool_call_start: tuple[str, str] | None = None  # (id, name)
    tool_call_delta: tuple[str, str] | None = None  # (id, delta)
    tool_call_end: str | None = None  # tool call id
    tool_call_complete: tuple[str, str, str] | None = None  # (id, name, arguments)
    finish_reason: str | None = None
    usage: dict | None = None


def is_complete_json(s: str) -> bool:
    """Check if a string is valid, complete JSON (object or array)."""
    s = s.strip()
    if not s:
        return False
    if s in ("{", "[", "]", "}"):
        return False
    try:
        import json

        json.loads(s)
        return True
    except json.JSONDecodeError:
        return False


def _tool_call_new(tc_delta: dict, index: int, tool_calls: dict):
    """Handle a new tool call delta. Yields StreamChunks."""
    tc_id = tc_delta.get("id")
    tc_name = tc_delta.get("function", {}).get("name", "")
    if not tc_id or not tc_name:
        return []
    tool_calls[index] = ToolCall(id=tc_id, name=tc_name, arguments={})
    chunks = [StreamChunk(tool_call_start=(tc_id, tc_name))]
    args = tc_delta.get("function", {}).get("arguments", "")
    if args:
        tool_calls[index].arguments = args
        chunks.append(StreamChunk(tool_call_delta=(tc_id, args)))
        if is_complete_json(args):
            tool_calls[index].has_finished = True
            chunks.append(StreamChunk(tool_call_end=tc_id))
            chunks.append(StreamChunk(tool_call_complete=(tc_id, tc_name, args)))
    return chunks


def _tool_call_existing(tc_delta: dict, tool_calls: dict, index: int):
    """Accumulate arguments for an existing tool call. Yields StreamChunks."""
    tc = tool_calls[index]
    if tc.has_finished:
        return []
    args_delta = tc_delta.get("function", {}).get("arguments", "")
    if not args_delta:
        return []
    tc.arguments += args_delta
    chunks = [StreamChunk(tool_call_delta=(tc.id, args_delta))]
    if is_complete_json(tc.arguments):
        tc.has_finished = True
        chunks.append(StreamChunk(tool_call_end=tc.id))
        chunks.append(StreamChunk(tool_call_complete=(tc.id, tc.name, tc.arguments)))
    return chunks


def _process_sse_chunk(
    chunk: dict, tool_calls: dict[int, ToolCall]
):
    """Process a single SSE chunk, updating tool_calls and yielding StreamChunks."""
    finish_reason = None
    usage = None
    if "usage" in chunk:
        usage = chunk["usage"]
    choice = chunk.get("choices", [{}])[0]
    if not choice:
        return finish_reason, usage, []
    if "finish_reason" in choice:
        finish_reason = choice["finish_reason"]
    delta = choice.get("delta", {})
    sub_chunks: list[StreamChunk] = []
    if "content" in delta:
        sub_chunks.append(StreamChunk(text=delta["content"]))
    for tc_delta in delta.get("tool_calls", []):
        index = tc_delta.get("index", 0)
        if index not in tool_calls:
            sub_chunks.extend(_tool_call_new(tc_delta, index, tool_calls))
        else:
            sub_chunks.extend(_tool_call_existing(tc_delta, tool_calls, index))
    return finish_reason, usage, sub_chunks


def _emit_final_stream_chunks(
    tool_calls: dict[int, ToolCall], finish_reason: str | None, usage: dict | None
) -> list[StreamChunk]:
    """Emit final chunks for unfinished tool calls, finish reason, and usage."""
    chunks: list[StreamChunk] = []
    for index, tc in sorted(tool_calls.items()):
        if not tc.has_finished:
            chunks.append(StreamChunk(tool_call_end=tc.id))
            chunks.append(StreamChunk(tool_call_complete=(tc.id, tc.name, tc.arguments)))
    if finish_reason:
        chunks.append(StreamChunk(finish_reason=finish_reason))
    if usage:
        chunks.append(StreamChunk(usage=usage))
    return chunks


async def parse_sse_stream(
    response: "httpx.AsyncResponse",
) -> AsyncIterator[StreamChunk]:
    """Parse Server-Sent Events stream with tool call support."""
    import json

    tool_calls: dict[int, ToolCall] = {}
    finish_reason = None
    usage = None

    async for line in response.aiter_lines():
        if not line.startswith("data: "):
            continue
        data_str = line[6:]
        if data_str == "[DONE]":
            break
        try:
            chunk = json.loads(data_str)
        except json.JSONDecodeError:
            continue

        fr, us, sub_chunks = _process_sse_chunk(chunk, tool_calls)
        if fr is not None:
            finish_reason = fr
        if us is not None:
            usage = us
        for c in sub_chunks:
            yield c

    for c in _emit_final_stream_chunks(tool_calls, finish_reason, usage):
        yield c


async def parse_stream_events(
    response: "httpx.AsyncResponse",
) -> AsyncIterator[dict]:
    """Parse streaming response into structured events.

    Returns events of types:
    - {"type": "text", "content": str}
    - {"type": "tool_start", "id": str, "name": str}
    - {"type": "tool_delta", "id": str, "delta": str}
    - {"type": "tool_end", "id": str}
    - {"type": "tool_call", "id": str, "name": str, "arguments": dict}
    - {"type": "finish", "reason": str, "usage": dict}
    """

    async for chunk in parse_sse_stream(response):
        if chunk.text is not None:
            yield {"type": "text", "content": chunk.text}

        if chunk.tool_call_start is not None:
            yield {
                "type": "tool_start",
                "id": chunk.tool_call_start[0],
                "name": chunk.tool_call_start[1],
            }

        if chunk.tool_call_delta is not None:
            yield {
                "type": "tool_delta",
                "id": chunk.tool_call_delta[0],
                "delta": chunk.tool_call_delta[1],
            }

        if chunk.tool_call_end is not None:
            yield {"type": "tool_end", "id": chunk.tool_call_end}

        if chunk.tool_call_complete is not None:
            import json as json_mod

            try:
                args = json_mod.loads(chunk.tool_call_complete[2])
            except json_mod.JSONDecodeError:
                args = {}
            yield {
                "type": "tool_call",
                "id": chunk.tool_call_complete[0],
                "name": chunk.tool_call_complete[1],
                "arguments": args,
            }

        if chunk.finish_reason is not None:
            yield {"type": "finish", "reason": chunk.finish_reason}

        if chunk.usage is not None:
            yield {"type": "usage", "usage": chunk.usage}
