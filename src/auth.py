"""Two-step login: who you are, then proof that it is really you.

The split this module exists to keep honest:

* **Factor 1** is the database role password, checked by PostgreSQL when the
  connection opens. It is what makes ``session_user`` unforgeable -- no
  statement a caller or a language model can emit changes it.
* **Factor 2** is a time-based one-time code (RFC 6238) verified by
  ``sec.verify_second_factor()`` inside the database, against a secret that
  never leaves it.

Until factor 2 succeeds the connection is authenticated but **entitled to
nothing**: ``sec.v_my_clients`` gates every grant on a live verified session,
so an attacker holding only the password sees zero rows rather than one
customer's finances.

The code generation here is for the demo only -- it stands in for the
authenticator app on a customer's phone. :func:`current_code` is the function
a real deployment would NOT have, and it is marked as such wherever it is
used, because a system that can print your second factor has not got two
factors. It exists so a stakeholder demo can be run without six phones.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

import psycopg

from src import config, db

LOGGER = db.setup_logging("auth")


class AuthenticationError(RuntimeError):
    """Raised when a login does not complete both factors."""


@dataclass(frozen=True)
class Session:
    """A completed two-factor login.

    :param db_role: The principal that authenticated.
    :param expires_at: When the second factor must be presented again.
    :param detail: What the database said about the verification.
    """

    db_role: str
    expires_at: object
    detail: str


def new_secret() -> str:
    """Generate a base32 TOTP shared secret.

    :returns: A 32-character base32 string, as an authenticator app expects.
    """
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def current_step(at: float | None = None) -> int:
    """Return the RFC 6238 time step for a moment.

    :param at: Unix time; defaults to now.
    :returns: The 30-second step number.
    """
    return int((time.time() if at is None else at) // config.TOTP_PERIOD_SECONDS)


def current_code(secret: str, at: float | None = None) -> str:
    """Compute the one-time code for a secret.

    **This is a demo affordance, not part of the control.** In a real
    deployment the code is produced by the user's authenticator app and the
    server never has the means to generate it on their behalf. It exists here
    so the demo can be driven without six physical devices, and every caller
    is expected to say so.

    :param secret: The base32 shared secret.
    :param at: Unix time; defaults to now.
    :returns: The zero-padded code.
    """
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", current_step(at)), hashlib.sha1).digest()
    offset = digest[19] & 0x0F
    truncated = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(truncated % (10 ** config.TOTP_DIGITS)).zfill(config.TOTP_DIGITS)


def seconds_remaining(at: float | None = None) -> int:
    """How long the current code stays valid.

    :param at: Unix time; defaults to now.
    :returns: Whole seconds until the code rolls over.
    """
    now = time.time() if at is None else at
    return int(config.TOTP_PERIOD_SECONDS - (now % config.TOTP_PERIOD_SECONDS))


def enrolled_secret(conn: psycopg.Connection, db_role: str) -> str | None:
    """Read a principal's enrolled TOTP secret, as the owner.

    Only the pipeline owner can do this, and only the demo needs to. It is the
    one call in this module that a production system would not expose at all.

    :param conn: Open connection as the owner.
    :param db_role: The principal.
    :returns: The base32 secret, or ``None`` when not enrolled.
    """
    return db.fetch_value(
        conn,
        "SELECT secret FROM sec.auth_factor WHERE db_role = %s AND factor_type = 'totp'",
        (db_role,),
    )


def demo_fresh_code(db_role: str) -> str:
    """Return a code for this principal that has not been spent yet.

    **Demo only**, like :func:`current_code`: it reads the shared secret, which
    is the thing a real deployment keeps on the user's phone and nowhere else.

    A TOTP code may be used once, even inside its own thirty-second window --
    otherwise anyone who observes a code has half a minute to replay it. A
    real user whose code has just been consumed waits for their authenticator
    to roll over, so the demo waits too. Weakening the replay check to make a
    script run faster would be removing the control to demonstrate it.

    :param db_role: The principal.
    :returns: An unspent code.
    :raises AuthenticationError: When the principal has no second factor.
    """
    while True:
        with db.connect() as owner_conn:
            row = db.fetch_all(
                owner_conn,
                """
                SELECT secret, last_step,
                       floor(extract(epoch FROM now()) / %s)::bigint AS server_step
                FROM sec.auth_factor
                WHERE db_role = %s AND factor_type = 'totp'
                """,
                (config.TOTP_PERIOD_SECONDS, db_role),
            )
        if not row:
            raise AuthenticationError(f"{db_role}: no second factor enrolled")
        secret, spent = row[0]["secret"], row[0]["last_step"]
        # Require BOTH clocks to have moved past the spent step before
        # generating a new code. The verifier accepts the adjacent steps to
        # tolerate drift, which means the step it records as spent can be one
        # ahead of the step this process thinks it generated. Waiting on the
        # local clock alone therefore produces a code that is already spent,
        # roughly whenever the two disagree -- an intermittent failure that is
        # much easier to prevent here than to debug later.
        if spent is None or min(current_step(), int(row[0]["server_step"])) > int(spent):
            return current_code(secret)
        wait = seconds_remaining() + 0.5
        LOGGER.debug("%s: code for this window already spent, waiting %.1fs", db_role, wait)
        time.sleep(wait)


def demo_code_state(db_role: str) -> tuple[str | None, int]:
    """Return a usable code, or how long until one exists. Never sleeps.

    The blocking :func:`demo_fresh_code` is right for a script, which can
    afford to wait. It is wrong behind an HTTP request: a browser gets a
    thirty-second spinner with nothing to explain it, and a proxy may give up
    first. This reports the situation and lets the caller decide.

    **Demo only**, for the same reason as :func:`current_code`: it reads the
    shared secret, which in a real deployment lives on the user's phone.

    :param db_role: The principal.
    :returns: ``(code, 0)`` when one is available, or ``(None, seconds)``
        when the current code has been spent and a new one is due.
    :raises AuthenticationError: When the principal has no second factor.
    """
    with db.connect() as owner_conn:
        row = db.fetch_all(
            owner_conn,
            """
            SELECT secret, last_step,
                   floor(extract(epoch FROM now()) / %s)::bigint AS server_step
            FROM sec.auth_factor
            WHERE db_role = %s AND factor_type = 'totp'
            """,
            (config.TOTP_PERIOD_SECONDS, db_role),
        )
    if not row:
        raise AuthenticationError(f"{db_role}: no second factor enrolled")
    secret, spent = row[0]["secret"], row[0]["last_step"]
    if spent is None or min(current_step(), int(row[0]["server_step"])) > int(spent):
        return current_code(secret), 0
    return None, seconds_remaining() + 1


def verify_second_factor(conn: psycopg.Connection, code: str) -> Session:
    """Present the second factor on an already-authenticated connection.

    :param conn: Connection authenticated as the principal (factor 1 done).
    :param code: The one-time code.
    :returns: The opened session.
    :raises AuthenticationError: When the code is wrong, spent or locked out.
    """
    row = db.fetch_all(conn, "SELECT * FROM sec.verify_second_factor(%s)", (code,))[0]
    role = db.fetch_value(conn, "SELECT session_user")
    # Commit whether or not the code was accepted, and before raising.
    #
    # Both outcomes write, and both writes must be durable. A success inserts
    # the session; if that were left in the caller's transaction, a later
    # rollback would silently revoke the login, and the spent-code marker
    # would never persist -- so replay protection would appear to work in one
    # connection and fail across two. A failure increments the attempt
    # counter; rolling that back would hand an attacker unlimited guesses.
    if not conn.autocommit:
        conn.commit()
    if not row["ok"]:
        raise AuthenticationError(f"{role}: {row['detail']}")
    return Session(db_role=str(role), expires_at=row["expires_at"], detail=row["detail"])


@contextmanager
def login(db_role: str, password: str | None = None, code: str | None = None,
          *, demo_autocode: bool = False) -> Iterator[psycopg.Connection]:
    """Open a fully authenticated connection, or fail.

    Both steps happen here, in order, and the connection is only yielded once
    the second factor has been accepted. A caller therefore cannot
    accidentally use a half-authenticated connection -- the failure mode is an
    exception, not a connection that quietly returns nothing.

    :param db_role: The principal to authenticate as.
    :param password: Factor 1. Defaults to the demo password.
    :param code: Factor 2. Required unless ``demo_autocode`` is set.
    :param demo_autocode: Generate the code from the stored secret instead of
        being given one. **Demo only** -- it is the server standing in for the
        user's phone, which in production would defeat the whole control.
    :yields: The authenticated connection.
    :raises AuthenticationError: When either factor fails.
    """
    if code is None and not demo_autocode:
        raise AuthenticationError(
            f"{db_role}: no second factor supplied; login is two steps by design"
        )
    if demo_autocode:
        code = demo_fresh_code(db_role)

    password = config.DEMO_USER_PASSWORD if password is None else password
    try:
        conn = db.connect(user=db_role, password=password)
    except psycopg.OperationalError as exc:
        raise AuthenticationError(f"{db_role}: first factor rejected") from exc
    try:
        verify_second_factor(conn, code)
        yield conn
    finally:
        try:
            db.fetch_value(conn, "SELECT sec.end_session()")
            if not conn.autocommit:
                conn.commit()
        except psycopg.Error:
            pass
        conn.close()


def is_verified(conn: psycopg.Connection) -> bool:
    """Whether this connection currently holds a verified session.

    :param conn: Any connection.
    :returns: ``True`` when the second factor has been accepted and is live.
    """
    return bool(db.fetch_value(conn, "SELECT sec.has_verified_session()"))
