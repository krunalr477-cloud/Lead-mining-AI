"""Fernet encryption for stored integration credentials.

ENCRYPTION_KEY is a urlsafe-base64 32-byte Fernet key. MultiFernet supports
rotation: put the new key first, keep old keys after it, re-encrypt lazily.
Outside DEMO_MODE the app refuses to handle credentials without a key.
"""

from cryptography.fernet import Fernet, MultiFernet

from app.config import get_settings


class CredentialCipher:
    def __init__(self, keys: list[str] | None = None) -> None:
        settings = get_settings()
        raw = (
            keys
            if keys is not None
            else ([settings.encryption_key] if settings.encryption_key else [])
        )
        if not raw:
            if not settings.demo_mode:
                raise RuntimeError(
                    "ENCRYPTION_KEY is required outside DEMO_MODE. "
                    'Generate one: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
                )
            # Demo mode: ephemeral key — credentials do not survive restarts, by design.
            raw = [Fernet.generate_key().decode()]
        self._fernet = MultiFernet([Fernet(k.encode()) for k in raw])

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        return self._fernet.decrypt(ciphertext.encode()).decode()


_cipher: CredentialCipher | None = None


def get_cipher() -> CredentialCipher:
    global _cipher
    if _cipher is None:
        _cipher = CredentialCipher()
    return _cipher


def mask_secret(secret: str) -> str:
    """Display form for the UI: ****last4."""
    return f"****{secret[-4:]}" if len(secret) >= 4 else "****"
