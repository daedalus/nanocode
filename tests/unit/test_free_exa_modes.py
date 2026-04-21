"""Tests for FreeExaSearchTool with web_search and web_search_advanced modes."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock


class TestFreeExaSearchToolInit:
    """Tests for FreeExaSearchTool initialization."""

    def test_create_tool(self):
        """Test FreeExaSearchTool can be instantiated."""
        from nanocode.tools.builtin.free_search import FreeExaSearchTool

        tool = FreeExaSearchTool()
        assert tool.name == "free_exa"
        assert "exa" in tool.description.lower()
        assert "no api key" in tool.description.lower()

    def test_has_web_search_mode(self):
        """Test tool has web_search mode in parameters."""
        from nanocode.tools.builtin.free_search import FreeExaSearchTool

        tool = FreeExaSearchTool()
        assert "mode" in tool.parameters["properties"]
        assert "enum" in tool.parameters["properties"]["mode"]
        assert "web_search" in tool.parameters["properties"]["mode"]["enum"]
        assert "web_search_advanced" in tool.parameters["properties"]["mode"]["enum"]

    def test_has_category_parameter(self):
        """Test tool has category parameter for advanced mode."""
        from nanocode.tools.builtin.free_search import FreeExaSearchTool

        tool = FreeExaSearchTool()
        assert "category" in tool.parameters["properties"]

    def test_has_date_parameters(self):
        """Test tool has start_date and end_date parameters."""
        from nanocode.tools.builtin.free_search import FreeExaSearchTool

        tool = FreeExaSearchTool()
        assert "start_date" in tool.parameters["properties"]
        assert "end_date" in tool.parameters["properties"]


class TestFreeExaSearchToolWebSearch:
    """Tests for web_search mode."""

    @pytest.mark.asyncio
    async def test_web_search_basic(self):
        """Test basic web search mode."""
        from nanocode.tools.builtin.free_search import FreeExaSearchTool

        tool = FreeExaSearchTool()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "result": [
                {"title": "Test Result", "url": "https://example.com"}
            ]
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await tool.execute(query="test query", mode="web_search")

            assert result.success is True
            assert result.content == [{"title": "Test Result", "url": "https://example.com"}]
            assert result.metadata["mode"] == "web_search"

    @pytest.mark.asyncio
    async def test_web_search_autoprompt_true(self):
        """Test web_search mode uses autoprompt by default."""
        from nanocode.tools.builtin.free_search import FreeExaSearchTool

        tool = FreeExaSearchTool()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": []}

        with patch("httpx.AsyncClient") as mock_client:
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            await tool.execute(query="test", mode="web_search")

            call_args = mock_post.call_args
            params = call_args.kwargs["json"]["params"]["arguments"]
            assert params["use_autoprompt"] is True

    @pytest.mark.asyncio
    async def test_web_search_num_results(self):
        """Test web_search respects num_results."""
        from nanocode.tools.builtin.free_search import FreeExaSearchTool

        tool = FreeExaSearchTool()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": []}

        with patch("httpx.AsyncClient") as mock_client:
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            await tool.execute(query="test", mode="web_search", num_results=5)

            call_args = mock_post.call_args
            params = call_args.kwargs["json"]["params"]["arguments"]
            assert params["num_results"] == 5


class TestFreeExaSearchToolAdvanced:
    """Tests for web_search_advanced mode."""

    @pytest.mark.asyncio
    async def test_advanced_mode_basic(self):
        """Test basic advanced search mode."""
        from nanocode.tools.builtin.free_search import FreeExaSearchTool

        tool = FreeExaSearchTool()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "result": [
                {"title": "Advanced Result", "url": "https://example.com/advanced"}
            ]
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await tool.execute(query="test query", mode="web_search_advanced")

            assert result.success is True
            assert result.metadata["mode"] == "web_search_advanced"

    @pytest.mark.asyncio
    async def test_advanced_autoprompt_false(self):
        """Test advanced mode uses autoprompt false by default."""
        from nanocode.tools.builtin.free_search import FreeExaSearchTool

        tool = FreeExaSearchTool()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": []}

        with patch("httpx.AsyncClient") as mock_client:
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            await tool.execute(query="test", mode="web_search_advanced")

            call_args = mock_post.call_args
            params = call_args.kwargs["json"]["params"]["arguments"]
            assert params["use_autoprompt"] is False

    @pytest.mark.asyncio
    async def test_advanced_with_category(self):
        """Test advanced search with category filter."""
        from nanocode.tools.builtin.free_search import FreeExaSearchTool

        tool = FreeExaSearchTool()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": []}

        with patch("httpx.AsyncClient") as mock_client:
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            await tool.execute(
                query="python",
                mode="web_search_advanced",
                category="github",
            )

            call_args = mock_post.call_args
            params = call_args.kwargs["json"]["params"]["arguments"]
            assert params["category"] == "github"

    @pytest.mark.asyncio
    async def test_advanced_with_dates(self):
        """Test advanced search with date filters."""
        from nanocode.tools.builtin.free_search import FreeExaSearchTool

        tool = FreeExaSearchTool()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": []}

        with patch("httpx.AsyncClient") as mock_client:
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            await tool.execute(
                query="AI news",
                mode="web_search_advanced",
                start_date="2026-01-01",
                end_date="2026-04-21",
            )

            call_args = mock_post.call_args
            params = call_args.kwargs["json"]["params"]["arguments"]
            assert params["start_date"] == "2026-01-01"
            assert params["end_date"] == "2026-04-21"


class TestFreeExaSearchToolErrors:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_rate_limit_error(self):
        """Test rate limit handling."""
        from nanocode.tools.builtin.free_search import FreeExaSearchTool

        tool = FreeExaSearchTool()

        mock_response = MagicMock()
        mock_response.status_code = 402

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await tool.execute(query="test")

            assert result.success is False
            assert "rate limit" in result.error.lower()

    @pytest.mark.asyncio
    async def test_invalid_response(self):
        """Test handling of invalid response."""
        from nanocode.tools.builtin.free_search import FreeExaSearchTool

        tool = FreeExaSearchTool()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"error": "something went wrong"}

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await tool.execute(query="test")

            assert result.success is False
            assert "unexpected response" in result.error.lower()

    @pytest.mark.asyncio
    async def test_exception_handling(self):
        """Test exception handling."""
        from nanocode.tools.builtin.free_search import FreeExaSearchTool

        tool = FreeExaSearchTool()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                side_effect=Exception("Network error")
            )

            result = await tool.execute(query="test")

            assert result.success is False
            assert result.content is None
            assert "network error" in result.error.lower()


class TestFreeExaSearchToolDefaults:
    """Tests for default values."""

    def test_default_num_results(self):
        """Test default num_results is 10."""
        from nanocode.tools.builtin.free_search import FreeExaSearchTool

        tool = FreeExaSearchTool()
        assert tool.parameters["properties"]["num_results"]["default"] == 10

    def test_default_mode(self):
        """Test default mode is web_search."""
        from nanocode.tools.builtin.free_search import FreeExaSearchTool

        tool = FreeExaSearchTool()
        assert tool.parameters["properties"]["mode"]["default"] == "web_search"

    @pytest.mark.asyncio
    async def test_execute_without_mode_uses_default(self):
        """Test execute without mode parameter uses default web_search."""
        from nanocode.tools.builtin.free_search import FreeExaSearchTool

        tool = FreeExaSearchTool()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": []}

        with patch("httpx.AsyncClient") as mock_client:
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            result = await tool.execute(query="test")

            assert result.success is True
            assert result.metadata["mode"] == "web_search"