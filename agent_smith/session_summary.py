"""Session summary generation - creates PR-like summaries of agent work."""

import os
import subprocess
from dataclasses import dataclass, field


SUMMARY_PROMPT = """Summarize what was done in this conversation. Write like a pull request description.

Rules:
- 2-3 sentences max
- Describe the changes made, not the process
- Do not mention running tests, builds, or other validation steps
- Do not explain what the user asked for
- Write in first person (I added..., I fixed...)
- Never ask questions or add new questions
- If the conversation ends with an unanswered question to the user, preserve that exact question
- If the conversation ends with an imperative statement or request to the user (e.g. "Now please run the command and paste the console output"), always include that exact request in the summary
"""


@dataclass
class FileChange:
    """Represents a file change."""

    file: str
    additions: int
    deletions: int


@dataclass
class SessionSummary:
    """Summary of session work."""

    additions: int = 0
    deletions: int = 0
    files: int = 0
    text: str = ""
    diffs: list[FileChange] = field(default_factory=list)


class SessionSummaryGenerator:
    """Generates summaries for agent sessions."""

    def __init__(self, llm, storage=None):
        self.llm = llm
        self.storage = storage

    async def summarize(self, messages: list, tool_results: list = None) -> SessionSummary:
        """Generate a summary for the session."""
        summary = SessionSummary()

        summary.diffs = await self._compute_diffs()
        summary.additions = sum(d.additions for d in summary.diffs)
        summary.deletions = sum(d.deletions for d in summary.diffs)
        summary.files = len(summary.diffs)

        if self.llm:
            summary.text = await self._generate_text_summary(messages, tool_results)

        if self.storage:
            await self._save_summary(summary)

        return summary

    async def _compute_diffs(self) -> list[FileChange]:
        """Compute file changes using git diff."""
        try:
            result = subprocess.run(
                ["git", "diff", "--stat"],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=os.getcwd(),
            )

            if result.returncode != 0:
                return []

            diffs = []
            for line in result.stdout.strip().split("\n"):
                if not line.strip() or "files changed" in line:
                    continue

                parts = line.split("|")
                if len(parts) >= 2:
                    file_path = parts[0].strip()
                    stats = parts[-1].strip()

                    additions = 0
                    deletions = 0

                    import re

                    match = re.search(r"(\d+)\s+additions?", stats)
                    if match:
                        additions = int(match.group(1))
                    match = re.search(r"(\d+)\s+deletions?", stats)
                    if match:
                        deletions = int(match.group(1))

                    if not additions and not deletions:
                        plus_count = stats.count("+")
                        minus_count = stats.count("-")
                        if plus_count or minus_count:
                            additions = plus_count
                            deletions = minus_count

                    if additions or deletions:
                        diffs.append(
                            FileChange(
                                file=file_path,
                                additions=additions,
                                deletions=deletions,
                            )
                        )

            return diffs

        except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
            return []

            diffs = []
            for line in result.stdout.strip().split("\n"):
                if not line.strip() or "files changed" in line:
                    continue

                parts = line.split("|")
                if len(parts) >= 2:
                    file_path = parts[0].strip()
                    stats = parts[-1].strip()

                    additions = 0
                    deletions = 0

                    import re

                    match = re.search(r"(\d+)\s+additions?", stats)
                    if match:
                        additions = int(match.group(1))
                    match = re.search(r"(\d+)\s+deletions?", stats)
                    if match:
                        deletions = int(match.group(1))

                    if additions or deletions:
                        diffs.append(
                            FileChange(
                                file=file_path,
                                additions=additions,
                                deletions=deletions,
                            )
                        )
                    else:
                        match = re.search(r"(\d+)\s+(\d+)", stats)
                        if match:
                            additions = int(match.group(1))
                            deletions = int(match.group(2))
                            diffs.append(
                                FileChange(
                                    file=file_path,
                                    additions=additions,
                                    deletions=deletions,
                                )
                            )

            return diffs

        except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
            return []

            diffs = []
            for line in result.stdout.strip().split("\n"):
                parts = line.split("\t")
                if len(parts) >= 2:
                    file_path = parts[0].strip()
                    stats = parts[-1].strip()

                    additions = 0
                    deletions = 0

                    if "+" in stats:
                        add_part = stats.split("+")[-1].split(",")[0]
                        try:
                            additions = int(add_part)
                        except ValueError:
                            pass

                    if "-" in stats:
                        del_part = stats.split("-")[-1].split(",")[0]
                        try:
                            deletions = int(del_part)
                        except ValueError:
                            pass

                    if additions or deletions:
                        diffs.append(
                            FileChange(
                                file=file_path,
                                additions=additions,
                                deletions=deletions,
                            )
                        )

            return diffs

        except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
            return []

    async def _generate_text_summary(self, messages: list, tool_results: list = None) -> str:
        """Generate a text summary using the LLM."""
        if not self.llm:
            return ""

        conversation_parts = []

        for msg in messages[-6:]:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")

            if role == "system":
                continue

            if isinstance(content, str):
                content = content[:1000]
                conversation_parts.append(f"{role}: {content}")
            elif isinstance(content, dict):
                text = content.get("content", "")
                if text:
                    text = text[:1000]
                    conversation_parts.append(f"{role}: {text}")

        conversation = "\n\n".join(conversation_parts)

        if not conversation.strip():
            return ""

        prompt = f"""{SUMMARY_PROMPT}

Conversation:
{conversation}

Summary:"""

        try:
            from nanocode.llm import Message as LLMMessage

            response = await self.llm.chat([LLMMessage(role="user", content=prompt)])
            return response.content.strip() if response.content else ""
        except Exception:
            return ""

    async def _save_summary(self, summary: SessionSummary):
        """Save summary to storage."""
        pass


async def create_summary(llm, messages: list, storage=None) -> SessionSummary:
    """Create a session summary."""
    generator = SessionSummaryGenerator(llm, storage)
    return await generator.summarize(messages)
