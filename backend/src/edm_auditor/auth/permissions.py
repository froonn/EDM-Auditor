"""Permission catalog, default starter groups, and union-based resolution."""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from edm_auditor.database.enums import GroupKind
from edm_auditor.database.models import Group, GroupPermission, User

from .errors import ValidationAuthError


class Permission(StrEnum):
    DOCUMENTS_UPLOAD = "documents.upload"
    DOCUMENTS_READ_ALL = "documents.read_all"
    DOCUMENTS_DELETE_OWN = "documents.delete_own"
    DOCUMENTS_DELETE_ANY = "documents.delete_any"
    AUDIT_RUN = "audit.run"
    REPORTS_READ = "reports.read"
    REPORTS_EXPORT = "reports.export"
    RESOLUTIONS_WRITE = "resolutions.write"
    LEGAL_ACTS_READ = "legal_acts.read"
    LEGAL_ACTS_EDIT = "legal_acts.edit"
    RULES_READ = "rules.read"
    RULES_EDIT = "rules.edit"
    DOCUMENT_TYPES_READ = "document_types.read"
    DOCUMENT_TYPES_EDIT = "document_types.edit"
    USERS_MANAGE = "users.manage"
    GROUPS_MANAGE = "groups.manage"


ALL_PERMISSIONS: frozenset[Permission] = frozenset(Permission)
SUPER_ADMIN_ONLY_PERMISSIONS: frozenset[Permission] = frozenset({Permission.GROUPS_MANAGE})
SUPER_ADMIN_GROUP_NAME = "super-admin"


@dataclass(frozen=True, slots=True)
class PermissionInfo:
    code: Permission
    description: str
    super_admin_only: bool = False


PERMISSION_CATALOG: tuple[PermissionInfo, ...] = (
    PermissionInfo(Permission.DOCUMENTS_UPLOAD, "Upload new documents"),
    PermissionInfo(
        Permission.DOCUMENTS_READ_ALL,
        "View all documents and reports (including legacy unassigned documents)",
    ),
    PermissionInfo(Permission.DOCUMENTS_DELETE_OWN, "Delete own uploaded documents"),
    PermissionInfo(Permission.DOCUMENTS_DELETE_ANY, "Delete any document in the system"),
    PermissionInfo(
        Permission.AUDIT_RUN,
        "Classify documents, configure and run audits, and link statements",
    ),
    PermissionInfo(Permission.REPORTS_READ, "View accessible documents, reports, and resolutions"),
    PermissionInfo(Permission.REPORTS_EXPORT, "Export accessible audit reports"),
    PermissionInfo(Permission.RESOLUTIONS_WRITE, "Record auditor resolutions on audit reports"),
    PermissionInfo(Permission.LEGAL_ACTS_READ, "View legal acts, text, and extraction diagnostics"),
    PermissionInfo(
        Permission.LEGAL_ACTS_EDIT,
        "Upload, create, edit, reprocess, and delete legal acts",
    ),
    PermissionInfo(Permission.RULES_READ, "View audit rules and applicability"),
    PermissionInfo(
        Permission.RULES_EDIT,
        "Create, edit, configure applicability, and delete audit rules",
    ),
    PermissionInfo(
        Permission.DOCUMENT_TYPES_READ,
        "View document types catalog and model type suggestions",
    ),
    PermissionInfo(
        Permission.DOCUMENT_TYPES_EDIT,
        "Create, edit, deactivate document types and handle suggestions",
    ),
    PermissionInfo(
        Permission.USERS_MANAGE,
        "Create/update/disable users, reset passwords, revoke sessions, and assign groups",
    ),
    PermissionInfo(
        Permission.GROUPS_MANAGE,
        "Create/delete empty custom groups and configure group permissions",
        super_admin_only=True,
    ),
)

_EMPLOYEE_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        Permission.DOCUMENTS_UPLOAD,
        Permission.DOCUMENTS_DELETE_OWN,
        Permission.REPORTS_READ,
        Permission.REPORTS_EXPORT,
    }
)

_AUDITOR_PERMISSIONS: frozenset[Permission] = _EMPLOYEE_PERMISSIONS | frozenset(
    {
        Permission.DOCUMENTS_READ_ALL,
        Permission.AUDIT_RUN,
        Permission.RESOLUTIONS_WRITE,
        Permission.LEGAL_ACTS_READ,
        Permission.RULES_READ,
        Permission.DOCUMENT_TYPES_READ,
    }
)

