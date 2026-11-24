"""Domain services for users, Linux-style groups, permissions, and super-admin."""

from collections.abc import Iterable
import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from edm_auditor.database.enums import GroupKind
from edm_auditor.database.models import (
    Group,
    GroupPermission,
    User,
    user_groups,
    utc_now,
)

from .audit_log import AuthAuditAction, record_auth_event
from .errors import (
    AccountDisabledError,
    AuthNotFoundError,
    GroupConflictError,
    GroupNotEmptyError,
    InvalidCredentialsError,
    PermissionDeniedError,
    PrivilegeEscalationError,
    SuperAdminInvariantError,
    UserConflictError,
    ValidationAuthError,
)
from .passwords import hash_password, verify_password
from .permissions import (
    SUPER_ADMIN_GROUP_NAME,
    SUPER_ADMIN_ONLY_PERMISSIONS,
    Permission,
    effective_permissions,
    ensure_default_groups,
    group_permissions,
    parse_permissions,
)
from .sessions import revoke_user_sessions

_USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,99}$")
_GROUP_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,99}$")
_UNSET = object()


def _normalize_username(username: str) -> str:
    cleaned = username.strip()
    if not _USERNAME_RE.match(cleaned):
        raise ValidationAuthError(
            "Username must be 2-100 characters of letters, digits, '.', '_' or '-'"
        )
    return cleaned


def _normalize_email(email: str) -> str:
    cleaned = email.strip().lower()
    if not cleaned or "@" not in cleaned or len(cleaned) > 255:
        raise ValidationAuthError("Valid email address is required")
    return cleaned


def _normalize_group_name(name: str) -> str:
    cleaned = name.strip()
    if not _GROUP_NAME_RE.match(cleaned):
        raise ValidationAuthError(
            "Group name must be 2-100 characters of letters, digits, '.', '_' or '-'"
        )
    if cleaned.lower() == SUPER_ADMIN_GROUP_NAME:
        raise GroupConflictError(f"Group name {SUPER_ADMIN_GROUP_NAME!r} is reserved")
    return cleaned


def load_user_with_groups(session: Session, user_id: int) -> User | None:
    return session.scalar(
        select(User)
        .options(
            selectinload(User.groups).selectinload(Group.permissions),
            selectinload(User.personal_group).selectinload(Group.permissions),
        )
        .where(User.id == user_id)
    )


def _require_permission(actor: User, required: Permission) -> frozenset[Permission]:
    actor_perms = effective_permissions(actor)
    if required not in actor_perms:
        raise PermissionDeniedError(f"Permission {required.value!r} is required")
    return actor_perms


def _ensure_unique_user_identity(
    session: Session,
    *,
    username: str | None = None,
    email: str | None = None,
    exclude_user_id: int | None = None,
) -> None:
    if username is not None:
        stmt = select(User.id).where(func.lower(User.username) == username.lower())
        if exclude_user_id is not None:
            stmt = stmt.where(User.id != exclude_user_id)
        if session.scalar(stmt) is not None:
            raise UserConflictError(f"Username {username!r} is already taken")
    if email is not None:
        stmt = select(User.id).where(func.lower(User.email) == email.lower())
        if exclude_user_id is not None:
            stmt = stmt.where(User.id != exclude_user_id)
        if session.scalar(stmt) is not None:
            raise UserConflictError(f"Email {email!r} is already registered")


def _create_personal_group(session: Session, user: User) -> Group:
    personal = Group(
        name=user.username,
        kind=GroupKind.PERSONAL.value,
        description=f"Personal group for user {user.username}",
        owner_user_id=user.id,
    )
    session.add(personal)
    session.flush()
    user.groups.append(personal)
    session.flush()
    return personal


