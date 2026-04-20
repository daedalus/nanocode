"""Text-to-Tool detection and command extraction.

This module handles cases where:
1. Model outputs text that looks like a command (e.g., "find . -name '*.py'")
2. Model doesn't use tools when it should
3. Need to extract structured commands from freeform text
"""

import json
import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class DetectedCommand:
    """A command detected in text."""
    command: str
    tool_name: str  # e.g., "bash", "edit", "read"
    confidence: float  # 0.0 to 1.0
    explanation: str


# Patterns that indicate a command should be executed
COMMAND_PATTERNS = {
    "bash": [
        # Match content inside code blocks (most flexible)
        r"```\s*\n([^\n]+(?:(?:\n[^\n]+)*))",
        # Inline backtick commands
        r"`(\$[^\n`]+)`",
        r"`(ls\s+[^\n`]+)`",
        r"`(cd\s+[^\n`]+)`",
        r"`(grep\s+[^\n`]+)`",
        r"`(find\s+[^\n`]+)`",
        r"`(python\s+[^\n`]+)`",
        r"`(npm\s+[^\n`]+)`",
        r"`(git\s+[^\n`]+)`",
    ],
    "read": [
        r"(?:read|view|show|cat)\s+(?:the\s+)?(?:file\s+)?[`'\"]([^`'\"]+)[`'\"]",
        r"(?:content|contents)\s+of\s+[`'\"]([^`'\"]+)[`'\"]",
    ],
    "edit": [
        r"(?:edit|modify|change|update)\s+(?:the\s+)?(?:file\s+)?[`'\"]([^`'\"]+)[`'\"]",
        r"(?:replace|substitute)\s+[`'\"][^`'\"]+[`'\"]\s+(?:in|with)\s+[`'\"]([^`'\"]+)[`'\"]",
    ],
    "write": [
        r"(?:write|create|make)\s+(?:new\s+)?(?:file\s+)?[`'\"]([^`'\"]+)[`'\"]",
        r"(?:add|saved)\s+(?:the\s+)?following\s+(?:to|in)\s+[`'\"]([^`'\"]+)[`'\"]",
    ],
}

# Common shell commands that should be detected
SHELL_COMMANDS = {"find", "grep", "ls", "cd", "python", "npm", "git", "pip", "uv", "pytest", "./", "mkdir", "rm", "cp", "mv", "cat", "head", "tail", "chmod", "chown"}


def detect_commands_in_text(text: str) -> list[DetectedCommand]:
    """Detect commands in text that should be tool calls.

    This helps handle cases where the model outputs text that looks like
    a command but doesn't explicitly use a tool call.

    Args:
        text: The assistant's text response

    Returns:
        List of detected commands with confidence scores
    """
    detected = []
    text_lower = text.lower()

    # Extract code block contents first (most reliable for commands)
    code_block_pattern = r"```(?:\w+)?\s*\n?(.*?)```"
    for match in re.finditer(code_block_pattern, text, re.DOTALL):
        content = match.group(1).strip()
        first_word = content.split()[0] if content.split() else ""
        # Check if it looks like a shell command
        if first_word in SHELL_COMMANDS or first_word.startswith("./") or first_word.startswith("-"):
            if len(content) > 3 and not content.startswith("#"):
                detected.append(DetectedCommand(
                    command=content,
                    tool_name="bash",
                    confidence=0.9 if first_word in SHELL_COMMANDS else 0.7,
                    explanation=f"Detected bash command in code block"
                ))

    # Check inline backticks (`command`)
    inline_pattern = r"`([^`]+)`"
    for match in re.finditer(inline_pattern, text):
        content = match.group(1).strip()
        if not content:
            continue
        first_word = content.split()[0] if content.split() else ""
        # Determine if it's a command or file path
        if first_word in SHELL_COMMANDS:
            detected.append(DetectedCommand(
                command=content,
                tool_name="bash",
                confidence=0.8,
                explanation=f"Detected bash command in backticks"
            ))
        elif "." in content or "/" in content or first_word.endswith(".py") or first_word.endswith(".yaml") or first_word.endswith(".json"):
            # Looks like a file path
            detected.append(DetectedCommand(
                command=content,
                tool_name="read",
                confidence=0.7,
                explanation=f"Detected file path in backticks"
            ))

    # Check for read commands in text
    for pattern in COMMAND_PATTERNS["read"]:
        matches = re.finditer(pattern, text, re.IGNORECASE)
        for match in matches:
            filepath = match.group(1).strip()
            detected.append(DetectedCommand(
                command=filepath,
                tool_name="read",
                confidence=0.7,
                explanation=f"Detected file path: {filepath}"
            ))

    # Deduplicate results
    seen = set()
    unique_detected = []
    for cmd in detected:
        key = (cmd.tool_name, cmd.command)
        if key not in seen:
            seen.add(key)
            unique_detected.append(cmd)
    detected = unique_detected

    return detected


