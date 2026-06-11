"""Context Reconstruction - Checkpoint-based context rebuilding.

Based on MiMo-Code's checkpoint system:
- Save session state to checkpoint files
- Rebuild context from checkpoint + memory when approaching limits
- Budgeted injection with importance ranking
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class CheckpointMessage:
    """A message in the checkpoint."""

    role: str
    content: str
    timestamp: float
    tokens: int = 0
    importance: float = 0.5
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Checkpoint:
    """Session checkpoint for context reconstruction."""

    session_id: str
    messages: List[CheckpointMessage] = field(default_factory=list)
    summary: str = ""
    task_progress: Dict[str, str] = field(default_factory=dict)
    memory_highlights: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    token_count: int = 0

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "messages": [
                {
                    "role": m.role,
                    "content": m.content,
                    "timestamp": m.timestamp,
                    "tokens": m.tokens,
                    "importance": m.importance,
                    "metadata": m.metadata,
                }
                for m in self.messages
            ],
            "summary": self.summary,
            "task_progress": self.task_progress,
            "memory_highlights": self.memory_highlights,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "token_count": self.token_count,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Checkpoint":
        messages = [
            CheckpointMessage(
                role=m["role"],
                content=m["content"],
                timestamp=m["timestamp"],
                tokens=m.get("tokens", 0),
                importance=m.get("importance", 0.5),
                metadata=m.get("metadata", {}),
            )
            for m in data.get("messages", [])
        ]
        return cls(
            session_id=data["session_id"],
            messages=messages,
            summary=data.get("summary", ""),
            task_progress=data.get("task_progress", {}),
            memory_highlights=data.get("memory_highlights", []),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            token_count=data.get("token_count", 0),
        )


class CheckpointManager:
    """Manages session checkpoints for context reconstruction."""

    def __init__(self, storage_dir: Optional[str] = None):
        """Initialize the checkpoint manager.

        Args:
            storage_dir: Directory to store checkpoints
        """
        if storage_dir is None:
            xdg_data = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
            storage_dir = str(Path(xdg_data) / "nanocode" / "checkpoints")
        self.storage_dir = storage_dir
        os.makedirs(storage_dir, exist_ok=True)

    def _checkpoint_path(self, session_id: str) -> str:
        """Get path to checkpoint file."""
        return os.path.join(self.storage_dir, f"{session_id}.json")

    def save_checkpoint(self, checkpoint: Checkpoint) -> bool:
        """Save a checkpoint to disk.

        Args:
            checkpoint: Checkpoint to save

        Returns:
            True if saved successfully
        """
        try:
            path = self._checkpoint_path(checkpoint.session_id)
            checkpoint.updated_at = time.time()
            with open(path, "w") as f:
                json.dump(checkpoint.to_dict(), f, indent=2)
            logger.debug(f"Checkpoint saved for session {checkpoint.session_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to save checkpoint: {e}")
            return False

    def load_checkpoint(self, session_id: str) -> Optional[Checkpoint]:
        """Load a checkpoint from disk.

        Args:
            session_id: Session identifier

        Returns:
            Checkpoint if found, None otherwise
        """
        try:
            path = self._checkpoint_path(session_id)
            if not os.path.exists(path):
                return None
            with open(path) as f:
                data = json.load(f)
            return Checkpoint.from_dict(data)
        except Exception as e:
            logger.error(f"Failed to load checkpoint: {e}")
            return None

    def delete_checkpoint(self, session_id: str) -> bool:
        """Delete a checkpoint.

        Args:
            session_id: Session identifier

        Returns:
            True if deleted successfully
        """
        try:
            path = self._checkpoint_path(session_id)
            if os.path.exists(path):
                os.remove(path)
                logger.debug(f"Checkpoint deleted for session {session_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete checkpoint: {e}")
            return False

    def list_checkpoints(self) -> List[str]:
        """List all checkpoint session IDs."""
        try:
            files = os.listdir(self.storage_dir)
            return [f.replace(".json", "") for f in files if f.endswith(".json")]
        except Exception:
            return []


class ContextReconstructor:
    """Rebuilds context from checkpoints and memory when approaching limits.

    Based on MiMo-Code's approach:
    - When context approaches limits, rebuild from checkpoint + memory
    - Budgeted injection with importance ranking
    - Preserves recent messages for continuity
    """

    def __init__(
        self,
        checkpoint_manager: Optional[CheckpointManager] = None,
        max_context_tokens: int = 8000,
        preserve_recent_count: int = 6,
        importance_threshold: float = 0.3,
    ):
        """Initialize the context reconstructor.

        Args:
            checkpoint_manager: CheckpointManager instance
            max_context_tokens: Maximum tokens for context
            preserve_recent_count: Number of recent messages to always keep
            importance_threshold: Minimum importance for older messages
        """
        self.checkpoint_manager = checkpoint_manager or CheckpointManager()
        self.max_context_tokens = max_context_tokens
        self.preserve_recent_count = preserve_recent_count
        self.importance_threshold = importance_threshold

    def should_reconstruct(self, current_tokens: int, threshold: float = 0.85) -> bool:
        """Check if context reconstruction is needed.

        Args:
            current_tokens: Current token count
            threshold: Threshold to trigger reconstruction (0-1)

        Returns:
            True if reconstruction is needed
        """
        return current_tokens >= self.max_context_tokens * threshold

    def create_checkpoint_from_messages(
        self,
        session_id: str,
        messages: List[Dict[str, Any]],
        summary: str = "",
    ) -> Checkpoint:
        """Create a checkpoint from current messages.

        Args:
            session_id: Session identifier
            messages: Current conversation messages
            summary: Optional summary of the session

        Returns:
            Checkpoint object
        """
        checkpoint_messages = []
        total_tokens = 0

        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, list):
                # Handle multi-part content
                content = " ".join(
                    p.get("text", "") for p in content if isinstance(p, dict)
                )

            tokens = self._estimate_tokens(content)
            importance = self._calculate_importance(msg.get("role", ""), content)

            checkpoint_messages.append(
                CheckpointMessage(
                    role=msg.get("role", "unknown"),
                    content=content,
                    timestamp=msg.get("timestamp", time.time()),
                    tokens=tokens,
                    importance=importance,
                )
            )
            total_tokens += tokens

        checkpoint = Checkpoint(
            session_id=session_id,
            messages=checkpoint_messages,
            summary=summary,
            token_count=total_tokens,
        )

        return checkpoint

    def reconstruct_context(
        self,
        session_id: str,
        current_messages: List[Dict[str, Any]],
        memory_highlights: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Reconstruct context from checkpoint and current messages.

        Args:
            session_id: Session identifier
            current_messages: Current messages to preserve
            memory_highlights: Important memory items to include

        Returns:
            Reconstructed context messages
        """
        # Load checkpoint
        checkpoint = self.checkpoint_manager.load_checkpoint(session_id)

        if not checkpoint:
            logger.debug(f"No checkpoint found for session {session_id}")
            return current_messages

        # Build reconstructed context
        reconstructed = []

        # 1. Add system summary if available
        if checkpoint.summary:
            reconstructed.append({
                "role": "system",
                "content": f"[Session Summary]\n{checkpoint.summary}",
            })

        # 2. Add memory highlights
        if memory_highlights:
            memory_text = "\n".join(f"- {h}" for h in memory_highlights)
            reconstructed.append({
                "role": "system",
                "content": f"[Important Context]\n{memory_text}",
            })

        # 3. Add task progress if available
        if checkpoint.task_progress:
            progress_text = "\n".join(
                f"- {task}: {status}"
                for task, status in checkpoint.task_progress.items()
            )
            reconstructed.append({
                "role": "system",
                "content": f"[Task Progress]\n{progress_text}",
            })

        # 4. Add important older messages from checkpoint
        budget = self.max_context_tokens // 2  # Half budget for older context
        important_msgs = sorted(
            checkpoint.messages,
            key=lambda m: m.importance,
            reverse=True,
        )

        added_tokens = 0
        for msg in important_msgs:
            if added_tokens + msg.tokens > budget:
                break
            if msg.importance >= self.importance_threshold:
                reconstructed.append({
                    "role": msg.role,
                    "content": msg.content,
                })
                added_tokens += msg.tokens

        # 5. Add current messages (recent ones)
        for msg in current_messages[-self.preserve_recent_count:]:
            reconstructed.append(msg)

        logger.info(
            f"Context reconstructed: {len(reconstructed)} messages, "
            f"added {added_tokens} tokens from checkpoint"
        )

        return reconstructed

    def save_session_checkpoint(
        self,
        session_id: str,
        messages: List[Dict[str, Any]],
        summary: str = "",
        task_progress: Optional[Dict[str, str]] = None,
    ) -> bool:
        """Save a session checkpoint.

        Args:
            session_id: Session identifier
            messages: Current messages
            summary: Session summary
            task_progress: Task progress dict

        Returns:
            True if saved successfully
        """
        checkpoint = self.create_checkpoint_from_messages(session_id, messages, summary)
        if task_progress:
            checkpoint.task_progress = task_progress
        return self.checkpoint_manager.save_checkpoint(checkpoint)

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count for text."""
        if not text:
            return 0
        # Simple approximation: ~4 chars per token
        return max(1, len(text) // 4)

    def _calculate_importance(self, role: str, content: str) -> float:
        """Calculate message importance score."""
        base = 0.5

        if role == "system":
            return 1.0
        elif role == "user":
            base = 0.7
        elif role == "assistant":
            base = 0.6
        elif role == "tool":
            base = 0.4

        # Boost importance for certain patterns
        content_lower = content.lower()
        if "error" in content_lower or "failed" in content_lower:
            base += 0.1
        if "important" in content_lower or "note" in content_lower:
            base += 0.1
        if len(content) > 1000:
            base -= 0.1  # Long messages slightly less important

        return min(1.0, max(0.0, base))

    def get_stats(self) -> dict:
        """Get reconstruction statistics."""
        checkpoints = self.checkpoint_manager.list_checkpoints()
        return {
            "total_checkpoints": len(checkpoints),
            "max_context_tokens": self.max_context_tokens,
            "preserve_recent_count": self.preserve_recent_count,
            "importance_threshold": self.importance_threshold,
        }


# Global instances
_checkpoint_manager: Optional[CheckpointManager] = None
_context_reconstructor: Optional[ContextReconstructor] = None


def get_checkpoint_manager(storage_dir: Optional[str] = None) -> CheckpointManager:
    """Get or create the global checkpoint manager."""
    global _checkpoint_manager
    if _checkpoint_manager is None:
        _checkpoint_manager = CheckpointManager(storage_dir)
    return _checkpoint_manager


def get_context_reconstructor(
    max_context_tokens: int = 8000,
) -> ContextReconstructor:
    """Get or create the global context reconstructor."""
    global _context_reconstructor
    if _context_reconstructor is None:
        _context_reconstructor = ContextReconstructor(
            checkpoint_manager=get_checkpoint_manager(),
            max_context_tokens=max_context_tokens,
        )
    return _context_reconstructor


def reset_context_reconstruction():
    """Reset global instances."""
    global _checkpoint_manager, _context_reconstructor
    _checkpoint_manager = None
    _context_reconstructor = None
