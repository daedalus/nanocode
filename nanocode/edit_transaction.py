"""Edit Transactions - Atomic multi-operation edits with content-hash safety.

Based on Aura's fs_edit_transaction.py:
- Atomic multi-operation edits
- Content-hash race-condition safety
- Operations: replace_text_once, replace_text_all, insert_before, insert_after, delete_lines, move_lines
"""

import hashlib
import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class EditOperationType(str, Enum):
    """Types of edit operations."""

    REPLACE_TEXT_ONCE = "replace_text_once"
    REPLACE_TEXT_ALL = "replace_text_all"
    INSERT_BEFORE = "insert_before"
    INSERT_AFTER = "insert_after"
    DELETE_LINES = "delete_lines"
    MOVE_LINES = "move_lines"


@dataclass
class EditOperation:
    """A single edit operation."""

    operation_type: EditOperationType
    old_text: Optional[str] = None
    new_text: Optional[str] = None
    line_number: Optional[int] = None
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    target_line: Optional[int] = None
    content_hash: Optional[str] = None  # Hash of file content before edit

    def to_dict(self) -> dict:
        return {
            "operation_type": self.operation_type.value,
            "old_text": self.old_text,
            "new_text": self.new_text,
            "line_number": self.line_number,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "target_line": self.target_line,
            "content_hash": self.content_hash,
        }


@dataclass
class EditResult:
    """Result of an edit operation."""

    success: bool
    operations_applied: int = 0
    error: Optional[str] = None
    old_content_hash: Optional[str] = None
    new_content_hash: Optional[str] = None
    changes: List[Dict[str, Any]] = field(default_factory=list)


