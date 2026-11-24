"""Domain exceptions for authentication, groups, and RBAC."""


class AuthError(Exception):
    """Base error carrying an HTTP status code and a stable API error code."""

    status_code: int = 400
    code: str = "auth_error"

    def __init__(self, message: str, *, code: str | None = None, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code


class InvalidCredentialsError(AuthError):
    status_code = 401
    code = "invalid_credentials"


class AccountDisabledError(AuthError):
    status_code = 403
    code = "account_disabled"


class PasswordChangeRequiredError(AuthError):
    status_code = 403
    code = "password_change_required"


class WeakPasswordError(AuthError):
    status_code = 422
    code = "weak_password"


class ValidationAuthError(AuthError):
    status_code = 422
    code = "validation_error"


class PermissionDeniedError(AuthError):
    status_code = 403
    code = "forbidden"


class PrivilegeEscalationError(AuthError):
    status_code = 403
    code = "privilege_escalation"


class GroupNotEmptyError(AuthError):
    status_code = 409
    code = "group_not_empty"


class GroupConflictError(AuthError):
    status_code = 409
    code = "group_conflict"


class UserConflictError(AuthError):
    status_code = 409
    code = "user_conflict"


class SuperAdminInvariantError(AuthError):
    status_code = 409
    code = "super_admin_invariant"


class AuthNotFoundError(AuthError):
    status_code = 404
    code = "not_found"


class LoginRateLimitedError(AuthError):
    status_code = 429
    code = "too_many_requests"
