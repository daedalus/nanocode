"""GitHub tools for the agent."""

from typing import Optional
from nanocode.tools import Tool, ToolResult
from nanocode.github import GitHubClient, GitHubGitOperations, create_github_client


class GitHubTool(Tool):
    """Tool for GitHub operations."""

    def __init__(self, github_client: GitHubClient = None):
        super().__init__(
            name="github",
            description="Perform GitHub operations like listing PRs, creating issues, etc.",
        )
        self.github_client = github_client
        self.git_ops = GitHubGitOperations()

    async def execute(
        self,
        operation: str,
        repo: Optional[str] = None,
        pr_number: Optional[int] = None,
        title: Optional[str] = None,
        body: Optional[str] = None,
        head: Optional[str] = None,
        base: Optional[str] = None,
        state: Optional[str] = None,
        issue_number: Optional[int] = None,
        comment: Optional[str] = None,
    ) -> ToolResult:
        """Execute a GitHub operation."""
        if not self.github_client:
            is_github, repo = self.git_ops.is_github_repo()
            if not is_github:
                return ToolResult(
                    success=False,
                    content=None,
                    error="Not in a GitHub repository. Configure GitHub token or run in a GitHub repo.",
                )
            client = create_github_client()
            if client:
                self.github_client = client
            else:
                return ToolResult(
                    success=False,
                    content=None,
                    error="GitHub not configured. Set GITHUB_TOKEN or configure in config.yaml.",
                )

        try:
            if operation == "list_prs":
                return await self._list_prs(repo, state, head, base)
            elif operation == "get_pr":
                return await self._get_pr(repo, pr_number)
            elif operation == "create_pr":
                return await self._create_pr(repo, title, body, head, base)
            elif operation == "list_issues":
                return await self._list_issues(repo, state)
            elif operation == "get_issue":
                return await self._get_issue(repo, issue_number)
            elif operation == "create_issue":
                return await self._create_issue(repo, title, body)
            elif operation == "add_comment":
                return await self._add_comment(repo, issue_number or pr_number, comment)
            elif operation == "get_pr_files":
                return await self._get_pr_files(repo, pr_number)
            elif operation == "get_current_repo":
                return await self._get_current_repo()
            elif operation == "get_current_branch":
                return await self._get_current_branch()
            else:
                return ToolResult(
                    success=False,
                    content=None,
                    error=f"Unknown operation: {operation}",
                )
        except Exception as e:
            return ToolResult(success=False, content=None, error=str(e))

    async def _list_prs(
        self,
        repo: str,
        state: str = "open",
        head: Optional[str] = None,
        base: Optional[str] = None,
    ) -> ToolResult:
        """List pull requests."""
        prs = self.github_client.list_pull_requests(repo, state, head, base)
        results = []
        for pr in prs[:20]:
            results.append(
                {
                    "number": pr.number,
                    "title": pr.title,
                    "state": pr.state,
                    "author": pr.user.login if pr.user else "unknown",
                    "base": pr.base.ref,
                    "head": pr.head.ref,
                    "url": pr.html_url,
                }
            )
        return ToolResult(
            success=True,
            content=results,
            metadata={"count": len(results)},
        )

    async def _get_pr(self, repo: str, pr_number: int) -> ToolResult:
        """Get a pull request."""
        pr = self.github_client.get_pull_request(repo, pr_number)
        files = self.github_client.get_pr_files(repo, pr_number)
        return ToolResult(
            success=True,
            content={
                "number": pr.number,
                "title": pr.title,
                "body": pr.body,
                "state": pr.state,
                "author": pr.user.login if pr.user else "unknown",
                "base": pr.base.ref,
                "head": pr.head.ref,
                "url": pr.html_url,
                "files": [
                    {
                        "filename": f.filename,
                        "status": f.status,
                        "additions": f.additions,
                        "deletions": f.deletions,
                    }
                    for f in files[:10]
                ],
            },
        )

    async def _create_pr(
        self,
        repo: str,
        title: str,
        body: str,
        head: str,
        base: str = "main",
    ) -> ToolResult:
        """Create a pull request."""
        pr = self.github_client.create_pull_request(repo, title, body, head, base)
        return ToolResult(
            success=True,
            content={
                "number": pr.number,
                "title": pr.title,
                "url": pr.html_url,
            },
        )

    async def _list_issues(self, repo: str, state: str = "open") -> ToolResult:
        """List issues."""
        issues = self.github_client.list_issues(repo, state)
        results = []
        for issue in issues[:20]:
            results.append(
                {
                    "number": issue.number,
                    "title": issue.title,
                    "state": issue.state,
                    "author": issue.user.login if issue.user else "unknown",
                    "labels": [label.name for label in issue.labels],
                    "url": issue.html_url,
                }
            )
        return ToolResult(
            success=True,
            content=results,
            metadata={"count": len(results)},
        )

    async def _get_issue(self, repo: str, issue_number: int) -> ToolResult:
        """Get an issue."""
        issue = self.github_client.get_issue(repo, issue_number)
        return ToolResult(
            success=True,
            content={
                "number": issue.number,
                "title": issue.title,
                "body": issue.body,
                "state": issue.state,
                "author": issue.user.login if issue.user else "unknown",
                "labels": [label.name for label in issue.labels],
                "url": issue.html_url,
            },
        )

    async def _create_issue(self, repo: str, title: str, body: str) -> ToolResult:
        """Create an issue."""
        issue = self.github_client.create_issue(repo, title, body)
        return ToolResult(
            success=True,
            content={
                "number": issue.number,
                "title": issue.title,
                "url": issue.html_url,
            },
        )

    async def _add_comment(self, repo: str, number: int, comment: str) -> ToolResult:
        """Add a comment to an issue or PR."""
        self.github_client.add_issue_comment(repo, number, comment)
        return ToolResult(
            success=True,
            content=f"Comment added to {repo}#{number}",
        )

    async def _get_pr_files(self, repo: str, pr_number: int) -> ToolResult:
        """Get files changed in a PR."""
        files = self.github_client.get_pr_files(repo, pr_number)
        results = [
            {
                "filename": f.filename,
                "status": f.status,
                "additions": f.additions,
                "deletions": f.deletions,
                "changes": f.changes,
            }
            for f in files
        ]
        return ToolResult(
            success=True,
            content=results,
            metadata={"count": len(results)},
        )

    async def _get_current_repo(self) -> ToolResult:
        """Get current GitHub repository info."""
        is_github, repo = self.git_ops.is_github_repo()
        if not is_github:
            return ToolResult(success=False, content=None, error="Not in a GitHub repository")
        return ToolResult(success=True, content={"repo": repo})

    async def _get_current_branch(self) -> ToolResult:
        """Get current git branch."""
        branch = self.git_ops.get_current_branch()
        if not branch:
            return ToolResult(success=False, content=None, error="Not in a git repository")
        return ToolResult(success=True, content={"branch": branch})


def create_github_tool(config: dict = None) -> Optional[GitHubTool]:
    """Create a GitHub tool from configuration."""
    client = create_github_client(config)
    if client:
        return GitHubTool(github_client=client)

    is_github, _ = GitHubGitOperations.is_github_repo()
    if is_github:
        return GitHubTool()

    return None
