"""Tests for format functionality."""

import pytest

from nanocode.format import (
    CppFormatter,
    FormatterInfo,
    GoFormat,
    PythonFormatter,
    RustFormat,
    ShellFormatter,
    format_file,
    get_available_formatters,
    get_formatter_for_file,
    get_formatter_status,
)


def test_formatter_info_dataclass():
    """Test FormatterInfo dataclass."""
    info = FormatterInfo(
        name="test",
        command=["test", "$FILE"],
        extensions=[".txt"],
    )
    assert info.name == "test"
    assert "$FILE" in info.command


def test_get_formatter_for_file_python():
    """Test getting formatter for Python files."""
    formatter = get_formatter_for_file("test.py")
    assert formatter is not None
    assert formatter.info.name in ["ruff", "black"]


def test_get_formatter_for_file_rust():
    """Test getting formatter for Rust files."""
    formatter = get_formatter_for_file("main.rs")
    assert formatter is not None
    assert formatter.info.name == "rustfmt"


def test_get_formatter_for_file_go():
    """Test getting formatter for Go files."""
    formatter = get_formatter_for_file("main.go")
    assert formatter is not None
    assert formatter.info.name == "gofmt"


def test_get_formatter_for_file_cpp():
    """Test getting formatter for C++ files."""
    formatter = get_formatter_for_file("main.cpp")
    assert formatter is not None
    assert formatter.info.name == "clang-format"


def test_get_formatter_for_file_shell():
    """Test getting formatter for shell files."""
    formatter = get_formatter_for_file("script.sh")
    assert formatter is not None
    assert formatter.info.name == "shfmt"


def test_get_formatter_for_file_unknown():
    """Test getting formatter for unknown file type."""
    formatter = get_formatter_for_file("file.xyz")
    assert formatter is None


def test_get_formatter_for_js():
    """Test getting formatter for JavaScript files."""
    formatter = get_formatter_for_file("app.js")
    assert formatter is not None


def test_get_formatter_for_ts():
    """Test getting formatter for TypeScript files."""
    formatter = get_formatter_for_file("app.ts")
    assert formatter is not None


def test_get_formatter_for_json():
    """Test getting formatter for JSON files."""
    formatter = get_formatter_for_file("data.json")
    assert formatter is not None


def test_get_formatter_for_yaml():
    """Test getting formatter for YAML files."""
    formatter = get_formatter_for_file("config.yaml")
    assert formatter is not None


def test_get_formatter_for_ruby():
    """Test getting formatter for Ruby files."""
    formatter = get_formatter_for_file("app.rb")
    assert formatter is not None


def test_get_formatter_for_php():
    """Test getting formatter for PHP files."""
    formatter = get_formatter_for_file("index.php")
    assert formatter is not None


def test_get_formatter_for_dart():
    """Test getting formatter for Dart files."""
    formatter = get_formatter_for_file("main.dart")
    assert formatter is not None


def test_get_formatter_for_elixir():
    """Test getting formatter for Elixir files."""
    formatter = get_formatter_for_file("test.exs")
    assert formatter is not None


def test_get_formatter_for_terraform():
    """Test getting formatter for Terraform files."""
    formatter = get_formatter_for_file("main.tf")
    assert formatter is not None


def test_get_formatter_for_zig():
    """Test getting formatter for Zig files."""
    formatter = get_formatter_for_file("main.zig")
    assert formatter is not None


def test_get_formatter_for_nix():
    """Test getting formatter for Nix files."""
    formatter = get_formatter_for_file("flake.nix")
    assert formatter is not None


def test_go_format_info():
    """Test GoFormat formatter info."""
    formatter = GoFormat()
    assert formatter.info.name == "gofmt"
    assert ".go" in formatter.info.extensions


def test_rust_format_info():
    """Test RustFormat formatter info."""
    formatter = RustFormat()
    assert formatter.info.name == "rustfmt"
    assert ".rs" in formatter.info.extensions


def test_python_formatter_info():
    """Test PythonFormatter info."""
    formatter = PythonFormatter()
    assert formatter.info.name == "ruff"
    assert ".py" in formatter.info.extensions


def test_shell_formatter_info():
    """Test ShellFormatter info."""
    formatter = ShellFormatter()
    assert formatter.info.name == "shfmt"
    assert ".sh" in formatter.info.extensions


def test_cpp_formatter_info():
    """Test CppFormatter info."""
    formatter = CppFormatter()
    assert formatter.info.name == "clang-format"
    assert ".cpp" in formatter.info.extensions


@pytest.mark.asyncio
async def test_format_file_not_found():
    """Test formatting non-existent file."""
    result = await format_file("/nonexistent/file.py")
    assert result is False


@pytest.mark.asyncio
async def test_get_formatter_status():
    """Test getting formatter status."""
    status = await get_formatter_status()
    assert isinstance(status, list)
    assert len(status) > 0
    for s in status:
        assert "name" in s
        assert "extensions" in s
        assert "enabled" in s


@pytest.mark.asyncio
async def test_get_available_formatters():
    """Test getting available formatters."""
    formatters = await get_available_formatters()
    assert isinstance(formatters, list)
