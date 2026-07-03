"""export_job_scope_target

Revision ID: 17ff621b4ad1
Revises: f030b9e1c677
Create Date: 2026-07-03 10:15:58.616798+00:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = '17ff621b4ad1'
down_revision: str | None = 'f030b9e1c677'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # server_default backfills any pre-existing rows so NOT NULL is satisfiable.
    op.add_column(
        'export_jobs',
        sa.Column('scope', sa.String(length=20), nullable=False, server_default='sales_ready'),
    )
    op.add_column(
        'export_jobs',
        sa.Column('target', sa.String(length=20), nullable=False, server_default='file'),
    )
    op.create_check_constraint(
        op.f('ck_export_jobs_scope_valid'),
        'export_jobs',
        "scope IN ('sales_ready', 'raw')",
    )
    op.create_check_constraint(
        op.f('ck_export_jobs_target_valid'),
        'export_jobs',
        "target IN ('file', 'google_sheets')",
    )


def downgrade() -> None:
    op.drop_constraint(op.f('ck_export_jobs_target_valid'), 'export_jobs', type_='check')
    op.drop_constraint(op.f('ck_export_jobs_scope_valid'), 'export_jobs', type_='check')
    op.drop_column('export_jobs', 'target')
    op.drop_column('export_jobs', 'scope')
