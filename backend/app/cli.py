"""Command-line maintenance tasks (suitable for Windows Task Scheduler or cron).

  python -m app.cli backup [--no-documents]
  python -m app.cli restore <path-to-zip> --yes
  python -m app.cli purge-documents [--days N]
  python -m app.cli reset-password <username>
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

from app.core.db import session_factory


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backup")
    b.add_argument("--no-documents", action="store_true")
    r = sub.add_parser("restore")
    r.add_argument("path")
    r.add_argument("--yes", action="store_true", help="confirm replacing ALL current data")
    p = sub.add_parser("purge-documents")
    p.add_argument("--days", type=int)
    u = sub.add_parser("reset-password")
    u.add_argument("username")
    args = ap.parse_args(argv)

    with session_factory()() as db:
        if args.cmd == "backup":
            from app.services.backup.service import backup_dir, create_backup

            rec = create_backup(db, include_documents=not args.no_documents)
            print(f"Backup written: {backup_dir() / rec.filename} ({rec.size_bytes} bytes, sha256 {rec.sha256})")
        elif args.cmd == "restore":
            from app.services.backup.service import restore_backup

            if not args.yes:
                print("Refusing to restore without --yes (this replaces ALL data).", file=sys.stderr)
                return 2
            result = restore_backup(db, Path(args.path).read_bytes(), confirm=True)
            print(f"Restored backup from {result['backup_created_at']}: {result['restored_tables']}")
        elif args.cmd == "purge-documents":
            from app.services.imports.retention import purge_old_documents

            print(f"Removed {purge_old_documents(db, args.days)} stored statement file(s).")
        elif args.cmd == "reset-password":
            from app.core.security import hash_password, validate_password_strength
            from app.models import User, UserSession

            user = db.query(User).filter(User.username == args.username).one_or_none()
            if user is None:
                print("No such user", file=sys.stderr)
                return 1
            pw = getpass.getpass("New password: ")
            validate_password_strength(pw)
            user.password_hash = hash_password(pw)
            db.query(UserSession).filter(UserSession.user_id == user.id).delete()
            db.commit()
            print("Password changed; existing sessions signed out.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
