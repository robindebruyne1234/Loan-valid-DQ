"""Test support: authenticated consumer connections, logged in once.

Every consumer query now needs both factors, and a TOTP code may be used only
once per thirty-second window. Logging in afresh for each of the ~40 consumer
assertions in this suite would therefore spend most of the run asleep waiting
for codes to roll over.

So each principal logs in once and the connection is reused, which is also
what a real user does: authenticate, then work. The reuse wrapper rolls back
after every block so one test cannot leave a transaction open for the next.

Tests that are specifically ABOUT authentication (a wrong code, a logout, an
expired session, a connection with no second factor at all) must not use this
-- they open their own connections, because the thing they are testing is the
login itself.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import psycopg

from src import auth

#: role -> (context manager, open connection), opened lazily, closed at exit.
_SESSIONS: dict[str, tuple[object, psycopg.Connection]] = {}


@contextmanager
def consumer(role: str) -> Iterator[psycopg.Connection]:
    """Yield a fully authenticated connection for a principal.

    :param role: The database role to authenticate as.
    :yields: A connection that has passed both factors.
    """
    if role not in _SESSIONS:
        manager = auth.login(role, demo_autocode=True)
        _SESSIONS[role] = (manager, manager.__enter__())
    connection = _SESSIONS[role][1]
    try:
        yield connection
    finally:
        # Leave no transaction behind for the next test in this session.
        try:
            connection.rollback()
        except psycopg.Error:
            pass


def forget(role: str) -> None:
    """Drop a cached session, for a principal a test is about to delete.

    :param role: The database role to forget.
    :returns: ``None``.
    """
    entry = _SESSIONS.pop(role, None)
    if entry is not None:
        try:
            entry[0].__exit__(None, None, None)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - teardown must not fail the run
            pass


def close_all() -> None:
    """Log every cached principal out. Called once, at the end of the run.

    :returns: ``None``.
    """
    while _SESSIONS:
        _role, (manager, _conn) = _SESSIONS.popitem()
        try:
            manager.__exit__(None, None, None)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - teardown must not fail the run
            pass
