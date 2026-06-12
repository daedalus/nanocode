"""Tests for the Edit Transactions system."""

import pytest
import tempfile
from pathlib import Path

from nanocode.edit_transaction import (
    EditTransaction,
    EditTransactionManager,
    EditOperation,
    EditOperationType,
    EditResult,
    calculate_content_hash,
    get_edit_transaction_manager,
    reset_edit_transaction_manager,
)


class TestEditOperationType:
    """Tests for EditOperationType enum."""

    def test_all_types_exist(self):
        """Test that all operation types are defined."""
        assert EditOperationType.REPLACE_TEXT_ONCE
        assert EditOperationType.REPLACE_TEXT_ALL
        assert EditOperationType.INSERT_BEFORE
        assert EditOperationType.INSERT_AFTER
        assert EditOperationType.DELETE_LINES
        assert EditOperationType.MOVE_LINES


class TestEditOperation:
    """Tests for EditOperation dataclass."""

    def test_operation_creation(self):
        """Test creating an operation."""
        op = EditOperation(
            operation_type=EditOperationType.REPLACE_TEXT_ONCE,
            old_text="hello",
            new_text="world",
        )
        assert op.operation_type == EditOperationType.REPLACE_TEXT_ONCE
        assert op.old_text == "hello"

    def test_operation_to_dict(self):
        """Test converting operation to dict."""
        op = EditOperation(
            operation_type=EditOperationType.DELETE_LINES,
            start_line=1,
            end_line=5,
        )
        d = op.to_dict()
        assert d["operation_type"] == "delete_lines"
        assert d["start_line"] == 1


class TestEditTransaction:
    """Tests for EditTransaction."""

    def test_init(self):
        """Test initialization."""
        tx = EditTransaction()
        assert len(tx.operations) == 0

    def test_add_operation(self):
        """Test adding an operation."""
        tx = EditTransaction()
        op = EditOperation(operation_type=EditOperationType.REPLACE_TEXT_ONCE)
        tx.add_operation(op)
        assert len(tx.operations) == 1

    def test_replace_text_once(self):
        """Test replace_text_once operation."""
        tx = EditTransaction()
        tx.replace_text_once("hello", "world")
        assert len(tx.operations) == 1
        assert tx.operations[0].operation_type == EditOperationType.REPLACE_TEXT_ONCE

    def test_replace_text_all(self):
        """Test replace_text_all operation."""
        tx = EditTransaction()
        tx.replace_text_all("a", "b")
        assert tx.operations[0].operation_type == EditOperationType.REPLACE_TEXT_ALL

    def test_insert_before(self):
        """Test insert_before operation."""
        tx = EditTransaction()
        tx.insert_before("target", "inserted")
        assert tx.operations[0].operation_type == EditOperationType.INSERT_BEFORE

    def test_insert_after(self):
        """Test insert_after operation."""
        tx = EditTransaction()
        tx.insert_after("target", "inserted")
        assert tx.operations[0].operation_type == EditOperationType.INSERT_AFTER

    def test_delete_lines(self):
        """Test delete_lines operation."""
        tx = EditTransaction()
        tx.delete_lines(1, 5)
        assert tx.operations[0].operation_type == EditOperationType.DELETE_LINES

    def test_move_lines(self):
        """Test move_lines operation."""
        tx = EditTransaction()
        tx.move_lines(1, 5, 10)
        assert tx.operations[0].operation_type == EditOperationType.MOVE_LINES

    def test_execute_replace_text_once(self):
        """Test executing replace_text_once."""
        tx = EditTransaction()
        tx.replace_text_once("hello", "world")

        result = tx.execute("hello world hello")
        assert result.success is True
        assert "world" in "\n".join(["world world hello"])

    def test_execute_replace_text_all(self):
        """Test executing replace_text_all."""
        tx = EditTransaction()
        tx.replace_text_all("hello", "world")

        result = tx.execute("hello world hello")
        assert result.success is True
        assert result.operations_applied == 1

    def test_execute_insert_before(self):
        """Test executing insert_before."""
        tx = EditTransaction()
        tx.insert_before("world", "hello")

        result = tx.execute("hello world")
        assert result.success is True

    def test_execute_insert_after(self):
        """Test executing insert_after."""
        tx = EditTransaction()
        tx.insert_after("hello", "world")

        result = tx.execute("hello world")
        assert result.success is True

    def test_execute_delete_lines(self):
        """Test executing delete_lines."""
        tx = EditTransaction()
        tx.delete_lines(2, 3)

        result = tx.execute("line1\nline2\nline3\nline4")
        assert result.success is True
        assert result.operations_applied == 1

    def test_execute_move_lines(self):
        """Test executing move_lines."""
        tx = EditTransaction()
        tx.move_lines(1, 2, 4)

        result = tx.execute("line1\nline2\nline3\nline4")
        assert result.success is True

    def test_execute_with_content_hash(self):
        """Test executing with content hash verification."""
        content = "hello world"
        content_hash = calculate_content_hash(content)

        tx = EditTransaction()
        tx.replace_text_once("hello", "world", content_hash=content_hash)

        result = tx.execute(content)
        assert result.success is True

    def test_execute_with_wrong_hash(self):
        """Test executing with wrong content hash."""
        tx = EditTransaction()
        tx.replace_text_once("hello", "world", content_hash="wrong_hash")

        result = tx.execute("hello world")
        assert result.success is False
        assert "hash mismatch" in result.error.lower()

    def test_execute_multiple_operations(self):
        """Test executing multiple operations."""
        tx = EditTransaction()
        tx.replace_text_once("hello", "world")
        tx.delete_lines(1, 1)

        result = tx.execute("hello\nworld")
        assert result.success is True
        assert result.operations_applied == 2

    def test_chaining(self):
        """Test operation chaining."""
        tx = EditTransaction()
        result = (
            tx.replace_text_once("a", "b")
            .replace_text_all("c", "d")
            .insert_before("e", "f")
        )
        assert len(tx.operations) == 3


