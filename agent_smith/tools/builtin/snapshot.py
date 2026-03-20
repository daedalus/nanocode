"""Snapshot tools for capturing and reverting changes."""

from nanocode.tools import Tool, ToolResult
from nanocode.snapshot import SnapshotManager


class SnapshotTrackTool(Tool):
    """Tool for capturing current file state as a snapshot."""

    def __init__(self, snapshot_manager: SnapshotManager):
        super().__init__(
            name="snapshot",
            description="Capture current state of all files as a snapshot for potential revert",
            parameters={
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "Optional description for this snapshot",
                    },
                },
            },
        )
        self.snapshot_manager = snapshot_manager

    async def execute(self, description: str = None, **kwargs) -> ToolResult:
        """Capture current state as a snapshot."""
        try:
            snapshot_hash = await self.snapshot_manager.track()

            if snapshot_hash is None:
                return ToolResult(
                    success=False,
                    content=None,
                    error="Failed to create snapshot",
                )

            return ToolResult(
                success=True,
                content=f"Snapshot created: {snapshot_hash[:8]}",
                metadata={"snapshot_hash": snapshot_hash, "description": description},
            )
        except Exception as e:
            return ToolResult(success=False, content=None, error=str(e))


class SnapshotRevertTool(Tool):
    """Tool for reverting files to a previous snapshot."""

    def __init__(self, snapshot_manager: SnapshotManager):
        super().__init__(
            name="revert",
            description="Revert files to a previous snapshot state",
            parameters={
                "type": "object",
                "properties": {
                    "snapshot": {
                        "type": "string",
                        "description": "The snapshot hash to revert to (use 'latest' for most recent)",
                    },
                },
                "required": ["snapshot"],
            },
        )
        self.snapshot_manager = snapshot_manager

    async def execute(self, snapshot: str = None, **kwargs) -> ToolResult:
        """Revert files to a snapshot."""
        try:
            if not snapshot:
                return ToolResult(
                    success=False,
                    content=None,
                    error="Snapshot hash is required",
                )

            if snapshot == "latest":
                snapshots = await self.snapshot_manager.list_snapshots()
                if not snapshots:
                    return ToolResult(
                        success=False,
                        content=None,
                        error="No snapshots available",
                    )
                snapshot = snapshots[0]["hash"]

            success = await self.snapshot_manager.restore(snapshot)

            if success:
                return ToolResult(
                    success=True,
                    content=f"Reverted to snapshot: {snapshot[:8]}",
                    metadata={"snapshot_hash": snapshot},
                )
            else:
                return ToolResult(
                    success=False,
                    content=None,
                    error=f"Failed to revert to snapshot: {snapshot[:8]}",
                )
        except Exception as e:
            return ToolResult(success=False, content=None, error=str(e))


class SnapshotListTool(Tool):
    """Tool for listing available snapshots."""

    def __init__(self, snapshot_manager: SnapshotManager):
        super().__init__(
            name="snapshots",
            description="List all available snapshots",
            parameters={
                "type": "object",
                "properties": {},
            },
        )
        self.snapshot_manager = snapshot_manager

    async def execute(self, **kwargs) -> ToolResult:
        """List available snapshots."""
        try:
            snapshots = await self.snapshot_manager.list_snapshots()

            if not snapshots:
                return ToolResult(
                    success=True,
                    content="No snapshots available. Use the 'snapshot' tool to create one.",
                )

            lines = ["Available snapshots:"]
            for s in snapshots:
                lines.append(f"  - {s['hash'][:8]} ({s['timestamp']})")

            return ToolResult(success=True, content="\n".join(lines))
        except Exception as e:
            return ToolResult(success=False, content=None, error=str(e))


class SnapshotDiffTool(Tool):
    """Tool for showing what changed since a snapshot."""

    def __init__(self, snapshot_manager: SnapshotManager):
        super().__init__(
            name="snapshot_diff",
            description="Show files that have changed since a snapshot",
            parameters={
                "type": "object",
                "properties": {
                    "snapshot": {
                        "type": "string",
                        "description": "The snapshot hash to compare against (use 'latest' for most recent)",
                    },
                },
                "required": ["snapshot"],
            },
        )
        self.snapshot_manager = snapshot_manager

    async def execute(self, snapshot: str = None, **kwargs) -> ToolResult:
        """Show what changed since a snapshot."""
        try:
            if not snapshot:
                return ToolResult(
                    success=False,
                    content=None,
                    error="Snapshot hash is required",
                )

            if snapshot == "latest":
                snapshots = await self.snapshot_manager.list_snapshots()
                if not snapshots:
                    return ToolResult(
                        success=False,
                        content=None,
                        error="No snapshots available",
                    )
                snapshot = snapshots[0]["hash"]

            patch = await self.snapshot_manager.patch(snapshot)

            if not patch.files:
                return ToolResult(
                    success=True,
                    content="No changes since this snapshot",
                )

            lines = [f"Changed files since {snapshot[:8]}:"]
            for f in patch.files:
                lines.append(f"  - {f}")

            return ToolResult(
                success=True,
                content="\n".join(lines),
                metadata={"file_count": len(patch.files)},
            )
        except Exception as e:
            return ToolResult(success=False, content=None, error=str(e))


def register_snapshot_tools(registry, snapshot_manager: SnapshotManager):
    """Register snapshot-related tools."""
    registry.register(SnapshotTrackTool(snapshot_manager))
    registry.register(SnapshotRevertTool(snapshot_manager))
    registry.register(SnapshotListTool(snapshot_manager))
    registry.register(SnapshotDiffTool(snapshot_manager))
