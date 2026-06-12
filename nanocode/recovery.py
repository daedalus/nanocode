"""Recovery State Machine - Track edit failures and inject recovery nudges.

Based on MiMo-Code's approach:
- Track per-turn: which edit patterns failed, syntax repair state, write attempts per path
- Inject recovery nudges when model repeats failures
- Complements doom_loop detection with failure-specific tracking
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class FailureType(StrEnum):
    """Types of failures that can occur."""

    EDIT_NO_MATCH = "edit_no_match"
    EDIT_MULTIPLE_MATCH = "edit_multiple_match"
    SYNTAX_ERROR = "syntax_error"
    IMPORT_ERROR = "import_error"
    RUNTIME_ERROR = "runtime_error"
    FILE_NOT_FOUND = "file_not_found"
    PERMISSION_DENIED = "permission_denied"
    WRITE_FAILED = "write_failed"


class RecoveryAction(StrEnum):
    """Recovery actions to suggest."""

    RETRY_DIFFERENT = "retry_different"
    USE_AST_EDIT = "use_ast_edit"
    CHECK_SYNTAX = "check_syntax"
    CHECK_IMPORTS = "check_imports"
    READ_FILE_FIRST = "read_file_first"
    CHECK_PERMISSIONS = "check_permissions"
    SIMPLIFY_APPROACH = "simplify_approach"
    STOP_AND_ASK = "stop_and_ask"


@dataclass
class FailureRecord:
    """Record of a single failure."""

    failure_type: FailureType
    tool_name: str
    file_path: str | None
    error_message: str
    attempt_number: int
    timestamp: float = field(default_factory=lambda: __import__("time").time())
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class FileFailureTracker:
    """Tracks failures for a specific file."""

    file_path: str
    failures: list[FailureRecord] = field(default_factory=list)
    total_attempts: int = 0
    successful_edits: int = 0

    @property
    def failure_rate(self) -> float:
        if self.total_attempts == 0:
            return 0.0
        return len(self.failures) / self.total_attempts

    @property
    def consecutive_failures(self) -> int:
        count = 0
        for f in reversed(self.failures):
            if f.failure_type in [FailureType.EDIT_NO_MATCH, FailureType.SYNTAX_ERROR]:
                count += 1
            else:
                break
        return count


@dataclass
class RecoveryNudge:
    """A recovery suggestion to inject into the conversation."""

    action: RecoveryAction
    message: str
    priority: int = 1  # Higher = more important
    context: dict[str, Any] = field(default_factory=dict)


class RecoveryStateMachine:
    """Tracks edit failures and injects recovery nudges.

    Based on MiMo-Code's recovery approach:
    - Track per-turn failure patterns
    - Detect syntax repair loops
    - Track write attempts per path
    - Inject recovery nudges when model repeats failures
    """

    def __init__(self, max_failures_before_nudge: int = 2, max_attempts_per_file: int = 5):
        """Initialize the recovery state machine.

        Args:
            max_failures_before_nudge: Failures before suggesting recovery
            max_attempts_per_file: Max attempts before blocking a file
        """
        self.max_failures_before_nudge = max_failures_before_nudge
        self.max_attempts_per_file = max_attempts_per_file
        self._file_trackers: dict[str, FileFailureTracker] = {}
        self._recent_failures: list[FailureRecord] = []
        self._recovery_suggestions: dict[str, list[RecoveryNudge]] = defaultdict(list)
        self._syntax_repair_mode: bool = False
        self._current_turn_failures: int = 0

    def record_failure(
        self,
        failure_type: FailureType,
        tool_name: str,
        file_path: str | None,
        error_message: str,
        context: dict[str, Any] = None,
    ) -> RecoveryNudge | None:
        """Record a failure and return recovery suggestion if needed.

        Args:
            failure_type: Type of failure
            tool_name: Tool that failed
            file_path: File being edited (if applicable)
            error_message: Error message
            context: Additional context

        Returns:
            RecoveryNudge if suggestion is available, None otherwise
        """
        self._current_turn_failures += 1

        # Get or create file tracker
        if file_path:
            if file_path not in self._file_trackers:
                self._file_trackers[file_path] = FileFailureTracker(file_path=file_path)
            tracker = self._file_trackers[file_path]
            tracker.total_attempts += 1
        else:
            tracker = None

        # Create failure record
        attempt = tracker.total_attempts if tracker else len(self._recent_failures) + 1
        record = FailureRecord(
            failure_type=failure_type,
            tool_name=tool_name,
            file_path=file_path,
            error_message=error_message,
            attempt_number=attempt,
            context=context or {},
        )

        self._recent_failures.append(record)
        if len(self._recent_failures) > 20:
            self._recent_failures.pop(0)

        if tracker:
            tracker.failures.append(record)

        # Check if we should suggest recovery
        nudge = self._suggest_recovery(record, tracker)
        if nudge:
            if file_path:
                self._recovery_suggestions[file_path].append(nudge)

        return nudge

    def record_success(self, tool_name: str, file_path: str | None):
        """Record a successful operation."""
        self._current_turn_failures = 0

        if file_path and file_path in self._file_trackers:
            self._file_trackers[file_path].successful_edits += 1

        # Clear syntax repair mode on success
        self._syntax_repair_mode = False

    def _suggest_recovery(
        self, record: FailureRecord, tracker: FileFailureTracker | None
    ) -> RecoveryNudge | None:
        """Suggest a recovery action based on failure pattern."""
        if not tracker:
            return None

        # Check consecutive failures
        if tracker.consecutive_failures >= self.max_failures_before_nudge:
            # Suggest different approach
            if record.failure_type == FailureType.EDIT_NO_MATCH:
                return RecoveryNudge(
                    action=RecoveryAction.USE_AST_EDIT,
                    message=(
                        f"Edit failed {tracker.consecutive_failures} times on {record.file_path}. "
                        "Try using the edit_symbol tool to edit by function/class name instead."
                    ),
                    priority=2,
                )
            elif record.failure_type == FailureType.SYNTAX_ERROR:
                self._syntax_repair_mode = True
                return RecoveryNudge(
                    action=RecoveryAction.CHECK_SYNTAX,
                    message=(
                        f"Syntax error repeated {tracker.consecutive_failures} times. "
                        "Read the file first to understand the current state, then make a smaller change."
                    ),
                    priority=3,
                )

        # Check total attempts on file
        if tracker.total_attempts >= self.max_attempts_per_file:
            return RecoveryNudge(
                action=RecoveryAction.STOP_AND_ASK,
                message=(
                    f"Too many attempts ({tracker.total_attempts}) on {record.file_path}. "
                    "Consider asking the user for help or trying a completely different approach."
                ),
                priority=3,
            )

        # First failure - suggest read first
        if tracker.consecutive_failures == 1 and record.failure_type == FailureType.EDIT_NO_MATCH:
            return RecoveryNudge(
                action=RecoveryAction.READ_FILE_FIRST,
                message=(
                    f"Edit failed on {record.file_path}. "
                    "Read the file first to see its current content, then retry the edit."
                ),
                priority=1,
            )

        return None

    def get_nudges_for_file(self, file_path: str) -> list[RecoveryNudge]:
        """Get pending recovery nudges for a file."""
        return self._recovery_suggestions.get(file_path, [])

    def clear_nudges(self, file_path: str = None):
        """Clear recovery nudges."""
        if file_path:
            self._recovery_suggestions.pop(file_path, None)
        else:
            self._recovery_suggestions.clear()

    def should_block_file(self, file_path: str) -> bool:
        """Check if a file should be blocked due to too many failures."""
        tracker = self._file_trackers.get(file_path)
        if not tracker:
            return False
        return tracker.total_attempts >= self.max_attempts_per_file

    def is_in_syntax_repair_mode(self) -> bool:
        """Check if we're in syntax repair mode."""
        return self._syntax_repair_mode

    def get_file_stats(self, file_path: str) -> dict[str, Any] | None:
        """Get failure statistics for a file."""
        tracker = self._file_trackers.get(file_path)
        if not tracker:
            return None
        return {
            "file_path": tracker.file_path,
            "total_attempts": tracker.total_attempts,
            "failures": len(tracker.failures),
            "successful_edits": tracker.successful_edits,
            "failure_rate": tracker.failure_rate,
            "consecutive_failures": tracker.consecutive_failures,
        }

    def get_stats(self) -> dict[str, Any]:
        """Get overall recovery statistics."""
        total_files = len(self._file_trackers)
        total_failures = sum(len(t.failures) for t in self._file_trackers.values())
        total_attempts = sum(t.total_attempts for t in self._file_trackers.values())

        return {
            "total_files_tracked": total_files,
            "total_failures": total_failures,
            "total_attempts": total_attempts,
            "overall_failure_rate": total_failures / total_attempts if total_attempts > 0 else 0,
            "syntax_repair_mode": self._syntax_repair_mode,
            "current_turn_failures": self._current_turn_failures,
        }

    def reset_turn(self):
        """Reset per-turn state."""
        self._current_turn_failures = 0

    def reset(self, file_path: str = None):
        """Reset state for a file or everything."""
        if file_path:
            self._file_trackers.pop(file_path, None)
            self._recovery_suggestions.pop(file_path, None)
        else:
            self._file_trackers.clear()
            self._recent_failures.clear()
            self._recovery_suggestions.clear()
            self._syntax_repair_mode = False
            self._current_turn_failures = 0


