# Nanocode Enhancement Plan: Lessons from "The Agent Harness Belongs Outside the Sandbox"

**Source:** https://www.mendral.com/blog/agent-harness-belongs-outside-sandbox  
**Date:** 2026-05-04

---

## Blog Post Summary

The blog post argues that in a multi-user agent system, the agent harness (the loop that drives an LLM) should run **outside** the sandbox, not inside it. Key points:

1. **Credentials stay out of the sandbox** — LLM API keys, user tokens, DB access live in the harness, not the sandbox
2. **Sandboxes become cattle** — can suspend/resume, die without losing the session
3. **Multi-user stops being a distributed filesystem problem** — shared skills/memories are a database, not synced files
4. **Virtualized filesystem** — one `read`/`write`/`edit` interface, but different backends based on path prefixes (`/skills/*` → DB, `/workspace/*` → sandbox)
5. **Durable execution** — agent loops are long-running; need checkpointing to survive deploys/restarts

---

## Gap Analysis: Blog Post vs Nanocode

| Feature from Blog | Nanocode Status |
|---|---|
| **Harness outside sandbox** | ✅ Server already runs loop outside (no sandbox exists) |
| **Durable execution (step checkpointing)** | ⚠️ Sessions saved to JSON/SQLite, but no step-level checkpointing that survives mid-loop restarts |
| **Sandbox lifecycle (suspend/resume)** | ❌ No sandbox at all — everything runs locally |
| **Virtualized filesystem / path dispatch** | ❌ Tools use local FS directly, no `/skills/*` → DB routing |
| **Skills/memories in database** | ❌ Filesystem-only (`.nanocode/skills/`, etc.) |
| **Multi-user/org scopes** | ❌ Single-user local, no `org_id`/`user_id` in DB models |
| **Credential isolation** | ❌ API keys in config/env, passed to bash subprocesses |
| **Bash path guards** | ❌ No restrictions on what bash can access |
| **One interface, two backends** | ❌ `read`/`write`/`edit` are local FS only |

---

## Current Architecture Findings

### Agent Loop (`core.py` — `AutonomousAgent`)
- Loop runs in memory
- Sessions persisted via JSON files (`~/.local/share/nanocode/storage/sessions/`) and SQLite (`SessionStorage`)
- Planning checkpoints saved as JSON (`~/.local/share/nanocode/storage/checkpoints/`)
- Git-based snapshots via `SnapshotManager`
- **No step-level checkpointing** — if server restarts mid-loop, current turn is lost

### Tools (`tools/builtin/__init__.py`)
| Tool | Class | Status |
|---|---|---|
| `bash` | `BashTool` | Executes `subprocess.run(command, shell=True, cwd=...)` — no path guards |
| `read` | `ReadFileTool` | Local FS only: `self.root_dir / path` |
| `write` | `WriteFileTool` | Local FS only: `self.root_dir / path` |
| `edit` | `EditTool` | Local FS only: `self.root_dir / path` |
| `glob` | `GlobTool` | Local FS only |
| `grep` | `GrepTool` | Local FS only |
| `skill` | `SkillTool` | Loads from local FS paths |

All tools use `root_dir` (defaults to `Path.cwd()`) — **no pluggable backends**.

### Skills System (`skills/__init__.py` — `SkillsManager`)
- Stored in local filesystem paths: `.nanocode/skills/`, `.claude/skills/`, `~/.opencode/skills/`, etc.
- Remote skills cached in `~/.local/share/nanocode/cache/skills/`
- **No database storage**

### Storage (`storage/`)
- SQLite via SQLAlchemy (`database.py`, `session.py`)
- Models: `Project`, `Session`, `Message`, `MessagePart`, `Todo`, `SessionShare`
- **No `user_id` or `org_id`** — single-user only
- Also used for prompt caching (`cache.py`)

### Server (`server/__init__.py` — `AgentServer`)
- Plain TCP socket with manual HTTP parsing (`asyncio.start_server`)
- Sessions stored **in-memory** (`ServerSessionManager._sessions: dict`)
- Agent runs in **same process** — no sandbox
- **No sandbox lifecycle management**

### Credential Handling
- API keys loaded from `config.yaml` or env vars (`OPENAI_API_KEY`, etc.)
- `BashTool` passes session env to subprocess — **keys visible to bash commands**
- No credential isolation boundary

