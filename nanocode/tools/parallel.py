"""Tool Parallelism - Execute read-only tools concurrently, write tools sequentially.

Based on MiMo-Code's approach to tool execution:
- Read-only tools (read, grep, glob, find_usages) run in parallel
- Write tools (edit, write, bash) run sequentially to avoid race conditions
"""

import asyncio
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("nanocode.tools.parallel")


class ToolAccessMode(str, Enum):
    """Tool access mode for parallelism decisions."""

    READ = "read"  # Safe to run concurrently
    WRITE = "write"  # Must run sequentially


# Default tool classifications
DEFAULT_READ_TOOLS = {
    "read",
    "read_file",
    "grep",
    "rg",
    "ripgrep",
    "glob",
    "find",
    "find_usages",
    "codesearch",
    "exa_search",
    "free_search",
    "git_status",
    "git_log",
    "git_diff",
    "git_show",
    "list_files",
    "ls",
    "cat",
    "head",
    "tail",
    "wc",
    "file_info",
    "memory",
    "history",
    "task_list",
    "task_get",
}

DEFAULT_WRITE_TOOLS = {
    "write",
    "write_file",
    "edit",
    "edit_file",
    "bash",
    "shell",
    "exec",
    "run",
    "git_add",
    "git_commit",
    "git_push",
    "git_checkout",
    "git_merge",
    "git_rebase",
    "git_reset",
    "git_stash",
    "mkdir",
    "rm",
    "delete",
    "move",
    "cp",
    "copy",
    "symlink",
    "chmod",
    "chown",
    "task_create",
    "task_start",
    "task_done",
    "task_block",
    "task_abandon",
}


@dataclass
class ToolClassification:
    """Classification of a tool for parallelism."""

    name: str
    mode: ToolAccessMode
    is_read_only: bool = True

    @property
    def can_parallel(self) -> bool:
        return self.mode == ToolAccessMode.READ


class ToolParallelismManager:
    """Manages parallel execution of tools based on access mode.

    Read-only tools can run concurrently, write tools run sequentially.
    """

    def __init__(
        self,
        read_tools: Optional[set[str]] = None,
        write_tools: Optional[set[str]] = None,
        max_concurrency: int = 10,
    ):
        """Initialize the parallelism manager.

        Args:
            read_tools: Set of tool names that are read-only
            write_tools: Set of tool names that are write operations
            max_concurrency: Max concurrent read-only tools
        """
        self.read_tools = read_tools or DEFAULT_READ_TOOLS.copy()
        self.write_tools = write_tools or DEFAULT_WRITE_TOOLS.copy()
        self.max_concurrency = max_concurrency
        self._classifications: Dict[str, ToolClassification] = {}

    def classify_tool(self, tool_name: str) -> ToolClassification:
        """Classify a tool's access mode."""
        if tool_name in self._classifications:
            return self._classifications[tool_name]

        if tool_name in self.write_tools:
            mode = ToolAccessMode.WRITE
        elif tool_name in self.read_tools:
            mode = ToolAccessMode.READ
        else:
            # Default: treat unknown tools as write (conservative)
            mode = ToolAccessMode.WRITE

        classification = ToolClassification(
            name=tool_name,
            mode=mode,
            is_read_only=mode == ToolAccessMode.READ,
        )
        self._classifications[tool_name] = classification
        return classification

    def classify_tools(
        self, tool_calls: List[Tuple[str, Dict[str, Any]]]
    ) -> Tuple[List[Tuple[str, Dict[str, Any]]], List[Tuple[str, Dict[str, Any]]]]:
        """Classify tool calls into read and write groups.

        Args:
            tool_calls: List of (tool_name, arguments) tuples

        Returns:
            Tuple of (read_calls, write_calls)
        """
        read_calls = []
        write_calls = []

        for tool_name, args in tool_calls:
            classification = self.classify_tool(tool_name)
            if classification.can_parallel:
                read_calls.append((tool_name, args))
            else:
                write_calls.append((tool_name, args))

        return read_calls, write_calls

    async def execute_parallel(
        self,
        tool_executor: Any,  # ToolExecutor instance
        tool_calls: List[Tuple[str, Dict[str, Any]]],
        session_id: Optional[str] = None,
        agent_name: Optional[str] = None,
    ) -> List[Any]:
        """Execute tool calls with parallel read-only tools and sequential writes.

        Args:
            tool_executor: ToolExecutor instance to execute tools
            tool_calls: List of (tool_name, arguments) tuples
            session_id: Optional session ID
            agent_name: Optional agent name

        Returns:
            List of ToolResult objects in order of input tool_calls
        """
        if not tool_calls:
            return []

        # Classify tools
        read_calls, write_calls = self.classify_tools(tool_calls)

        logger.debug(
            f"Parallel execution: {len(read_calls)} read, "
            f"{len(write_calls)} write out of {len(tool_calls)} total"
        )

        # Create result mapping
        results: Dict[int, Any] = {}
        call_order = {name: i for i, (name, _) in enumerate(tool_calls)}

        # Execute read-only tools concurrently
        if read_calls:
            semaphore = asyncio.Semaphore(self.max_concurrency)

            async def execute_with_semaphore(name: str, args: dict) -> Tuple[str, Any]:
                async with semaphore:
                    result = await tool_executor.execute(
                        name, args, session_id=session_id, agent_name=agent_name
                    )
                    return name, result

            read_tasks = [
                execute_with_semaphore(name, args) for name, args in read_calls
            ]
            read_results = await asyncio.gather(*read_tasks, return_exceptions=True)

            for result in read_results:
                if isinstance(result, Exception):
                    logger.error(f"Read tool failed: {result}")
                    continue
                name, tool_result = result
                # Find original index
                for i, (cn, _) in enumerate(tool_calls):
                    if cn == name and i not in results:
                        results[i] = tool_result
                        break

        # Execute write tools sequentially
        for name, args in write_calls:
            result = await tool_executor.execute(
                name, args, session_id=session_id, agent_name=agent_name
            )
            # Find original index
            for i, (cn, _) in enumerate(tool_calls):
                if cn == name and i not in results:
                    results[i] = result
                    break

        # Return results in original order
        return [results.get(i) for i in range(len(tool_calls))]

    def add_read_tool(self, tool_name: str):
        """Add a tool to the read-only list."""
        self.read_tools.add(tool_name)
        self.write_tools.discard(tool_name)
        self._classifications.pop(tool_name, None)

    def add_write_tool(self, tool_name: str):
        """Add a tool to the write list."""
        self.write_tools.add(tool_name)
        self.read_tools.discard(tool_name)
        self._classifications.pop(tool_name, None)

    def get_stats(self) -> Dict[str, Any]:
        """Get parallelism statistics."""
        return {
            "read_tools": len(self.read_tools),
            "write_tools": len(self.write_tools),
            "max_concurrency": self.max_concurrency,
            "classifications_cached": len(self._classifications),
        }


# Global instance
_parallelism_manager: Optional[ToolParallelismManager] = None


def get_parallelism_manager() -> ToolParallelismManager:
    """Get or create the global parallelism manager."""
    global _parallelism_manager
    if _parallelism_manager is None:
        _parallelism_manager = ToolParallelismManager()
    return _parallelism_manager


def reset_parallelism_manager():
    """Reset the global parallelism manager."""
    global _parallelism_manager
    _parallelism_manager = None
