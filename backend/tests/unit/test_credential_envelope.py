"""Unit: credential envelope encrypt/decrypt/mask round-trip (spec §17).

Verifies that a tenant-supplied provider secret is stored as an encrypted
versioned envelope, decrypts back to its field map, and only ever exposes a
``****last4`` mask of the primary secret — the plaintext must never appear in
the ciphertext or the mask.
"""

from __future__ import annotations

from app.security.crypto import (
    decrypt_credential,
    encrypt_credential,
    mask_secret,
    masked_hint,
)


class TestEnvelopeRoundTrip:
    def test_api_key_round_trip(self) -> None:
        blob = encrypt_credential({"api_key": "sk-secret-abcd1234"})
        assert decrypt_credential(blob) == {"api_key": "sk-secret-abcd1234"}

    def test_oauth_pair_round_trip(self) -> None:
        fields = {"client_id": "cid-123.apps", "client_secret": "GOCSPX-topsecret"}
        blob = encrypt_credential(fields)
        assert decrypt_credential(blob) == fields

    def test_base_url_and_key(self) -> None:
        fields = {"api_key": "key-9999", "base_url": "https://api.provider.com/v1"}
        blob = encrypt_credential(fields)
        assert decrypt_credential(blob) == fields

    def test_empty_fields_dropped(self) -> None:
        blob = encrypt_credential({"api_key": "real", "base_url": ""})
        assert decrypt_credential(blob) == {"api_key": "real"}


class TestNeverLeaks:
    def test_ciphertext_does_not_contain_plaintext(self) -> None:
        secret = "sk-super-secret-value-7788"
        blob = encrypt_credential({"api_key": secret})
        assert secret not in blob

    def test_mask_is_last_four_only(self) -> None:
        secret = "sk-super-secret-value-7788"
        blob = encrypt_credential({"api_key": secret})
        hint = masked_hint(blob)
        assert hint == "****7788"
        assert secret not in hint

    def test_oauth_masks_client_secret_not_id(self) -> None:
        fields = {"client_id": "cid-123.apps", "client_secret": "GOCSPX-tail9911"}
        blob = encrypt_credential(fields)
        # client_secret is the primary field for OAuth -> mask its tail.
        assert masked_hint(blob) == "****9911"

    def test_short_secret_masks_fully(self) -> None:
        assert mask_secret("ab") == "****"


class TestBackwardCompatibleRawSecret:
    """A pre-envelope Fernet-encrypted raw string (e.g. the Google refresh
    token stored by the OAuth flow) must still decrypt + mask gracefully."""

    def test_raw_string_decrypts_to_api_key(self) -> None:
        from app.security.crypto import get_cipher

        raw = get_cipher().encrypt("1//refresh-token-tail4242")
        fields = decrypt_credential(raw)
        assert fields.get("api_key") == "1//refresh-token-tail4242"

    def test_raw_string_masks_tail(self) -> None:
        from app.security.crypto import get_cipher

        raw = get_cipher().encrypt("1//refresh-token-tail4242")
        assert masked_hint(raw) == "****4242"
