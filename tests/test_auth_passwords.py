import pytest

from app.auth.passwords import hash_password, verify_password


def test_correct_password():
    stored = hash_password("LabDemo2026!")
    assert stored != "LabDemo2026!"
    assert verify_password(stored, "LabDemo2026!")


def test_wrong_password():
    stored = hash_password("LabDemo2026!")
    assert not verify_password(stored, "WrongPassword!")


def test_passwords_have_different_salts():
    first = hash_password("LabDemo2026!")
    second = hash_password("LabDemo2026!")
    assert first != second
    assert verify_password(first, "LabDemo2026!")
    assert verify_password(second, "LabDemo2026!")


def test_invalid_stored_hash():
    assert not verify_password("invalid", "LabDemo2026!")


@pytest.mark.parametrize("password", ["", None, 123])
def test_invalid_password_rejected(password):
    with pytest.raises(ValueError):
        hash_password(password)


def test_empty_password_cannot_authenticate():
    stored = hash_password("LabDemo2026!")
    assert not verify_password(stored, "")