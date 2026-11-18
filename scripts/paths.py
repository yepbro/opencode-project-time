"""Shared paths and output safety rules for the report scripts."""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_DB = Path.home() / ".local" / "share" / "opencode" / "opencode.db"


class UnsafeOutputError(Exception):
    """Raised when an output path would overwrite the source database."""


def database_paths(db: Path) -> tuple[Path, Path, Path]:
    """Return the database file and the two SQLite WAL side files."""
    resolved = db.resolve()
    return resolved, Path(f"{resolved}-wal"), Path(f"{resolved}-shm")


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
