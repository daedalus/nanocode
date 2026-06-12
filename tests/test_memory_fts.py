"""Tests for memory FTS5 system."""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from nanocode.memory.indexer import MemoryIndexer
from nanocode.memory.search import MemorySearch
from nanocode.memory.reconciler import MemoryReconciler


@pytest.fixture
def mock_session():
    """Create a mock async session."""
    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    
    # Mock the result of execute to return a proper async iterator
    mock_result = AsyncMock()
    mock_result.fetchall = MagicMock(return_value=[])
    session.execute.return_value = mock_result
    
    return session


@pytest.fixture
def indexer(mock_session):
    """Create a MemoryIndexer with mock session."""
    return MemoryIndexer(mock_session)


@pytest.fixture
def search(mock_session):
    """Create a MemorySearch with mock session."""
    return MemorySearch(mock_session)


@pytest.fixture
def reconciler(mock_session, tmp_path):
    """Create a MemoryReconciler with mock session and temp directory."""
    return MemoryReconciler(mock_session, memory_dir=str(tmp_path))


class TestMemoryIndexer:
    """Tests for MemoryIndexer."""

    @pytest.mark.asyncio
    async def test_initialize_creates_tables(self, indexer, mock_session):
        """Test that initialize creates FTS5 tables."""
        await indexer.initialize()
        
        assert mock_session.execute.call_count >= 5  # CREATE TABLE + triggers
        assert mock_session.commit.call_count >= 1
        assert indexer._initialized is True

    @pytest.mark.asyncio
    async def test_index_file_returns_zero_for_nonexistent(self, indexer, mock_session):
        """Test indexing nonexistent file returns 0."""
        chunks = await indexer.index_file("/nonexistent/file.md")
        assert chunks == 0

    @pytest.mark.asyncio
    async def test_index_file_splits_content(self, indexer, mock_session):
        """Test that content is split into chunks."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write("Paragraph 1\n\nParagraph 2\n\nParagraph 3")
            temp_path = f.name
        
        try:
            chunks = await indexer.index_file(temp_path, scope="global")
            assert chunks >= 1
        finally:
            Path(temp_path).unlink()

    def test_split_into_chunks_short_content(self, indexer):
        """Test chunk splitting with short content."""
        content = "Short content"
        chunks = indexer._split_into_chunks(content)
        assert len(chunks) == 1
        assert chunks[0] == content

    def test_split_into_chunks_long_content(self, indexer):
        """Test chunk splitting with long content."""
        # Create content with paragraphs that exceed chunk size
        paragraphs = ["Paragraph " + str(i) + " content " + "x" * 200 for i in range(10)]
        content = "\n\n".join(paragraphs)
        chunks = indexer._split_into_chunks(content, max_chunk_size=500)
        assert len(chunks) > 1

    def test_detect_memory_type(self, indexer):
        """Test memory type detection."""
        assert indexer._detect_memory_type("checkpoint.md") == "checkpoint"
        assert indexer._detect_memory_type("notes.md") == "notes"
        assert indexer._detect_memory_type("task_progress.md") == "task"
        assert indexer._detect_memory_type("memory.md") == "memory"


class TestMemorySearch:
    """Tests for MemorySearch."""

    @pytest.mark.asyncio
    async def test_search_empty_query(self, search):
        """Test search with empty query returns empty."""
        results = await search.search("")
        assert results == []

    def test_build_fts_query_simple(self, search):
        """Test FTS query building with simple terms."""
        query = search._build_fts_query("hello world")
        assert '"hello" OR "world"' == query

    def test_build_fts_query_with_punctuation(self, search):
        """Test FTS query building strips punctuation."""
        query = search._build_fts_query("hello-world.test")
        assert '"hello" OR "world" OR "test"' == query

    def test_build_fts_query_empty(self, search):
        """Test FTS query building with empty string."""
        query = search._build_fts_query("!!!")
        assert query == ""

    def test_build_search_query(self, search):
        """Test SQL query building."""
        sql, params = search._build_search_query(
            '"test"', scope="project", scope_id="123", memory_type="memory", limit=10
        )
        assert "memory_fts_idx MATCH :query" in sql
        assert "m.scope = :scope" in sql
        assert "m.scope_id = :scope_id" in sql
        assert "m.type = :memory_type" in sql
        assert params["scope"] == "project"
        assert params["scope_id"] == "123"

    def test_build_search_query_no_filters(self, search):
        """Test SQL query building without filters."""
        sql, params = search._build_search_query('"test"', None, None, None, 5)
        assert "WHERE m.scope" not in sql  # No scope filter in WHERE
        assert params["limit"] == 15  # 5 * 3 for over-fetch


class TestMemoryReconciler:
    """Tests for MemoryReconciler."""

    def test_init_creates_indexer(self, reconciler):
        """Test reconciler creates indexer."""
        assert reconciler.indexer is not None
        assert isinstance(reconciler.indexer, MemoryIndexer)

    def test_detect_type(self, reconciler):
        """Test type detection."""
        assert reconciler._detect_type("checkpoint.md") == "checkpoint"
        assert reconciler._detect_type("notes.md") == "notes"
        assert reconciler._detect_type("task.md") == "task"
        assert reconciler._detect_type("memory.md") == "memory"
        assert reconciler._detect_type("unknown.md") == "memory"

    def test_scan_global(self, reconciler, tmp_path):
        """Test scanning global directory."""
        # Create test structure
        global_dir = tmp_path / "global"
        global_dir.mkdir()
        (global_dir / "memory.md").write_text("content")

        files = {}
        reconciler._scan_global(files, tmp_path, None)
        assert len(files) == 1
        assert list(files.values())[0]["scope"] == "global"

    def test_scan_global_skip(self, reconciler, tmp_path):
        """Test scanning global with scope filter."""
        files = {}
        reconciler._scan_global(files, tmp_path, ["project"])
        assert len(files) == 0

    def test_scan_projects(self, reconciler, tmp_path):
        """Test scanning projects directory."""
        projects_dir = tmp_path / "projects" / "proj1"
        projects_dir.mkdir(parents=True)
        (projects_dir / "memory.md").write_text("content")

        files = {}
        reconciler._scan_projects(files, tmp_path, None)
        assert len(files) == 1
        assert list(files.values())[0]["scope"] == "project"

    def test_scan_sessions(self, reconciler, tmp_path):
        """Test scanning sessions directory."""
        session_dir = tmp_path / "sessions" / "ses1"
        session_dir.mkdir(parents=True)
        (session_dir / "checkpoint.md").write_text("content")

        files = {}
        reconciler._scan_sessions(files, tmp_path, None)
        assert len(files) == 1
        assert list(files.values())[0]["scope"] == "session"

    @pytest.mark.asyncio
    async def test_reconcile_empty_dir(self, reconciler):
        """Test reconciliation with empty directory."""
        stats = await reconciler.reconcile()
        assert stats["indexed"] == 0
        assert stats["pruned"] == 0
        assert stats["errors"] == []
