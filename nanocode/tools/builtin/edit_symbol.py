"""AST-based structured editing: edit_symbol tool for Python files.

Uses Python's builtin ast module to locate functions, classes, and
methods by name, completely bypassing string matching for structured edits.

Ported from Aura-IDE (fs_edit_structured.py).
"""

import ast
import warnings
from pathlib import Path

from nanocode.tools import Tool, ToolResult


def parse_python_ast(source: str, filename: str = "<unknown>") -> ast.Module:
    """Parse Python source without console warning noise."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        return ast.parse(source, filename=filename)


def _collect_available_symbols(tree: ast.AST) -> dict[str, list[str]]:
    available: dict[str, list[str]] = {"functions": [], "classes": [], "methods": []}
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            available["functions"].append(node.name)
        elif isinstance(node, ast.ClassDef):
            available["classes"].append(node.name)
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    available["methods"].append(f"{node.name}.{child.name}")
    return available


def _symbol_start_line(node: ast.AST) -> int:
    """Return 0-indexed start line accounting for decorators."""
    start = node.lineno - 1
    if hasattr(node, "decorator_list") and node.decorator_list:
        start = node.decorator_list[0].lineno - 1
    return start


def _symbol_end_line(node: ast.AST, start_line: int) -> int:
    """Return exclusive end line with fallback."""
    return node.end_lineno or (start_line + 1)


def _find_method(
    tree: ast.Module, class_name: str, symbol_name: str, warning: str | None,
    available: dict[str, list[str]]
) -> tuple[int, int, dict]:
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == symbol_name:
                    start = _symbol_start_line(child)
                    end = _symbol_end_line(child, start)
                    return (start, end, {"warning": warning})
            return (-1, -1, {
                "error": f"Method '{symbol_name}' not found in class '{class_name}'",
                "available_symbols": available,
            })
    return (-1, -1, {
        "error": f"Class '{class_name}' not found",
        "available_symbols": available,
    })


def _find_top_level_symbol(
    tree: ast.Module, effective_type: str, symbol_name: str, warning: str | None,
    available: dict[str, list[str]]
) -> tuple[int, int, dict]:
    found_nodes: list[ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef] = []
    for node in ast.iter_child_nodes(tree):
        if effective_type == "function" and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == symbol_name:
                found_nodes.append(node)
        elif effective_type == "class" and isinstance(node, ast.ClassDef):
            if node.name == symbol_name:
                found_nodes.append(node)

    if found_nodes:
        if len(found_nodes) > 1:
            warning = f"Multiple symbols named '{symbol_name}' found; using first occurrence"
        found = found_nodes[0]
        start = _symbol_start_line(found)
        end = _symbol_end_line(found, start)
        return (start, end, {"warning": warning})

    return (-1, -1, {
        "error": (
            f"Symbol '{symbol_name}' of type '{effective_type}' not found. "
            f"Available top-level functions: {available['functions']}. "
            f"Available classes: {available['classes']}."
        ),
        "available_symbols": available,
    })


def find_symbol_range(
    source: str,
    symbol_type: str,
    symbol_name: str,
    class_name: str | None = None,
    filename: str = "<unknown>",
) -> tuple[int, int, dict]:
    """Locate a Python symbol in source and return its 0-indexed line range."""
    tree = parse_python_ast(source, filename=filename)
    warning: str | None = None

    effective_type = symbol_type
    if symbol_type == "function" and class_name:
        effective_type = "method"

    available = _collect_available_symbols(tree)

    if effective_type == "method":
        if not class_name:
            return (-1, -1, {
                "error": "class_name is required when symbol_type is 'method'",
                "available_symbols": available,
            })
        return _find_method(tree, class_name, symbol_name, warning, available)

    return _find_top_level_symbol(tree, effective_type, symbol_name, warning, available)


def _validate_python_file(file_path: Path) -> dict | None:
    """Validate file_path is an existing .py file. Returns error dict or None."""
    if not file_path.exists():
        return {
            "ok": False, "error": f"file not found: {file_path}",
            "old_content": "", "new_content": "",
        }
    if not file_path.is_file():
        return {
            "ok": False, "error": f"not a regular file: {file_path}",
            "old_content": "", "new_content": "",
        }
    if file_path.suffix != ".py":
        return {
            "ok": False,
            "error": "edit_symbol only supports Python (.py) files. Use edit for other languages.",
            "old_content": "", "new_content": "",
        }
    return None


def _auto_indent_definition(orig_block: str, new_definition: str) -> str:
    """Indent new_definition to match the original block's indentation."""
    first_orig_line = orig_block.split("\n", 1)[0]
    orig_indent = first_orig_line[: len(first_orig_line) - len(first_orig_line.lstrip())]
    if orig_indent:
        first_new_line = new_definition.split("\n", 1)[0]
        if not first_new_line.startswith(orig_indent):
            new_definition = "\n".join(
                (orig_indent + line) if line else ""
                for line in new_definition.split("\n")
            )
    return new_definition