def create_super_admin(
    session: Session,
    *,
    username: str,
    email: str,
    password: str,
    full_name: str = "",
) -> User:
    """Create the single super-admin user along with personal, system, and admin groups."""
    groups = ensure_default_groups(session)
    existing_super = session.scalar(select(User).where(User.is_super_admin.is_(True)))
    if existing_super is not None:
        raise SuperAdminInvariantError("A super-admin user already exists")

    clean_username = _normalize_username(username)
    clean_email = _normalize_email(email)
    _ensure_unique_user_identity(session, username=clean_username, email=clean_email)

    user = User(
        username=clean_username,
        email=clean_email,
        full_name=full_name.strip(),
        hashed_password=hash_password(password),
        is_active=True,
        is_super_admin=True,
        must_change_password=False,
    )
    session.add(user)
    session.flush()

    _create_personal_group(session, user)
    user.groups.append(groups[SUPER_ADMIN_GROUP_NAME])
    admin_group = groups.get("admin")
    if admin_group is not None:
        user.groups.append(admin_group)
    session.flush()

    record_auth_event(
        session,
        AuthAuditAction.USER_CREATED,
        actor=user,
        target_type="user",
        target_id=user.id,
        details={"username": user.username, "is_super_admin": True, "bootstrap": True},
    )
    return user


def ensure_initial_super_admin(
    session: Session,
    *,
    username: str | None,
    email: str | None,
    password: str | None,
    full_name: str = "Super Administrator",
) -> User | None:
    """Idempotent startup bootstrap; does nothing if a super-admin already exists."""
    ensure_default_groups(session)
    if not (username and email and password):
        return None
    existing_super = session.scalar(select(User).where(User.is_super_admin.is_(True)))
    if existing_super is not None:
        return None
    return create_super_admin(
        session,
        username=username,
        email=email,
        password=password,
        full_name=full_name,
    )


def authenticate_user(
    session: Session,
    *,
    username: str,
    password: str,
    ip_address: str | None = None,
) -> User:
    identifier = username.strip()
    user = session.scalar(
        select(User)
        .options(
            selectinload(User.groups).selectinload(Group.permissions),
            selectinload(User.personal_group).selectinload(Group.permissions),
        )
        .where(
            (func.lower(User.username) == identifier.lower())
            | (func.lower(User.email) == identifier.lower())
        )
    )
    if user is None or not verify_password(password, user.hashed_password):
        record_auth_event(
            session,
            AuthAuditAction.LOGIN_FAILED,
            actor=user,
            actor_username=identifier,
            target_type="session",
            details={"reason": "invalid_credentials"},
            ip_address=ip_address,
        )
        raise InvalidCredentialsError("Invalid username or password")
    if not user.is_active:
        record_auth_event(
            session,
            AuthAuditAction.LOGIN_FAILED,
            actor=user,
            target_type="session",
            details={"reason": "account_disabled"},
            ip_address=ip_address,
        )
        raise AccountDisabledError("This user account is disabled")

    user.last_login_at = utc_now()
    session.flush()
    record_auth_event(
        session,
        AuthAuditAction.LOGIN_SUCCESS,
        actor=user,
        target_type="session",
        ip_address=ip_address,
    )
    return user


def _check_group_assignment_ceiling(actor: User, actor_perms: frozenset[Permission], group: Group) -> None:
    if actor.is_super_admin:
        return
    perms = group_permissions(group)
    if perms & SUPER_ADMIN_ONLY_PERMISSIONS:
        raise PrivilegeEscalationError(
            "Only super-admin may assign or remove groups containing groups.manage"
        )
    if not perms.issubset(actor_perms):
        raise PrivilegeEscalationError(
            f"Group {group.name!r} has permissions exceeding your own"
        )


def _load_custom_groups(session: Session, group_ids: Iterable[int]) -> list[Group]:
    unique_ids = sorted(set(group_ids))
    if not unique_ids:
        return []
    groups = session.scalars(
        select(Group)
        .options(selectinload(Group.permissions))
        .where(Group.id.in_(unique_ids))
    ).all()
    if len(groups) != len(unique_ids):
        found = {g.id for g in groups}
        missing = [gid for gid in unique_ids if gid not in found]
        raise AuthNotFoundError(f"Group not found: {missing}")
    for group in groups:
        if group.kind != GroupKind.CUSTOM.value:
            raise ValidationAuthError(
                f"Only custom groups can be manually assigned (group {group.name!r} is {group.kind})"
            )
    return list(groups)


