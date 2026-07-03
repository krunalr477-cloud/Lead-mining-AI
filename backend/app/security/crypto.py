"""Fernet encryption for stored integration credentials.

ENCRYPTION_KEY is a urlsafe-base64 32-byte Fernet key. MultiFernet supports
rotation: put the new key first, keep old keys after it, re-encrypt lazily.
Outside DEMO_MODE the app refuses to handle credentials without a key.
"""

import json

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


# --------------------------------------------------------------------------- #
# Credential envelope — how a tenant-supplied provider secret is stored.
#
# A stored secret can carry more than one field (e.g. google_oauth needs both a
# client_id and client_secret; a licensed provider carries base_url + api_key).
# We serialise the field map into a versioned JSON envelope and Fernet-encrypt
# the whole thing into ``IntegrationCredential.encrypted_secret_reference``.
#
# The envelope also carries a NON-secret ``mask`` (``****last4`` of the primary
# secret) so the Integrations list can render a masked hint WITHOUT decrypting —
# but since only the encrypted blob is stored, the list decrypts once to read
# the mask and never surfaces the plaintext. The primary secret field (the one
# masked / used as the resolved key) is the first of api_key / client_secret /
# refresh_token that is present.
# --------------------------------------------------------------------------- #

_ENVELOPE_VERSION = 1
# Order matters: the first present field is the "primary" secret (masked + the
# value returned by resolved-key lookups).
_PRIMARY_FIELDS = ("api_key", "client_secret", "refresh_token")


def _primary_value(fields: dict[str, str]) -> str | None:
    for name in _PRIMARY_FIELDS:
        value = fields.get(name)
        if value:
            return value
    # Fall back to any non-empty field so a mask can still be derived.
    for value in fields.values():
        if value:
            return value
    return None


def encrypt_credential(fields: dict[str, str]) -> str:
    """Fernet-encrypt a versioned JSON envelope of provider-secret fields."""
    clean = {k: v for k, v in fields.items() if v}
    primary = _primary_value(clean) or ""
    envelope = {
        "v": _ENVELOPE_VERSION,
        "fields": clean,
        "mask": mask_secret(primary),
    }
    return get_cipher().encrypt(json.dumps(envelope, separators=(",", ":")))


def decrypt_credential(ciphertext: str) -> dict[str, str]:
    """Decrypt a stored credential back to its field map.

    Backward-compatible with the pre-envelope format (a Fernet-encrypted raw
    string, e.g. the Google refresh token stored by the OAuth flow): if the
    plaintext is not a JSON envelope, it is returned as ``{"refresh_token": …}``
    when it looks like a Google row, else ``{"api_key": …}``.
    """
    plaintext = get_cipher().decrypt(ciphertext)
    try:
        data = json.loads(plaintext)
    except (json.JSONDecodeError, ValueError):
        return {"api_key": plaintext}
    if isinstance(data, dict) and data.get("v") == _ENVELOPE_VERSION:
        fields = data.get("fields")
        if isinstance(fields, dict):
            return {str(k): str(v) for k, v in fields.items()}
    # Some other JSON shape — treat the whole plaintext as the opaque secret.
    return {"api_key": plaintext}


def masked_hint(ciphertext: str) -> str:
    """``****last4`` of a stored credential's primary secret.

    Reads the envelope's precomputed mask when present (no need to expose the
    secret), else decrypts and masks the primary field. Never returns plaintext.
    """
    plaintext = get_cipher().decrypt(ciphertext)
    try:
        data = json.loads(plaintext)
        if isinstance(data, dict) and data.get("v") == _ENVELOPE_VERSION:
            mask = data.get("mask")
            if isinstance(mask, str) and mask:
                return mask
            fields = data.get("fields") or {}
            primary = _primary_value({str(k): str(v) for k, v in fields.items()})
            return mask_secret(primary or "")
    except (json.JSONDecodeError, ValueError):
        pass
    # Legacy raw-string secret (e.g. Google refresh token).
    return mask_secret(plaintext)