---

## Implementation Plan

### Phase 1: Virtualized Filesystem Layer (Core Change)

**Goal:** Add path-dispatch so `read`/`write`/`edit` route to different backends based on path prefixes.

**Why:** Keeps the `read(path)` / `write(path, content)` / `edit(path, old, new)` API surface the model was trained on, while enabling database-backed skills and memories.

**Implementation:**
1. Create `nanocode/tools/backends/` with:
   - `FileSystemBackend` ABC with methods: `read(path)`, `write(path, content)`, `edit(path, old, new)`, `exists(path)`, `list(path)`
   - `LocalFSBackend` — existing behavior using `root_dir`
   - `DatabaseBackend` — reads/writes from SQLite tables

2. Create `nanocode/tools/fs_router.py` with `FileSystemRouter`:
   - Maps path prefixes to backends:
     - `/workspace/*` → `LocalFSBackend` (sandbox or CWD)
     - `/skills/*` → `DatabaseBackend`
     - `/memory/*` → `DatabaseBackend`
   - Strips prefix before passing to backend (or backend is aware of its namespace)

3. Modify `ReadFileTool`, `WriteFileTool`, `EditTool`:
   - Accept `FileSystemRouter` instead of single `root_dir`
   - Route each call through router based on path

4. Update `GlobTool` and `GrepTool` to also use router (or document they only work on workspace)

**Files to create/modify:**
- `nanocode/tools/backends/__init__.py` (new)
- `nanocode/tools/backends/base.py` (new)
- `nanocode/tools/backends/local.py` (new)
- `nanocode/tools/backends/database.py` (new)
- `nanocode/tools/fs_router.py` (new)
- `nanocode/tools/builtin/__init__.py` (modify tool classes)

---

### Phase 2: Move Skills & Memories to Database

**Goal:** Skills and memories stored in SQLite, shared across sessions.

**Implementation:**
1. Extend `nanocode/storage/models.py`:
   ```python
   class Skill(Base):
       __tablename__ = "skills"
       id = Column(String, primary_key=True)
       name = Column(String, nullable=False)
       description = Column(String)
       content = Column(Text, nullable=False)
       scope = Column(String, default="user")  # "user", "org", "project"
       scope_id = Column(String)  # user_id or org_id when multi-user added
       created_at = Column(DateTime)
       updated_at = Column(DateTime)

   class Memory(Base):
       __tablename__ = "memories"
       id = Column(String, primary_key=True)
       key = Column(String, nullable=False)  # e.g., "MEMORY.md"
       content = Column(Text, nullable=False)
       scope = Column(String, default="user")
       scope_id = Column(String)
       version = Column(Integer, default=1)
       created_at = Column(DateTime)
       updated_at = Column(DateTime)
   ```

2. Update `SkillsManager`:
   - Add `load_from_db()` and `save_to_db()` methods
   - Fallback to filesystem for initial load, then sync to DB
   - New skills/memory writes go to DB

3. Update context/memory system:
   - Use `DatabaseBackend` for memory paths
   - Last-writer-wins per key (as blog suggests)

4. Add DB migration or auto-create tables on startup

**Files to modify:**
- `nanocode/storage/models.py`
- `nanocode/storage/session.py` (add skill/memory methods)
- `nanocode/skills/__init__.py`
- `nanocode/context.py` (if memory is managed there)

---

### Phase 3: Credential Isolation

**Goal:** API keys and tokens never reach bash tools or sandboxes.

