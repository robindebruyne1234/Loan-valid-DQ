"""Shared fixtures.

The authentication tests deliberately present wrong and replayed codes, and
the verifier counts those: five failures lock a principal out for fifteen
minutes. That is the behaviour under test, but it accumulates across runs, so
without this the suite poisons itself -- passing the first time and failing
the next with a lockout that has nothing to do with the code being tested.
"""

from __future__ import annotations

import pytest

from src import db
from tests import support


@pytest.fixture(autouse=True, scope="session")
def _clear_second_factor_lockouts() -> None:
    """Reset failed attempt counters before the suite runs.

    Session-scoped and autouse: no test should have to remember to do this,
    and forgetting would produce a failure that looks like a real one.
    """
    try:
        with db.connect() as conn:
            db.execute(
                conn,
                "UPDATE sec.auth_factor SET failed_count = 0, locked_until = NULL",
            )
            conn.commit()
    except Exception:  # noqa: BLE001 - the table may not exist yet on a fresh clone
        pass


@pytest.fixture(autouse=True, scope="session")
def _close_shared_consumer_sessions() -> None:
    """Log out every shared consumer connection when the run finishes.

    :returns: ``None``.
    """
    yield
    support.close_all()
