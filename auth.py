import hashlib
import hmac
import os
import secrets
from typing import Optional

PBKDF2_ITERATIONS = int(os.getenv("PASSWORD_HASH_ITERATIONS", "260000"))


def hash_password(password: str) -> str:
    if not password or len(password) < 6:
        raise ValueError("Şifre en az 6 karakter olmalı.")
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        PBKDF2_ITERATIONS,
    ).hex()
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored_hash: Optional[str]) -> bool:
    if not password or not stored_hash:
        return False

    try:
        algorithm, iterations, salt, expected_digest = stored_hash.split("$", 3)
    except ValueError:
        return False

    if algorithm != "pbkdf2_sha256":
        return False

    calculated_digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        int(iterations),
    ).hex()
    return hmac.compare_digest(calculated_digest, expected_digest)


def generate_temp_password(length: int = 14) -> str:
    alphabet = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789!@#$"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def normalize_phone(phone: str) -> str:
    return (phone or "").replace(" ", "").replace("-", "").replace("(", "").replace(")", "").strip()


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()
