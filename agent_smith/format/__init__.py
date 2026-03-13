"""Code formatting tools integration."""

import os
import subprocess
import shutil
from pathlib import Path
from typing import Optional
from dataclasses import dataclass
from abc import ABC, abstractmethod


@dataclass
class FormatterInfo:
    """Information about a formatter."""

    name: str
    command: list[str]
    extensions: list[str]
    environment: Optional[dict] = None


class Formatter(ABC):
    """Base class for formatters."""

    @property
    @abstractmethod
    def info(self) -> FormatterInfo:
        """Return formatter info."""
        pass

    async def is_enabled(self) -> bool:
        """Check if formatter is available."""
        return True

    async def format(self, file_path: str, cwd: str = None) -> bool:
        """Format a file."""
        cmd = [arg.replace("$FILE", file_path) for arg in self.info.command]
        env = os.environ.copy()
        if self.info.environment:
            env.update(self.info.environment)

        try:
            result = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                env=env,
            )
            return result.returncode == 0
        except Exception:
            return False


class GoFormat(Formatter):
    """Go formatter."""

    @property
    def info(self) -> FormatterInfo:
        return FormatterInfo(
            name="gofmt",
            command=["gofmt", "-w", "$FILE"],
            extensions=[".go"],
        )

    async def is_enabled(self) -> bool:
        return shutil.which("gofmt") is not None


class RustFormat(Formatter):
    """Rust formatter."""

    @property
    def info(self) -> FormatterInfo:
        return FormatterInfo(
            name="rustfmt",
            command=["rustfmt", "$FILE"],
            extensions=[".rs"],
        )

    async def is_enabled(self) -> bool:
        return shutil.which("rustfmt") is not None


class PythonFormatter(Formatter):
    """Python formatter (ruff or black)."""

    @property
    def info(self) -> FormatterInfo:
        return FormatterInfo(
            name="ruff",
            command=["ruff", "format", "$FILE"],
            extensions=[".py", ".pyi"],
        )

    async def is_enabled(self) -> bool:
        if shutil.which("ruff"):
            return True
        if shutil.which("black"):
            self._info.command = ["black", "$FILE"]
            self._info.name = "black"
            return True
        return False


class JavaScriptFormatter(Formatter):
    """JavaScript/TypeScript formatter (prettier or biome)."""

    def __init__(self):
        self._info = FormatterInfo(
            name="prettier",
            command=["npx", "prettier", "--write", "$FILE"],
            extensions=[
                ".js",
                ".jsx",
                ".mjs",
                ".cjs",
                ".ts",
                ".tsx",
                ".mts",
                ".cts",
                ".html",
                ".htm",
                ".css",
                ".scss",
                ".sass",
                ".less",
                ".vue",
                ".svelte",
                ".json",
                ".jsonc",
                ".yaml",
                ".yml",
                ".toml",
                ".xml",
                ".md",
                ".mdx",
                ".graphql",
                ".gql",
            ],
        )

    @property
    def info(self) -> FormatterInfo:
        return self._info

    async def is_enabled(self) -> bool:
        if shutil.which("prettier"):
            return True
        if shutil.which("npx"):
            return True
        if shutil.which("biome"):
            self._info.command = ["biome", "format", "--write", "$FILE"]
            self._info.name = "biome"
            return True
        return False


class ShellFormatter(Formatter):
    """Shell script formatter."""

    @property
    def info(self) -> FormatterInfo:
        return FormatterInfo(
            name="shfmt",
            command=["shfmt", "-w", "$FILE"],
            extensions=[".sh", ".bash"],
        )

    async def is_enabled(self) -> bool:
        return shutil.which("shfmt") is not None


class RubyFormatter(Formatter):
    """Ruby formatter."""

    @property
    def info(self) -> FormatterInfo:
        return FormatterInfo(
            name="rubocop",
            command=["rubocop", "--autocorrect", "$FILE"],
            extensions=[".rb", ".rake", ".gemspec", ".ru"],
        )

    async def is_enabled(self) -> bool:
        return shutil.which("rubocop") is not None


class PHPFormatter(Formatter):
    """PHP formatter."""

    @property
    def info(self) -> FormatterInfo:
        return FormatterInfo(
            name="pint",
            command=["./vendor/bin/pint", "$FILE"],
            extensions=[".php"],
        )

    async def is_enabled(self) -> bool:
        if shutil.which("pint"):
            return True
        vendor_pint = os.path.join(os.getcwd(), "vendor", "bin", "pint")
        if os.path.exists(vendor_pint):
            return True
        if shutil.which("php-cs-fixer"):
            self._info.command = ["php-cs-fixer", "fix", "$FILE"]
            self._info.name = "php-cs-fixer"
            return True
        return False


