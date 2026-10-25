"""Prove the second factor is a control and not a formality.

The claim this module tests is narrow and checkable: **a principal holding the
correct password, and nothing else, can read no customer data at all.** If
that is true, a leaked database credential is not a breach on its own, which
is the entire point of adding a second factor.

It also pins the TOTP implementation against the published RFC 6238 test
vectors. "It looks like TOTP and the demo works" is not a standard; an
authenticator app will not interoperate with an almost-TOTP, and a code
generator that is subtly wrong is a control that cannot be re-implemented by
anyone else.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import struct
import time

import psycopg
import pytest

from src import auth, config, db

#: RFC 6238 appendix B, the SHA-1 rows. Seed is the ASCII string
#: "12345678901234567890"; codes are the 8-digit form.
RFC_SEED_B32 = base64.b32encode(b"12345678901234567890").decode("ascii")
RFC_VECTORS: tuple[tuple[int, str], ...] = (
    (59, "94287082"),
    (1111111109, "07081804"),
    (1111111111, "14050471"),
    (1234567890, "89005924"),
    (2000000000, "69279037"),
    (20000000000, "65353130"),
)


def _reference_totp(secret_b32: str, step: int, digits: int = 6) -> str:
    """An independent TOTP, written from the RFC rather than from our code.

    Deliberately not a call into :mod:`src.auth`: a test that uses the
    implementation it is testing proves only that the code is consistent with
    itself.

    :param secret_b32: Base32 shared secret.
    :param step: The 30-second time step.
    :param digits: Code length.
    :returns: The code.
    """
    key = base64.b32decode(secret_b32 + "=" * (-len(secret_b32) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[19] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % (10 ** digits)).zfill(digits)


# ---------------------------------------------------------------------------
# The algorithm
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("unix_time", "expected"), RFC_VECTORS)
def test_postgres_totp_matches_the_rfc_vectors(unix_time: int, expected: str) -> None:
    """The in-database generator must be real RFC 6238, not an approximation."""
    step = unix_time // config.TOTP_PERIOD_SECONDS
    with db.connect() as conn:
        produced = db.fetch_value(
            conn, "SELECT sec.totp_code(%s, %s, 8)", (RFC_SEED_B32, step)
        )
    assert produced == expected


@pytest.mark.parametrize(("unix_time", "expected"), RFC_VECTORS)
def test_python_totp_matches_the_rfc_vectors(unix_time: int, expected: str) -> None:
    """And so must the demo-side generator, or the two will disagree live."""
    assert _reference_totp(RFC_SEED_B32, unix_time // 30, 8) == expected


def test_the_two_implementations_agree_on_a_fresh_secret() -> None:
    """Postgres verifies; Python generates. A mismatch breaks every login."""
    secret = auth.new_secret()
    step = auth.current_step()
    with db.connect() as conn:
        in_db = db.fetch_value(
            conn, "SELECT sec.totp_code(%s, %s, %s)",
            (secret, step, config.TOTP_DIGITS),
        )
    assert in_db == auth.current_code(secret) == _reference_totp(
        secret, step, config.TOTP_DIGITS
    )


def test_base32_decode_rejects_rubbish() -> None:
    """A bad secret must raise, not silently decode to something."""
    with db.connect() as conn, pytest.raises(psycopg.Error):
        db.fetch_value(conn, "SELECT sec.base32_decode('not-base32!')")


# ---------------------------------------------------------------------------
# The control
# ---------------------------------------------------------------------------

#: Every principal, so none of them can be the one that was forgotten.
ALL_PRINCIPALS: tuple[str, ...] = config.DEMO_USERS


@pytest.mark.parametrize("role", ALL_PRINCIPALS)
def test_the_password_alone_reveals_nothing(role: str) -> None:
    """The headline claim: factor 1 on its own is worth zero rows.

    Not "fewer rows" and not "an error" -- the connection works, the queries
    run, and every one of them comes back empty. A stolen password is
    therefore not a breach by itself.
    """
    with db.connect(user=role, password=config.DEMO_USER_PASSWORD) as conn:
        assert db.fetch_value(conn, "SELECT sec.has_verified_session()") is False
        for view in ("client", "account", "loan", "transaction", "card",
                     "account_month_end_balance", "account_owner"):
            rows = int(db.fetch_value(conn, f"SELECT count(*) FROM ai.{view}") or 0)
            assert rows == 0, f"{role} read {rows} rows of ai.{view} with no second factor"


@pytest.mark.parametrize("role", ALL_PRINCIPALS)
def test_both_factors_together_do_reveal_something(role: str) -> None:
    """And the control must not simply be "nobody sees anything, ever"."""
    expect_rows = role != "rm_unassigned"
    with auth.login(role, demo_autocode=True) as conn:
        assert db.fetch_value(conn, "SELECT sec.has_verified_session()") is True
        rows = int(db.fetch_value(conn, "SELECT count(*) FROM ai.client") or 0)
    assert (rows > 0) is expect_rows, f"{role} saw {rows} clients after a full login"


def test_a_wrong_code_is_refused_and_changes_nothing() -> None:
    """A failed second factor must leave the connection exactly as it was."""
    with db.connect(user="rm_north", password=config.DEMO_USER_PASSWORD) as conn:
        result = db.fetch_all(conn, "SELECT * FROM sec.verify_second_factor('000000')")[0]
        assert result["ok"] is False
        assert result["session_id"] is None
        assert int(db.fetch_value(conn, "SELECT count(*) FROM ai.client") or 0) == 0


def test_a_code_cannot_be_used_twice() -> None:
    """Replay inside the validity window must be refused.

    A TOTP code lives for thirty seconds. Without this, an attacker who
    observes one code has a thirty-second window to open their own session
    with it.
    """
    code = auth.demo_fresh_code("rm_south")
    with db.connect(user="rm_south", password=config.DEMO_USER_PASSWORD) as first:
        accepted = db.fetch_all(
            first, "SELECT * FROM sec.verify_second_factor(%s)", (code,))[0]
        assert accepted["ok"], f"first use was refused: {accepted['detail']}"
    with db.connect(user="rm_south", password=config.DEMO_USER_PASSWORD) as second:
        replay = db.fetch_all(second, "SELECT * FROM sec.verify_second_factor(%s)", (code,))[0]
        assert replay["ok"] is False
        assert "already used" in replay["detail"]
        assert int(db.fetch_value(second, "SELECT count(*) FROM ai.client") or 0) == 0


def test_a_session_does_not_leak_to_another_connection() -> None:
    """A verified session belongs to one backend, not to the role.

    Without the backend binding, one user completing a login would authorise
    every other connection open as the same role -- which is precisely the
    hole that makes shared service accounts dangerous.
    """
    with auth.login("rm_north", demo_autocode=True) as verified:
        assert int(db.fetch_value(verified, "SELECT count(*) FROM ai.client") or 0) > 0
        # A second, independent connection as the SAME role, no second factor.
        with db.connect(user="rm_north", password=config.DEMO_USER_PASSWORD) as other:
            assert db.fetch_value(other, "SELECT sec.has_verified_session()") is False
            assert int(db.fetch_value(other, "SELECT count(*) FROM ai.client") or 0) == 0


def test_logging_out_takes_the_data_away_again() -> None:
    """End the session and the same connection goes back to seeing nothing."""
    code = auth.demo_fresh_code("rm_north")
    with db.connect(user="rm_north", password=config.DEMO_USER_PASSWORD) as conn:
        auth.verify_second_factor(conn, code)
        before = int(db.fetch_value(conn, "SELECT count(*) FROM ai.client") or 0)
        db.fetch_value(conn, "SELECT sec.end_session()")
        after = int(db.fetch_value(conn, "SELECT count(*) FROM ai.client") or 0)
    assert before > 0 and after == 0, f"before={before} after={after}"


def test_an_expired_session_stops_working() -> None:
    """Expiry is enforced on read, not merely recorded."""
    with auth.login("rm_north", demo_autocode=True) as conn:
        assert int(db.fetch_value(conn, "SELECT count(*) FROM ai.client") or 0) > 0
        # Age the session past its expiry, as the owner.
        with db.connect() as owner:
            db.execute(
                owner,
                """
                UPDATE sec.auth_session SET expires_at = now() - interval '1 minute'
                WHERE db_role = 'rm_north' AND ended_at IS NULL
                """,
            )
            owner.commit()
        assert int(db.fetch_value(conn, "SELECT count(*) FROM ai.client") or 0) == 0


def test_a_consumer_cannot_reach_the_authentication_machinery() -> None:
    """The secrets, the sessions and the grants are not the consumer's to read."""
    with auth.login("client_11409", demo_autocode=True) as conn:
        for statement in (
            "SELECT count(*) FROM sec.auth_factor",
            "SELECT count(*) FROM sec.auth_session",
            "SELECT count(*) FROM sec.access_grant",
            "SELECT count(*) FROM sec.v_who_can_reach_client",
            "SELECT sec.totp_code('AAAA', 1)",
        ):
            with pytest.raises(psycopg.Error):
                db.fetch_value(conn, statement)
            conn.rollback()
        # Still logged in and still entitled to their own row afterwards.
        assert int(db.fetch_value(conn, "SELECT count(*) FROM ai.client") or 0) == 1


