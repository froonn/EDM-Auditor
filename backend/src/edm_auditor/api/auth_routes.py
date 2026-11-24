"""FastAPI router for authentication, users, Linux-style groups, and security audit logs."""

import json
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from edm_auditor.auth.audit_log import AuthAuditAction, record_auth_event
from edm_auditor.auth.dependencies import (
    AuthContext,
    extract_client_ip,
    get_auth_context_allow_password_change,
    require_any_permission,
    require_permission,
    require_super_admin,
)
from edm_auditor.auth.errors import AuthError
from edm_auditor.auth.permissions import (
    PERMISSION_CATALOG,
    Permission,
    effective_permissions,
    group_permissions,
)
from edm_auditor.auth.service import (
    authenticate_user,
    change_own_password,
    create_custom_group,
    create_user,
    delete_custom_group,
    load_user_with_groups,
    revoke_target_user_sessions,
    set_group_permissions,
    set_user_groups,
    transfer_super_admin,
    update_custom_group,
    update_user,
)
from edm_auditor.auth.sessions import (
    authenticate_session,
    create_session,
    revoke_session,
    revoke_user_sessions,
)
from edm_auditor.database.enums import GroupKind
from edm_auditor.database.models import AuthAuditLog, Group, User

from .schemas import (
    AuthAuditLogResponse,
    AuthUserResponse,
    ChangePasswordRequest,
    GroupCreate,
    GroupMemberSummary,
    GroupPermissionsUpdate,
    GroupResponse,
    GroupSummaryResponse,
    GroupUpdate,
    LoginRequest,
    PermissionInfoResponse,
    RevokeSessionsResponse,
    TransferSuperAdminRequest,
    TransferSuperAdminResponse,
    UserCreate,
    UserGroupsUpdate,
    UserResponse,
    UserUpdate,
)


def _auth_user_response(user: User) -> AuthUserResponse:
    perms = sorted(p.value for p in effective_permissions(user))
    groups = [
        GroupSummaryResponse(id=g.id, name=g.name, kind=g.kind)
        for g in sorted(user.groups, key=lambda item: (item.kind, item.name))
    ]
    return AuthUserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        is_super_admin=user.is_super_admin,
        must_change_password=user.must_change_password,
        groups=groups,
        permissions=perms,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
    )


def _user_response(user: User) -> UserResponse:
    perms = sorted(p.value for p in effective_permissions(user))
    personal_group_id = user.personal_group.id if user.personal_group is not None else None
    custom_groups = [
        GroupSummaryResponse(id=g.id, name=g.name, kind=g.kind)
        for g in sorted(user.groups, key=lambda item: item.name)
        if g.kind == GroupKind.CUSTOM.value
    ]
    return UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        is_super_admin=user.is_super_admin,
        must_change_password=user.must_change_password,
        personal_group_id=personal_group_id,
        custom_groups=custom_groups,
        permissions=perms,
        created_at=user.created_at,
        updated_at=user.updated_at,
        last_login_at=user.last_login_at,
    )


def _group_response(group: Group) -> GroupResponse:
    members = [
        GroupMemberSummary(
            id=member.id,
            username=member.username,
            full_name=member.full_name,
            is_active=member.is_active,
        )
        for member in sorted(group.members, key=lambda item: item.username)
    ]
    return GroupResponse(
        id=group.id,
        name=group.name,
        kind=group.kind,
        description=group.description,
        owner_user_id=group.owner_user_id,
        owner_username=group.owner.username if group.owner is not None else None,
        member_count=len(members),
        members=members,
        permissions=sorted(p.value for p in group_permissions(group)),
        created_at=group.created_at,
        updated_at=group.updated_at,
    )


def _set_session_cookie(response: Response, request: Request, raw_token: str) -> None:
    settings = request.app.state.settings
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=raw_token,
        httponly=True,
        samesite="lax",
        secure=settings.auth_cookie_secure,
        path="/",
        max_age=settings.auth_session_ttl_hours * 3600,
    )


