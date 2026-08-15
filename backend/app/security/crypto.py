"""Symmetric encryption at rest for sensitive columns (biometric embeddings)."""
from cryptography.fernet import Fernet, InvalidToken

from app.config.settings import settings

_fernet = Fernet(settings.encryption_key)


def encrypt_bytes(data: bytes) -> bytes:
    return _fernet.encrypt(data)


def decrypt_bytes(token: bytes) -> bytes:
    try:
        return _fernet.decrypt(token)
    except InvalidToken as exc:
        raise ValueError("Unable to decrypt protected data") from exc