def test_a_consumer_cannot_verify_a_factor_for_someone_else() -> None:
    """The function takes a code, never a principal. Check it stays that way."""
    with db.connect() as conn:
        arguments = db.fetch_value(
            conn,
            """
            SELECT pg_get_function_identity_arguments(p.oid)
            FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
            WHERE n.nspname = 'sec' AND p.proname = 'verify_second_factor'
            """,
        )
    assert arguments.count(",") == 0 and arguments.endswith("text"), (
        f"verify_second_factor takes ({arguments}); a second parameter would let "
        f"a caller nominate whose factor is being checked"
    )
    assert "role" not in arguments and "user" not in arguments


def test_login_refuses_to_hand_back_a_half_authenticated_connection() -> None:
    """A caller must not be able to forget step two by accident."""
    with pytest.raises(auth.AuthenticationError):
        with auth.login("rm_north"):
            pass
    with pytest.raises(auth.AuthenticationError):
        with auth.login("rm_north", code="000000"):
            pass


def test_the_demo_code_generator_tracks_the_clock() -> None:
    """seconds_remaining must describe the window the code is actually in."""
    secret = auth.new_secret()
    now = time.time()
    assert auth.current_code(secret, now) == auth.current_code(
        secret, now + auth.seconds_remaining(now) - 1
    )
    assert auth.current_code(secret, now) != auth.current_code(
        secret, now + auth.seconds_remaining(now) + 1
    )