def create_user(
    session: Session,
    *,
    actor: User,
    username: str,
    email: str,
    password: str,
    full_name: str = "",
    custom_group_ids: Iterable[int] = (),
    must_change_password: bool = True,
    ip_address: str | None = None,
) -> User:
    actor_perms = _require_permission(actor, Permission.USERS_MANAGE)
    clean_username = _normalize_username(username)
    clean_email = _normalize_email(email)
    _ensure_unique_user_identity(session, username=clean_username, email=clean_email)

    assigned_groups = _load_custom_groups(session, custom_group_ids)
    for group in assigned_groups:
        _check_group_assignment_ceiling(actor, actor_perms, group)

    user = User(
        username=clean_username,
        email=clean_email,
        full_name=full_name.strip(),
        hashed_password=hash_password(password),
        is_active=True,
        is_super_admin=False,
        must_change_password=must_change_password,
    )
    session.add(user)
    session.flush()

    _create_personal_group(session, user)
    for group in assigned_groups:
        user.groups.append(group)
    session.flush()

    record_auth_event(
        session,
        AuthAuditAction.USER_CREATED,
        actor=actor,
        target_type="user",
        target_id=user.id,
        details={
            "username": user.username,
            "custom_groups": sorted(g.name for g in assigned_groups),
            "must_change_password": must_change_password,
        },
        ip_address=ip_address,
    )
    return user


def update_user(
    session: Session,
    *,
    actor: User,
    target_user_id: int,
    email: str | object = _UNSET,
    full_name: str | object = _UNSET,
    is_active: bool | object = _UNSET,
    new_password: str | object = _UNSET,
    ip_address: str | None = None,
) -> User:
    _require_permission(actor, Permission.USERS_MANAGE)
    target = load_user_with_groups(session, target_user_id)
    if target is None:
        raise AuthNotFoundError(f"User {target_user_id} not found")
    if target.is_super_admin and not actor.is_super_admin:
        raise PermissionDeniedError("Only super-admin may modify the super-admin account")

    changes: dict[str, object] = {}
    if email is not _UNSET:
        clean_email = _normalize_email(str(email))
        if clean_email != target.email:
            _ensure_unique_user_identity(
                session, email=clean_email, exclude_user_id=target.id
            )
            target.email = clean_email
            changes["email"] = clean_email

    if full_name is not _UNSET:
        clean_name = str(full_name).strip()
        if clean_name != target.full_name:
            target.full_name = clean_name
            changes["full_name"] = clean_name

    toggled_active: bool | None = None
    if is_active is not _UNSET:
        desired_active = bool(is_active)
        if not desired_active:
            if target.is_super_admin:
                raise SuperAdminInvariantError(
                    "Cannot disable the super-admin account before transferring super-admin rights"
                )
            if target.id == actor.id:
                raise PermissionDeniedError("You cannot disable your own account")
        if desired_active != target.is_active:
            target.is_active = desired_active
            toggled_active = desired_active
            if not desired_active:
                revoke_user_sessions(session, target.id)

    password_was_reset = False
    if new_password is not _UNSET and new_password is not None:
        target.hashed_password = hash_password(str(new_password))
        target.must_change_password = True
        revoke_user_sessions(session, target.id)
        password_was_reset = True

    session.flush()

    if changes:
        record_auth_event(
            session,
            AuthAuditAction.USER_UPDATED,
            actor=actor,
            target_type="user",
            target_id=target.id,
            details={"changes": changes},
            ip_address=ip_address,
        )
    if toggled_active is False:
        record_auth_event(
            session,
            AuthAuditAction.USER_DISABLED,
            actor=actor,
            target_type="user",
            target_id=target.id,
            details={"username": target.username},
            ip_address=ip_address,
        )
    elif toggled_active is True:
        record_auth_event(
            session,
            AuthAuditAction.USER_ENABLED,
            actor=actor,
            target_type="user",
            target_id=target.id,
            details={"username": target.username},
            ip_address=ip_address,
        )
    if password_was_reset:
        record_auth_event(
            session,
            AuthAuditAction.PASSWORD_RESET,
            actor=actor,
            target_type="user",
            target_id=target.id,
            details={"username": target.username, "must_change_password": True},
            ip_address=ip_address,
        )

    return target


