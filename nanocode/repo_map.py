"""Generate a concise AST-based structural map of the workspace.

Injected into the system prompt on every turn so the model has a structural
overview of the codebase — file tree, classes, methods, top-level functions.
"""

from __future__ import annotations

import ast
import os
import warnings
from pathlib import Path
from typing import Any

SKIP_DIRS: set[str] = {
    ".git", "__pycache__", "node_modules", "build", "dist",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".venv",
    "venv", ".svn", ".hg", "eggs", ".eggs", ".tox", ".cache",
    ".next", ".nuxt", ".svelte-kit",
}

SKIP_FILE_SUFFIXES: set[str] = {
    ".pyc", ".pyo", ".so", ".o", ".class", ".jar",
    ".min.js", ".min.css", ".map",
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg",
    ".woff", ".woff2", ".ttf", ".eot",
    ".zip", ".tar", ".gz", ".bz2", ".xz",
}

MAX_LINES = 300
MAX_FILE_BYTES = 128 * 1024

_RELEVANT_EXTENSIONS = {".py", ".ts", ".tsx", ".js"}
_PY_FUNC_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef)

_repo_map_cache: dict[str, tuple[float, str]] = {}


def _should_skip(path: Path) -> bool:
    parts = set(path.parts)
    if parts & SKIP_DIRS:
        return True
    if path.name.startswith("."):
        return True
    if path.suffix.lower() in SKIP_FILE_SUFFIXES:
        return True
    return False


def _get_max_mtime(root: Path) -> float:
    latest = 0.0
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [
                d for d in dirnames
                if not d.startswith(".") and d not in SKIP_DIRS
            ]
            for fname in filenames:
                suffix = Path(fname).suffix.lower()
                if suffix not in _RELEVANT_EXTENSIONS:
                    continue
                try:
                    mtime = os.path.getmtime(os.path.join(dirpath, fname))
                    if mtime > latest:
                        latest = mtime
                except OSError:
                    continue
    except (OSError, PermissionError):
        pass
    return latest


def _parse_python_ast(source: str, filename: str = "<unknown>") -> ast.Module:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        return ast.parse(source, filename=filename)


def _ast_expr_to_str(node: ast.expr) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return type(node).__name__


def _py_func_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    try:
        return ast.unparse(node).split("\n")[0].rstrip(":")
    except Exception:
        args = ", ".join(a.arg for a in node.args.args)
        prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
        return f"{prefix} {node.name}({args})"


def _outline_python(text: str, filename: str = "<unknown>") -> dict[str, Any]:
    imports: list[str] = []
    classes: list[dict[str, Any]] = []
    functions: list[dict[str, Any]] = []

    try:
        tree = _parse_python_ast(text, filename=filename)
    except SyntaxError:
        return {"language": "python", "imports": [], "classes": [], "functions": []}

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name
                imports.append(
                    f"import {name} as {alias.asname}" if alias.asname else f"import {name}"
                )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names: list[str] = []
            for alias in node.names:
                names.append(
                    f"{alias.name} as {alias.asname}" if alias.asname else alias.name
                )
            imports.append(f"from {module} import {', '.join(names)}")
        elif isinstance(node, ast.ClassDef):
            bases = [_ast_expr_to_str(b) for b in node.bases]
            methods: list[str] = []
            for body_node in node.body:
                if isinstance(body_node, _PY_FUNC_TYPES):
                    methods.append(_py_func_signature(body_node))
            classes.append({
                "name": node.name,
                "line": node.lineno,
                "bases": bases,
                "methods": methods,
            })
        elif isinstance(node, _PY_FUNC_TYPES):
            sig = _py_func_signature(node)
            functions.append({"name": node.name, "line": node.lineno, "signature": sig})

    return {
        "language": "python",
        "imports": imports,
        "classes": classes,
        "functions": functions,
    }


def generate_repo_map(workspace_root: Path, force: bool = False) -> str:
    """Generate a structural map of the workspace.

    Returns a tree-like string with per-file classes, methods, and top-level
    functions.  Results are cached in memory with mtime validation; pass
    *force=True* to skip the fast path.
    """
    root_str = str(workspace_root.resolve())

    if not force and root_str in _repo_map_cache:
        _, cached_text = _repo_map_cache[root_str]
        if cached_text:
            return cached_text

    current_mtime = _get_max_mtime(workspace_root)
    cached_mtime, cached_text = _repo_map_cache.get(root_str, (0.0, ""))
    if current_mtime == cached_mtime and cached_text:
        return cached_text

    tree_lines: list[str] = []
    file_count = 0

    for dirpath, dirnames, filenames in os.walk(workspace_root):
        dirnames[:] = [
            d for d in dirnames
            if not d.startswith(".") and d not in SKIP_DIRS
        ]

        rel_dir = os.path.relpath(dirpath, workspace_root)
        if rel_dir == ".":
            rel_dir = ""

        for fname in sorted(filenames):
            suffix = Path(fname).suffix.lower()
            if suffix not in _RELEVANT_EXTENSIONS:
                continue

            fpath = os.path.join(dirpath, fname)
            try:
                file_size = os.path.getsize(fpath)
                if file_size > MAX_FILE_BYTES:
                    continue
                with open(fpath, "rb") as f:
                    raw = f.read(MAX_FILE_BYTES)
            except (OSError, PermissionError):
                continue

            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                continue

            rel_path = os.path.join(rel_dir, fname) if rel_dir else fname
            file_count += 1

            if suffix != ".py":
                tree_lines.append(rel_path)
                continue

            outline = _outline_python(text, filename=fpath)
            if not outline["classes"] and not outline["functions"]:
                tree_lines.append(rel_path)
                continue

            tree_lines.append("")
            tree_lines.append(rel_path)
            if outline["classes"]:
                for cls in outline["classes"]:
                    bases_str = f" (extends {', '.join(cls['bases'])})" if cls["bases"] else ""
                    tree_lines.append(f"  class {cls['name']}{bases_str}")
                    for m in cls["methods"]:
                        tree_lines.append(f"    {m}")
            if outline["functions"]:
                for fn in outline["functions"]:
                    tree_lines.append(f"  {fn['signature']}")

    if file_count == 0:
        result = "No Python/TypeScript files found."
        _repo_map_cache[root_str] = (current_mtime, result)
        return result

    header = f"### Repository Structure ({file_count} files)\n"

    if len(tree_lines) > MAX_LINES:
        tree_lines = tree_lines[: MAX_LINES - 2]
        tree_lines.append("")
        tree_lines.append("... (output truncated)")

    result = header + "\n".join(tree_lines)
    _repo_map_cache[root_str] = (current_mtime, result)
    return result