**Implementation:**
1. Audit `BashTool` (`tools/builtin/__init__.py:117-226`):
   - Stop passing full `session["env"]` to subprocess
   - Create a sanitized env for bash: only allowlisted vars (PATH, HOME, etc.)
   - Never forward `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, etc.

2. Store LLM API keys only in harness process:
   - Load once at startup in `config.py`
   - Pass to LLM client directly, never put in session env

3. Add `credential_scope` concept:
   - Tools declare what env vars they need
   - Harness provides only those

**Files to modify:**
- `nanocode/tools/builtin/__init__.py` (BashTool)
- `nanocode/core.py` (credential handling)
- `nanocode/config.py` (if needed)

---

### Phase 4: Bash Path Guards

**Goal:** Prevent bash from accessing virtualized namespace paths.

**Implementation:**
1. Parse bash commands to detect accesses to `/skills/`, `/memory/` paths:
   - Simple regex approach (quick): detect patterns like `/skills/`, `/memory/`, `.nanocode/skills`, etc.
   - Better approach: use tree-sitter to parse bash (as blog mentions)

2. Add system prompt guidance:
   - "Do not use bash to access skill or memory directories; use read/write tools"
   - "Bash tool is for workspace operations only"

3. Block or warn on detected virtualized-path accesses:
   - Log warning and return error to agent
   - Optionally sanitize the command

**Files to modify:**
- `nanocode/tools/builtin/__init__.py` (BashTool.execute)
- `nanocode/core.py` (system prompt construction)

---

### Phase 5: Durable Execution (Optional, Longer-Term)

**Goal:** Survive process restarts mid-agent-loop.

**Implementation:**
1. Replace in-memory session state with step-level checkpointing:
   - Before each tool execution: save current state
   - After each tool execution: save results
   - State includes: messages, current step, tool call results

2. Use SQLite + simple event loop (avoid Inngest/Temporal dependency for now):
   - `nanocode/storage/models.py`: add `AgentCheckpoint` model
   - Serialize agent state to JSON, store in DB
   - On restart, check for unfinished sessions and resume

3. Each agent loop turn becomes a "step" that checkpoints

**Files to create/modify:**
- `nanocode/storage/models.py` (add checkpoint model)
- `nanocode/core.py` (add checkpoint logic)

---

### Phase 6: Sandbox Lifecycle (Optional, Requires Docker)

**Goal:** Provision sandboxes only when needed, suspend when idle.

**Implementation:**
1. Create `nanocode/sandbox/` module with `SandboxProvider` ABC:
   ```python
   class SandboxProvider(ABC):
       @abstractmethod
       async def create(self) -> Sandbox: ...
       @abstractmethod
       async def suspend(self, sandbox_id: str): ...
       @abstractmethod
       async def resume(self, sandbox_id: str): ...
       @abstractmethod
       async def destroy(self, sandbox_id: str): ...
   ```

2. Implementations:
   - `LocalSandbox` — existing behavior (no sandbox)
   - `DockerSandbox` — Docker container per session
   - `BlaxelSandbox` — integrate with Blaxel API (25ms resume)

3. Integrate with agent loop:
   - Suspend sandbox when agent is in LLM call / waiting
   - Resume only for bash/workspace tool calls
   - 25ms resume target (or best-effort for Docker)

**Files to create:**
- `nanocode/sandbox/__init__.py`
- `nanocode/sandbox/base.py`
- `nanocode/sandbox/local.py`
- `nanocode/sandbox/docker.py` (optional)
- `nanocode/sandbox/blaxel.py` (optional)

---

## Recommended Starting Point

**Start with Phase 1 + Phase 2** — the virtualized FS layer and DB-backed skills/memories. These are the highest-value changes that:
- Keep the `read`/`write`/`edit` API surface the model was trained on
- Improve session sharing and memory persistence
- Don't require major infrastructure (no Docker, no Inngest)

Phases 3-4 are security hardening. Phase 5-6 are larger architectural changes.

---

## Progress Tracking

- [x] Phase1: Virtualized Filesystem Layer
   - [x] Create `nanocode/tools/backends/` module
   - [x] Implement `FileSystemRouter`
   - [x] Modify tool classes to use router
- [x] Phase2: Skills & Memories in Database
   - [x] Extend DB models
   - [x] Update `SkillsManager`
   - [x] Update context/memory system
- [x] Phase3: Credential Isolation
   - [x] Audit and fix `BashTool`
   - [x] Sanitize subprocess environment
- [x] Phase4: Bash Path Guards
   - [x] Add path detection in bash commands
   - [x] Update system prompt (done in core.py _build_system_prompt)
- [x] Phase5: Durable Execution
   - [x] Add checkpoint model
   - [x] Integrate checkpointing in agent loop
- [x] Phase6: Sandbox Lifecycle
   - [x] Create `SandboxProvider` ABC
   - [x] Implement LocalSandbox (backward compatible)
   - [x] Add DockerSandbox skeleton (optional)
   - [x] Implement BlaxelSandbox (optional)
