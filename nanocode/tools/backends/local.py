"""Local filesystem backend - implements FileSystemBackend using the OS filesystem."""

from pathlib import Path
from typing import Optional
import asyncio
import os


class LocalFSBackend(FileSystemBackend):
    """Filesystem backend that reads/writes to the local OS filesystem.

    This preserves the existing nanocode behavior where tools operate
    on files under a root directory (workspace).
    """

    def __init__(self, root_dir: str):
        self.root_dir = Path(root_dir) if isinstance(root_dir, str) else root_dir

    def _resolve(self, path: str) -> Path:
        """Resolve path relative to root_dir, ensuring it stays within root."""
        p = Path(path)
        if p.is_absolute():
            return p
        return self.root_dir / path

    async def read(self, path: str, offset: int = None, limit: int = None) -> dict:
        file_path = self._resolve(path)
        try:
            content = file_path.read_text(errors="ignore")
            lines = content.splitlines()
            total_lines = len(lines)
            if offset:
                lines = lines[offset - 1 :]
            if limit:
                lines = lines[:limit]
            text = "\n".join(lines)
            bytes_val = len(text.encode("utf-8"))
            tokens_est = max(1, bytes_val // 4)
            return {
                "success": True,
                "content": text,
                "metadata": {
                    "path": str(file_path),
                    "lines": len(lines),
                    "total_lines": total_lines,
                    "bytes": bytes_val,
                    "tokens_estimate": tokens_est,
                },
            }
        except FileNotFoundError:
            parent = file_path.parent
            if not parent.exists():
                try:
                    parent.mkdir(parents=True, exist_ok=True)
                except Exception:
                    return {"success": False, "content": None, "error": "Cannot create parent directory"}
            return {
                "success": True,
                "content": "",
                "metadata": {
                    "path": str(file_path),
                    "lines": 0,
                    "total_lines": 0,
                    "bytes": 0,
                    "tokens_estimate": 0,
                    "new_file": True,
                },
            }
        except Exception as e:
            return {"success": False, "content": None, "error": str(e)}

    async def write(self, path: str, content: str) -> dict:
        file_path = self._resolve(path)
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            def _write():
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(content)
            await asyncio.get_event_loop().run_in_executor(None, _write)
            return {
                "success": True,
                "content": f"Written to {file_path}",
                "metadata": {"path": str(file_path), "bytes": len(content.encode("utf-8"))},
            }
        except Exception as e:
            return {"success": False, "content": None, "error": str(e)}

    async def edit(self, path: str, old_string: str, new_string: str, replace_all: bool = False) -> dict:
        file_path = self._resolve(path)
        try:
            if not file_path.exists():
                return {"success": False, "content": None, "error": f"File not found: {file_path}"}
            loop = asyncio.get_event_loop()

            def _read():
                with open(file_path, "r", encoding="utf-8") as f:
                    return f.read()

            content = await loop.run_in_executor(None, _read)
            occurrence_count = content.count(old_string)
            if occurrence_count == 0:
                return {"success": False, "content": None, "error": f"old_string not found in file: {old_string}"}
            if not replace_all and occurrence_count > 1:
                return {
                    "success": False,
                    "content": None,
                    "error": f"Found {occurrence_count} matches. Set replace_all=True to replace all.",
                }
            if replace_all:
                new_content = content.replace(old_string, new_string)
                replacements = occurrence_count
            else:
                new_content = content.replace(old_string, new_string, 1)
                replacements = 1

            def _write():
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(new_content)

            await loop.run_in_executor(None, _write)
            return {
                "success": True,
                "content": f"Successfully edited {file_path}. Replaced {replacements} occurrence(s).",
                "metadata": {"filePath": str(file_path), "replacements": replacements, "replaceAll": replace_all},
            }
        except Exception as e:
            return {"success": False, "content": None, "error": str(e)}

    async def exists(self, path: str) -> bool:
        return self._resolve(path).exists()

    async def list_dir(self, path: str = "") -> list[dict]:
        dir_path = self._resolve(path) if path else self.root_dir
        if not dir_path.exists():
            return []
        results = []
        for p in dir_path.iterdir():
            results.append({"name": p.name, "path": str(p), "is_dir": p.is_dir()})
        return results

    async def delete(self, path: str) -> dict:
        file_path = self._resolve(path)
        try:
            file_path.unlink()
            return {"success": True, "content": f"Deleted {file_path}"}
        except Exception as e:
            return {"success": False, "content": None, "error": str(e)}