def _normalize_trailing_newline(orig_block: str, new_definition: str) -> str:
    """Match trailing newline of the original block."""
    if orig_block.endswith("\n") and not new_definition.endswith("\n"):
        return new_definition + "\n"
    if not orig_block.endswith("\n") and new_definition.endswith("\n"):
        return new_definition.rstrip("\n")
    return new_definition


def propose_edit_symbol(
    file_path: Path,
    symbol_type: str,
    symbol_name: str,
    new_definition: str,
    class_name: str | None = None,
) -> dict:
    """Replace a named Python symbol (function, class, or method) using AST."""
    error = _validate_python_file(file_path)
    if error:
        return error

    try:
        original = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return {
            "ok": False, "error": "file is not valid UTF-8 text",
            "old_content": "", "new_content": "",
        }

    try:
        start_line, end_line, info = find_symbol_range(
            original, symbol_type, symbol_name, class_name, filename=str(file_path)
        )
    except SyntaxError as exc:
        return {
            "ok": False,
            "error": f"Syntax error in file: {exc}",
            "old_content": original, "new_content": "",
        }

    if start_line == -1:
        return {
            "ok": False,
            "error": info.get("error", f"Symbol '{symbol_name}' not found"),
            "old_content": original, "new_content": "",
            "available_symbols": info.get("available_symbols", {}),
        }

    lines_with_nl = original.splitlines(keepends=True)
    orig_block = "".join(lines_with_nl[start_line:end_line])
    new_definition = _auto_indent_definition(orig_block, new_definition)
    new_definition = _normalize_trailing_newline(orig_block, new_definition)

    from nanocode.tools.builtin.edit import replace_line_range
    new_content = replace_line_range(original, lines_with_nl, start_line, end_line, new_definition)

    try:
        parse_python_ast(new_content, filename=str(file_path))
    except SyntaxError as exc:
        return {
            "ok": False,
            "error": f"Proposed replacement makes the file invalid: {exc}",
            "old_content": original, "new_content": "",
        }

    result: dict = {
        "ok": True,
        "old_content": original,
        "new_content": new_content,
        "match_tier": "symbol",
    }
    if info.get("warning"):
        result["warning"] = info["warning"]
    return result


class EditSymbolTool(Tool):
    """AST-based structured editing for Python files."""

    def __init__(self):
        super().__init__(
            name="edit_symbol",
            description="Replace a named Python function, class, or method using AST parsing. "
            "Completely bypasses string matching issues. "
            "Specify symbol_type ('function', 'class', 'method'), symbol_name, "
            "and the complete new definition. For methods, also provide class_name.",
            parameters={
                "type": "object",
                "properties": {
                    "filePath": {
                        "type": "string",
                        "description": "Path to the Python file to edit",
                    },
                    "symbol_type": {
                        "type": "string",
                        "enum": ["function", "class", "method"],
                        "description": "Type of symbol to replace",
                    },
                    "symbol_name": {
                        "type": "string",
                        "description": "Name of the symbol to replace",
                    },
                    "new_definition": {
                        "type": "string",
                        "description": "Complete new definition (decorators, signature, body)",
                    },
                    "class_name": {
                        "type": "string",
                        "description": "Required when symbol_type is 'method'",
                    },
                },
                "required": ["filePath", "symbol_type", "symbol_name", "new_definition"],
            },
        )

    async def execute(
        self,
        filePath: str,
        symbol_type: str,
        symbol_name: str,
        new_definition: str,
        class_name: str | None = None,
    ) -> ToolResult:
        file_path = Path(filePath)
        result = propose_edit_symbol(file_path, symbol_type, symbol_name, new_definition, class_name)

        if not result.get("ok"):
            return ToolResult.err(result.get("error", "Edit failed"))

        new_content = result["new_content"]
        file_path.write_text(new_content)

        lines = new_content.split("\n")
        preview = "\n".join(lines[:20])
        if len(lines) > 20:
            preview += f"\n... ({len(lines) - 20} more lines)"

        return ToolResult.ok(
            content=f"Edited {file_path} (match_tier: {result.get('match_tier', 'symbol')}):\n{preview}",
            metadata={
                "filePath": str(file_path),
                "match_tier": result.get("match_tier", "symbol"),
                "bytes": len(new_content.encode("utf-8")),
            },
        )
