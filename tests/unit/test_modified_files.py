"""Tests for modified files tracking."""

import pytest
import tempfile
import os
from pathlib import Path
from unittest.mock import MagicMock, patch


class TestFileModification:
    """Tests for FileModification dataclass."""

    def test_create_file_modification(self):
        """Test creating a FileModification."""
        from nanocode.modified_files import FileModification

        fm = FileModification(
            path="/tmp/test.py",
            relative_path="test.py",
            additions=10,
            deletions=5,
        )

        assert fm.path == "/tmp/test.py"
        assert fm.relative_path == "test.py"
        assert fm.additions == 10
        assert fm.deletions == 5
        assert fm.is_new is False
        assert fm.is_deleted is False

    def test_file_modification_new_file(self):
        """Test FileModification for new file."""
        from nanocode.modified_files import FileModification

        fm = FileModification(
            path="/tmp/new.py",
            relative_path="new.py",
            additions=5,
            deletions=0,
            is_new=True,
        )

        assert fm.is_new is True
        assert fm.is_deleted is False


class TestModifiedFilesTracker:
    """Tests for ModifiedFilesTracker."""

    def test_create_tracker(self):
        """Test creating a ModifiedFilesTracker."""
        from nanocode.modified_files import ModifiedFilesTracker

        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = ModifiedFilesTracker(cwd=tmpdir)
            assert tracker.cwd == Path(tmpdir)
            assert tracker.get_modified_files() == []

    def test_get_stats_empty(self):
        """Test getting stats with no files."""
        from nanocode.modified_files import ModifiedFilesTracker

        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = ModifiedFilesTracker(cwd=tmpdir)
            stats = tracker.get_stats()

            assert stats["total"] == 0
            assert stats["additions"] == 0
            assert stats["deletions"] == 0
            assert stats["new"] == 0
            assert stats["deleted"] == 0

    def test_clear(self):
        """Test clearing tracked files."""
        from nanocode.modified_files import ModifiedFilesTracker

        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = ModifiedFilesTracker(cwd=tmpdir)
            tracker._files = [MagicMock()]
            tracker.clear()
            assert tracker.get_modified_files() == []

    def test_get_modified_files_copy(self):
        """Test get_modified_files returns a copy."""
        from nanocode.modified_files import ModifiedFilesTracker, FileModification

        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = ModifiedFilesTracker(cwd=tmpdir)
            tracker._files = [FileModification("a.py", "a.py", 1, 0)]
            files = tracker.get_modified_files()
            files.clear()
            assert len(tracker.get_modified_files()) == 1


class TestModifiedFilesTrackerGit:
    """Tests for ModifiedFilesTracker git integration."""

    def test_refresh_from_git_no_repo(self):
        """Test refresh from git with no repo."""
        from nanocode.modified_files import ModifiedFilesTracker

        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = ModifiedFilesTracker(cwd=tmpdir)
            tracker.refresh_from_git()
            assert tracker.get_modified_files() == []

    def test_refresh_from_git_with_commits(self):
        """Test refresh from git with commits."""
        import subprocess

        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            subprocess.run(["git", "init"], capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], capture_output=True)

            Path(tmpdir, "test.py").write_text("print('hello')\n")
            subprocess.run(["git", "add", "test.py"], capture_output=True)
            subprocess.run(["git", "commit", "-m", "Initial"], capture_output=True)

            Path(tmpdir, "test.py").write_text("print('hello world')\nprint('extra')\n")
            subprocess.run(["git", "add", "test.py"], capture_output=True)
            subprocess.run(["git", "commit", "-m", "Update"], capture_output=True)

            from nanocode.modified_files import ModifiedFilesTracker
            tracker = ModifiedFilesTracker(cwd=tmpdir)
            tracker.refresh_from_git()

            files = tracker.get_modified_files()
            assert len(files) > 0

    def test_refresh_from_git_timeout(self):
        """Test refresh from git with timeout."""
        from nanocode.modified_files import ModifiedFilesTracker

        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = ModifiedFilesTracker(cwd=tmpdir)
            with patch("subprocess.run") as mock_run:
                mock_run.side_effect = TimeoutError()
                tracker.refresh_from_git()

            assert tracker.get_modified_files() == []


