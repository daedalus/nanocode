"""Unit tests for GitHub integration."""

import pytest
from unittest.mock import Mock, patch

from nanocode.github import (
    GitHubClient,
    GitHubGitOperations,
    create_github_client,
)
from nanocode.github.tools import GitHubTool


class TestGitHubClient:
    """Tests for GitHubClient."""

    @patch("nanocode.github.Github")
    def test_client_init_with_token(self, mock_github):
        """Test client initialization with token."""
        client = GitHubClient(token="test_token")
        assert client._token == "test_token"
        assert client._github is None

    @patch("nanocode.github.Github")
    def test_client_init_with_app(self, mock_github):
        """Test client initialization with GitHub App."""
        client = GitHubClient(
            app_id="12345",
            app_private_key="private_key",
            installation_id="67890",
        )
        assert client._app_id == "12345"
        assert client._app_private_key == "private_key"
        assert client._installation_id == "67890"

    @patch("nanocode.github.Github")
    def test_authenticate_with_token(self, mock_github):
        """Test authenticating with a token."""
        client = GitHubClient()
        result = client.authenticate_with_token("new_token")
        assert result is client
        assert client._token == "new_token"
        assert client._github is None

    @patch("nanocode.github.Github")
    def test_authenticate_with_app(self, mock_github):
        """Test authenticating with GitHub App."""
        client = GitHubClient()
        result = client.authenticate_with_app("12345", "private_key", "67890")
        assert result is client
        assert client._app_id == "12345"
        assert client._app_private_key == "private_key"
        assert client._installation_id == "67890"


class TestGitHubGitOperations:
    """Tests for GitHubGitOperations."""

    @patch("subprocess.run")
    def test_is_github_repo_https(self, mock_run):
        """Test detecting GitHub repo with HTTPS URL."""
        mock_run.return_value = Mock(
            returncode=0,
            stdout="https://github.com/owner/repo.git",
        )
        is_github, repo = GitHubGitOperations.is_github_repo()
        assert is_github is True
        assert repo == "owner/repo"

    @patch("subprocess.run")
    def test_is_github_repo_ssh(self, mock_run):
        """Test detecting GitHub repo with SSH URL."""
        mock_run.return_value = Mock(
            returncode=0,
            stdout="git@github.com:owner/repo.git",
        )
        is_github, repo = GitHubGitOperations.is_github_repo()
        assert is_github is True
        assert repo == "owner/repo"

    @patch("subprocess.run")
    def test_is_not_github_repo(self, mock_run):
        """Test detecting non-GitHub repo."""
        mock_run.return_value = Mock(
            returncode=0,
            stdout="https://gitlab.com/owner/repo.git",
        )
        is_github, repo = GitHubGitOperations.is_github_repo()
        assert is_github is False

    @patch("subprocess.run")
    def test_parse_github_url_https(self, mock_run):
        """Test parsing HTTPS GitHub URL."""
        url = "https://github.com/owner/repo.git"
        repo = GitHubGitOperations._parse_github_url(url)
        assert repo == "owner/repo"

    @patch("subprocess.run")
    def test_parse_github_url_ssh(self, mock_run):
        """Test parsing SSH GitHub URL."""
        url = "git@github.com:owner/repo.git"
        repo = GitHubGitOperations._parse_github_url(url)
        assert repo == "owner/repo"

    @patch("subprocess.run")
    def test_get_current_branch(self, mock_run):
        """Test getting current branch."""
        mock_run.return_value = Mock(returncode=0, stdout="main")
        branch = GitHubGitOperations.get_current_branch()
        assert branch == "main"

    @patch("subprocess.run")
    def test_get_current_branch_error(self, mock_run):
        """Test getting current branch with error."""
        mock_run.side_effect = Exception("Not a git repo")
        branch = GitHubGitOperations.get_current_branch()
        assert branch is None


class TestCreateGitHubClient:
    """Tests for create_github_client."""

    @patch("nanocode.github.Github")
    def test_create_client_with_token(self, mock_github):
        """Test creating client with token from config."""
        config = {"github": {"token": "test_token"}}
        client = create_github_client(config)
        assert client is not None
        assert client._token == "test_token"

    @patch("nanocode.github.Github")
    def test_create_client_from_env(self, mock_github):
        """Test creating client with token from environment."""
        with patch.dict("os.environ", {"GITHUB_TOKEN": "env_token"}):
            client = create_github_client({})
        assert client is not None
        assert client._token == "env_token"

    def test_create_client_no_config(self):
        """Test creating client with no configuration."""
        client = create_github_client(None)
        assert client is None


class TestGitHubTool:
    """Tests for GitHubTool."""

    def test_tool_init(self):
        """Test tool initialization."""
        tool = GitHubTool()
        assert tool.name == "github"
        assert tool.description is not None

    @patch("nanocode.github.Github")
    def test_tool_init_with_client(self, mock_github):
        """Test tool initialization with client."""
        client = GitHubClient(token="test")
        tool = GitHubTool(github_client=client)
        assert tool.github_client is client

    @pytest.mark.asyncio
    @patch("nanocode.github.Github")
    async def test_tool_get_current_repo(self, mock_github):
        """Test getting current repo."""
        mock_git_ops = Mock()
        mock_git_ops.is_github_repo.return_value = (True, "owner/repo")

        mock_client = Mock()

        tool = GitHubTool(github_client=mock_client)
        tool.git_ops = mock_git_ops

        result = await tool.execute(operation="get_current_repo")
        assert result.success is True

    @pytest.mark.asyncio
    @patch("nanocode.github.Github")
    async def test_tool_get_current_branch(self, mock_github):
        """Test getting current branch."""
        mock_git_ops = Mock()
        mock_git_ops.get_current_branch.return_value = "feature-branch"

        mock_client = Mock()

        tool = GitHubTool(github_client=mock_client)
        tool.git_ops = mock_git_ops

        result = await tool.execute(operation="get_current_branch")
        assert result.success is True
        assert "feature-branch" in str(result.content)


class TestGitHubToolOperations:
    """Tests for GitHub tool operations."""

    @pytest.mark.asyncio
    @patch("nanocode.github.Github")
    async def test_list_prs_operation(self, mock_github):
        """Test list_prs operation."""
        mock_pr = Mock()
        mock_pr.number = 1
        mock_pr.title = "Test PR"
        mock_pr.state = "open"
        mock_pr.user = Mock(login="testuser")
        mock_pr.base = Mock(ref="main")
        mock_pr.head = Mock(ref="feature")
        mock_pr.html_url = "https://github.com/owner/repo/pull/1"

        mock_client = Mock()
        mock_client.list_pull_requests.return_value = [mock_pr]

        tool = GitHubTool(github_client=mock_client)

        result = await tool.execute(operation="list_prs", repo="owner/repo")
        assert result.success is True

    @pytest.mark.asyncio
    @patch("nanocode.github.Github")
    async def test_unknown_operation(self, mock_github):
        """Test unknown operation."""
        mock_github_client = Mock()
        tool = GitHubTool(github_client=mock_github_client)

        result = await tool.execute(operation="unknown_op")
        assert result.success is False
        assert result.error is not None
        assert "Unknown operation" in result.error
