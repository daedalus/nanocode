"""Tests for the Research Sub-Agent."""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from nanocode.research import (
    ResearchAgent,
    ResearchQuery,
    SearchResult,
    ScrapedPage,
    ResearchReport,
    QueryGenerator,
    WebSearcher,
    PageScraper,
    get_research_agent,
    reset_research_agent,
)


class TestResearchQuery:
    """Tests for ResearchQuery dataclass."""

    def test_creation(self):
        """Test creating a query."""
        q = ResearchQuery(query="test query")
        assert q.query == "test query"
        assert q.source == "user"
        assert q.priority == 1


class TestSearchResult:
    """Tests for SearchResult dataclass."""

    def test_creation(self):
        """Test creating a search result."""
        r = SearchResult(title="Test", url="http://test.com", snippet="A test")
        assert r.title == "Test"
        assert r.url == "http://test.com"


class TestScrapedPage:
    """Tests for ScrapedPage dataclass."""

    def test_creation(self):
        """Test creating a scraped page."""
        p = ScrapedPage(url="http://test.com", title="Test", content="Content")
        assert p.url == "http://test.com"
        assert p.links == []


class TestResearchReport:
    """Tests for ResearchReport dataclass."""

    def test_creation(self):
        """Test creating a report."""
        r = ResearchReport(
            topic="test",
            queries_used=["q1"],
            sources=[],
            summary="Summary",
            key_findings=["finding1"],
        )
        assert r.topic == "test"
        assert r.confidence_score == 0.0


class TestQueryGenerator:
    """Tests for QueryGenerator."""

    def test_init(self):
        """Test initialization."""
        gen = QueryGenerator()
        assert gen.llm is None

    def test_generate_basic(self):
        """Test basic query generation."""
        gen = QueryGenerator()
        queries = gen._generate_basic("python programming", 3)
        assert len(queries) == 3
        assert queries[0].query == "python programming"
        assert queries[0].source == "basic"

    @pytest.mark.asyncio
    async def test_generate_queries_no_llm(self):
        """Test query generation without LLM."""
        gen = QueryGenerator()
        queries = await gen.generate_queries("test topic", 3)
        assert len(queries) == 3


class TestWebSearcher:
    """Tests for WebSearcher."""

    def test_init(self):
        """Test initialization."""
        s = WebSearcher(timeout=5)
        assert s.timeout == 5

    def test_parse_ddg_results(self):
        """Test parsing DDG results."""
        html = '''
        <table>
        <tr><td><a class="result-link" href="http://example.com">Example</a></td></tr>
        <tr><td class="result-snippet">This is a test snippet.</td></tr>
        </table>
        '''
        s = WebSearcher()
        results = s._parse_ddg_results(html)
        assert len(results) == 1
        assert results[0].title == "Example"
        assert results[0].url == "http://example.com"


class TestPageScraper:
    """Tests for PageScraper."""

    def test_init(self):
        """Test initialization."""
        s = PageScraper(timeout=10)
        assert s.timeout == 10

    def test_extract_title(self):
        """Test title extraction."""
        html = "<html><head><title>Test Title</title></head><body></body></html>"
        s = PageScraper()
        title = s._extract_title(html)
        assert title == "Test Title"

    def test_extract_text(self):
        """Test text extraction."""
        html = "<html><body><p>Hello world</p><script>ignore</script></body></html>"
        s = PageScraper()
        text = s._extract_text(html)
        assert "Hello world" in text
        assert "ignore" not in text

    def test_extract_links(self):
        """Test link extraction."""
        html = '<a href="/relative">Relative</a><a href="http://example.com">Absolute</a>'
        s = PageScraper()
        links = s._extract_links(html, "http://base.com")
        assert len(links) == 2


class TestResearchAgent:
    """Tests for ResearchAgent."""

    def test_init(self):
        """Test initialization."""
        agent = ResearchAgent()
        assert agent.llm is None

    @pytest.mark.asyncio
    async def test_research_basic(self):
        """Test basic research without LLM."""
        agent = ResearchAgent()

        # Mock the searcher and scraper
        agent.searcher.search = AsyncMock(return_value=[
            SearchResult(title="Test", url="http://test.com", snippet="Test snippet")
        ])
        agent.scraper.scrape_many = AsyncMock(return_value=[
            ScrapedPage(url="http://test.com", title="Test", content="Test content")
        ])

        report = await agent.research("test topic", max_queries=1, max_pages=1)

        assert report.topic == "test topic"
        assert len(report.queries_used) == 1
        assert report.confidence_score > 0

    def test_calculate_confidence(self):
        """Test confidence calculation."""
        agent = ResearchAgent()

        pages = [ScrapedPage(url="x", title="x", content="x" * 1000) for _ in range(5)]
        results = [SearchResult(title="x", url="x", snippet="x") for _ in range(10)]

        confidence = agent._calculate_confidence(pages, results)
        assert 0.0 <= confidence <= 1.0

    def test_calculate_confidence_empty(self):
        """Test confidence with no data."""
        agent = ResearchAgent()
        confidence = agent._calculate_confidence([], [])
        assert confidence == 0.0

    def test_generate_basic_summary(self):
        """Test basic summary generation."""
        agent = ResearchAgent()
        pages = [
            ScrapedPage(url="x", title="Page 1", content="Content about topic.")
        ]
        summary = agent._generate_basic_summary("test", pages)
        assert "test" in summary
        assert "Page 1" in summary


class TestGlobalInstance:
    """Tests for global instance."""

    def test_get_research_agent_singleton(self):
        """Test global instance is singleton."""
        reset_research_agent()
        a1 = get_research_agent()
        a2 = get_research_agent()
        assert a1 is a2

    def test_reset_research_agent(self):
        """Test resetting global instance."""
        a1 = get_research_agent()
        reset_research_agent()
        a2 = get_research_agent()
        assert a1 is not a2
