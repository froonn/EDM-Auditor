import pytest

from edm_auditor.auth.errors import WeakPasswordError
from edm_auditor.auth.passwords import (
    MIN_PASSWORD_LENGTH,
    hash_password,
    needs_rehash,
    validate_password,
    verify_password,
)


def test_hash_and_verify_argon2id_password() -> None:
    hashed = hash_password("correct-horse-battery")

    assert hashed.startswith("$argon2id$")
    assert verify_password("correct-horse-battery", hashed) is True
    assert verify_password("wrong-password", hashed) is False
    assert needs_rehash(hashed) is False


def test_verify_handles_invalid_or_empty_hashes() -> None:
    assert verify_password("anything", "") is False
    assert verify_password("", "$argon2id$invalid") is False
    assert verify_password("anything", "not-a-valid-hash") is False
    assert needs_rehash("not-a-valid-hash") is True


@pytest.mark.parametrize(
    "bad_password",
    [
        "",
        "short",
        "a" * (MIN_PASSWORD_LENGTH - 1),
        "        ",
        "x" * 1025,
    ],
)
def test_validate_password_rejects_weak_inputs(bad_password: str) -> None:
    with pytest.raises(WeakPasswordError):
        validate_password(bad_password)