class RecoveryHandler:
    """Handles recovery state machine integration with tool execution."""

    def __init__(self, max_failures: int = 2, max_attempts: int = 5):
        """Initialize the recovery handler."""
        self.state_machine = RecoveryStateMachine(
            max_failures_before_nudge=max_failures,
            max_attempts_per_file=max_attempts,
        )
        self.enabled = True

    def on_tool_failure(
        self,
        tool_name: str,
        error: str,
        file_path: str | None = None,
        arguments: dict[str, Any] = None,
    ) -> str | None:
        """Handle a tool failure and return recovery suggestion if available.

        Args:
            tool_name: Tool that failed
            error: Error message
            file_path: File being edited (if applicable)
            arguments: Tool arguments

        Returns:
            Recovery message to inject, or None
        """
        if not self.enabled:
            return None

        # Determine failure type from error
        failure_type = self._classify_failure(error, tool_name)

        # Record failure
        nudge = self.state_machine.record_failure(
            failure_type=failure_type,
            tool_name=tool_name,
            file_path=file_path,
            error_message=error,
            context={"arguments": arguments} if arguments else {},
        )

        if nudge:
            return nudge.message
        return None

    def on_tool_success(self, tool_name: str, file_path: str | None = None):
        """Handle a tool success."""
        if self.enabled:
            self.state_machine.record_success(tool_name, file_path)

    def _classify_failure(self, error: str, tool_name: str) -> FailureType:
        """Classify the failure type from error message."""
        error_lower = error.lower()

        if "no such file" in error_lower or "file not found" in error_lower:
            return FailureType.FILE_NOT_FOUND
        elif "permission denied" in error_lower:
            return FailureType.PERMISSION_DENIED
        elif "syntaxerror" in error_lower or "syntax error" in error_lower:
            return FailureType.SYNTAX_ERROR
        elif "importerror" in error_lower or "import error" in error_lower or "modulenotfounderror" in error_lower or "module not found" in error_lower:
            return FailureType.IMPORT_ERROR
        elif "could not find" in error_lower or "no match" in error_lower:
            return FailureType.EDIT_NO_MATCH
        elif "multiple matches" in error_lower:
            return FailureType.EDIT_MULTIPLE_MATCH
        elif "traceback" in error_lower or "exception" in error_lower:
            return FailureType.RUNTIME_ERROR
        else:
            return FailureType.RUNTIME_ERROR

    def get_recovery_message(self, file_path: str = None) -> str | None:
        """Get a recovery message to inject into the conversation."""
        if not file_path:
            # Get most recent nudge from any file
            for nudges in self.state_machine._recovery_suggestions.values():
                if nudges:
                    return nudges[-1].message
            return None

        nudges = self.state_machine.get_nudges_for_file(file_path)
        if nudges:
            return nudges[-1].message
        return None

    def should_block_edit(self, file_path: str) -> bool:
        """Check if an edit should be blocked."""
        return self.state_machine.should_block_file(file_path)

    def reset(self):
        """Reset recovery state."""
        self.state_machine.reset()


# Global instance
_recovery_handler: RecoveryHandler | None = None


def get_recovery_handler(max_failures: int = 2, max_attempts: int = 5) -> RecoveryHandler:
    """Get or create the global recovery handler."""
    global _recovery_handler
    if _recovery_handler is None:
        _recovery_handler = RecoveryHandler(max_failures=max_failures, max_attempts=max_attempts)
    return _recovery_handler


def reset_recovery_handler():
    """Reset the global recovery handler."""
    global _recovery_handler
    _recovery_handler = None
