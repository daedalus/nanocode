"""GitHub integration for authentication, PR management, and repository operations.

This module provides:
- GitHub OAuth and Personal Access Token authentication
- Pull Request creation, listing, and management
- Issue and comment operations
- Repository information lookup
"""

import os
import subprocess
from dataclasses import dataclass
from typing import Optional

from github import Github, GithubIntegration, Auth
from github.PullRequest import PullRequest


@dataclass
class GitHubAuth:
    """GitHub authentication configuration."""

    token: Optional[str] = None
    app_id: Optional[str] = None
    app_private_key: Optional[str] = None
    installation_id: Optional[str] = None


class GitHubClient:
    """GitHub API client with authentication support."""

    def __init__(
        self,
        token: Optional[str] = None,
        app_id: Optional[str] = None,
        app_private_key: Optional[str] = None,
        installation_id: Optional[str] = None,
    ):
        """Initialize GitHub client.

        Args:
            token: Personal Access Token or OAuth token
            app_id: GitHub App ID (for app authentication)
            app_private_key: GitHub App private key
            installation_id: GitHub App installation ID
        """
        self._github: Optional[Github] = None
        self._token = token
        self._app_id = app_id
        self._app_private_key = app_private_key
        self._installation_id = installation_id
        self._installation_token: Optional[str] = None

    def _get_github_client(self) -> Github:
        """Get or create the GitHub client."""
        if self._github is not None:
            return self._github

        if self._installation_token:
            self._github = Github(auth=Auth.Token(self._installation_token))
        elif self._token:
            self._github = Github(auth=Auth.Token(self._token))
        elif self._app_id and self._app_private_key and self._installation_id:
            self._github = self._create_app_client()
        else:
            self._github = Github()

        return self._github

    def _create_app_client(self) -> Github:
        """Create client using GitHub App authentication."""
        auth = Auth.AppAuth(
            app_id=self._app_id,
            private_key=self._app_private_key,
        )
        integration = GithubIntegration(auth=auth)
        self._installation_token = integration.get_access_token(int(self._installation_id)).token
        return Github(auth=Auth.Token(self._installation_token))

    def authenticate_with_token(self, token: str) -> "GitHubClient":
        """Authenticate with a personal access token or OAuth token."""
        self._token = token
        self._github = None
        return self

    def authenticate_with_app(
        self, app_id: str, private_key: str, installation_id: str
    ) -> "GitHubClient":
        """Authenticate as a GitHub App."""
        self._app_id = app_id
        self._app_private_key = private_key
        self._installation_id = installation_id
        self._github = None
        return self

    @property
    def user(self):
        """Get authenticated user."""
        return self._get_github_client().get_user()

    @property
    def rate_limit(self):
        """Get current rate limit status."""
        return self._get_github_client().get_rate_limit()

    def get_repo(self, full_name: str):
        """Get a repository by full name (owner/repo)."""
        return self._get_github_client().get_repo(full_name)

    def get_current_user_repos(self, sort="updated", limit=30):
        """Get repositories for the authenticated user."""
        return list(self.user.get_repos(sort=sort, per_page=limit))

    def search_repos(self, query: str, limit=30):
        """Search repositories."""
        return list(self._get_github_client().search_repositories(query, per_page=limit))

    def get_pull_request(self, repo: str, pr_number: int) -> PullRequest:
        """Get a pull request by number."""
        return self.get_repo(repo).get_pull(pr_number)

    def list_pull_requests(
        self,
        repo: str,
        state: str = "open",
        head: Optional[str] = None,
        base: Optional[str] = None,
    ) -> list[PullRequest]:
        """List pull requests in a repository."""
        repo_obj = self.get_repo(repo)
        return list(repo_obj.get_pulls(state=state, head=head, base=base))

    def create_pull_request(
        self,
        repo: str,
        title: str,
        body: str,
        head: str,
        base: str = "main",
    ) -> PullRequest:
        """Create a new pull request."""
        repo_obj = self.get_repo(repo)
        return repo_obj.create_pull(title=title, body=body, head=head, base=base)

    def get_issue(self, repo: str, issue_number: int):
        """Get an issue by number."""
        return self.get_repo(repo).get_issue(issue_number)

    def list_issues(
        self, repo: str, state: str = "open", labels: Optional[list[str]] = None
    ) -> list:
        """List issues in a repository."""
        repo_obj = self.get_repo(repo)
        issues = repo_obj.get_issues(state=state)
        if labels:
            return [i for i in issues if any(label.name in labels for label in i.labels)]
        return list(issues)

    def create_issue(self, repo: str, title: str, body: str, labels: Optional[list[str]] = None):
        """Create a new issue."""
        repo_obj = self.get_repo(repo)
        return repo_obj.create_issue(title=title, body=body, labels=labels or [])

    def add_issue_comment(self, repo: str, issue_number: int, body: str) -> None:
        """Add a comment to an issue."""
        issue = self.get_issue(repo, issue_number)
        issue.create_comment(body)

    def add_pr_comment(self, repo: str, pr_number: int, body: str) -> None:
        """Add a comment to a pull request."""
        pr = self.get_pull_request(repo, pr_number)
        pr.create_review_comment(body)

    def get_pr_files(self, repo: str, pr_number: int) -> list:
        """Get files changed in a pull request."""
        pr = self.get_pull_request(repo, pr_number)
        return list(pr.get_files())

    def get_pr_commits(self, repo: str, pr_number: int) -> list:
        """Get commits in a pull request."""
        pr = self.get_pull_request(repo, pr_number)
        return list(pr.get_commits())

    def get_pr_diff(self, repo: str, pr_number: int) -> str:
        """Get the diff of a pull request."""
        pr = self.get_pull_request(repo, pr_number)
        return pr.as_dict().get("diff_url", "")

    def get_branch(self, repo: str, branch: str):
        """Get a branch from a repository."""
        return self.get_repo(repo).get_branch(branch)

    def create_branch(self, repo: str, branch: str, sha: str):
        """Create a new branch."""
        repo_obj = self.get_repo(repo)
        repo_obj.create_git_ref(f"refs/heads/{branch}", sha)

    def merge_pr(self, repo: str, pr_number: int, message: str = "") -> bool:
        """Merge a pull request."""
        pr = self.get_pull_request(repo, pr_number)
        return pr.merge(message)

    def close_pr(self, repo: str, pr_number: int) -> None:
        """Close a pull request without merging."""
        pr = self.get_pull_request(repo, pr_number)
        pr.edit(state="closed")

    def get_file_content(self, repo: str, path: str, ref: str = "main") -> str:
        """Get file content from repository."""
        repo_obj = self.get_repo(repo)
        return repo_obj.get_contents(path, ref).decoded_content.decode("utf-8")


