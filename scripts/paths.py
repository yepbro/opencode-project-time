"""Shared paths and output safety rules for the report scripts."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def default_db() -> Path:
    """Resolve OpenCode's data directory, honoring XDG and platform conventions."""
    if sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    elif sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return root / "opencode" / "opencode.db"


DEFAULT_DB = default_db()


class UnsafeOutputError(Exception):
    """Raised when an output path would overwrite the source database."""


def database_paths(db: Path) -> tuple[Path, Path, Path]:
    """Return the database file and the two SQLite WAL side files."""
    resolved = db.resolve()
    return resolved, Path(f"{resolved}-wal"), Path(f"{resolved}-shm")


def describe_default_db() -> str:
    return str(DEFAULT_DB)


def refuse_database_output(out: Path, db: Path) -> None:
    """Refuse ``--out`` targets that are the database, its WAL, or its SHM.

    Both path identity and, for existing files, inode identity are checked so
    symlinks and hard links cannot bypass the guard.
    """
    for protected in database_paths(db):
        if out.resolve() == protected.resolve():
            raise UnsafeOutputError(f"refusing to overwrite the OpenCode database via {out}")
        try:
            if out.exists() and protected.exists() and os.path.samefile(out, protected):
                raise UnsafeOutputError(f"refusing to overwrite the OpenCode database via {out}")
        except OSError:
            pass