def set_user_groups(
    session: Session,
    *,
    actor: User,
    target_user_id: int,
    custom_group_ids: Iterable[int],
    ip_address: str | None = None,
) -> User:
    actor_perms = _require_permission(actor, Permission.USERS_MANAGE)
    target = load_user_with_groups(session, target_user_id)
    if target is None:
        raise AuthNotFoundError(f"User {target_user_id} not found")
    if target.is_super_admin and not actor.is_super_admin:
        raise PermissionDeniedError("Only super-admin may change super-admin group memberships")

    desired_custom = _load_custom_groups(session, custom_group_ids)
    current_custom = [g for g in target.groups if g.kind == GroupKind.CUSTOM.value]
    preserved_groups = [g for g in target.groups if g.kind != GroupKind.CUSTOM.value]

    current_by_id = {g.id: g for g in current_custom}
    desired_by_id = {g.id: g for g in desired_custom}

    added = [g for gid, g in desired_by_id.items() if gid not in current_by_id]
    removed = [g for gid, g in current_by_id.items() if gid not in desired_by_id]

    for group in added + removed:
        _check_group_assignment_ceiling(actor, actor_perms, group)

    if target.id == actor.id and not actor.is_super_admin:
        resulting_perms: set[Permission] = set()
        for group in preserved_groups + desired_custom:
            resulting_perms.update(group_permissions(group))
        if Permission.USERS_MANAGE not in resulting_perms:
            raise PermissionDeniedError(
                "You cannot remove your own users.manage permission"
            )

    target.groups = preserved_groups + desired_custom
    session.flush()

    record_auth_event(
        session,
        AuthAuditAction.USER_GROUPS_UPDATED,
        actor=actor,
        target_type="user",
        target_id=target.id,
        details={
            "username": target.username,
            "added": sorted(g.name for g in added),
            "removed": sorted(g.name for g in removed),
            "custom_groups": sorted(g.name for g in desired_custom),
        },
        ip_address=ip_address,
    )
    return target


def revoke_target_user_sessions(
    session: Session,
    *,
    actor: User,
    target_user_id: int,
    ip_address: str | None = None,
) -> int:
    _require_permission(actor, Permission.USERS_MANAGE)
    target = session.get(User, target_user_id)
    if target is None:
        raise AuthNotFoundError(f"User {target_user_id} not found")
    if target.is_super_admin and not actor.is_super_admin:
        raise PermissionDeniedError("Only super-admin may revoke super-admin sessions")
    count = revoke_user_sessions(session, target.id)
    record_auth_event(
        session,
        AuthAuditAction.USER_SESSIONS_REVOKED,
        actor=actor,
        target_type="user",
        target_id=target.id,
        details={"username": target.username, "revoked_count": count},
        ip_address=ip_address,
    )
    return count


def create_custom_group(
    session: Session,
    *,
    actor: User,
    name: str,
    description: str = "",
    permissions: Iterable[str | Permission] = (),
    ip_address: str | None = None,
) -> Group:
    actor_perms = _require_permission(actor, Permission.GROUPS_MANAGE)
    clean_name = _normalize_group_name(name)
    parsed_perms = parse_permissions(permissions)

    if not actor.is_super_admin:
        if parsed_perms & SUPER_ADMIN_ONLY_PERMISSIONS:
            raise PrivilegeEscalationError(
                "Only super-admin may grant groups.manage permission"
            )
        if not parsed_perms.issubset(actor_perms):
            raise PrivilegeEscalationError(
                "Cannot grant permissions you do not possess"
            )

    existing = session.scalar(
        select(Group.id).where(
            Group.kind == GroupKind.CUSTOM.value,
            func.lower(Group.name) == clean_name.lower(),
        )
    )
    if existing is not None:
        raise GroupConflictError(f"Custom group {clean_name!r} already exists")

    group = Group(
        name=clean_name,
        kind=GroupKind.CUSTOM.value,
        description=description.strip(),
    )
    session.add(group)
    session.flush()
    for perm in sorted(parsed_perms, key=lambda p: p.value):
        session.add(GroupPermission(group_id=group.id, permission=perm.value))
    session.flush()

    record_auth_event(
        session,
        AuthAuditAction.GROUP_CREATED,
        actor=actor,
        target_type="group",
        target_id=group.id,
        details={
            "name": group.name,
            "permissions": sorted(p.value for p in parsed_perms),
        },
        ip_address=ip_address,
    )
    return group


