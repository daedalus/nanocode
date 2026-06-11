"""Tests for the Recovery State Machine."""

import pytest
from nanocode.recovery import (
    RecoveryStateMachine,
    RecoveryHandler,
    FailureType,
    RecoveryAction,
    FailureRecord,
    FileFailureTracker,
    get_recovery_handler,
    reset_recovery_handler,
)


class TestFailureType:
    """Tests for FailureType enum."""

    def test_failure_types_exist(self):
        """Test that all failure types are defined."""
        assert FailureType.EDIT_NO_MATCH
        assert FailureType.EDIT_MULTIPLE_MATCH
        assert FailureType.SYNTAX_ERROR
        assert FailureType.IMPORT_ERROR
        assert FailureType.RUNTIME_ERROR
        assert FailureType.FILE_NOT_FOUND
        assert FailureType.PERMISSION_DENIED
        assert FailureType.WRITE_FAILED


class TestRecoveryAction:
    """Tests for RecoveryAction enum."""

    def test_recovery_actions_exist(self):
        """Test that all recovery actions are defined."""
        assert RecoveryAction.RETRY_DIFFERENT
        assert RecoveryAction.USE_AST_EDIT
        assert RecoveryAction.CHECK_SYNTAX
        assert RecoveryAction.CHECK_IMPORTS
        assert RecoveryAction.READ_FILE_FIRST
        assert RecoveryAction.CHECK_PERMISSIONS
        assert RecoveryAction.SIMPLIFY_APPROACH
        assert RecoveryAction.STOP_AND_ASK


class TestFileFailureTracker:
    """Tests for FileFailureTracker."""

    def test_tracker_creation(self):
        """Test creating a tracker."""
        tracker = FileFailureTracker(file_path="/test/file.py")
        assert tracker.file_path == "/test/file.py"
        assert tracker.total_attempts == 0
        assert tracker.successful_edits == 0
        assert tracker.failure_rate == 0.0

    def test_failure_rate(self):
        """Test failure rate calculation."""
        tracker = FileFailureTracker(file_path="/test/file.py")
        tracker.total_attempts = 10
        tracker.failures = [None, None, None]  # 3 failures
        assert tracker.failure_rate == 0.3


class TestRecoveryStateMachine:
    """Tests for RecoveryStateMachine."""

    def test_init(self):
        """Test initialization."""
        sm = RecoveryStateMachine()
        assert sm.max_failures_before_nudge == 2
        assert sm.max_attempts_per_file == 5
        assert len(sm._file_trackers) == 0

    def test_record_failure_first_time(self):
        """Test recording first failure returns no nudge."""
        sm = RecoveryStateMachine(max_failures_before_nudge=2)
        nudge = sm.record_failure(
            failure_type=FailureType.EDIT_NO_MATCH,
            tool_name="edit",
            file_path="/test/file.py",
            error_message="no match found",
        )
        # First failure should return read first suggestion
        assert nudge is not None
        assert nudge.action == RecoveryAction.READ_FILE_FIRST

    def test_record_failure_triggers_nudge(self):
        """Test that consecutive failures trigger recovery nudge."""
        sm = RecoveryStateMachine(max_failures_before_nudge=2)

        # Record failures
        sm.record_failure(
            failure_type=FailureType.EDIT_NO_MATCH,
            tool_name="edit",
            file_path="/test/file.py",
            error_message="no match",
        )
        nudge = sm.record_failure(
            failure_type=FailureType.EDIT_NO_MATCH,
            tool_name="edit",
            file_path="/test/file.py",
            error_message="no match",
        )

        # Should suggest AST edit
        assert nudge is not None
        assert nudge.action == RecoveryAction.USE_AST_EDIT

    def test_record_failure_syntax_error(self):
        """Test syntax error triggers syntax repair mode."""
        sm = RecoveryStateMachine(max_failures_before_nudge=2)

        sm.record_failure(
            failure_type=FailureType.SYNTAX_ERROR,
            tool_name="edit",
            file_path="/test/file.py",
            error_message="SyntaxError: invalid syntax",
        )
        nudge = sm.record_failure(
            failure_type=FailureType.SYNTAX_ERROR,
            tool_name="edit",
            file_path="/test/file.py",
            error_message="SyntaxError: invalid syntax",
        )

        assert nudge is not None
        assert nudge.action == RecoveryAction.CHECK_SYNTAX
        assert sm.is_in_syntax_repair_mode()

    def test_record_success_clears_state(self):
        """Test that success clears failure state."""
        sm = RecoveryStateMachine(max_failures_before_nudge=2)

        sm.record_failure(
            failure_type=FailureType.EDIT_NO_MATCH,
            tool_name="edit",
            file_path="/test/file.py",
            error_message="no match",
        )
        sm.record_success("edit", "/test/file.py")

        assert sm._current_turn_failures == 0
        assert not sm.is_in_syntax_repair_mode()

    def test_max_attempts_blocks_file(self):
        """Test that max attempts blocks file."""
        sm = RecoveryStateMachine(max_attempts_per_file=3)

        for i in range(3):
            sm.record_failure(
                failure_type=FailureType.EDIT_NO_MATCH,
                tool_name="edit",
                file_path="/test/file.py",
                error_message="no match",
            )

        assert sm.should_block_file("/test/file.py")

    def test_get_nudges_for_file(self):
        """Test getting nudges for a specific file."""
        sm = RecoveryStateMachine(max_failures_before_nudge=2)

        sm.record_failure(
            failure_type=FailureType.EDIT_NO_MATCH,
            tool_name="edit",
            file_path="/test/file.py",
            error_message="no match",
        )
        sm.record_failure(
            failure_type=FailureType.EDIT_NO_MATCH,
            tool_name="edit",
            file_path="/test/file.py",
            error_message="no match",
        )

        nudges = sm.get_nudges_for_file("/test/file.py")
        assert len(nudges) > 0

    def test_clear_nudges(self):
        """Test clearing nudges."""
        sm = RecoveryStateMachine(max_failures_before_nudge=2)

        sm.record_failure(
            failure_type=FailureType.EDIT_NO_MATCH,
            tool_name="edit",
            file_path="/test/file.py",
            error_message="no match",
        )
        sm.record_failure(
            failure_type=FailureType.EDIT_NO_MATCH,
            tool_name="edit",
            file_path="/test/file.py",
            error_message="no match",
        )

        sm.clear_nudges("/test/file.py")
        nudges = sm.get_nudges_for_file("/test/file.py")
        assert len(nudges) == 0

    def test_get_file_stats(self):
        """Test getting file statistics."""
        sm = RecoveryStateMachine()
        sm.record_failure(
            failure_type=FailureType.EDIT_NO_MATCH,
            tool_name="edit",
            file_path="/test/file.py",
            error_message="no match",
        )

        stats = sm.get_file_stats("/test/file.py")
        assert stats is not None
        assert stats["total_attempts"] == 1
        assert stats["failures"] == 1

    def test_get_stats(self):
        """Test getting overall statistics."""
        sm = RecoveryStateMachine()
        sm.record_failure(
            failure_type=FailureType.EDIT_NO_MATCH,
            tool_name="edit",
            file_path="/test/file.py",
            error_message="no match",
        )

        stats = sm.get_stats()
        assert stats["total_files_tracked"] == 1
        assert stats["total_failures"] == 1

    def test_reset(self):
        """Test resetting state."""
        sm = RecoveryStateMachine()
        sm.record_failure(
            failure_type=FailureType.EDIT_NO_MATCH,
            tool_name="edit",
            file_path="/test/file.py",
            error_message="no match",
        )

        sm.reset()
        assert len(sm._file_trackers) == 0
        assert len(sm._recent_failures) == 0


