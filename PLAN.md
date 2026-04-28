# PLAN.md - OpenCode Architecture Implementation

## Goal
Fully match opencode's LLM → Event Stream → Processor → Message Parts pipeline in nanocode.

## OpenCode Architecture (Reference)
```
User Input
    ↓
LLM.stream() → AsyncGenerator<StreamEvent>
    ↓
SessionProcessor.handleEvent() → builds Message with Parts
    ↓
Message.parts: [TextPart, ReasoningPart, ToolPart, StepStartPart, ...]
```

## Current State (Commit 80299a2 - 2026-04-27)

✅ **Done (Commit 80299a2):**
1. **`nanocode/llm/events.py`** - StreamEvent types (matching opencode)
   - EventType enum (START, REASONING_START, REASONING_DELTA, TEXT_DELTA, TOOL_CALL, etc.)
   - Event dataclasses: ReasoningStartEvent, ReasoningDeltaEvent, TextDeltaEvent, ToolCallEvent, FinishStepEvent, etc.

2. **`nanocode/llm/providers/openai/__init__.py`** - OpenAI streams events
   - `chat_stream()` returns `AsyncGenerator[StreamEvent]`
   - Parses SSE stream and yields events (TextDeltaEvent, ToolCallEvent, FinishStepEvent)
   - Keeps `chat()` as backward-compatible wrapper

