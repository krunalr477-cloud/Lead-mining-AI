"""Select the right SheetsClient for a tenant (spec §5, §19).

``get_sheets_client(tenant_id, session)`` returns:

- :class:`FakeSheetsClient` in DEMO_MODE, or when the tenant has no active
  Google credential / Google OAuth is not configured — the safe in-memory
  mirror used for the demo pipeline.
- :class:`GoogleSheetsClient` otherwise, built from the tenant's decrypted
  refresh token (``IntegrationCredential`` provider="google") minted into a
  :class:`google.oauth2.credentials.Credentials` on demand.

The sync worker and ``POST /sheets/connect`` both go through this factory so the
real-vs-mock decision lives in exactly one place.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import IntegrationCredential, Tenant
from app.security.crypto import get_cipher
from app.sheetsync.client import FakeSheetsClient, GoogleSheetsClient, SheetsClient

__all__ = ["GOOGLE_PROVIDER", "GOOGLE_TOKEN_URI", "get_sheets_client"]

GOOGLE_PROVIDER = "google"
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"


def get_sheets_client(tenant_id: UUID, session: Session) -> SheetsClient:
    """Return the real or fake Sheets client for ``tenant_id``.

    Falls back to the Fake backend whenever real Sheets cannot be used:
    DEMO_MODE, missing OAuth app config, or no active tenant credential.
    """
    settings = get_settings()

    if settings.demo_mode:
        return FakeSheetsClient.load(tenant_id)
    if not (settings.google_client_id and settings.google_client_secret):
        return FakeSheetsClient.load(tenant_id)

    credential = session.scalars(
        select(IntegrationCredential).where(
            IntegrationCredential.tenant_id == tenant_id,
            IntegrationCredential.provider == GOOGLE_PROVIDER,
            IntegrationCredential.status == "active",
        )
    ).first()
    if credential is None:
        return FakeSheetsClient.load(tenant_id)

    scopes = list(credential.scopes) or settings.google_sheets_scopes.split()
    # The user may have signed in without granting the Sheets scope (e.g. only
    # openid/email/profile). Without it, real Sheets calls 403 — use the local
    # mirror instead so live jobs still complete cleanly (reconnect Google with
    # the Sheets permission to write to a real spreadsheet).
    if "https://www.googleapis.com/auth/spreadsheets" not in scopes:
        return FakeSheetsClient.load(tenant_id)

    refresh_token = get_cipher().decrypt(credential.encrypted_secret_reference)

    tenant = session.get(Tenant, tenant_id)
    spreadsheet_id = tenant.google_spreadsheet_id if tenant else None

    def _make_credentials():
        # Imported lazily so DEMO_MODE deployments need not have google-auth.
        from google.oauth2.credentials import Credentials

        return Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri=GOOGLE_TOKEN_URI,
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            scopes=scopes,
        )

    return GoogleSheetsClient(_make_credentials, spreadsheet_id=spreadsheet_id)
