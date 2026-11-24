"""Server-side session lifecycle management with SHA-256 token hashing."""

from datetime import UTC, datetime, timedelta
import hashlib
import secrets

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session, selectinload

from edm_auditor.database.models import Group, User, UserSession, utc_now


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def hash_session_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def create_session(
    session: Session,
    user: User,
    *,
    ttl_hours: int = 24,
    ip_address: str | None = None,
    user_agent: str | None = None,
    now: datetime | None = None,
) -> tuple[str, UserSession]:
    current_time = _as_utc(now) if now is not None else utc_now()
    raw_token = secrets.token_urlsafe(32)
    record = UserSession(
        user_id=user.id,
        token_hash=hash_session_token(raw_token),
        created_at=current_time,
        expires_at=current_time + timedelta(hours=ttl_hours),
        ip_address=ip_address[:64] if ip_address else None,
        user_agent=user_agent[:500] if user_agent else None,
    )
    session.add(record)
    session.flush()
    return raw_token, record


def authenticate_session(
    session: Session,
    raw_token: str | None,
    *,
    now: datetime | None = None,
) -> tuple[User, UserSession] | None:
    if not raw_token:
        return None
    current_time = _as_utc(now) if now is not None else utc_now()
    token_digest = hash_session_token(raw_token)
    record = session.scalar(
        select(UserSession)
        .options(
            selectinload(UserSession.user)
            .selectinload(User.groups)
            .selectinload(Group.permissions),
            selectinload(UserSession.user).selectinload(User.personal_group),
        )
        .where(UserSession.token_hash == token_digest)
    )
    if record is None or record.revoked_at is not None:
        return None
    if _as_utc(record.expires_at) <= current_time:
        return None
    user = record.user
    if user is None or not user.is_active:
        return None
    return user, record


def revoke_session(
    session: Session,
    raw_token: str | None,
    *,
    now: datetime | None = None,
) -> UserSession | None:
    if not raw_token:
        return None
    current_time = _as_utc(now) if now is not None else utc_now()
    record = session.scalar(
        select(UserSession).where(UserSession.token_hash == hash_session_token(raw_token))
    )
    if record is None:
        return None
    if record.revoked_at is None:
        record.revoked_at = current_time
        session.flush()
    return record


def revoke_user_sessions(
    session: Session,
    user_id: int,
    *,
    except_session_id: int | None = None,
    now: datetime | None = None,
) -> int:
    current_time = _as_utc(now) if now is not None else utc_now()
    stmt = (
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=current_time)
    )
    if except_session_id is not None:
        stmt = stmt.where(UserSession.id != except_session_id)
    result = session.execute(stmt)
    return int(result.rowcount or 0)


def purge_expired_sessions(session: Session, *, now: datetime | None = None) -> int:
    current_time = _as_utc(now) if now is not None else utc_now()
    result = session.execute(
        delete(UserSession).where(UserSession.expires_at <= current_time)
    )
    return int(result.rowcount or 0)
