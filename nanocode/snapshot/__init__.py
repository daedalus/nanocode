"""Snapshot module - git-based workspace state tracking."""

from nanocode.snapshot.git import GitSnapshotManager

def create_snapshot_manager(worktree: str, session_id: str) -> GitSnapshotManager:
    """Create a snapshot manager for a session.

    Args:
        worktree: Path to the workspace
        session_id: Session ID to namespace snapshots

    Returns:
        GitSnapshotManager instance
    """
    return GitSnapshotManager(worktree, snapshot_dir=None, session_id=session_id)


__all__ = ["GitSnapshotManager", "create_snapshot_manager"]