def calculate_content_hash(content: str) -> str:
    """Calculate SHA-256 hash of content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class EditTransaction:
    """Atomic multi-operation edit transaction.

    Based on Aura's approach:
    - Multiple operations applied atomically
    - Content-hash verification for race-condition safety
    - Rollback on failure
    """

    def __init__(self):
        self.operations: List[EditOperation] = []
        self._file_hashes: Dict[str, str] = {}

    def add_operation(self, operation: EditOperation) -> "EditTransaction":
        """Add an operation to the transaction.

        Args:
            operation: Edit operation to add

        Returns:
            Self for chaining
        """
        self.operations.append(operation)
        return self

    def replace_text_once(
        self,
        old_text: str,
        new_text: str,
        content_hash: Optional[str] = None,
    ) -> "EditTransaction":
        """Add a replace_text_once operation.

        Args:
            old_text: Text to replace (first occurrence)
            new_text: Replacement text
            content_hash: Expected content hash for safety

        Returns:
            Self for chaining
        """
        self.operations.append(
            EditOperation(
                operation_type=EditOperationType.REPLACE_TEXT_ONCE,
                old_text=old_text,
                new_text=new_text,
                content_hash=content_hash,
            )
        )
        return self

    def replace_text_all(
        self,
        old_text: str,
        new_text: str,
        content_hash: Optional[str] = None,
    ) -> "EditTransaction":
        """Add a replace_text_all operation.

        Args:
            old_text: Text to replace (all occurrences)
            new_text: Replacement text
            content_hash: Expected content hash for safety

        Returns:
            Self for chaining
        """
        self.operations.append(
            EditOperation(
                operation_type=EditOperationType.REPLACE_TEXT_ALL,
                old_text=old_text,
                new_text=new_text,
                content_hash=content_hash,
            )
        )
        return self

    def insert_before(
        self,
        target_text: str,
        insert_text: str,
        content_hash: Optional[str] = None,
    ) -> "EditTransaction":
        """Add an insert_before operation.

        Args:
            target_text: Text to insert before
            insert_text: Text to insert
            content_hash: Expected content hash for safety

        Returns:
            Self for chaining
        """
        self.operations.append(
            EditOperation(
                operation_type=EditOperationType.INSERT_BEFORE,
                old_text=target_text,
                new_text=insert_text,
                content_hash=content_hash,
            )
        )
        return self

    def insert_after(
        self,
        target_text: str,
        insert_text: str,
        content_hash: Optional[str] = None,
    ) -> "EditTransaction":
        """Add an insert_after operation.

        Args:
            target_text: Text to insert after
            insert_text: Text to insert
            content_hash: Expected content hash for safety

        Returns:
            Self for chaining
        """
        self.operations.append(
            EditOperation(
                operation_type=EditOperationType.INSERT_AFTER,
                old_text=target_text,
                new_text=insert_text,
                content_hash=content_hash,
            )
        )
        return self

    def delete_lines(
        self,
        start_line: int,
        end_line: int,
        content_hash: Optional[str] = None,
    ) -> "EditTransaction":
        """Add a delete_lines operation.

        Args:
            start_line: Start line (1-indexed)
            end_line: End line (1-indexed, inclusive)
            content_hash: Expected content hash for safety

        Returns:
            Self for chaining
        """
        self.operations.append(
            EditOperation(
                operation_type=EditOperationType.DELETE_LINES,
                start_line=start_line,
                end_line=end_line,
                content_hash=content_hash,
            )
        )
        return self

    def move_lines(
        self,
        start_line: int,
        end_line: int,
        target_line: int,
        content_hash: Optional[str] = None,
    ) -> "EditTransaction":
        """Add a move_lines operation.

        Args:
            start_line: Start line (1-indexed)
            end_line: End line (1-indexed, inclusive)
            target_line: Target line to move to (1-indexed)
            content_hash: Expected content hash for safety

        Returns:
            Self for chaining
        """
        self.operations.append(
            EditOperation(
                operation_type=EditOperationType.MOVE_LINES,
                start_line=start_line,
                end_line=end_line,
                target_line=target_line,
                content_hash=content_hash,
            )
        )
        return self

    def execute(self, content: str) -> EditResult:
        """Execute all operations on the content.

        Args:
            content: File content to edit

        Returns:
            EditResult with success status and changes
        """
        old_hash = calculate_content_hash(content)
        lines = content.split("\n")
        changes = []

        # Verify content hashes
        for i, op in enumerate(self.operations):
            if op.content_hash and op.content_hash != old_hash:
                return EditResult(
                    success=False,
                    error=f"Content hash mismatch at operation {i}: expected {op.content_hash}, got {old_hash}",
                    old_content_hash=old_hash,
                )

        # Apply operations
        for i, op in enumerate(self.operations):
            try:
                result = self._apply_operation(lines, op)
                if result["success"]:
                    changes.append({
                        "operation": op.operation_type.value,
                        "details": result.get("details", ""),
                    })
                else:
                    return EditResult(
                        success=False,
                        operations_applied=i,
                        error=f"Operation {i} failed: {result.get('error', 'unknown')}",
                        old_content_hash=old_hash,
                        changes=changes,
                    )
            except Exception as e:
                return EditResult(
                    success=False,
                    operations_applied=i,
                    error=f"Operation {i} exception: {e}",
                    old_content_hash=old_hash,
                    changes=changes,
                )

        new_content = "\n".join(lines)
        new_hash = calculate_content_hash(new_content)

        return EditResult(
            success=True,
            operations_applied=len(self.operations),
            old_content_hash=old_hash,
            new_content_hash=new_hash,
            changes=changes,
        )

    def _apply_operation(
        self, lines: List[str], op: EditOperation
    ) -> Dict[str, Any]:
        """Apply a single operation to the lines list."""
        if op.operation_type == EditOperationType.REPLACE_TEXT_ONCE:
            return self._replace_text_once(lines, op)
        elif op.operation_type == EditOperationType.REPLACE_TEXT_ALL:
            return self._replace_text_all(lines, op)
        elif op.operation_type == EditOperationType.INSERT_BEFORE:
            return self._insert_before(lines, op)
        elif op.operation_type == EditOperationType.INSERT_AFTER:
            return self._insert_after(lines, op)
        elif op.operation_type == EditOperationType.DELETE_LINES:
            return self._delete_lines(lines, op)
        elif op.operation_type == EditOperationType.MOVE_LINES:
            return self._move_lines(lines, op)
        else:
            return {"success": False, "error": f"Unknown operation: {op.operation_type}"}

    def _replace_text_once(
        self, lines: List[str], op: EditOperation
    ) -> Dict[str, Any]:
        """Replace first occurrence of text."""
        content = "\n".join(lines)
        if op.old_text not in content:
            return {"success": False, "error": f"Text not found: {op.old_text[:50]}..."}

        new_content = content.replace(op.old_text, op.new_text, 1)
        lines.clear()
        lines.extend(new_content.split("\n"))
        return {"success": True, "details": f"Replaced first occurrence"}

    def _replace_text_all(
        self, lines: List[str], op: EditOperation
    ) -> Dict[str, Any]:
        """Replace all occurrences of text."""
        content = "\n".join(lines)
        if op.old_text not in content:
            return {"success": False, "error": f"Text not found: {op.old_text[:50]}..."}

        count = content.count(op.old_text)
        new_content = content.replace(op.old_text, op.new_text)
        lines.clear()
        lines.extend(new_content.split("\n"))
        return {"success": True, "details": f"Replaced {count} occurrences"}

    def _insert_before(
        self, lines: List[str], op: EditOperation
    ) -> Dict[str, Any]:
        """Insert text before target."""
        content = "\n".join(lines)
        if op.old_text not in content:
            return {"success": False, "error": f"Target not found: {op.old_text[:50]}..."}

        new_content = content.replace(op.old_text, f"{op.new_text}\n{op.old_text}")
        lines.clear()
        lines.extend(new_content.split("\n"))
        return {"success": True, "details": "Inserted text before target"}

    def _insert_after(
        self, lines: List[str], op: EditOperation
    ) -> Dict[str, Any]:
        """Insert text after target."""
        content = "\n".join(lines)
        if op.old_text not in content:
            return {"success": False, "error": f"Target not found: {op.old_text[:50]}..."}

        new_content = content.replace(op.old_text, f"{op.old_text}\n{op.new_text}")
        lines.clear()
        lines.extend(new_content.split("\n"))
        return {"success": True, "details": "Inserted text after target"}

    def _delete_lines(
        self, lines: List[str], op: EditOperation
    ) -> Dict[str, Any]:
        """Delete lines by line number."""
        if not op.start_line or not op.end_line:
            return {"success": False, "error": "start_line and end_line required"}

        start = op.start_line - 1  # Convert to 0-indexed
        end = op.end_line  # end is inclusive, so don't subtract

        if start < 0 or end > len(lines):
            return {"success": False, "error": f"Line range out of bounds: {op.start_line}-{op.end_line}"}

        deleted = end - start
        del lines[start:end]
        return {"success": True, "details": f"Deleted {deleted} lines"}

    def _move_lines(
        self, lines: List[str], op: EditOperation
    ) -> Dict[str, Any]:
        """Move lines to a new position."""
        if not op.start_line or not op.end_line or not op.target_line:
            return {"success": False, "error": "start_line, end_line, and target_line required"}

        start = op.start_line - 1
        end = op.end_line
        target = op.target_line - 1

        if start < 0 or end > len(lines) or target < 0 or target > len(lines):
            return {"success": False, "error": "Line numbers out of bounds"}

        # Extract lines to move
        moved_lines = lines[start:end]
        del lines[start:end]

        # Adjust target if needed
        if target > start:
            target -= len(moved_lines)

        # Insert at target
        for i, line in enumerate(moved_lines):
            lines.insert(target + i, line)

        return {"success": True, "details": f"Moved {len(moved_lines)} lines"}


class EditTransactionManager:
    """Manages edit transactions for files."""

    def __init__(self):
        self._file_hashes: Dict[str, str] = {}

    def get_file_hash(self, file_path: str) -> Optional[str]:
        """Get cached content hash for a file."""
        return self._file_hashes.get(file_path)

    def set_file_hash(self, file_path: str, content_hash: str):
        """Cache content hash for a file."""
        self._file_hashes[file_path] = content_hash

    def execute_file_transaction(
        self,
        file_path: str,
        transaction: EditTransaction,
    ) -> EditResult:
        """Execute a transaction on a file.

        Args:
            file_path: Path to file
            transaction: EditTransaction to execute

        Returns:
            EditResult
        """
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            result = transaction.execute(content)

            if result.success:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(content.replace("\n", "\n"))

                # Update cached hash
                if result.new_content_hash:
                    self._file_hashes[file_path] = result.new_content_hash

            return result

        except Exception as e:
            return EditResult(
                success=False,
                error=f"File error: {e}",
            )

    def clear_cache(self, file_path: Optional[str] = None):
        """Clear cached hashes."""
        if file_path:
            self._file_hashes.pop(file_path, None)
        else:
            self._file_hashes.clear()


# Global instance
_edit_transaction_manager: Optional[EditTransactionManager] = None


def get_edit_transaction_manager() -> EditTransactionManager:
    """Get or create the global edit transaction manager."""
    global _edit_transaction_manager
    if _edit_transaction_manager is None:
        _edit_transaction_manager = EditTransactionManager()
    return _edit_transaction_manager


def reset_edit_transaction_manager():
    """Reset the global edit transaction manager."""
    global _edit_transaction_manager
    _edit_transaction_manager = None
