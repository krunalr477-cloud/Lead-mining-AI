"""ORM models. Importing this package registers every table on app.db.Base.metadata."""

from app.models.audit import AuditLog
from app.models.campaign import (
    BounceEvent,
    Campaign,
    EmailMessage,
    EmailTemplate,
    ReplyEvent,
    Suppression,
)
from app.models.company import Company, CompanySource, HiringSignal
from app.models.contact import Contact, EmailCandidate, ValidationCheck
from app.models.export import ExportJob
from app.models.integration import APIUsage, IntegrationCredential
from app.models.job import DataSourceAuditEvent, JobEvent, MiningJob, SourceRun
from app.models.sales import SalesReadyLead
from app.models.settings_models import (
    CampaignSettings,
    DataSourceConfig,
    ValidationRuleSet,
    default_validation_rules,
)
from app.models.sheets import SheetRowMap, SpreadsheetSyncEvent
from app.models.tenant import Tenant, User

__all__ = [
    "APIUsage",
    "AuditLog",
    "BounceEvent",
    "Campaign",
    "CampaignSettings",
    "Company",
    "CompanySource",
    "Contact",
    "DataSourceAuditEvent",
    "DataSourceConfig",
    "EmailCandidate",
    "EmailMessage",
    "EmailTemplate",
    "ExportJob",
    "HiringSignal",
    "IntegrationCredential",
    "JobEvent",
    "MiningJob",
    "ReplyEvent",
    "SalesReadyLead",
    "SheetRowMap",
    "SourceRun",
    "SpreadsheetSyncEvent",
    "Suppression",
    "Tenant",
    "User",
    "ValidationCheck",
    "ValidationRuleSet",
    "default_validation_rules",
]
