"""Research Sub-Agent - Background web research with synthesis.

Based on Aura's run_research:
- Generates search queries from research topics
- Searches web using httpx
- Scrapes and extracts content
- Produces synthesized reports
"""

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, urljoin

logger = logging.getLogger(__name__)


@dataclass
class ResearchQuery:
    """A search query for research."""

    query: str
    source: str = "user"
    priority: int = 1


@dataclass
class SearchResult:
    """A single search result."""

    title: str
    url: str
    snippet: str
    score: float = 0.0


@dataclass
class ScrapedPage:
    """Content from a scraped page."""

    url: str
    title: str
    content: str
    summary: str = ""
    links: List[str] = field(default_factory=list)


@dataclass
class ResearchReport:
    """Synthesized research report."""

    topic: str
    queries_used: List[str]
    sources: List[ScrapedPage]
    summary: str
    key_findings: List[str]
    recommendations: List[str] = field(default_factory=list)
    confidence_score: float = 0.0


class QueryGenerator:
    """Generate search queries from research topics."""

    def __init__(self, llm=None):
        """Initialize query generator.

        Args:
            llm: LLM for query generation
        """
        self.llm = llm

    async def generate_queries(
        self,
        topic: str,
        num_queries: int = 5,
    ) -> List[ResearchQuery]:
        """Generate search queries from a topic.

        Args:
            topic: Research topic
            num_queries: Number of queries to generate

        Returns:
            List of ResearchQuery objects
        """
        if self.llm:
            return await self._generate_with_llm(topic, num_queries)
        else:
            return self._generate_basic(topic, num_queries)

    async def _generate_with_llm(
        self,
        topic: str,
        num_queries: int,
    ) -> List[ResearchQuery]:
        """Generate queries using LLM."""
        from nanocode.llm import Message

        prompt = f"""Generate {num_queries} diverse search queries to research this topic thoroughly.

Topic: {topic}

Provide queries that:
1. Cover different aspects of the topic
2. Include both broad and specific queries
3. Consider different perspectives and angles
4. Use natural language, not just keywords

Return as a JSON array of strings, just the query text, no other explanation.
Example: ["query 1", "query 2", "query 3"]
"""

        try:
            response = await self.llm.chat([Message("user", prompt)])
            # Parse JSON array from response
            import json
            queries = json.loads(response.content)
            return [ResearchQuery(query=q, source="llm") for q in queries[:num_queries]]
        except Exception as e:
            logger.warning(f"LLM query generation failed: {e}")
            return self._generate_basic(topic, num_queries)

    def _generate_basic(
        self,
        topic: str,
        num_queries: int,
    ) -> List[ResearchQuery]:
        """Generate basic queries without LLM."""
        queries = [
            topic,
            f"{topic} overview",
            f"{topic} tutorial",
            f"{topic} examples",
            f"{topic} best practices",
        ]
        return [ResearchQuery(query=q, source="basic") for q in queries[:num_queries]]


class WebSearcher:
    """Search the web for information."""

    def __init__(self, timeout: int = 10):
        """Initialize web searcher.

        Args:
            timeout: Request timeout in seconds
        """
        self.timeout = timeout

    async def search(
        self,
        query: str,
        max_results: int = 5,
    ) -> List[SearchResult]:
        """Search the web.

        Args:
            query: Search query
            max_results: Maximum results

        Returns:
            List of SearchResult objects
        """
        try:
            import httpx

            # Use a search API (fallback to simple scraping)
            results = await self._search_with_httpx(query, max_results)
            return results

        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []

    async def _search_with_httpx(
        self,
        query: str,
        max_results: int,
    ) -> List[SearchResult]:
        """Search using httpx."""
        import httpx

        # Use DuckDuckGo lite as a simple fallback
        url = "https://lite.duckduckgo.com/lite/"
        params = {"q": query}

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, data=params)
            response.raise_for_status()

            # Parse simple HTML results
            results = self._parse_ddg_results(response.text)
            return results[:max_results]

    def _parse_ddg_results(self, html: str) -> List[SearchResult]:
        """Parse DuckDuckGo lite results."""
        results = []

        # Simple regex parsing for DDG lite
        # Links are in <a> tags with class="result-link"
        link_pattern = re.compile(r'<a[^>]*class="result-link"[^>]*href="([^"]*)"[^>]*>([^<]*)</a>')
        snippet_pattern = re.compile(r'<td[^>]*class="result-snippet"[^>]*>(.*?)</td>', re.DOTALL)

        links = link_pattern.findall(html)
        snippets = snippet_pattern.findall(html)

        for i, (url, title) in enumerate(links):
            snippet = snippets[i][0].strip() if i < len(snippets) else ""
            # Clean HTML tags from snippet
            snippet = re.sub(r'<[^>]+>', '', snippet).strip()

            results.append(
                SearchResult(
                    title=title.strip(),
                    url=url,
                    snippet=snippet,
                )
            )

        return results


