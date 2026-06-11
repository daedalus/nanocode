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

    @pytest.mark.asyncio
    async def test_reconcile_empty_dir(self, reconciler):
        """Test reconciliation with empty directory."""
        stats = await reconciler.reconcile()
        assert stats["indexed"] == 0
        assert stats["pruned"] == 0
        assert stats["errors"] == []
