"""FastAPI dependencies for session authentication and permission enforcement."""

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Depends, Request

from edm_auditor.api.errors import ApiError
from edm_auditor.database.models import User

from .permissions import Permission, effective_permissions
from .sessions import authenticate_session


@dataclass(frozen=True, slots=True)
class AuthContext:
    user: User
    session_id: int
    permissions: frozenset[Permission]
    ip_address: str | None


def extract_client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",", 1)[0].strip()
        if first:
            return first
    if request.client and request.client.host:
        return request.client.host
    return None


def _authenticate_request(
    request: Request, *, allow_password_change_pending: bool
) -> AuthContext:
    settings = request.app.state.settings
    session_factory = request.app.state.session_factory
    raw_token = request.cookies.get(settings.auth_cookie_name)
    if not raw_token:
        raise ApiError(401, "unauthorized", "Authentication required")

    with session_factory() as db_session:
        authenticated = authenticate_session(db_session, raw_token)
        if authenticated is None:
            raise ApiError(401, "unauthorized", "Invalid or expired session")
        user, user_session = authenticated
        perms = effective_permissions(user)
        session_id = user_session.id
        must_change = user.must_change_password

    if must_change and not allow_password_change_pending:
        raise ApiError(
            403,
            "password_change_required",
            "You must change your temporary password before continuing",
        )

    return AuthContext(
        user=user,
        session_id=session_id,
        permissions=perms,
        ip_address=extract_client_ip(request),
    )


def get_auth_context_allow_password_change(request: Request) -> AuthContext:
    return _authenticate_request(request, allow_password_change_pending=True)


def get_auth_context(request: Request) -> AuthContext:
    return _authenticate_request(request, allow_password_change_pending=False)


def require_permission(permission: Permission) -> Callable[..., AuthContext]:
    def _dependency(auth: AuthContext = Depends(get_auth_context)) -> AuthContext:
        if permission not in auth.permissions:
            raise ApiError(
                403,
                "forbidden",
                f"Missing required permission: {permission.value}",
            )
        return auth

    return _dependency


def require_any_permission(*permissions: Permission) -> Callable[..., AuthContext]:
    required = frozenset(permissions)

    def _dependency(auth: AuthContext = Depends(get_auth_context)) -> AuthContext:
        if not (auth.permissions & required):
            names = ", ".join(sorted(p.value for p in required))
            raise ApiError(
                403,
                "forbidden",
                f"Missing required permission (one of: {names})",
            )
        return auth

    return _dependency


def require_super_admin(auth: AuthContext = Depends(get_auth_context)) -> AuthContext:
    if not auth.user.is_super_admin:
        raise ApiError(403, "forbidden", "Super-admin privileges required")
    return auth