class PageScraper:
    """Scrape and extract content from web pages."""

    def __init__(self, timeout: int = 15):
        """Initialize page scraper.

        Args:
            timeout: Request timeout in seconds
        """
        self.timeout = timeout

    async def scrape(self, url: str) -> Optional[ScrapedPage]:
        """Scrape a single page.

        Args:
            url: URL to scrape

        Returns:
            ScrapedPage if successful, None otherwise
        """
        try:
            import httpx

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, follow_redirects=True)
                response.raise_for_status()

                content = response.text
                title = self._extract_title(content)
                text = self._extract_text(content)
                links = self._extract_links(content, url)

                return ScrapedPage(
                    url=url,
                    title=title,
                    content=text[:5000],  # Limit content size
                    links=links[:20],  # Limit links
                )

        except Exception as e:
            logger.warning(f"Failed to scrape {url}: {e}")
            return None

    async def scrape_many(self, urls: List[str]) -> List[ScrapedPage]:
        """Scrape multiple pages concurrently.

        Args:
            urls: URLs to scrape

        Returns:
            List of ScrapedPage objects
        """
        tasks = [self.scrape(url) for url in urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        pages = []
        for result in results:
            if isinstance(result, ScrapedPage):
                pages.append(result)

        return pages

    def _extract_title(self, html: str) -> str:
        """Extract title from HTML."""
        match = re.search(r'<title[^>]*>(.*?)</title>', html, re.DOTALL | re.IGNORECASE)
        return match.group(1).strip() if match else "Untitled"

    def _extract_text(self, html: str) -> str:
        """Extract text content from HTML."""
        # Remove script and style tags
        html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
        html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL)

        # Remove HTML tags
        text = re.sub(r'<[^>]+>', ' ', html)

        # Clean up whitespace
        text = re.sub(r'\s+', ' ', text)
        text = text.strip()

        return text

    def _extract_links(self, html: str, base_url: str) -> List[str]:
        """Extract links from HTML."""
        links = []
        for match in re.finditer(r'href="([^"]*)"', html):
            url = match.group(1)
            # Make absolute
            if not url.startswith(('http://', 'https://')):
                url = urljoin(base_url, url)
            # Only include http/https links
            if url.startswith(('http://', 'https://')):
                links.append(url)
        return links