class TestCalculateContentHash:
    """Tests for calculate_content_hash."""

    def test_hash_calculation(self):
        """Test hash calculation."""
        h = calculate_content_hash("hello world")
        assert len(h) == 64  # SHA-256 hex digest

    def test_hash_deterministic(self):
        """Test hash is deterministic."""
        h1 = calculate_content_hash("test")
        h2 = calculate_content_hash("test")
        assert h1 == h2

    def test_hash_different_for_different_content(self):
        """Test different content produces different hashes."""
        h1 = calculate_content_hash("hello")
        h2 = calculate_content_hash("world")
        assert h1 != h2


class TestEditTransactionManager:
    """Tests for EditTransactionManager."""

    def test_init(self):
        """Test initialization."""
        manager = EditTransactionManager()
        assert len(manager._file_hashes) == 0

    def test_file_hash_cache(self):
        """Test file hash caching."""
        manager = EditTransactionManager()
        manager.set_file_hash("test.py", "abc123")
        assert manager.get_file_hash("test.py") == "abc123"

    def test_clear_cache(self):
        """Test clearing cache."""
        manager = EditTransactionManager()
        manager.set_file_hash("test.py", "abc123")
        manager.clear_cache()
        assert manager.get_file_hash("test.py") is None

    def test_clear_cache_specific(self):
        """Test clearing specific file cache."""
        manager = EditTransactionManager()
        manager.set_file_hash("test.py", "abc123")
        manager.set_file_hash("other.py", "def456")
        manager.clear_cache("test.py")
        assert manager.get_file_hash("test.py") is None
        assert manager.get_file_hash("other.py") == "def456"

    def test_execute_file_transaction(self, tmp_path):
        """Test executing a transaction on a file."""
        manager = EditTransactionManager()
        test_file = tmp_path / "test.py"
        test_file.write_text("hello world")

        tx = EditTransaction()
        tx.replace_text_once("hello", "world")

        result = manager.execute_file_transaction(str(test_file), tx)
        assert result.success is True

        # Verify file was updated
        content = test_file.read_text()
        assert "world" in content


class TestGlobalInstance:
    """Tests for global instance."""

    def test_get_edit_transaction_manager_singleton(self):
        """Test global instance is singleton."""
        reset_edit_transaction_manager()
        m1 = get_edit_transaction_manager()
        m2 = get_edit_transaction_manager()
        assert m1 is m2

    def test_reset_edit_transaction_manager(self):
        """Test resetting global instance."""
        m1 = get_edit_transaction_manager()
        reset_edit_transaction_manager()
        m2 = get_edit_transaction_manager()
        assert m1 is not m2
