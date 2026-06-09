# Failure Mode Analysis: nanocode

## Summary

nanocode is an autonomous AI agent with multi-provider LLM support, tool execution, planning, MCP integration, and context management. Its primary risk surface is **LLM API network failures**, **tool execution with unvalidated model output**, **context management corruption**, **MCP subprocess security boundaries**, and **state inconsistency across async operations**.

---

## High Priority Failures (score ≥ 8)

### 1. Tool argument injection from model output
- **Category**: AI/LLM System / Security
- **Likelihood**: 3-High | **Impact**: 4-Critical | **Detectability**: 2-Hard
- **Priority**: 9
- **Description**: The LLM generates tool call arguments that are directly executed in `_handle_tool_calls` → `self.tool_executor.execute(tool_name, args, ...)`. No semantic validation beyond JSON schema. A model could be tricked into calling `bash` with `rm -rf /`, `write` to `/etc/passwd`, or `webfetch` to SSRF internal services. The `yolo` mode bypasses all permission checks.
- **Mitigation**: Implement allowlist/blocklist for tool+arg combinations. Add path traversal checks for file tools. Never bypass with yolo in production.

### 2. Context overflow → silent truncation / data loss
- **Category**: Code / Algorithm
- **Likelihood**: 3-High | **Impact**: 3-High | **Detectability**: 3-Silent
- **Priority**: 9
- **Description**: `_compact_context()` and `_prune_old_tool_results()` silently remove messages and tool results when context exceeds limits. The compaction uses an LLM summary which can hallucinate or lose critical details. The `importance` strategy drops low-importance messages without user awareness. Fallback to `"[N messages from earlier in the conversation]"` destroys all history.
- **Mitigation**: Log compacted content to disk. Add user confirmation before destructive compaction. Use deterministic truncation (last-N only) as safer default.

### 3. MCP stdio connection subprocess lifecycle
- **Category**: Security / Distributed System
- **Likelihood**: 2-Medium | **Impact**: 4-Critical | **Detectability**: 3-Silent
- **Priority**: 9
- **Description**: `MCPStdioConnection.start()` spawns subprocesses with `subprocess.Popen`. If `close()` is not called (e.g., crash, exception), zombie processes accumulate. The `_reader_task` can leak if not properly cancelled. Stderr is piped but never consumed → process deadlock on stderr buffer fill. Environment variables are passed through to subprocess without sanitization.
- **Mitigation**: Use context managers (`async with`). Implement subprocess timeout and reap in watchdog. Consume stderr in background. Sanitize `MCP_STDIO_ENV_*` keys.

### 4. Prompt cache staleness / incorrect hit
- **Category**: Code / Algorithm
- **Likelihood**: 2-Medium | **Impact**: 3-High | **Detectability**: 3-Silent
- **Priority**: 8
- **Description**: Cache key is `sha256(json(messages + tools))`. But `_check_cache` is called before `_make_first_llm_request` and returned directly without validating the model hasn't changed, temperature/params differ, or the current agent is the same. The cache logging at `core.py:1568` even says "this is a bug if input changed!" — this is an acknowledged risk.
- **Mitigation**: Include model, temperature, session_id, and agent name in cache key. Add TTL. Never cache tool-call responses (only text responses). Make cache opt-in with explicit user acknowledgment.

### 5. File tracker path traversal
- **Category**: Security
- **Likelihood**: 2-Medium | **Impact**: 4-Critical | **Detectability**: 2-Hard
- **Priority**: 8
- **Description**: `FileTracker` in `_init_file_tracker` takes a cache_dir from config that could be an attacker-controlled path. If a malicious config or env var sets `cache_dir` to `/etc/`, file operations could overwrite system files. The virtualized filesystem hints mention `/skills/*` and `/memory/*` paths but `read`/`write` tools may not enforce these boundaries.
- **Mitigation**: Chroot the tool file paths. Validate all paths against a workspace root. Refuse paths with `..` or symlinks outside workspace.

### 6. Async event loop blockage in context compaction
- **Category**: Concurrency
- **Likelihood**: 3-High | **Impact**: 3-High | **Detectability**: 2-Hard
- **Priority**: 8
- **Description**: `_compact()` in `context.py` calls `loop.run_until_complete(self._compact_async())` which BLOCKS the event loop if one is already running (raises `RuntimeError` → caught and silently ignored). `_summary_strategy()` has a `loop.is_running()` guard that falls back to a useless summary string. This means compaction silently fails, potentially leading to context overflow crashes.
- **Mitigation**: Use `asyncio.create_task()` instead of blocking calls. Always have a deterministic fallback that doesn't require LLM.

### 7. LLM retry with message corruption
- **Category**: Code / Algorithm
- **Likelihood**: 2-Medium | **Impact**: 3-High | **Detectability**: 3-Silent
- **Priority**: 8
- **Description**: `_chat_with_retry()` on retry (lines 1073-1094) rebuilds messages but only keeps the first user message and all system messages — all subsequent user messages and ALL assistant/tool messages are DROPPED. This corrupts multi-turn context. The retry path produces an incomplete conversation state.
- **Mitigation**: On retry, send ALL original messages. Only the last user message needs to be preserved. Never drop assistant/tool messages.

### 8. Session processor headless mode ignores state
- **Category**: Code / Algorithm
- **Likelihood**: 3-High | **Impact**: 2-Medium | **Detectability**: 3-Silent
- **Priority**: 8
- **Description**: `SessionProcessor` in headless mode (`headless=True`) skips all persistence calls (`session.set_status`, `session.update_part`, etc.). This means snapshots, session state, and permission checks are silently no-ops. Errors in these calls are swallowed. Checkpoints may be saved but never referenced for recovery on restart.
- **Mitigation**: Log when headless mode skips operations. Implement at least a basic in-memory state tracker even in headless mode.

