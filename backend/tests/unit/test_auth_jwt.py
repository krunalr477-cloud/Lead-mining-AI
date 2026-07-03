"""JWT session token issue/verify round trip and expiry handling."""

import uuid
from datetime import timedelta
from types import SimpleNamespace

import jwt
import pytest
from freezegun import freeze_time

from app.db import utcnow
from app.security.auth import JWT_ALGORITHM, TOKEN_TTL, issue_token, verify_token


def _fake_user() -> SimpleNamespace:
    """Duck-typed stand-in for app.models.User (issue_token only reads attrs)."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        role="admin",
        email="test@example.com",
    )


class TestIssueVerifyRoundTrip:
    def test_round_trip_claims(self) -> None:
        user = _fake_user()
        token = issue_token(user)  # type: ignore[arg-type]
        claims = verify_token(token)
        assert claims["sub"] == str(user.id)
        assert claims["tenant_id"] == str(user.tenant_id)
        assert claims["role"] == "admin"
        assert claims["email"] == "test@example.com"

    def test_expiry_is_seven_days(self) -> None:
        assert timedelta(days=7) == TOKEN_TTL
        with freeze_time("2026-07-03 12:00:00"):
            claims = verify_token(issue_token(_fake_user()))  # type: ignore[arg-type]
            assert claims["exp"] - claims["iat"] == int(TOKEN_TTL.total_seconds())


class TestRejection:
    def test_expired_token_rejected(self) -> None:
        with freeze_time(utcnow() - TOKEN_TTL - timedelta(minutes=5)):
            stale = issue_token(_fake_user())  # type: ignore[arg-type]
        with pytest.raises(jwt.ExpiredSignatureError):
            verify_token(stale)

    def test_token_valid_just_before_expiry(self) -> None:
        with freeze_time(utcnow() - TOKEN_TTL + timedelta(minutes=5)):
            almost_stale = issue_token(_fake_user())  # type: ignore[arg-type]
        assert verify_token(almost_stale)["email"] == "test@example.com"

    def test_wrong_secret_rejected(self) -> None:
        forged = jwt.encode(
            {"sub": str(uuid.uuid4()), "exp": utcnow() + TOKEN_TTL},
            "not-the-real-secret",
            algorithm=JWT_ALGORITHM,
        )
        with pytest.raises(jwt.InvalidSignatureError):
            verify_token(forged)

    def test_tampered_payload_rejected(self) -> None:
        header, _payload, signature = issue_token(_fake_user()).split(".")  # type: ignore[arg-type]
        evil = jwt.encode(
            {"sub": "attacker", "exp": utcnow() + TOKEN_TTL},
            "attacker-key",
            algorithm=JWT_ALGORITHM,
        ).split(".")[1]
        with pytest.raises(jwt.InvalidTokenError):
            verify_token(f"{header}.{evil}.{signature}")

    def test_missing_required_claims_rejected(self) -> None:
        from app.config import get_settings

        no_exp = jwt.encode(
            {"sub": str(uuid.uuid4())}, get_settings().jwt_secret, algorithm=JWT_ALGORITHM
        )
        with pytest.raises(jwt.MissingRequiredClaimError):
            verify_token(no_exp)

    def test_garbage_token_rejected(self) -> None:
        with pytest.raises(jwt.InvalidTokenError):
            verify_token("not.a.jwt")