def _clear_session_cookie(response: Response, request: Request) -> None:
    settings = request.app.state.settings
    response.delete_cookie(
        key=settings.auth_cookie_name,
        httponly=True,
        samesite="lax",
        secure=settings.auth_cookie_secure,
        path="/",
    )


def create_auth_router() -> APIRouter:
    router = APIRouter()

    # ------------------------------------------------------------------
    # Authentication & session endpoints
    # ------------------------------------------------------------------

    @router.post("/api/auth/login", response_model=AuthUserResponse)
    def login(
        payload: LoginRequest,
        request: Request,
        response: Response,
    ) -> AuthUserResponse:
        settings = request.app.state.settings
        session_factory = request.app.state.session_factory
        limiter = request.app.state.login_rate_limiter
        ip_address = extract_client_ip(request)
        user_agent = request.headers.get("user-agent")

        limiter.check(ip_address, payload.username)
        auth_error: AuthError | None = None
        raw_token = ""
        result: AuthUserResponse | None = None
        with session_factory.begin() as db_session:
            try:
                user = authenticate_user(
                    db_session,
                    username=payload.username,
                    password=payload.password,
                    ip_address=ip_address,
                )
            except AuthError as exc:
                limiter.record_failure(ip_address, payload.username)
                auth_error = exc
            else:
                raw_token, _ = create_session(
                    db_session,
                    user,
                    ttl_hours=settings.auth_session_ttl_hours,
                    ip_address=ip_address,
                    user_agent=user_agent,
                )
                result = _auth_user_response(user)

        if auth_error is not None:
            raise auth_error
        assert result is not None
        limiter.reset(ip_address, payload.username)
        _set_session_cookie(response, request, raw_token)
        return result

    @router.post("/api/auth/logout", status_code=204)
    def logout(request: Request, response: Response) -> None:
        settings = request.app.state.settings
        session_factory = request.app.state.session_factory
        raw_token = request.cookies.get(settings.auth_cookie_name)
        ip_address = extract_client_ip(request)
        if raw_token:
            with session_factory.begin() as db_session:
                found = authenticate_session(db_session, raw_token)
                revoke_session(db_session, raw_token)
                if found is not None:
                    user, _ = found
                    record_auth_event(
                        db_session,
                        AuthAuditAction.LOGOUT,
                        actor=user,
                        target_type="session",
                        ip_address=ip_address,
                    )
        _clear_session_cookie(response, request)

    @router.post("/api/auth/logout-all", status_code=204)
    def logout_all(
        request: Request,
        response: Response,
        auth: AuthContext = Depends(get_auth_context_allow_password_change),
    ) -> None:
        session_factory = request.app.state.session_factory
        with session_factory.begin() as db_session:
            revoked = revoke_user_sessions(db_session, auth.user.id)
            record_auth_event(
                db_session,
                AuthAuditAction.LOGOUT_ALL,
                actor=auth.user,
                target_type="session",
                details={"revoked_count": revoked},
                ip_address=auth.ip_address,
            )
        _clear_session_cookie(response, request)

    @router.get("/api/auth/me", response_model=AuthUserResponse)
    def get_me(
        auth: AuthContext = Depends(get_auth_context_allow_password_change),
    ) -> AuthUserResponse:
        return _auth_user_response(auth.user)

    @router.post("/api/auth/change-password", response_model=AuthUserResponse)
    def change_password(
        payload: ChangePasswordRequest,
        request: Request,
        auth: AuthContext = Depends(get_auth_context_allow_password_change),
    ) -> AuthUserResponse:
        session_factory = request.app.state.session_factory
        with session_factory.begin() as db_session:
            user = load_user_with_groups(db_session, auth.user.id)
            assert user is not None
            change_own_password(
                db_session,
                user=user,
                current_password=payload.current_password,
                new_password=payload.new_password,
                current_session_id=auth.session_id,
                ip_address=auth.ip_address,
            )
            return _auth_user_response(user)

    @router.post("/api/auth/transfer-super-admin", response_model=TransferSuperAdminResponse)
    def transfer_super_admin_endpoint(
        payload: TransferSuperAdminRequest,
        request: Request,
        auth: AuthContext = Depends(require_super_admin),
    ) -> TransferSuperAdminResponse:
        session_factory = request.app.state.session_factory
        with session_factory.begin() as db_session:
            target = transfer_super_admin(
                db_session,
                actor=auth.user,
                current_password=payload.current_password,
                target_user_id=payload.target_user_id,
                ip_address=auth.ip_address,
            )
            return TransferSuperAdminResponse(
                previous_super_admin_id=auth.user.id,
                previous_super_admin_username=auth.user.username,
                new_super_admin_id=target.id,
                new_super_admin_username=target.username,
            )

    @router.get("/api/auth/audit-log", response_model=list[AuthAuditLogResponse])
    def list_auth_audit_log(
        request: Request,
        response: Response,
        action: str | None = None,
        actor_username: str | None = None,
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        _: AuthContext = Depends(
            require_any_permission(Permission.USERS_MANAGE, Permission.GROUPS_MANAGE)
        ),
    ) -> list[AuthAuditLogResponse]:
        session_factory = request.app.state.session_factory
        with session_factory() as db_session:
            base = select(AuthAuditLog)
            if action:
                base = base.where(AuthAuditLog.action == action.strip())
            if actor_username:
                base = base.where(
                    func.lower(AuthAuditLog.actor_username).contains(
                        actor_username.strip().lower()
                    )
                )
            total = db_session.scalar(
                select(func.count()).select_from(base.subquery())
            )
            rows = db_session.scalars(
                base.order_by(AuthAuditLog.created_at.desc(), AuthAuditLog.id.desc())
                .limit(limit)
                .offset(offset)
            ).all()
        response.headers["X-Total-Count"] = str(int(total or 0))
        return [
            AuthAuditLogResponse(
                id=row.id,
                actor_user_id=row.actor_user_id,
                actor_username=row.actor_username,
                action=row.action,
                target_type=row.target_type,
                target_id=row.target_id,
                details=json.loads(row.details_json) if row.details_json else {},
                ip_address=row.ip_address,
                created_at=row.created_at,
            )
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Users management endpoints
    # ------------------------------------------------------------------

    @router.get("/api/users", response_model=list[UserResponse])
    def list_users(
        request: Request,
        response: Response,
        search: str | None = None,
        is_active: bool | None = None,
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        _: AuthContext = Depends(require_permission(Permission.USERS_MANAGE)),
    ) -> list[UserResponse]:
        session_factory = request.app.state.session_factory
        with session_factory() as db_session:
            base = select(User)
            if search and search.strip():
                needle = search.strip().lower()
                base = base.where(
                    func.lower(User.username).contains(needle)
                    | func.lower(User.email).contains(needle)
                    | func.lower(User.full_name).contains(needle)
                )
            if is_active is not None:
                base = base.where(User.is_active.is_(is_active))
            total = db_session.scalar(select(func.count()).select_from(base.subquery()))
            users = db_session.scalars(
                base.options(
                    selectinload(User.groups).selectinload(Group.permissions),
                    selectinload(User.personal_group),
                )
                .order_by(User.is_super_admin.desc(), User.username.asc())
                .limit(limit)
                .offset(offset)
            ).all()
            items = [_user_response(user) for user in users]
        response.headers["X-Total-Count"] = str(int(total or 0))
        return items

    @router.post("/api/users", response_model=UserResponse, status_code=201)
    def create_user_endpoint(
        payload: UserCreate,
        request: Request,
        auth: AuthContext = Depends(require_permission(Permission.USERS_MANAGE)),
    ) -> UserResponse:
        session_factory = request.app.state.session_factory
        with session_factory.begin() as db_session:
            actor = load_user_with_groups(db_session, auth.user.id)
            assert actor is not None
            user = create_user(
                db_session,
                actor=actor,
                username=payload.username,
                email=payload.email,
                password=payload.password,
                full_name=payload.full_name,
                custom_group_ids=payload.custom_group_ids,
                must_change_password=payload.must_change_password,
                ip_address=auth.ip_address,
            )
            loaded = load_user_with_groups(db_session, user.id)
            assert loaded is not None
            return _user_response(loaded)

    @router.patch("/api/users/{user_id}", response_model=UserResponse)
    def update_user_endpoint(
        user_id: int,
        payload: UserUpdate,
        request: Request,
        auth: AuthContext = Depends(require_permission(Permission.USERS_MANAGE)),
    ) -> UserResponse:
        session_factory = request.app.state.session_factory
        fields = payload.model_dump(exclude_unset=True)
        kwargs: dict[str, object] = {}
        for key in ("email", "full_name", "is_active", "new_password"):
            if key in fields:
                kwargs[key] = fields[key]
        with session_factory.begin() as db_session:
            actor = load_user_with_groups(db_session, auth.user.id)
            assert actor is not None
            user = update_user(
                db_session,
                actor=actor,
                target_user_id=user_id,
                ip_address=auth.ip_address,
                **kwargs,
            )
            return _user_response(user)

    @router.put("/api/users/{user_id}/groups", response_model=UserResponse)
    def set_user_groups_endpoint(
        user_id: int,
        payload: UserGroupsUpdate,
        request: Request,
        auth: AuthContext = Depends(require_permission(Permission.USERS_MANAGE)),
    ) -> UserResponse:
        session_factory = request.app.state.session_factory
        with session_factory.begin() as db_session:
            actor = load_user_with_groups(db_session, auth.user.id)
            assert actor is not None
            user = set_user_groups(
                db_session,
                actor=actor,
                target_user_id=user_id,
                custom_group_ids=payload.custom_group_ids,
                ip_address=auth.ip_address,
            )
            return _user_response(user)

    @router.post("/api/users/{user_id}/revoke-sessions", response_model=RevokeSessionsResponse)
    def revoke_user_sessions_endpoint(
        user_id: int,
        request: Request,
        auth: AuthContext = Depends(require_permission(Permission.USERS_MANAGE)),
    ) -> RevokeSessionsResponse:
        session_factory = request.app.state.session_factory
        with session_factory.begin() as db_session:
            actor = load_user_with_groups(db_session, auth.user.id)
            assert actor is not None
            count = revoke_target_user_sessions(
                db_session,
                actor=actor,
                target_user_id=user_id,
                ip_address=auth.ip_address,
            )
            return RevokeSessionsResponse(revoked_count=count)

    # ------------------------------------------------------------------
    # Permissions catalog & groups endpoints
    # ------------------------------------------------------------------

    @router.get("/api/permissions", response_model=list[PermissionInfoResponse])
    def list_permissions(
        _: AuthContext = Depends(
            require_any_permission(Permission.GROUPS_MANAGE, Permission.USERS_MANAGE)
        ),
    ) -> list[PermissionInfoResponse]:
        return [
            PermissionInfoResponse(
                code=item.code.value,
                description=item.description,
                super_admin_only=item.super_admin_only,
            )
            for item in PERMISSION_CATALOG
        ]

    @router.get("/api/groups", response_model=list[GroupResponse])
    def list_groups(
        request: Request,
        kind: Literal["system", "custom", "personal"] | None = None,
        search: str | None = None,
        _: AuthContext = Depends(
            require_any_permission(Permission.GROUPS_MANAGE, Permission.USERS_MANAGE)
        ),
    ) -> list[GroupResponse]:
        session_factory = request.app.state.session_factory
        with session_factory() as db_session:
            stmt = select(Group).options(
                selectinload(Group.permissions),
                selectinload(Group.members),
                selectinload(Group.owner),
            )
            if kind is not None:
                stmt = stmt.where(Group.kind == kind)
            if search and search.strip():
                needle = search.strip().lower()
                stmt = stmt.where(
                    func.lower(Group.name).contains(needle)
                    | func.lower(Group.description).contains(needle)
                )
            groups = db_session.scalars(
                stmt.order_by(Group.kind.asc(), Group.name.asc())
            ).all()
            return [_group_response(group) for group in groups]

    @router.post("/api/groups", response_model=GroupResponse, status_code=201)
    def create_group_endpoint(
        payload: GroupCreate,
        request: Request,
        auth: AuthContext = Depends(require_permission(Permission.GROUPS_MANAGE)),
    ) -> GroupResponse:
        session_factory = request.app.state.session_factory
        with session_factory.begin() as db_session:
            actor = load_user_with_groups(db_session, auth.user.id)
            assert actor is not None
            group = create_custom_group(
                db_session,
                actor=actor,
                name=payload.name,
                description=payload.description,
                permissions=payload.permissions,
                ip_address=auth.ip_address,
            )
            loaded = db_session.scalar(
                select(Group)
                .options(
                    selectinload(Group.permissions),
                    selectinload(Group.members),
                    selectinload(Group.owner),
                )
                .where(Group.id == group.id)
            )
            assert loaded is not None
            return _group_response(loaded)

    @router.patch("/api/groups/{group_id}", response_model=GroupResponse)
    def update_group_endpoint(
        group_id: int,
        payload: GroupUpdate,
        request: Request,
        auth: AuthContext = Depends(require_permission(Permission.GROUPS_MANAGE)),
    ) -> GroupResponse:
        session_factory = request.app.state.session_factory
        fields = payload.model_dump(exclude_unset=True)
        kwargs: dict[str, object] = {}
        for key in ("name", "description"):
            if key in fields:
                kwargs[key] = fields[key]
        with session_factory.begin() as db_session:
            actor = load_user_with_groups(db_session, auth.user.id)
            assert actor is not None
            group = update_custom_group(
                db_session,
                actor=actor,
                group_id=group_id,
                ip_address=auth.ip_address,
                **kwargs,
            )
            loaded = db_session.scalar(
                select(Group)
                .options(
                    selectinload(Group.permissions),
                    selectinload(Group.members),
                    selectinload(Group.owner),
                )
                .where(Group.id == group.id)
            )
            assert loaded is not None
            return _group_response(loaded)

    @router.put("/api/groups/{group_id}/permissions", response_model=GroupResponse)
    def set_group_permissions_endpoint(
        group_id: int,
        payload: GroupPermissionsUpdate,
        request: Request,
        auth: AuthContext = Depends(require_permission(Permission.GROUPS_MANAGE)),
    ) -> GroupResponse:
        session_factory = request.app.state.session_factory
        with session_factory.begin() as db_session:
            actor = load_user_with_groups(db_session, auth.user.id)
            assert actor is not None
            group = set_group_permissions(
                db_session,
                actor=actor,
                group_id=group_id,
                permissions=payload.permissions,
                ip_address=auth.ip_address,
            )
            loaded = db_session.scalar(
                select(Group)
                .options(
                    selectinload(Group.permissions),
                    selectinload(Group.members),
                    selectinload(Group.owner),
                )
                .where(Group.id == group.id)
            )
            assert loaded is not None
            return _group_response(loaded)

    @router.delete("/api/groups/{group_id}", status_code=204)
    def delete_group_endpoint(
        group_id: int,
        request: Request,
        auth: AuthContext = Depends(require_permission(Permission.GROUPS_MANAGE)),
    ) -> None:
        session_factory = request.app.state.session_factory
        with session_factory.begin() as db_session:
            actor = load_user_with_groups(db_session, auth.user.id)
            assert actor is not None
            delete_custom_group(
                db_session,
                actor=actor,
                group_id=group_id,
                ip_address=auth.ip_address,
            )

    return router