---

## Medium Priority Failures (score 5–7)

### 9. Doom loop detector cold-start bypass
- **Priority**: 6
- Threshold starts at 3 identical calls. First 2 identical destructive calls always execute. No pre-warming or static analysis.

### 10. Proxy typo detection is fragile
- **Priority**: 6
- `base.py:164` checks for `"172.0.0.1"` in proxy string — this is a substring match that also matches other IPs containing that octet.

### 11. SQLAlchemy session leak
- **Priority**: 6
- `Database.session()` context manager catches and swallows exceptions in `session.rollback()` path. If rollback itself fails, exception is silently caught.

### 12. System prompt template loading order
- **Priority**: 6
- `_load_system_prompt_template()` tries multiple search paths but uses first found. If multiple `.system_prompts/template.md` files exist, which wins depends on search order, not explicit config.

### 13. MCP `asyncio.run()` in sync context
- **Priority**: 6
- `MCPManager.get_all_tools()` calls `asyncio.run(client.list_tools())` which creates a new event loop — dangerous if called from within a running loop (throws `RuntimeError`). Silent `except: pass`.

### 14. Tool discovery from untrusted directories
- **Priority**: 6
- `ToolRegistry.discover_tools()` walks `DEFAULT_TOOL_DIRS` (.nanocode/tools, .opencode/tools, .claude/tools, etc.) and `exec_module()` on any `.py` file. A malicious file in the workspace could be loaded and executed.

### 15. Rate limit cross-contamination
- **Priority**: 5
- `_request_with_retry()` uses provider name for rate-limit tracking. If two models share a provider, one rate-limited model blocks the other.

### 16. JSON-RPC ID collision
- **Priority**: 5
- MCP `create_request()` uses `id(self)` as request ID. Multiple requests from the same connection could collide.

### 17. Background review task fire-and-forget
- **Priority**: 5
- `_spawn_background_review()` runs an LLM call with `asyncio.create_task()` — never awaited or error-handled. If the LLM is rate-limited or down, the error is silently swallowed.

### 18. Snapshot manager not awaited
- **Priority**: 5
- `_init_snapshot()` calls `create_snapshot_manager()` which may do I/O. No `await`. If git snapshots fail, the error is caught at step boundaries.

### 19. Token counting is an approximation
- **Priority**: 5
- `TokenCounter.count_tokens()` uses a 4-char-per-token heuristic. This can underestimate for code/JSON (token-dense) and overestimate for short messages. Context may be pruned prematurely or too late.

### 20. Delegate tool circular delegation
- **Priority**: 5
- `create_delegate_tool()` creates tools that can delegate to other agents. No depth limit is enforced beyond `_delegate_depth` (unused). Deadly embrace between agents.

---

## Low Priority Failures (score ≤ 4)

- **Config YAML injection**: YAML `safe_load` used, but arbitrary structures in config can reach `setdefault` chains.
- **Race condition on session ID**: Global `_current_session_id` set/get without lock.
- **Trace file unbounded growth**: `/tmp/nanocode_trace.log` appends forever.
- **MCP SSE `aiter_lines` never closed**: On cancel, the `client.stream` context manager may not be cleaned up.
- **Console with `force_terminal=True`**: Forces terminal output even when piped. Breaks CI/log capture.
- **UUID v4 used for checkpoint IDs**: Not URL-safe or sortable.
- **`_find_prunable_tool_results` reversed loop bug**: Lines 937-941 show duplicated `for i, j in reversed(to_remove)` inside itself — copy-paste bug causing double-deletion or index errors.

---

## Key Mitigations (Priority Ordered)

1. **Tool argument sandboxing**: Add path validation (reject `..`, enforce workspace root), command allowlist for `bash`, argument schema validation beyond JSON type checking.
2. **Fix retry message corruption**: Remove the broken message rebuild in `_chat_with_retry()` retry path. Always resend original messages.
3. **Fix event-loop-blocking compaction**: Replace `run_until_complete` in `_compact()` with proper async design. Never swallow `RuntimeError`.
4. **Fix prompt cache invalidation**: Include model/temperature/agent in cache key. Never cache requests containing tool-call responses.
5. **Secure MCP subprocess lifecycle**: Context-manager-based lifecycle, stderr consumer, timeout enforcement, env var sanitization.
6. **Fix duplicate loop in `_find_prunable_tool_results`**: The nested `for i, j in reversed(to_remove)` is a copy-paste bug that would cause double-deletion or index errors.
7. **Audit all `except: pass`**: Replace silent swallows with at minimum `logger.debug()`.

---

## Assumptions Made

- **Threat model**: Opportunistic attacker who can supply malicious workspace files (configs, tools, prompts) OR control LLM output via prompt injection. NOT assuming filesystem-level compromise.
- **Scope**: Analysis covers `nanocode/core.py`, `nanocode/context.py`, `nanocode/config.py`, `nanocode/state.py`, `nanocode/llm/base.py`, `nanocode/tools/__init__.py`, `nanocode/session/processor.py`, `nanocode/mcp/__init__.py`, `nanocode/storage/database.py`, `nanocode/doom_loop.py`, `nanocode/agent_pipeline.py`. Omitted: bus, effect, share, admin, hooks, skills, planning (secondary risk surface).
- **What was NOT analyzed**: Downstream provider API security, physical node security, supply chain of pip dependencies, network-level MITM.