class TestRecoveryHandler:
    """Tests for RecoveryHandler."""

    def test_init(self):
        """Test initialization."""
        handler = RecoveryHandler()
        assert handler.enabled is True
        assert handler.state_machine is not None

    def test_on_tool_failure(self):
        """Test handling tool failure."""
        handler = RecoveryHandler(max_failures=2)

        # First failure
        msg = handler.on_tool_failure(
            tool_name="edit",
            error="no match found",
            file_path="/test/file.py",
        )
        assert msg is not None
        assert "Read the file" in msg

    def test_on_tool_failure_syntax(self):
        """Test handling syntax failure."""
        handler = RecoveryHandler(max_failures=2)

        handler.on_tool_failure(
            tool_name="edit",
            error="SyntaxError: invalid syntax",
            file_path="/test/file.py",
        )
        msg = handler.on_tool_failure(
            tool_name="edit",
            error="SyntaxError: invalid syntax",
            file_path="/test/file.py",
        )
        assert msg is not None
        assert "Syntax" in msg

    def test_on_tool_success(self):
        """Test handling tool success."""
        handler = RecoveryHandler()
        handler.on_tool_failure(
            tool_name="edit",
            error="no match",
            file_path="/test/file.py",
        )
        handler.on_tool_success("edit", "/test/file.py")
        assert handler.state_machine._current_turn_failures == 0

    def test_classify_failure(self):
        """Test failure classification."""
        handler = RecoveryHandler()

        assert handler._classify_failure("no such file", "edit") == FailureType.FILE_NOT_FOUND
        assert handler._classify_failure("permission denied", "bash") == FailureType.PERMISSION_DENIED
        assert handler._classify_failure("SyntaxError: invalid syntax", "edit") == FailureType.SYNTAX_ERROR
        assert handler._classify_failure("ModuleNotFoundError: No module named 'foo'", "bash") == FailureType.IMPORT_ERROR
        assert handler._classify_failure("no match found", "edit") == FailureType.EDIT_NO_MATCH
        assert handler._classify_failure("Traceback (most recent call last)", "bash") == FailureType.RUNTIME_ERROR

    def test_should_block_edit(self):
        """Test edit blocking."""
        handler = RecoveryHandler(max_attempts=2)

        for _ in range(2):
            handler.on_tool_failure(
                tool_name="edit",
                error="no match",
                file_path="/test/file.py",
            )

        assert handler.should_block_edit("/test/file.py")

    def test_disabled_handler(self):
        """Test disabled handler returns None."""
        handler = RecoveryHandler()
        handler.enabled = False

        msg = handler.on_tool_failure(
            tool_name="edit",
            error="no match",
            file_path="/test/file.py",
        )
        assert msg is None


class TestGlobalHandler:
    """Tests for global handler."""

    def test_get_recovery_handler_singleton(self):
        """Test global handler is singleton."""
        reset_recovery_handler()
        h1 = get_recovery_handler()
        h2 = get_recovery_handler()
        assert h1 is h2

    def test_reset_recovery_handler(self):
        """Test resetting global handler."""
        h1 = get_recovery_handler()
        reset_recovery_handler()
        h2 = get_recovery_handler()
        assert h1 is not h2
