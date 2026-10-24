"""Operator bootstrap CLI (PLAT-SEC-02): the trusted way to make the first operator.

No HTTP request can create an operator without an operator's token. Run this in
a shell on the host instead, against the same database the app uses
(``PLUME_DATABASE_URL``, default ``sqlite:///plume.db``):

    uv run python -m plume.auth.cli create-operator --email you@example.com

On Railway, open the shell with ``railway ssh`` first. The password is read
from the terminal twice, never from argv (so it stays out of shell history and
process listings). An empty or mismatched password, or an email already in use,
creates nothing and exits non-zero.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from collections.abc import Callable, Sequence

from sqlmodel import Session

from plume.auth.service import create_operator
from plume.db import get_engine


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m plume.auth.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-operator", help="create an operator account")
    create.add_argument("--email", required=True)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    read_password: Callable[[str], str] = getpass.getpass,
) -> int:
    args = _parser().parse_args(argv)
    # create-operator is the only command; argparse enforces that one was given.
    password = read_password("Password: ")
    if password != read_password("Repeat password: "):
        print("Passwords do not match; nothing created.", file=sys.stderr)  # noqa: T201
        return 2
    try:
        with Session(get_engine()) as session:
            user = create_operator(session, email=args.email, password=password)
    except ValueError as exc:
        print(f"Not created: {exc}", file=sys.stderr)  # noqa: T201
        return 1
    print(f"Created operator {user.email} (id {user.id}).")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
