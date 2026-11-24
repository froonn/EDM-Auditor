"""Structured security event logging for authentication and RBAC actions."""

import json
from enum import StrEnum
from typing import Any

from sqlalchemy.orm import Session

from edm_auditor.database.models import AuthAuditLog, User


class AuthAuditAction(StrEnum):
    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILED = "login_failed"
    LOGOUT = "logout"
    LOGOUT_ALL = "logout_all"
    PASSWORD_CHANGED = "password_changed"
    PASSWORD_RESET = "password_reset"
    USER_CREATED = "user_created"
    USER_UPDATED = "user_updated"
    USER_DISABLED = "user_disabled"
    USER_ENABLED = "user_enabled"
    USER_SESSIONS_REVOKED = "user_sessions_revoked"
    USER_GROUPS_UPDATED = "user_groups_updated"
    GROUP_CREATED = "group_created"
    GROUP_UPDATED = "group_updated"
    GROUP_PERMISSIONS_UPDATED = "group_permissions_updated"
    GROUP_DELETED = "group_deleted"
    SUPER_ADMIN_TRANSFERRED = "super_admin_transferred"


def record_auth_event(
    session: Session,
    action: AuthAuditAction | str,
    *,
    actor: User | None = None,
    actor_username: str | None = None,
    target_type: str | None = None,
    target_id: str | int | None = None,
    details: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> AuthAuditLog:
    resolved_username = actor_username
    if resolved_username is None:
        resolved_username = actor.username if actor is not None else ""
    entry = AuthAuditLog(
        actor_user_id=actor.id if actor is not None else None,
        actor_username=resolved_username[:100],
        action=str(action),
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        details_json=json.dumps(details or {}, ensure_ascii=False, sort_keys=True),
        ip_address=ip_address[:64] if ip_address else None,
    )
    session.add(entry)
    session.flush()
    return entry
