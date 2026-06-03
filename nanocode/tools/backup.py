"""Pre-write file backups.

Before any write_file/edit_file, saves the existing file to
``.nanocode/backups/<ISO-timestamp>/<relpath>`` so changes are reversible.
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path


def backup_existing(file_path: str | Path, backup_root: str | Path | None = None) -> Path | None:
    """Copy *file_path* to a timestamped backup location before overwriting.

    Args:
        file_path: Absolute or relative path to the file about to be written.
        backup_root: Root directory for backups (default: ``Path.cwd() / ".nanocode" / "backups"``).

    Returns:
        The backup destination path, or ``None`` if the file didn't exist
        (nothing to back up).
    """
    src = Path(file_path)
    if not src.is_file():
        return None

    root = Path(backup_root) if backup_root else Path.cwd() / ".nanocode" / "backups"
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    dest_dir = root / timestamp
    dest_dir.mkdir(parents=True, exist_ok=True)

    dest = dest_dir / src.name
    shutil.copy2(src, dest)
    return dest
