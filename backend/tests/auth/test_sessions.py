from datetime import UTC, datetime, timedelta

import pytest

from edm_auditor.auth.errors import LoginRateLimitedError
from edm_auditor.auth.rate_limit import LoginRateLimiter
from edm_auditor.auth.service import create_super_admin
from edm_auditor.auth.sessions import (
    authenticate_session,
    create_session,
    hash_session_token,
    purge_expired_sessions,
    revoke_session,
    revoke_user_sessions,
)
from edm_auditor.database import Base, create_engine_for, create_session_factory
from edm_auditor.database.models import User, UserSession


@pytest.fixture
def session_factory():
    engine = create_engine_for("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    try:
        yield factory
    finally:
        engine.dispose()


def test_session_lifecycle_hashing_expiry_and_revocation(session_factory) -> None:
    t0 = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)
    with session_factory.begin() as session:
        user = create_super_admin(
            session,
            username="rootadmin",
            email="root@example.com",
            password="strong-password-123",
        )
        token1, s1 = create_session(
            session, user, ttl_hours=2, ip_address="127.0.0.1", user_agent="pytest", now=t0
        )
        token2, s2 = create_session(session, user, ttl_hours=2, now=t0)
        s1_id = s1.id
        user_id = user.id

        # Raw token is never stored in DB.
        assert s1.token_hash == hash_session_token(token1)
        assert s1.token_hash != token1
        assert s2.token_hash != token2

    # Valid within TTL.
    with session_factory() as session:
        found = authenticate_session(session, token1, now=t0 + timedelta(hours=1))
        assert found is not None
        loaded_user, loaded_sess = found
        assert loaded_user.id == user_id
        assert loaded_sess.id == s1_id

    # Expired after TTL.
    with session_factory() as session:
        assert authenticate_session(session, token1, now=t0 + timedelta(hours=2)) is None

    # Revoke all except s1.
    with session_factory.begin() as session:
        revoked = revoke_user_sessions(session, user_id, except_session_id=s1_id, now=t0)
        assert revoked == 1

    with session_factory() as session:
        assert authenticate_session(session, token1, now=t0 + timedelta(minutes=10)) is not None
        assert authenticate_session(session, token2, now=t0 + timedelta(minutes=10)) is None

    # Revoke single session directly.
    with session_factory.begin() as session:
        assert revoke_session(session, token1, now=t0 + timedelta(minutes=20)) is not None

    with session_factory() as session:
        assert authenticate_session(session, token1, now=t0 + timedelta(minutes=30)) is None

    # Purge expired sessions.
    with session_factory.begin() as session:
        purged = purge_expired_sessions(session, now=t0 + timedelta(hours=3))
        assert purged == 2
        assert session.query(UserSession).count() == 0


def test_authenticate_session_rejects_disabled_user(session_factory) -> None:
    t0 = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)
    with session_factory.begin() as session:
        user = User(
            username="bob",
            email="bob@example.com",
            hashed_password="hash",
            is_active=True,
        )
        session.add(user)
        session.flush()
        token, _ = create_session(session, user, ttl_hours=1, now=t0)
        user_id = user.id

    with session_factory.begin() as session:
        session.get(User, user_id).is_active = False

    with session_factory() as session:
        assert authenticate_session(session, token, now=t0 + timedelta(minutes=1)) is None


def test_login_rate_limiter_sliding_window_and_reset() -> None:
    now = [100.0]
    limiter = LoginRateLimiter(max_attempts=3, window_seconds=60.0, clock=lambda: now[0])

    for _ in range(3):
        limiter.check("10.0.0.1", "Alice")
        limiter.record_failure("10.0.0.1", "alice")

    with pytest.raises(LoginRateLimitedError):
        limiter.check("10.0.0.1", "ALICE")

    # Different user or IP is unaffected.
    limiter.check("10.0.0.1", "bob")
    limiter.check("10.0.0.2", "alice")

    # After window elapses, attempts expire.
    now[0] += 61.0
    limiter.check("10.0.0.1", "alice")

    # Explicit reset clears accumulated failures.
    limiter.record_failure("10.0.0.1", "alice")
    limiter.record_failure("10.0.0.1", "alice")
    limiter.record_failure("10.0.0.1", "alice")
    limiter.reset("10.0.0.1", "alice")
    limiter.check("10.0.0.1", "alice")