class DartFormatter(Formatter):
    """Dart formatter."""

    @property
    def info(self) -> FormatterInfo:
        return FormatterInfo(
            name="dart",
            command=["dart", "format", "$FILE"],
            extensions=[".dart"],
        )

    async def is_enabled(self) -> bool:
        return shutil.which("dart") is not None


class ElixirFormatter(Formatter):
    """Elixir formatter."""

    @property
    def info(self) -> FormatterInfo:
        return FormatterInfo(
            name="mix",
            command=["mix", "format", "$FILE"],
            extensions=[".ex", ".exs", ".eex", ".heex", ".leex", ".neex", ".sface"],
        )

    async def is_enabled(self) -> bool:
        return shutil.which("mix") is not None


class CppFormatter(Formatter):
    """C/C++ formatter."""

    @property
    def info(self) -> FormatterInfo:
        return FormatterInfo(
            name="clang-format",
            command=["clang-format", "-i", "$FILE"],
            extensions=[
                ".c",
                ".cc",
                ".cpp",
                ".cxx",
                ".c++",
                ".h",
                ".hh",
                ".hpp",
                ".hxx",
                ".h++",
                ".ino",
            ],
        )

    async def is_enabled(self) -> bool:
        return shutil.which("clang-format") is not None


class TerraformFormatter(Formatter):
    """Terraform formatter."""

    @property
    def info(self) -> FormatterInfo:
        return FormatterInfo(
            name="terraform",
            command=["terraform", "fmt", "$FILE"],
            extensions=[".tf", ".tfvars"],
        )

    async def is_enabled(self) -> bool:
        return shutil.which("terraform") is not None


class NixFormatter(Formatter):
    """Nix formatter."""

    @property
    def info(self) -> FormatterInfo:
        return FormatterInfo(
            name="nixfmt",
            command=["nixfmt", "$FILE"],
            extensions=[".nix"],
        )

    async def is_enabled(self) -> bool:
        return shutil.which("nixfmt") is not None


class ZigFormatter(Formatter):
    """Zig formatter."""

    @property
    def info(self) -> FormatterInfo:
        return FormatterInfo(
            name="zig",
            command=["zig", "fmt", "$FILE"],
            extensions=[".zig", ".zon"],
        )

    async def is_enabled(self) -> bool:
        return shutil.which("zig") is not None


class JsonYamlFormatter(Formatter):
    """JSON/YAML formatter."""

    @property
    def info(self) -> FormatterInfo:
        return FormatterInfo(
            name="prettier",
            command=["npx", "prettier", "--write", "$FILE"],
            extensions=[".json", ".jsonc", ".yaml", ".yml", ".toml"],
        )

    async def is_enabled(self) -> bool:
        return shutil.which("prettier") is not None or shutil.which("npx") is not None


FORMATTERS: list[Formatter] = [
    GoFormat(),
    RustFormat(),
    PythonFormatter(),
    JavaScriptFormatter(),
    ShellFormatter(),
    RubyFormatter(),
    PHPFormatter(),
    DartFormatter(),
    ElixirFormatter(),
    CppFormatter(),
    TerraformFormatter(),
    NixFormatter(),
    ZigFormatter(),
    JsonYamlFormatter(),
]


def get_formatter_for_file(file_path: str) -> Optional[Formatter]:
    """Get the appropriate formatter for a file."""
    ext = Path(file_path).suffix.lower()

    for formatter in FORMATTERS:
        if ext in formatter.info.extensions:
            return formatter

    return None


async def format_file(file_path: str, cwd: str = None) -> bool:
    """Format a file using the appropriate formatter."""
    formatter = get_formatter_for_file(file_path)

    if formatter is None:
        return False

    if not await formatter.is_enabled():
        return False

    return await formatter.format(file_path, cwd)


async def get_available_formatters() -> list[FormatterInfo]:
    """Get list of available formatters."""
    available = []

    for formatter in FORMATTERS:
        if await formatter.is_enabled():
            available.append(formatter.info)

    return available


async def get_formatter_status() -> list[dict]:
    """Get status of all formatters."""
    status = []

    for formatter in FORMATTERS:
        enabled = await formatter.is_enabled()
        status.append(
            {
                "name": formatter.info.name,
                "extensions": formatter.info.extensions,
                "enabled": enabled,
            }
        )

    return status
