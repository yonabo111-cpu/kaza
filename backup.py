#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Kaza database backup — a safe, dependency-free snapshot & restore tool.

Kaza stores everything in a single SQLite file (``data/app.db``). That file is a
single point of failure: if it is lost or corrupted, every household's data goes
with it. This script takes consistent snapshots of it and can restore one.

It uses SQLite's online-backup API, so a snapshot is consistent even while the
app is running (it is safe with WAL mode). Backups land in ``data/backups/`` and
are rotated automatically, keeping the most recent ``KAZA_BACKUP_KEEP`` (14 by
default).

Run it on the server (PythonAnywhere → Consoles → Bash):

    cd ~/kaza && python3 backup.py            # create a snapshot (+ prune old)
    python3 backup.py list                    # show existing snapshots
    python3 backup.py restore <file>          # restore from a snapshot

Point it at a different database with the ``KAZA_DB`` environment variable.
Schedule the plain ``python3 backup.py`` daily (see the README) for hands-off
protection.
"""

from __future__ import annotations

import os
import pathlib
import re
import shutil
import sqlite3
import sys
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

# The live database sits under data/app.db, next to this script (same as the app).
ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.environ.get("KAZA_DB") or os.path.join(ROOT, "data", "app.db")

# How many rotating snapshots to keep. Older ones are pruned after each backup.
KEEP = int(os.environ.get("KAZA_BACKUP_KEEP", "14"))

# Snapshot filenames look like app-20260721-143005-872014.db; the microseconds
# keep names unique (and correctly ordered) even for back-to-back runs. Safety
# copies made just before a restore use a different prefix and are never pruned.
_SNAPSHOT_RE = re.compile(r"^app-\d{8}-\d{6}-\d{6}\.db$")


def _timestamp() -> str:
    """A unique, sortable, filesystem-safe timestamp, e.g. ``20260721-143005-872014``."""
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f")


def _backups_dir(db_path: str) -> str:
    """Return (creating if needed) the backups directory beside the database."""
    path = os.path.join(os.path.dirname(os.path.abspath(db_path)), "backups")
    os.makedirs(path, exist_ok=True)
    return path


def _open_readonly(path: str) -> sqlite3.Connection:
    """Open ``path`` read-only so a snapshot can never disturb live data."""
    try:
        uri = f"{pathlib.Path(os.path.abspath(path)).as_uri()}?mode=ro"
        return sqlite3.connect(uri, uri=True)
    except Exception:
        return sqlite3.connect(path)  # fallback: still only read below


def _integrity_ok(path: str) -> bool:
    """True if SQLite reports the database at ``path`` as internally consistent."""
    con = _open_readonly(path)
    try:
        return con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    except Exception:
        return False
    finally:
        con.close()


def _human_size(num_bytes: int) -> str:
    """Format a byte count as KB/MB for display."""
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:,.0f} {unit}" if unit == "B" else f"{value:,.1f} {unit}"
        value /= 1024
    return f"{value:,.1f} GB"


def create_backup(db_path: str = DEFAULT_DB, keep: int = KEEP) -> str:
    """Write a consistent snapshot of ``db_path`` and prune old ones.

    Returns the path of the snapshot just written. Raises ``FileNotFoundError``
    if the database does not exist yet (nobody has registered).
    """
    if not os.path.exists(db_path):
        raise FileNotFoundError(db_path)

    backups = _backups_dir(db_path)
    dest = os.path.join(backups, f"app-{_timestamp()}.db")

    src = _open_readonly(db_path)
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)  # online backup: consistent even under concurrent writes
    finally:
        dst.close()
        src.close()

    if not _integrity_ok(dest):
        os.remove(dest)
        raise RuntimeError("integrity check failed on the fresh snapshot")

    _prune(backups, keep)
    return dest


def _prune(backups_dir: str, keep: int) -> list[str]:
    """Delete all but the ``keep`` most recent snapshots. Returns removed paths."""
    snapshots = sorted(
        (f for f in os.listdir(backups_dir) if _SNAPSHOT_RE.match(f)),
        reverse=True,  # newest first (timestamped names sort chronologically)
    )
    removed = []
    for name in snapshots[keep:]:
        path = os.path.join(backups_dir, name)
        os.remove(path)
        removed.append(path)
    return removed


def list_backups(db_path: str = DEFAULT_DB) -> list[str]:
    """Return existing snapshot paths for the given database, newest first."""
    backups = os.path.join(os.path.dirname(os.path.abspath(db_path)), "backups")
    if not os.path.isdir(backups):
        return []
    names = sorted((f for f in os.listdir(backups) if _SNAPSHOT_RE.match(f)), reverse=True)
    return [os.path.join(backups, n) for n in names]


def restore_backup(backup_file: str, db_path: str = DEFAULT_DB) -> str:
    """Replace ``db_path`` with ``backup_file`` after safety-copying the current db.

    A copy of the current database is saved as ``pre-restore-<timestamp>.db`` in
    the backups directory first, so a restore is itself reversible. Returns the
    path of that safety copy (empty string if there was no database to copy).
    Raises ``ValueError`` if ``backup_file`` fails its integrity check.
    """
    if not os.path.exists(backup_file):
        raise FileNotFoundError(backup_file)
    if not _integrity_ok(backup_file):
        raise ValueError("the backup file failed its integrity check — not restoring")

    backups = _backups_dir(db_path)
    safety = ""
    if os.path.exists(db_path):
        safety = os.path.join(backups, f"pre-restore-{_timestamp()}.db")
        shutil.copy2(db_path, safety)

    # Drop any stale WAL/SHM sidecars so they can't be replayed onto the new file.
    for sidecar in (db_path + "-wal", db_path + "-shm"):
        if os.path.exists(sidecar):
            os.remove(sidecar)

    # Rewrite the live file from the snapshot via the backup API (clean copy).
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    src = _open_readonly(backup_file)
    dst = sqlite3.connect(db_path)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return safety


# --------------------------------------------------------------------------- CLI


def _cmd_backup(db_path: str) -> int:
    try:
        dest = create_backup(db_path)
    except FileNotFoundError:
        print(f"\n⚠  לא נמצא מסד נתונים בנתיב:\n   {db_path}")
        print("   (הקובץ נוצר בהרשמה הראשונה — ודא שמישהו כבר נרשם.)\n")
        return 1
    except Exception as exc:  # pragma: no cover - defensive
        print(f"\n❌ הגיבוי נכשל: {exc}\n")
        return 1
    size = _human_size(os.path.getsize(dest))
    kept = len(list_backups(db_path))
    print("\n✅ גיבוי נוצר בהצלחה")
    print(f"   {dest}   ({size})")
    print(f'   סה"כ גיבויים שמורים: {kept} (שומר עד {KEEP} אחרונים)\n')
    return 0


def _cmd_list(db_path: str) -> int:
    files = list_backups(db_path)
    if not files:
        print("\nאין עדיין גיבויים. הריצו `python3 backup.py` כדי ליצור אחד.\n")
        return 0
    print(f"\n🗂  גיבויים ({len(files)}):")
    for path in files:
        size = _human_size(os.path.getsize(path))
        when = datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M")
        print(f"   {when}   {size:>10}   {os.path.basename(path)}")
    print()
    return 0


def _cmd_restore(db_path: str, backup_file: str) -> int:
    try:
        safety = restore_backup(backup_file, db_path)
    except FileNotFoundError:
        print(f"\n⚠  קובץ הגיבוי לא נמצא:\n   {backup_file}\n")
        return 1
    except ValueError as exc:
        print(f"\n❌ {exc}\n")
        return 1
    print("\n✅ המסד שוחזר מהגיבוי")
    print(f"   מקור:  {backup_file}")
    if safety:
        print(f"   המצב הקודם נשמר ל: {safety}")
    print("   ⚠  בצעו Reload לאפליקציה כדי שתטען את הנתונים המשוחזרים.\n")
    return 0


def main(argv: list[str]) -> int:
    """Dispatch the CLI: no args = backup, ``list``, or ``restore <file>``."""
    db_path = DEFAULT_DB
    args = argv[1:]
    if not args:
        return _cmd_backup(db_path)
    if args[0] == "list":
        return _cmd_list(db_path)
    if args[0] == "restore":
        if len(args) < 2:
            print("\nשימוש: python3 backup.py restore <קובץ-גיבוי>\n")
            return 2
        return _cmd_restore(db_path, args[1])
    print("\nשימוש: python3 backup.py [list | restore <file>]\n")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
