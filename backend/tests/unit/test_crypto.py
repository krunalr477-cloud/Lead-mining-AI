"""Fernet credential cipher and secret masking."""

import pytest
from cryptography.fernet import Fernet, InvalidToken

from app.security.crypto import CredentialCipher, get_cipher, mask_secret


class TestCredentialCipher:
    def test_encrypt_decrypt_round_trip(self) -> None:
        cipher = get_cipher()
        plaintext = "super-secret-refresh-token-1234"
        ciphertext = cipher.encrypt(plaintext)
        assert ciphertext != plaintext
        assert cipher.decrypt(ciphertext) == plaintext

    def test_ciphertext_is_not_reused(self) -> None:
        # Fernet includes a random IV: same plaintext, different ciphertexts.
        cipher = get_cipher()
        assert cipher.encrypt("same") != cipher.encrypt("same")

    def test_explicit_key_round_trip(self) -> None:
        key = Fernet.generate_key().decode()
        cipher = CredentialCipher(keys=[key])
        assert cipher.decrypt(cipher.encrypt("payload")) == "payload"

    def test_key_rotation_multifernet(self) -> None:
        old_key = Fernet.generate_key().decode()
        new_key = Fernet.generate_key().decode()
        old_cipher = CredentialCipher(keys=[old_key])
        legacy_ciphertext = old_cipher.encrypt("legacy-credential")

        # New key first, old key retained: old ciphertexts still decrypt,
        # new ciphertexts use the new key.
        rotated = CredentialCipher(keys=[new_key, old_key])
        assert rotated.decrypt(legacy_ciphertext) == "legacy-credential"
        fresh = rotated.encrypt("fresh-credential")
        assert CredentialCipher(keys=[new_key]).decrypt(fresh) == "fresh-credential"

    def test_wrong_key_rejected(self) -> None:
        cipher_a = CredentialCipher(keys=[Fernet.generate_key().decode()])
        cipher_b = CredentialCipher(keys=[Fernet.generate_key().decode()])
        token = cipher_a.encrypt("secret")
        with pytest.raises(InvalidToken):
            cipher_b.decrypt(token)

    def test_get_cipher_is_singleton(self) -> None:
        assert get_cipher() is get_cipher()


class TestMaskSecret:
    def test_long_secret_shows_last_four(self) -> None:
        assert mask_secret("sk-abcdef123456") == "****3456"

    def test_exactly_four_chars(self) -> None:
        assert mask_secret("abcd") == "****abcd"

    def test_short_secret_fully_masked(self) -> None:
        assert mask_secret("abc") == "****"

    def test_empty_secret_fully_masked(self) -> None:
        assert mask_secret("") == "****"