def update_custom_group(
    session: Session,
    *,
    actor: User,
    group_id: int,
    name: str | object = _UNSET,
    description: str | object = _UNSET,
    ip_address: str | None = None,
) -> Group:
    actor_perms = _require_permission(actor, Permission.GROUPS_MANAGE)
    group = session.scalar(
        select(Group).options(selectinload(Group.permissions)).where(Group.id == group_id)
    )
    if group is None:
        raise AuthNotFoundError(f"Group {group_id} not found")
    if group.kind != GroupKind.CUSTOM.value:
        raise PermissionDeniedError("Only custom groups can be renamed or edited")
    _check_group_assignment_ceiling(actor, actor_perms, group)

    changes: dict[str, object] = {}
    if name is not _UNSET:
        clean_name = _normalize_group_name(str(name))
        if clean_name != group.name:
            duplicate = session.scalar(
                select(Group.id).where(
                    Group.kind == GroupKind.CUSTOM.value,
                    func.lower(Group.name) == clean_name.lower(),
                    Group.id != group.id,
                )
            )
            if duplicate is not None:
                raise GroupConflictError(f"Custom group {clean_name!r} already exists")
            group.name = clean_name
            changes["name"] = clean_name

    if description is not _UNSET:
        clean_desc = str(description).strip()
        if clean_desc != group.description:
            group.description = clean_desc
            changes["description"] = clean_desc

    session.flush()
    if changes:
        record_auth_event(
            session,
            AuthAuditAction.GROUP_UPDATED,
            actor=actor,
            target_type="group",
            target_id=group.id,
            details={"changes": changes},
            ip_address=ip_address,
        )
    return group


def set_group_permissions(
    session: Session,
    *,
    actor: User,
    group_id: int,
    permissions: Iterable[str | Permission],
    ip_address: str | None = None,
) -> Group:
    actor_perms = _require_permission(actor, Permission.GROUPS_MANAGE)
    group = session.scalar(
        select(Group)
        .options(selectinload(Group.permissions), selectinload(Group.owner))
        .where(Group.id == group_id)
    )
    if group is None:
        raise AuthNotFoundError(f"Group {group_id} not found")
    if group.kind == GroupKind.SYSTEM.value:
        raise PermissionDeniedError("System super-admin group permissions cannot be modified")
    if (
        group.kind == GroupKind.PERSONAL.value
        and group.owner is not None
        and group.owner.is_super_admin
        and not actor.is_super_admin
    ):
        raise PermissionDeniedError("Only super-admin may edit super-admin's personal group")

    desired = parse_permissions(permissions)
    current = group_permissions(group)
    changed = desired ^ current

    if not actor.is_super_admin:
        if changed & SUPER_ADMIN_ONLY_PERMISSIONS:
            raise PrivilegeEscalationError(
                "Only super-admin may grant or revoke groups.manage permission"
            )
        if not changed.issubset(actor_perms):
            raise PrivilegeEscalationError(
                "Cannot grant or revoke permissions you do not possess"
            )

    existing_by_perm = {entry.permission: entry for entry in list(group.permissions)}
    desired_values = {perm.value for perm in desired}

    for perm_value, entry in existing_by_perm.items():
        if perm_value not in desired_values:
            group.permissions.remove(entry)
    for perm_value in sorted(desired_values):
        if perm_value not in existing_by_perm:
            group.permissions.append(GroupPermission(group_id=group.id, permission=perm_value))

    session.flush()

    record_auth_event(
        session,
        AuthAuditAction.GROUP_PERMISSIONS_UPDATED,
        actor=actor,
        target_type="group",
        target_id=group.id,
        details={
            "name": group.name,
            "kind": group.kind,
            "added": sorted(p.value for p in (desired - current)),
            "removed": sorted(p.value for p in (current - desired)),
            "permissions": sorted(desired_values),
        },
        ip_address=ip_address,
    )
    return group


