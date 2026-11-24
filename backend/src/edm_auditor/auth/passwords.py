"""Argon2id password hashing and validation."""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from .errors import WeakPasswordError

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 1024

_hasher = PasswordHasher()


def validate_password(password: str) -> None:
    if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
        raise WeakPasswordError(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters long"
        )
    if len(password) > MAX_PASSWORD_LENGTH:
        raise WeakPasswordError(
            f"Password must be at most {MAX_PASSWORD_LENGTH} characters long"
        )
    if not password.strip():
        raise WeakPasswordError("Password cannot consist solely of whitespace")


def hash_password(password: str) -> str:
    validate_password(password)
    return _hasher.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    if not password or not hashed_password:
        return False
    try:
        return bool(_hasher.verify(hashed_password, password))
    except (VerifyMismatchError, InvalidHashError, VerificationError):
        return False


def needs_rehash(hashed_password: str) -> bool:
    try:
        return bool(_hasher.check_needs_rehash(hashed_password))
    except InvalidHashError:
        return True