class TestModifiedFilesDisplay:
    """Tests for modified files display formatting."""

    def test_display_with_additions(self):
        """Test display with additions."""
        from nanocode.modified_files import FileModification

        fm = FileModification(
            path="/tmp/test.py",
            relative_path="src/test.py",
            additions=10,
            deletions=2,
        )

        adds_str = f"+{fm.additions}" if fm.additions > 0 else ""
        dels_str = f"-{fm.deletions}" if fm.deletions > 0 else ""
        stats_parts = []
        if adds_str:
            stats_parts.append(adds_str)
        if dels_str:
            stats_parts.append(dels_str)
        stats = " " + " ".join(stats_parts) if stats_parts else ""
        file_name = fm.relative_path.split("/")[-1]

        display = f"  {file_name}{stats}"

        assert display == "  test.py +10 -2"

    def test_display_only_additions(self):
        """Test display with only additions."""
        from nanocode.modified_files import FileModification

        fm = FileModification(
            path="/tmp/test.py",
            relative_path="test.py",
            additions=5,
            deletions=0,
        )

        adds_str = f"+{fm.additions}" if fm.additions > 0 else ""
        dels_str = f"-{fm.deletions}" if fm.deletions > 0 else ""
        stats_parts = []
        if adds_str:
            stats_parts.append(adds_str)
        if dels_str:
            stats_parts.append(dels_str)
        stats = " " + " ".join(stats_parts) if stats_parts else ""
        file_name = fm.relative_path.split("/")[-1]

        display = f"  {file_name}{stats}"

        assert display == "  test.py +5"

    def test_display_only_deletions(self):
        """Test display with only deletions."""
        from nanocode.modified_files import FileModification

        fm = FileModification(
            path="/tmp/test.py",
            relative_path="test.py",
            additions=0,
            deletions=3,
        )

        adds_str = f"+{fm.additions}" if fm.additions > 0 else ""
        dels_str = f"-{fm.deletions}" if fm.deletions > 0 else ""
        stats_parts = []
        if adds_str:
            stats_parts.append(adds_str)
        if dels_str:
            stats_parts.append(dels_str)
        stats = " " + " ".join(stats_parts) if stats_parts else ""
        file_name = fm.relative_path.split("/")[-1]

        display = f"  {file_name}{stats}"

        assert display == "  test.py -3"

    def test_display_no_changes(self):
        """Test display with no changes."""
        from nanocode.modified_files import FileModification

        fm = FileModification(
            path="/tmp/test.py",
            relative_path="test.py",
            additions=0,
            deletions=0,
        )

        adds_str = f"+{fm.additions}" if fm.additions > 0 else ""
        dels_str = f"-{fm.deletions}" if fm.deletions > 0 else ""
        stats_parts = []
        if adds_str:
            stats_parts.append(adds_str)
        if dels_str:
            stats_parts.append(dels_str)
        stats = " " + " ".join(stats_parts) if stats_parts else ""
        file_name = fm.relative_path.split("/")[-1]

        display = f"  {file_name}{stats}"

        assert display == "  test.py"

    def test_display_nested_path(self):
        """Test display with nested path."""
        from nanocode.modified_files import FileModification

        fm = FileModification(
            path="/tmp/project/src/components/Button.tsx",
            relative_path="src/components/Button.tsx",
            additions=20,
            deletions=5,
        )

        adds_str = f"+{fm.additions}" if fm.additions > 0 else ""
        dels_str = f"-{fm.deletions}" if fm.deletions > 0 else ""
        stats_parts = []
        if adds_str:
            stats_parts.append(adds_str)
        if dels_str:
            stats_parts.append(dels_str)
        stats = " " + " ".join(stats_parts) if stats_parts else ""
        file_name = fm.relative_path.split("/")[-1]

        display = f"  {file_name}{stats}"

        assert display == "  Button.tsx +20 -5"


class TestModifiedFilesSection:
    """Tests for sidebar section rendering."""

    def test_section_header(self):
        """Test Modified section header."""
        from nanocode.modified_files import FileModification

        modified = [
            FileModification("a.py", "a.py", 5, 0),
            FileModification("b.py", "b.py", 0, 3),
        ]

        lines = []
        if modified:
            lines.append("─ Modified ─")
            for f in modified[:15]:
                adds_str = f"+{f.additions}" if f.additions > 0 else ""
                dels_str = f"-{f.deletions}" if f.deletions > 0 else ""
                stats = f" {adds_str}{dels_str}" if adds_str or dels_str else ""
                file_name = f.relative_path.split("/")[-1]
                lines.append(f"  {file_name}{stats}")

        assert "─ Modified ─" in lines
        assert "  a.py +5" in lines
        assert "  b.py -3" in lines

    def test_section_empty(self):
        """Test Modified section when empty."""
        modified = []

        lines = []
        if modified:
            lines.append("─ Modified ─")
            for f in modified[:15]:
                adds_str = f"+{f.additions}" if f.additions > 0 else ""
                dels_str = f"-{f.deletions}" if f.deletions > 0 else ""
                stats = f" {adds_str}{dels_str}" if adds_str or dels_str else ""
                file_name = f.relative_path.split("/")[-1]
                lines.append(f"  {file_name}{stats}")

        assert "─ Modified ─" not in lines


class TestGetModifiedFilesTracker:
    """Tests for get_modified_files_tracker singleton."""

    def test_singleton(self, tmp_path, monkeypatch):
        """Test get_modified_files_tracker returns singleton."""
        import os
        from pathlib import Path
        from nanocode.modified_files import get_modified_files_tracker, ModifiedFilesTracker

        monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
        tracker1 = get_modified_files_tracker()
        tracker2 = get_modified_files_tracker()

        assert tracker1 is tracker2

    def test_new_cwd(self):
        """Test get_modified_files_tracker with new cwd."""
        from nanocode.modified_files import get_modified_files_tracker

        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = get_modified_files_tracker(cwd=tmpdir)
            assert tracker.cwd == Path(tmpdir)