def extract_json_from_text(text: str) -> Optional[dict]:
    """Try to extract JSON from text that might contain it.

    Some models output JSON in code blocks or as raw text.
    """
    # Try code block first
    json_match = re.search(r"```(?:json)?\s*\n(.+?)\n```", text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    # Try raw JSON
    json_match = re.search(r"^\s*(\{[\s\S]*\})\s*$", text, re.MULTILINE)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    return None


def format_detected_commands_message(commands: list[DetectedCommand]) -> str:
    """Format detected commands for user presentation."""
    if not commands:
        return ""

    lines = ["\n⚠ Detected commands in response that were not executed:\n"]
    for i, cmd in enumerate(commands, 1):
        lines.append(f"{i}. [{cmd.tool_name}] {cmd.command}")
        if len(cmd.command) > 80:
            lines[-1] += "..."

    lines.append("\nYou can execute these manually or re-prompt.")
    return "\n".join(lines)


def should_reprompt_for_tools(response_text: str | None, tools_were_expected: bool = True) -> tuple[bool, str]:
    """Check if model should have used tools instead of describing them in text.

    Args:
        response_text: The model's text response (can be None)
        tools_were_expected: Whether tools were available (default True)

    Returns:
        Tuple of (should_reprompt, reason)
    """
    if not response_text:
        return False, ""

    response_text = str(response_text)

    # Only trigger if response actually contains shell-like commands or specific tool patterns
    # Don't trigger on general task descriptions like "find bugs"
    shell_like_patterns = [
        r"find\s+[-.\w]+\s+",  # find -name, find . -type
        r"grep\s+['\"]",  # grep "pattern"
        r"ls\s+[-\w]+",  # ls -la
        r"cd\s+\S+",  # cd some/path
        r"python\s+\S+",  # python script.py
        r"npm\s+(install|run|test)",  # npm install, npm run
        r"pytest\s+",  # pytest tests/
        r"git\s+(status|log|diff|branch)",  # git commands
    ]
    
    has_shell_like = any(re.search(p, response_text) for p in shell_like_patterns)
    
    if not has_shell_like:
        return False, ""

    # Indicators that response is complete without tools
    completion_indicators = [
        "here is", "the answer", "summary:", "conclusion:",
        "as follows:", "```", "done.", "finished.",
        "i have", "based on", "according to",
    ]
    
    has_completion = any(ind in response_text.lower() for ind in completion_indicators)

    if tools_were_expected and not has_completion:
        return True, (
            "Response contains shell-like commands but did not use the available tools. "
            "Consider re-prompting to use tools directly."
        )

    return False, ""


def create_reprompt_message(commands: list[DetectedCommand] = None) -> str:
    """Create a re-prompt that asks the model to use tools.

    Args:
        commands: Optional list of detected commands

    Returns:
        Re-prompt message
    """
    message = (
        "\n\nIMPORTANT: Your previous response did not use the available tools "
        "to complete the task. You have access to the following tools:\n"
        "- bash: Execute shell commands\n"
        "- read: Read file contents\n"
        "- glob: Find files by pattern\n"
        "- grep: Search file contents\n"
        "- edit: Make changes to files\n"
        "- write: Create new files\n\n"
    )

    if commands:
        message += (
            "Please execute the necessary commands using the appropriate tools. "
            "Here are commands that were detected in your previous response:\n"
        )
        for cmd in commands:
            message += f"- [{cmd.tool_name}] {cmd.command}\n"
        message += "\n"

    message += "Use the tools to complete the task and report the results."
    return message
