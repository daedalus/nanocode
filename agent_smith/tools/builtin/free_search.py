"""Free web search tools using various free APIs."""

import os

from nanocode.tools import Tool, ToolResult


class FreeExaSearchTool(Tool):
    """Free web search using Exa's hosted MCP API (no API key required).

    This uses Exa's free MCP endpoint which has rate limits but doesn't require
    an API key. For higher limits, use the paid exa tool with an API key.
    """

    def __init__(self):
        super().__init__(
            name="free_exa",
            description="Free web search using Exa AI (no API key, rate limited). Use for quick searches.",
        )
        self.base_url = "https://mcp.exa.ai/mcp"

    async def execute(self, query: str, num_results: int = 5, **kwargs) -> ToolResult:
        """Execute free Exa search."""
        try:
            import httpx

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.base_url,
                    params={"tools": "web_search_exa"},
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {
                            "name": "web_search_exa",
                            "arguments": {"query": query, "num_results": num_results},
                        },
                    },
                    timeout=30.0,
                )

                if response.status_code == 402:
                    return ToolResult(
                        success=False,
                        content=None,
                        error="Exa rate limit reached. Try again later or use 'exa' tool with API key.",
                    )

                data = response.json()

                if "result" in data:
                    return ToolResult(
                        success=True,
                        content=data["result"],
                        metadata={"query": query, "count": num_results},
                    )

                return ToolResult(
                    success=False,
                    content=None,
                    error=f"Unexpected response: {data}",
                )

        except Exception as e:
            return ToolResult(success=False, content=None, error=str(e))


class OpenWebSearchTool(Tool):
    """Free web search using Open WebSearch MCP API.

    Supports multiple search engines: Bing, DuckDuckGo, Brave, Exa, Baidu, CSDN, etc.
    No API key required.
    """

    def __init__(self):
        super().__init__(
            name="openwebsearch",
            description="Free multi-engine web search (Bing, DuckDuckGo, Brave, Exa). No API key required.",
        )
        self.base_url = "https://open-web-search.vercel.app/mcp"

    async def execute(
        self,
        query: str,
        engine: str = "duckduckgo",
        num_results: int = 10,
    ) -> ToolResult:
        """Execute free web search."""
        valid_engines = ["bing", "duckduckgo", "brave", "exa", "baidu", "juejin", "google"]

        if engine not in valid_engines:
            engine = "duckduckgo"

        try:
            import httpx

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.base_url,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {
                            "name": "web_search",
                            "arguments": {
                                "query": query,
                                "engine": engine,
                                "num_results": num_results,
                            },
                        },
                    },
                    timeout=30.0,
                )

                data = response.json()

                if "result" in data:
                    return ToolResult(
                        success=True,
                        content=data["result"],
                        metadata={"query": query, "engine": engine},
                    )

                return ToolResult(
                    success=False,
                    content=None,
                    error=f"Unexpected response: {data}",
                )

        except Exception as e:
            return ToolResult(success=False, content=None, error=str(e))


class BraveSearchTool(Tool):
    """Free web search using Brave's API.

    Note: Requires Brave API key for production use.
    Free tier has limited requests.
    """

    def __init__(self, api_key: str = None):
        super().__init__(
            name="brave_search",
            description="Web search using Brave Search API. Requires API key for production.",
        )
        self.api_key = api_key or os.getenv("BRAVE_API_KEY")

    async def execute(
        self,
        query: str,
        num_results: int = 10,
    ) -> ToolResult:
        """Execute Brave search."""
        if not self.api_key:
            return ToolResult(
                success=False,
                content=None,
                error="BRAVE_API_KEY not set. Get one at https://brave.com/search/api/",
            )

        try:
            import httpx

            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://api.brave.com/res/v1/web/search",
                    params={
                        "q": query,
                        "count": num_results,
                    },
                    headers={"Accept-Encoding": "gzip", "X-Subscription-Token": self.api_key},
                    timeout=30.0,
                )

                data = response.json()

                results = []
                for item in data.get("web", {}).get("results", []):
                    results.append(
                        {
                            "title": item.get("title"),
                            "url": item.get("url"),
                            "description": item.get("description"),
                        }
                    )

                return ToolResult(
                    success=True,
                    content=results,
                    metadata={"query": query, "count": len(results)},
                )

        except Exception as e:
            return ToolResult(success=False, content=None, error=str(e))
