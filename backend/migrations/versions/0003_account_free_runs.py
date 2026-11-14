"""Signed-in free runs: account_free_runs and account_free_run_holds.

`account_free_runs` counts the free runs (shared Gemini key, no BYOK) each
account has started per UTC calendar month: primary key (account_id,
period "YYYY-MM"), `used` integer. `account_free_run_holds` records which
account run a queued run took, so the pipeline can hand it back when a link
run is rejected before analysis (same contract as the device holds in
Redis). Both reference `accounts.id` with ON DELETE CASCADE, so deleting an
account (`DELETE /api/me`) always takes its usage with it.

On Postgres (Supabase) also: row level security on both, the backend role's
policy and grants, exactly as 0001 does for the identity tables. The
migration FAILS before creating anything if that role (`DATABASE_APP_ROLE`,
default `videolens_api`) does not exist; offline (`--sql`) that check is
skipped.

Apply BEFORE deploying the code that uses it: without these tables every
signed-in run without a Gemini key fails at admission.

Revision ID: 0003_account_free_runs
Revises: 0002_auth_user_deleter
Create Date: 2026-11-13
"""

import os
import re

import sqlalchemy as sa
from alembic import context, op

revision = "0003_account_free_runs"
down_revision = "0002_auth_user_deleter"
branch_labels = None
depends_on = None

TABLES = ("account_free_runs", "account_free_run_holds")


def _app_role() -> str:
    role = os.environ.get("DATABASE_APP_ROLE", "videolens_api").strip()
    # Keep: the role name is interpolated into DDL below, which is safe only
    # because it is a plain lowercase identifier. Same rule as 0001.
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", role):
        raise ValueError(f"DATABASE_APP_ROLE {role!r} is not a plain lowercase identifier")
    return role


def _require_role(role: str) -> None:
    if context.is_offline_mode():
        return
    exists = op.get_bind().execute(sa.text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": role}).scalar()
    if not exists:
        raise RuntimeError(
            f"Role {role!r} (DATABASE_APP_ROLE) does not exist. Create it first (docs/backend/auth.md, "
            "\"Storage\"), or set DATABASE_APP_ROLE to the backend's role. Nothing was created."
        )


def upgrade() -> None:
    postgres = op.get_bind().dialect.name == "postgresql"
    role = _app_role() if postgres else ""
    if postgres:
        _require_role(role)

    op.create_table(
        "account_free_runs",
        sa.Column(
            "account_id", sa.String(36), sa.ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("period", sa.String(7), primary_key=True),
        sa.Column("used", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_table(
        "account_free_run_holds",
        sa.Column("run_id", sa.String(36), primary_key=True),
        sa.Column("account_id", sa.String(36), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("period", sa.String(7), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_account_free_run_holds_created", "account_free_run_holds", ["created_at"])
    # The cascade from accounts looks rows up by account_id.
    op.create_index("ix_account_free_run_holds_account", "account_free_run_holds", ["account_id"])

    if not postgres:
        return

    # Same posture as 0001: Supabase's REST roles see nothing, the backend
    # role and only it gets through.
    for table in TABLES:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON public.{table} TO {role}")
        op.execute(f"CREATE POLICY {role}_all ON public.{table} FOR ALL TO {role} USING (true) WITH CHECK (true)")


def downgrade() -> None:
    # Dropping a table drops its policies and grants with it.
    op.drop_index("ix_account_free_run_holds_account", table_name="account_free_run_holds")
    op.drop_index("ix_account_free_run_holds_created", table_name="account_free_run_holds")
    op.drop_table("account_free_run_holds")
    op.drop_table("account_free_runs")