class ResearchAgent:
    """Background sub-agent for web research.

    Based on Aura's run_research:
    - Generates search queries
    - Searches web
    - Scrapes pages
    - Produces synthesized reports
    """

    def __init__(self, llm=None):
        """Initialize research agent.

        Args:
            llm: LLM for query generation and synthesis
        """
        self.llm = llm
        self.query_generator = QueryGenerator(llm)
        self.searcher = WebSearcher()
        self.scraper = PageScraper()

    async def research(
        self,
        topic: str,
        max_queries: int = 3,
        max_results_per_query: int = 3,
        max_pages: int = 5,
    ) -> ResearchReport:
        """Conduct research on a topic.

        Args:
            topic: Research topic
            max_queries: Maximum search queries
            max_results_per_query: Maximum results per query
            max_pages: Maximum pages to scrape

        Returns:
            ResearchReport with findings
        """
        logger.info(f"Starting research on: {topic}")

        # Generate queries
        queries = await self.query_generator.generate_queries(topic, max_queries)
        queries_used = [q.query for q in queries]

        # Search for each query
        all_results = []
        for q in queries:
            results = await self.searcher.search(q.query, max_results_per_query)
            all_results.extend(results)

        # Deduplicate URLs
        seen_urls = set()
        unique_results = []
        for r in all_results:
            if r.url not in seen_urls:
                seen_urls.add(r.url)
                unique_results.append(r)

        # Scrape top pages
        urls_to_scrape = [r.url for r in unique_results[:max_pages]]
        pages = await self.scraper.scrape_many(urls_to_scrape)

        # Generate summary
        summary = await self._generate_summary(topic, pages)
        key_findings = await self._extract_key_findings(pages)
        confidence = self._calculate_confidence(pages, unique_results)

        report = ResearchReport(
            topic=topic,
            queries_used=queries_used,
            sources=pages,
            summary=summary,
            key_findings=key_findings,
            confidence_score=confidence,
        )

        logger.info(f"Research complete: {len(pages)} pages scraped")
        return report

    async def _generate_summary(
        self,
        topic: str,
        pages: List[ScrapedPage],
    ) -> str:
        """Generate summary of research findings."""
        if not pages:
            return f"No information found about {topic}."

        if self.llm:
            return await self._generate_summary_with_llm(topic, pages)
        else:
            return self._generate_basic_summary(topic, pages)

    async def _generate_summary_with_llm(
        self,
        topic: str,
        pages: List[ScrapedPage],
    ) -> str:
        """Generate summary using LLM."""
        from nanocode.llm import Message

        # Combine page contents
        combined = "\n\n".join(
            f"Source: {p.title}\n{p.content[:1000]}"
            for p in pages[:3]
        )

        prompt = f"""Summarize the following research about {topic}:

{combined}

Provide a concise summary (2-3 paragraphs) covering:
1. What is {topic}?
2. Key points and findings
3. Current state or trends
"""

        try:
            response = await self.llm.chat([Message("user", prompt)])
            return response.content
        except Exception as e:
            logger.warning(f"LLM summary failed: {e}")
            return self._generate_basic_summary(topic, pages)

    def _generate_basic_summary(
        self,
        topic: str,
        pages: List[ScrapedPage],
    ) -> str:
        """Generate basic summary without LLM."""
        if not pages:
            return f"No information found about {topic}."

        summaries = []
        for p in pages[:3]:
            if p.content:
                # Take first 200 chars as summary
                summary = p.content[:200].strip()
                if summary:
                    summaries.append(f"- {p.title}: {summary}...")

        return f"Research on {topic}:\n\n" + "\n".join(summaries)

    async def _extract_key_findings(self, pages: List[ScrapedPage]) -> List[str]:
        """Extract key findings from pages."""
        findings = []
        for p in pages[:5]:
            if p.content and len(p.content) > 100:
                # Extract first meaningful sentence
                sentences = re.split(r'[.!?]+', p.content)
                for s in sentences:
                    s = s.strip()
                    if len(s) > 30 and not s.startswith(('http', 'www')):
                        findings.append(s[:150])
                        break
        return findings[:5]

    def _calculate_confidence(
        self,
        pages: List[ScrapedPage],
        results: List[SearchResult],
    ) -> float:
        """Calculate confidence score for research."""
        if not pages:
            return 0.0

        # Factors for confidence
        page_score = min(len(pages) / 5, 1.0)  # More pages = higher confidence
        result_score = min(len(results) / 10, 1.0)  # More results = higher confidence

        # Content quality (pages with substantial content)
        quality_pages = sum(1 for p in pages if len(p.content) > 500)
        quality_score = min(quality_pages / 3, 1.0)

        return (page_score + result_score + quality_score) / 3


# Global instance
_research_agent: Optional[ResearchAgent] = None


def get_research_agent(llm=None) -> ResearchAgent:
    """Get or create the global research agent."""
    global _research_agent
    if _research_agent is None:
        _research_agent = ResearchAgent(llm)
    elif llm and not _research_agent.llm:
        _research_agent.llm = llm
    return _research_agent


def reset_research_agent():
    """Reset the global research agent."""
    global _research_agent
    _research_agent = None
