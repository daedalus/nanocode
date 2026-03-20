"""Code search tool using Exa Code API."""

import os
import json
import asyncio

from nanocode.tools import Tool, ToolResult


class CodeSearchTool(Tool):
    """Search and get relevant context for programming tasks using Exa Code API.

    Provides the highest quality and freshest context for libraries, SDKs, and APIs.
    Use this tool for ANY question or task related to programming.
    Returns comprehensive code examples, documentation, and API references.
    Optimized for finding specific programming patterns and solutions.

    Usage notes:
      - Adjustable token count (1000-50000) for focused or comprehensive results
      - Default 5000 tokens provides balanced context for most queries
      - Use lower values for specific questions, higher values for comprehensive documentation
      - Supports queries about frameworks, libraries, APIs, and programming concepts
      - Examples: 'React useState hook examples', 'Python pandas dataframe filtering', 'Express.js middleware'
    """

    def __init__(self, api_key: str = None):
        super().__init__(
            name="codesearch",
            description="Search and get relevant context for any programming task using Exa Code API. "
            "Provides the highest quality and freshest context for libraries, SDKs, and APIs. "
            "Returns comprehensive code examples, documentation, and API references.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query to find relevant context for APIs, Libraries, and SDKs. "
                        "For example, 'React useState hook examples', 'Python pandas dataframe filtering', "
                        "'Express.js middleware', 'Next js partial prerendering configuration'",
                    },
                    "tokensNum": {
                        "type": "integer",
                        "description": "Number of tokens to return (1000-50000). Default is 5000 tokens. "
                        "Adjust this value based on how much context you need - use lower values "
                        "for focused queries and higher values for comprehensive documentation.",
                        "default": 5000,
                        "minimum": 1000,
                        "maximum": 50000,
                    },
                },
                "required": ["query"],
            },
        )
        self.api_key = api_key or os.getenv("EXA_API_KEY")
        self.base_url = "https://mcp.exa.ai"
        self.timeout = 30

    async def execute(
        self,
        query: str,
        tokensNum: int = 5000,
    ) -> ToolResult:
        """Execute code search.

        Args:
            query: Search query to find relevant context for programming tasks
            tokensNum: Number of tokens to return (1000-50000), default 5000
        """
        if not self.api_key:
            return ToolResult(
                success=False,
                content=None,
                error="EXA_API_KEY not set. Get one at https://exa.ai/dashboard",
            )

        if tokensNum < 1000 or tokensNum > 50000:
            return ToolResult(
                success=False, content=None, error="tokensNum must be between 1000 and 50000"
            )

        try:
            return await self._do_search(query, tokensNum)
        except asyncio.TimeoutError:
            return ToolResult(success=False, content=None, error="Code search request timed out")
        except Exception as e:
            return ToolResult(success=False, content=None, error=f"Code search error: {str(e)}")

    async def _do_search(self, query: str, tokens_num: int) -> ToolResult:
        """Execute the code search request."""
        code_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "get_code_context_exa",
                "arguments": {
                    "query": query,
                    "tokensNum": tokens_num,
                },
            },
        }

        headers = {
            "accept": "application/json, text/event-stream",
            "content-type": "application/json",
        }

        async with asyncio.timeout(self.timeout):
            async with asyncio.StreamReader() as reader:
                import aiohttp

                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        f"{self.base_url}/mcp",
                        json=code_request,
                        headers=headers,
                    ) as response:
                        if not response.ok:
                            error_text = await response.text()
                            return ToolResult(
                                success=False,
                                content=None,
                                error=f"Code search error ({response.status}): {error_text}",
                            )

                        response_text = await response.text()

        lines = response_text.split("\n")
        for line in lines:
            if line.startswith("data: "):
                data = json.loads(line[6:])
                if (
                    data.get("result")
                    and data["result"].get("content")
                    and len(data["result"]["content"]) > 0
                ):
                    return ToolResult(
                        success=True,
                        content=data["result"]["content"][0]["text"],
                        metadata={
                            "title": f"Code search: {query}",
                            "query": query,
                            "tokensNum": tokens_num,
                        },
                    )

        return ToolResult(
            success=True,
            content="No code snippets or documentation found. Please try a different query, "
            "be more specific about the library or programming concept, or check the spelling of framework names.",
            metadata={
                "title": f"Code search: {query}",
                "query": query,
                "tokensNum": tokens_num,
            },
        )