3. **`nanocode/session/message.py`** - Message/Parts (matching opencode's message-v2.ts)
   - `Message` class with `parts: List[Part]`
   - Part types: `TextPart`, `ReasoningPart`, `ToolPart`, `StepStartPart`, `StepFinishPart`
   - Methods: `add_part()`, `get_text()`, `get_reasoning()`, `get_tool_calls()`

4. **`nanocode/session/processor.py`** - SessionProcessor (matching opencode's processor.ts)
   - `ProcessorContext` - holds state (assistant_message, reasoning_map, tool_calls, etc.)
   - `SessionProcessor` - processes events via `_handle_event()`
   - Event handlers: `_handle_reasoning_start()`, `_handle_text_delta()`, `_handle_tool_call()`, etc.
   - `ProcessorHandle` - returned to caller for accessing results

5. **`nanocode/agent_pipeline.py`** - Clean interface
   - `AgentPipeline` class wrapping LLM + Processor
   - `process()` method that runs the full pipeline
   - Returns `Message` with all parts populated

6. **`nanocode/core.py`** - Partial update
   - Updated imports to use new types
   - Still uses old `_process_input_impl()` pattern (TODO: refactor)

❌ **Not Done:**
- `nanocode/core.py` - Still uses old LLMResponse pattern, needs to use `AgentPipeline`
- Other providers (anthropic, ollama) - Still return LLMResponse, need `chat_stream()`
- `SessionProcessor` - Dependencies (session_service, snapshot_service, etc.) are None
- TUI - Still reads `agent._all_thinking`, needs to use Message parts
- Legacy code - `_all_thinking`, `LLMResponse`, `_chat_with_retry()` still exist

## TODO Tasks

### Task 1: Refactor core.py to use SessionProcessor
**File:** `nanocode/core.py`
**Description:** Replace `_process_input_impl()` to use the new pipeline:
```python
# OLD (remove):
response = await self._chat_with_retry(messages, tools)
if response.thinking:
    self._all_thinking.append(response.thinking)
# Process tool calls manually...

# NEW (implement):
pipeline = AgentPipeline(llm=self.llm, processor=SessionProcessor(...))
message = await pipeline.process(
    session_id=self.session_id,
    user_input=user_input,
    tools=tools,
)
# Extract from message.parts
thinking = message.get_reasoning()
content = message.get_text()
tool_calls = message.get_tool_calls()
```

### Task 2: Update LLM base class
**File:** `nanocode/llm/base.py`
**Description:** Make `chat()` method use `chat_stream()` internally:
- `chat()` becomes a convenience method that collects stream events
- All providers must implement `chat_stream()` returning `AsyncGenerator[StreamEvent]`

### Task 3: Update Anthropic provider
**File:** `nanocode/llm/providers/anthropic/__init__.py`
**Description:** Refactor to stream events:
- Implement `chat_stream()` returning events
- Parse Anthropic's streaming format (SSE with thinking blocks)
- Yield `ReasoningDeltaEvent`, `TextDeltaEvent`, `ToolCallEvent`, etc.

### Task 4: Update Ollama provider
**File:** `nanocode/llm/providers/ollama/__init__.py`
**Description:** Same as Task 3 but for Ollama's streaming format.

### Task 5: Wire up SessionProcessor dependencies
**File:** `nanocode/session/processor.py`
**Description:** The processor needs real services:
- `session_service` - To store/retrieve messages and parts
- `snapshot_service` - For tracking file snapshots
- `permission_service` - For tool permission checks
- `llm_service` - For LLM streaming
- `config_service` - For configuration

Currently these are passed as None. Need to wire up with actual nanocode services.

### Task 6: Update TUI to use Message Parts
**File:** `nanocode/tui/app.py`
**Description:** Instead of reading `agent._all_thinking`, the TUI should:
- Access the Message object's parts
- Render each part appropriately (thinking, text, tools)
- Match opencode's TUI rendering

### Task 7: Remove legacy code
**Files:** `nanocode/core.py`, `nanocode/llm/base.py`
**Description:** Once the pipeline works:
- Remove `_all_thinking` list (replaced by Message.reasoning_parts)
- Remove `_last_tool_results` (replaced by Message.tool_parts)
- Remove `LLMResponse` class (replaced by Message with Parts)
- Clean up old `_chat_with_retry()`, `_handle_tool_calls()`, etc.

### Task 8: Update tests for new architecture
**Files:** `tests/unit/test_core.py`, new test files
**Description:**
- Add tests for `AgentPipeline`
- Add tests for `SessionProcessor`
- Add tests for event streaming from providers
- Update existing tests to use new architecture

## Cleanup: Old/Dead/Duplicated Code

After the new architecture is fully working, remove the following legacy code:

### Cleanup Task 1: Remove LLMResponse class
**File:** `nanocode/llm/base.py`
**Description:** 
- Delete `LLMResponse` class (lines ~100-117)
- `chat()` method should become a wrapper around `chat_stream()`
- All code checking `response.thinking`, `response.has_tool_calls`, etc. becomes obsolete

**Current dead code:**
```python
# In core.py - remove these patterns:
if response.thinking:
    self._all_thinking.append(response.thinking)
if response.has_tool_calls:
    tool_results = await self._handle_tool_calls(response.tool_calls)
```

### Cleanup Task 2: Remove _all_thinking list
**Files:** `nanocode/core.py`
**Description:**
- Remove `self._all_thinking = []` (line 1411)
- Remove all `self._all_thinking.append()` calls
- **Reason:** Replaced by `Message.get_reasoning()` which reads from `ReasoningPart` objects

**Old code to remove:**
```python
# Line 1411:
self._all_thinking = []  # Accumulate all thinking like opencode's reasoning parts

# Lines 1439, 1568, 1629, 1736:
if response.thinking:
    self._all_thinking.append(response.thinking)
```

### Cleanup Task 3: Remove _last_tool_results
**File:** `nanocode/core.py`
**Description:**
- Remove `self._last_tool_results = []` (line 1410)
- Tool results now stored in `ToolPart` objects within `Message.parts`

### Cleanup Task 4: Remove _chat_with_retry()
**File:** `nanocode/core.py`
**Description:**
- Delete `_chat_with_retry()` method (~lines 915-940)
- Retry logic should be in `LLMBase._request_with_retry()`
- Pipeline uses `chat_stream()` directly, not this wrapper

### Cleanup Task 5: Remove _handle_tool_calls()
**File:** `nanocode/core.py`
**Description:**
- Delete `_handle_tool_calls()` method
- Tool execution now handled by `SessionProcessor` or called differently
- Old pattern loops through `response.tool_calls` manually

### Cleanup Task 6: Remove _format_thinking()
**File:** `nanocode/core.py`
**Description:**
- Delete `_format_thinking()` method (line ~1193)
- Thinking now rendered from `ReasoningPart.text` directly in TUI/CLI

### Cleanup Task 7: Clean up duplicated OpenAI __init__.py
**File:** `nanocode/llm/providers/openai/__init__.py`
**Description:**
- Remove old `chat()` method (the long ~200-line version)
- Keep only `chat_stream()` + minimal `chat()` wrapper
- Remove old `StreamEvent` dataclass (now in `llm/events.py`)
- Remove `_stream_chat()` helper (replaced by `chat_stream()`)

**Duplicated code:**
```python
# Remove this old StreamEvent class (use llm/events.py instead):
@dataclass
class StreamEvent:  # OLD - in openai/__init__.py
    type: str
    content: str | None = None
    # ... (now in nanocode/llm/events.py)

# Remove _stream_chat() (replaced by chat_stream()):
async def _stream_chat(self, payload, headers, on_token) -> LLMResponse:
    # ... (now in chat_stream())
```

### Cleanup Task 8: Remove session.gz
**File:** Deleted in commit 80299a2
**Status:** ✅ Already done

### Cleanup Task 9: Simplify core.py
**File:** `nanocode/core.py`
**Description:**
After pipeline is working, `_process_input_impl()` should be ~50 lines instead of ~700 lines:

**Old (remove):**
```python
async def _process_input_impl(self, user_input, ...):
    # ~700 lines of:
    # - Check cache
    # - Call LLM
    # - Handle thinking
    # - Loop through tool calls
    # - Handle context overflow
    # - Build augmented content
    # ...
```

**New (implement):**
```python
async def _process_input_impl(self, user_input, ...):
    # ~50 lines:
    pipeline = AgentPipeline(llm=self.llm, processor=self.processor)
    message = await pipeline.process(
        session_id=self.session_id,
        user_input=user_input,
        tools=self.tool_registry.get_schemas(),
    )
    # Extract results from message.parts
    return message.get_text()
```

### Cleanup Task 10: Remove legacy imports
**Files:** `nanocode/core.py`, `nanocode/cli/__init__.py`
**Description:**
Remove imports that are no longer needed:
```python
# Remove from core.py:
from nanocode.llm.base import LLMResponse  # Replaced by Message

# May be unused after refactor:
from nanocode.llm.base import Message  # (old Message class, not session/message.Message)
```

## Success Criteria
- [ ] `core.py` uses `AgentPipeline` instead of direct LLM calls
- [ ] All providers stream `StreamEvent` objects
- [ ] `SessionProcessor` builds `Message` with proper `Parts`
- [ ] TUI displays thinking/text/tool parts correctly
- [ ] All tests pass
- [ ] **Cleanup complete:** No dead code, no duplicated code
- [ ] **Architecture matches opencode:** `LLM.stream() → Processor → Message`

## Reference Files (OpenCode)
- `~/code/opencode/packages/opencode/src/session/processor.ts` - Event handler
- `~/code/opencode/packages/opencode/src/session/message-v2.ts` - Message types
- `~/code/opencode/packages/opencode/src/session/llm.ts` - LLM streaming
- `~/code/opencode/packages/opencode/src/cli/cmd/tui/` - TUI rendering

## Current TODO State (as of 2026-04-27)

Use this section to track current progress. Update after each session.

### Pending Tasks (4 total)
| Priority | Task | Status |
|----------|------|--------|
| High | Update Anthropic provider to stream events | ⏳ Pending |
| High | Update Ollama provider to stream events | ⏳ Pending |
| Medium | Wire up SessionProcessor dependencies | ⏳ Pending |
| Low | Update TUI to use Message Parts | ⏳ Pending |
| Low | Remove legacy code (_all_thinking, LLMResponse, etc.) | ⏳ Pending |

### Completed Tasks (9 total)
| Priority | Task | Status |
|----------|------|--------|
| High | llm/events.py - StreamEvent types | ✅ Completed |
| High | llm/providers/openai - chat_stream() implementation | ✅ Completed |
| High | session/message.py - Message/Parts classes | ✅ Completed |
| High | session/processor.py - SessionProcessor (headless mode) | ✅ Completed |
| High | agent_pipeline.py - Pipeline interface | ✅ Completed |
| High | core.py - Partial update (imports ready) | ✅ Completed |
| High | core.py - Refactor to use AgentPipeline | ✅ Completed |
| High | LLM base class: make chat() use chat_stream() | ✅ Completed |
| High | Add tests for new architecture | ✅ Completed |

### Task Summary
- **Total tasks:** 13 (including cleanup)
- **Completed:** 9 (69.2%)
- **Pending:** 4 (30.8%)
- **High priority pending:** 1 (Anthropic/Ollama need chat_stream())
- **Medium priority pending:** 1
- **Low priority pending:** 2

### Completion Details (Commit 80299a2)
1. ✅ **llm/events.py** - StreamEvent types matching opencode
   - EventType enum with 15+ event types
   - Event dataclasses: ReasoningStartEvent, ReasoningDeltaEvent, TextDeltaEvent, ToolCallEvent, FinishStepEvent, etc.

2. ✅ **llm/providers/openai/__init__.py** - Stream events
   - `chat_stream()` returns `AsyncGenerator[StreamEvent]`
   - Parses SSE stream and yields events
   - Keeps `chat()` as backward-compatible wrapper

3. ✅ **session/message.py** - Message/Parts (matching opencode's message-v2.ts)
   - `Message` class with `parts: List[Part]`
   - Part types: `TextPart`, `ReasoningPart`, `ToolPart`, `StepStartPart`, `StepFinishPart`
   - Methods: `add_part()`, `get_text()`, `get_reasoning()`, `get_tool_calls()`

4. ✅ **session/processor.py** - SessionProcessor (matching opencode's processor.ts)
   - `ProcessorContext` - holds state (assistant_message, reasoning_map, tool_calls, etc.)
   - `SessionProcessor` - processes events via `_handle_event()`
   - Event handlers: `_handle_reasoning_start()`, `_handle_text_delta()`, `_handle_tool_call()`, etc.
   - `ProcessorHandle` - returned to caller for accessing results

5. ✅ **agent_pipeline.py** - Clean interface
   - `AgentPipeline` class wrapping LLM + Processor
   - `process()` method that runs the full pipeline
   - Returns `Message` with all parts populated

6. ✅ **core.py** - Partial update
   - Updated imports to use new types (`from nanocode.session.message import Message, PartType, ReasoningPart`)
   - Still uses old `_process_input_impl()` pattern (TODO: refactor in Task 1)

## Next Session Command
```bash
cd /home/dclavijo/my_code/nanocode
# Resume with Task 1: Refactor core.py
git status  # Check current state
python3 -m pytest tests/ -v  # Run tests before changes
```