def delete_custom_group(
    session: Session,
    *,
    actor: User,
    group_id: int,
    ip_address: str | None = None,
) -> None:
    actor_perms = _require_permission(actor, Permission.GROUPS_MANAGE)
    group = session.scalar(
        select(Group).options(selectinload(Group.permissions)).where(Group.id == group_id)
    )
    if group is None:
        raise AuthNotFoundError(f"Group {group_id} not found")
    if group.kind != GroupKind.CUSTOM.value:
        raise PermissionDeniedError("Only custom groups can be deleted")
    _check_group_assignment_ceiling(actor, actor_perms, group)

    member_count = session.scalar(
        select(func.count()).select_from(user_groups).where(user_groups.c.group_id == group.id)
    )
    if int(member_count or 0) > 0:
        raise GroupNotEmptyError(
            f"Cannot delete group {group.name!r} while it still has {member_count} member(s)"
        )

    group_name = group.name
    session.delete(group)
    session.flush()

    record_auth_event(
        session,
        AuthAuditAction.GROUP_DELETED,
        actor=actor,
        target_type="group",
        target_id=group_id,
        details={"name": group_name},
        ip_address=ip_address,
    )


def change_own_password(
    session: Session,
    *,
    user: User,
    current_password: str,
    new_password: str,
    current_session_id: int | None = None,
    ip_address: str | None = None,
) -> None:
    if not verify_password(current_password, user.hashed_password):
        raise InvalidCredentialsError("Current password is incorrect")
    user.hashed_password = hash_password(new_password)
    user.must_change_password = False
    revoked = revoke_user_sessions(
        session, user.id, except_session_id=current_session_id
    )
    session.flush()

    record_auth_event(
        session,
        AuthAuditAction.PASSWORD_CHANGED,
        actor=user,
        target_type="user",
        target_id=user.id,
        details={"revoked_other_sessions": revoked},
        ip_address=ip_address,
    )


def transfer_super_admin(
    session: Session,
    *,
    actor: User,
    current_password: str,
    target_user_id: int,
    ip_address: str | None = None,
) -> User:
    """Atomically transfer super-admin status from actor to another active user."""
    if not actor.is_super_admin:
        raise PermissionDeniedError("Only super-admin may transfer super-admin rights")
    if not verify_password(current_password, actor.hashed_password):
        raise InvalidCredentialsError("Current password is incorrect")
    if target_user_id == actor.id:
        raise ValidationAuthError("Target user must be different from the current super-admin")

    loaded_actor = load_user_with_groups(session, actor.id)
    target = load_user_with_groups(session, target_user_id)
    if loaded_actor is None or target is None:
        raise AuthNotFoundError(f"User {target_user_id} not found")
    if not target.is_active:
        raise SuperAdminInvariantError("Cannot transfer super-admin rights to a disabled user")

    groups = ensure_default_groups(session)
    super_group = groups[SUPER_ADMIN_GROUP_NAME]

    # Clear the current super-admin first so the partial unique index never sees two rows.
    loaded_actor.is_super_admin = False
    loaded_actor.groups = [g for g in loaded_actor.groups if g.id != super_group.id]
    session.flush()

    target.is_super_admin = True
    if all(g.id != super_group.id for g in target.groups):
        target.groups.append(super_group)
    session.flush()

    record_auth_event(
        session,
        AuthAuditAction.SUPER_ADMIN_TRANSFERRED,
        actor=loaded_actor,
        target_type="user",
        target_id=target.id,
        details={
            "from_user_id": loaded_actor.id,
            "from_username": loaded_actor.username,
            "to_user_id": target.id,
            "to_username": target.username,
        },
        ip_address=ip_address,
    )
    return target