class GitHubGitOperations:
    """Git operations using GitHub CLI and local git."""

    @staticmethod
    def is_github_repo() -> tuple[bool, Optional[str]]:
        """Check if current directory is a GitHub repository.

        Returns:
            Tuple of (is_github, repo_full_name)
        """
        try:
            result = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                url = result.stdout.strip()
                if "github.com" in url:
                    owner_repo = GitHubGitOperations._parse_github_url(url)
                    if owner_repo:
                        return True, owner_repo
            return False, None
        except Exception:
            return False, None

    @staticmethod
    def _parse_github_url(url: str) -> Optional[str]:
        """Parse GitHub URL to get owner/repo."""
        url = url.replace(".git", "")
        if "github.com/" in url:
            parts = url.split("github.com/")[-1].split("/")
            if len(parts) >= 2:
                return f"{parts[0]}/{parts[1]}"
        if url.startswith("git@github.com:"):
            parts = url.replace("git@github.com:", "").split("/")
            if len(parts) >= 2:
                return f"{parts[0]}/{parts[1]}"
        return None

    @staticmethod
    def get_current_branch() -> Optional[str]:
        """Get the current git branch."""
        try:
            result = subprocess.run(
                ["git", "branch", "--show-current"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.stdout.strip() if result.returncode == 0 else None
        except Exception:
            return None

    @staticmethod
    def get_default_branch() -> Optional[str]:
        """Get the default branch of the repository."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD@{upstream}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                return "main"
            return "main"
        except Exception:
            return "main"

    @staticmethod
    def checkout_branch(branch: str, create: bool = False) -> bool:
        """Checkout or create a branch."""
        try:
            if create:
                subprocess.run(
                    ["git", "checkout", "-b", branch],
                    check=True,
                    timeout=10,
                )
            else:
                subprocess.run(
                    ["git", "checkout", branch],
                    check=True,
                    timeout=10,
                )
            return True
        except Exception:
            return False

    @staticmethod
    def push_branch(branch: str, force: bool = False, remote: str = "origin") -> bool:
        """Push branch to remote."""
        try:
            cmd = ["git", "push", remote, branch]
            if force:
                cmd.append("--force")
            subprocess.run(cmd, check=True, timeout=30)
            return True
        except Exception:
            return False

    @staticmethod
    def create_branch_from_remote(
        new_branch: str, remote_branch: str, remote: str = "origin"
    ) -> bool:
        """Create a new branch from a remote branch."""
        try:
            subprocess.run(
                ["git", "fetch", remote, remote_branch],
                check=True,
                timeout=30,
            )
            subprocess.run(
                ["git", "checkout", "-b", new_branch, f"{remote}/{remote_branch}"],
                check=True,
                timeout=10,
            )
            return True
        except Exception:
            return False

    @staticmethod
    def get_latest_commit_sha(branch: str = "HEAD") -> Optional[str]:
        """Get the SHA of the latest commit on a branch."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", branch],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.stdout.strip() if result.returncode == 0 else None
        except Exception:
            return None


def create_github_client(config: dict = None) -> Optional[GitHubClient]:
    """Create a GitHub client from configuration.

    Args:
        config: Configuration dictionary with GitHub settings

    Returns:
        GitHubClient instance or None if not configured
    """
    if config is None:
        config = {}

    github_config = config.get("github", {})

    token = github_config.get("token") or os.getenv("GITHUB_TOKEN")
    app_id = github_config.get("app_id")
    app_private_key = github_config.get("app_private_key")
    installation_id = github_config.get("installation_id")

    if not token and not app_id:
        return None

    return GitHubClient(
        token=token,
        app_id=app_id,
        app_private_key=app_private_key,
        installation_id=installation_id,
    )
