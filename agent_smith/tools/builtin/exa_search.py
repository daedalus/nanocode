"""Exa.ai web search tool."""

import os

from nanocode.tools import Tool, ToolResult


class ExaSearchTool(Tool):
    """Web search using Exa.ai API.

    Exa is a neural search engine designed for AI applications.
    Supports auto, neural, keyword, and deep search types.
    """

    def __init__(self, api_key: str = None, num_results: int = 10):
        super().__init__(
            name="exa",
            description="Search the web using Exa.ai neural search engine. Supports 'auto' (default), 'neural', 'keyword', and 'deep' search types.",
        )
        self.api_key = api_key or os.getenv("EXA_API_KEY")
        self.num_results = num_results
        self._client = None

    @property
    def client(self):
        """Lazy initialization of Exa client."""
        if self._client is None:
            try:
                from exa_py import Exa

                self._client = Exa(api_key=self.api_key)
            except ImportError:
                raise ImportError("exa-py package not installed. Run: pip install exa-py")
        return self._client

    async def execute(
        self,
        query: str,
        search_type: str = "auto",
        num_results: int = None,
        highlights: bool = True,
        answer: bool = False,
    ) -> ToolResult:
        """Execute Exa search.

        Args:
            query: Search query
            search_type: 'auto', 'neural', 'keyword', or 'deep'
            num_results: Number of results to return
            highlights: Include text highlights from results
            answer: Use Exa's answer endpoint for direct answers
        """
        if not self.api_key:
            return ToolResult(
                success=False,
                content=None,
                error="EXA_API_KEY not set. Get one at https://exa.ai/dashboard",
            )

        try:
            num_results = num_results or self.num_results

            if answer:
                return await self._execute_answer(query, num_results)

            return await self._execute_search(query, search_type, num_results, highlights)

        except Exception as e:
            return ToolResult(success=False, content=None, error=str(e))

    async def _execute_search(
        self,
        query: str,
        search_type: str,
        num_results: int,
        highlights: bool,
    ) -> ToolResult:
        """Execute search request."""
        import asyncio

        loop = asyncio.get_event_loop()

        contents = None
        if highlights:
            contents = {"highlights": {"num_chars": 500, "max_num": 5}}

        result = await loop.run_in_executor(
            None,
            lambda: self.client.search(
                query,
                type=search_type,
                num_results=num_results,
                contents=contents,
            ),
        )

        results = []
        for item in result.results:
            entry = {
                "title": item.title,
                "url": item.url,
                "published": item.published,
            }
            if highlights and hasattr(item, "highlights") and item.highlights:
                entry["highlights"] = item.highlights
            results.append(entry)

        return ToolResult(
            success=True,
            content=results,
            metadata={
                "query": query,
                "search_type": search_type,
                "count": len(results),
            },
        )

    async def _execute_answer(self, query: str, num_results: int) -> ToolResult:
        """Execute answer request for direct answers."""
        import asyncio

        loop = asyncio.get_event_loop()

        result = await loop.run_in_executor(
            None,
            lambda: self.client.answer(
                query,
                num_results=num_results,
            ),
        )

        return ToolResult(
            success=True,
            content={
                "answer": result.answer,
                "results": [{"title": r.title, "url": r.url} for r in result.results],
            },
            metadata={"query": query},
        )


class ExaFetchTool(Tool):
    """Fetch and extract content from URLs using Exa.ai."""

    def __init__(self, api_key: str = None):
        super().__init__(
            name="exa_fetch",
            description="Fetch and extract content from URLs using Exa.ai content extraction.",
        )
        self.api_key = api_key or os.getenv("EXA_API_KEY")
        self._client = None

    @property
    def client(self):
        """Lazy initialization of Exa client."""
        if self._client is None:
            try:
                from exa_py import Exa

                self._client = Exa(api_key=self.api_key)
            except ImportError:
                raise ImportError("exa-py package not installed. Run: pip install exa-py")
        return self._client

    async def execute(
        self,
        urls: list[str],
        text: bool = True,
        highlights: bool = True,
    ) -> ToolResult:
        """Fetch content from URLs.

        Args:
            urls: List of URLs to fetch
            text: Include text content
            highlights: Include relevant highlights
        """
        if not self.api_key:
            return ToolResult(
                success=False,
                content=None,
                error="EXA_API_KEY not set. Get one at https://exa.ai/dashboard",
            )

        try:
            import asyncio

            loop = asyncio.get_event_loop()

            contents = {}
            if text:
                contents["text"] = True
            if highlights:
                contents["highlights"] = {"num_chars": 1000, "max_num": 3}

            result = await loop.run_in_executor(
                None, lambda: self.client.get_contents(urls, **contents)
            )

            fetched = []
            for item in result.results:
                entry = {
                    "url": item.url,
                }
                if text and hasattr(item, "text") and item.text:
                    entry["text"] = item.text[:5000]
                if highlights and hasattr(item, "highlights") and item.highlights:
                    entry["highlights"] = item.highlights
                fetched.append(entry)

            return ToolResult(
                success=True,
                content=fetched,
                metadata={"count": len(fetched)},
            )

        except Exception as e:
            return ToolResult(success=False, content=None, error=str(e))