_LAWYER_PERMISSIONS: frozenset[Permission] = _AUDITOR_PERMISSIONS | frozenset(
    {
        Permission.LEGAL_ACTS_EDIT,
        Permission.RULES_EDIT,
        Permission.DOCUMENT_TYPES_EDIT,
    }
)

_ADMIN_PERMISSIONS: frozenset[Permission] = _LAWYER_PERMISSIONS | frozenset(
    {
        Permission.DOCUMENTS_DELETE_ANY,
        Permission.USERS_MANAGE,
    }
)

DEFAULT_CUSTOM_GROUPS: dict[str, tuple[str, frozenset[Permission]]] = {
    "employee": (
        "Uploads and reviews own documents and audit reports without running audits",
        _EMPLOYEE_PERMISSIONS,
    ),
    "auditor": (
        "Reviews all documents, runs audits, writes resolutions, reads legal acts and rules",
        _AUDITOR_PERMISSIONS,
    ),
    "lawyer": (
        "Maintains legal acts, audit rules, and document types, plus full audit capabilities",
        _LAWYER_PERMISSIONS,
    ),
    "admin": (
        "Manages users and group assignments plus full audit and knowledge-base access",
        _ADMIN_PERMISSIONS,
    ),
}

LEGACY_ROLE_TO_GROUP: dict[str, str] = {
    "hr": "employee",
    "employee": "employee",
    "auditor": "auditor",
    "lawyer": "lawyer",
    "admin": "admin",
}


def parse_permissions(values: Iterable[str | Permission]) -> frozenset[Permission]:
    parsed: set[Permission] = set()
    for raw in values:
        if isinstance(raw, Permission):
            parsed.add(raw)
            continue
        try:
            parsed.add(Permission(raw))
        except ValueError as exc:
            raise ValidationAuthError(f"Unknown permission: {raw!r}") from exc
    return frozenset(parsed)


def group_permissions(group: Group) -> frozenset[Permission]:
    if group.kind == GroupKind.SYSTEM.value:
        return ALL_PERMISSIONS
    result: set[Permission] = set()
    for entry in group.permissions:
        try:
            result.add(Permission(entry.permission))
        except ValueError:
            continue
    return frozenset(result)


def effective_permissions(user: User) -> frozenset[Permission]:
    if not user.is_active:
        return frozenset()
    if user.is_super_admin:
        return ALL_PERMISSIONS
    combined: set[Permission] = set()
    for group in user.groups:
        combined.update(group_permissions(group))
    return frozenset(combined)


def ensure_default_groups(session: Session) -> dict[str, Group]:
    """Ensure the system super-admin group and starter custom groups exist.

    Existing custom groups keep their current permissions so administrator edits
    are never overwritten.
    """
    existing_groups = session.scalars(
        select(Group).where(Group.kind.in_([GroupKind.SYSTEM.value, GroupKind.CUSTOM.value]))
    ).all()
    by_key = {(g.kind, g.name): g for g in existing_groups}
    result: dict[str, Group] = {}

    super_group = by_key.get((GroupKind.SYSTEM.value, SUPER_ADMIN_GROUP_NAME))
    if super_group is None:
        super_group = Group(
            name=SUPER_ADMIN_GROUP_NAME,
            kind=GroupKind.SYSTEM.value,
            description="Single system super-administrator with unrestricted permissions",
        )
        session.add(super_group)
        session.flush()
        for perm in sorted(ALL_PERMISSIONS, key=lambda p: p.value):
            session.add(GroupPermission(group_id=super_group.id, permission=perm.value))
        session.flush()
    result[SUPER_ADMIN_GROUP_NAME] = super_group

    for name, (description, perms) in DEFAULT_CUSTOM_GROUPS.items():
        group = by_key.get((GroupKind.CUSTOM.value, name))
        if group is None:
            group = Group(
                name=name,
                kind=GroupKind.CUSTOM.value,
                description=description,
            )
            session.add(group)
            session.flush()
            for perm in sorted(perms, key=lambda p: p.value):
                session.add(GroupPermission(group_id=group.id, permission=perm.value))
            session.flush()
        result[name] = group

    return result
