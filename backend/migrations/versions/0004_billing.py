"""The paid plan: billing_accounts, billing_events, billing_extra_runs.

`billing_accounts` links an account to its Stripe customer and the
subscription it holds or last held, as Stripe last reported it (webhooks
re-fetch the subscription, so this is a cache of Stripe, never the source of
truth). `billing_events` holds the Stripe event ids already handled, for
webhook idempotency (pruned after 30 days). `billing_extra_runs` is the
ledger of paid runs past the included ones: held at admission, due once the
run completes, reported once Stripe took the meter event (identifier = run
id), void when the run did not complete. No run content, no card data, no
email: ids, states and timestamps only.

`billing_accounts` and `billing_extra_runs` reference `accounts.id` with ON
DELETE CASCADE, so deleting an account takes them with it.

On Postgres (Supabase) also: row level security on all three, the backend
role's policy and grants, exactly as 0001 and 0003 do. The migration FAILS
before creating anything if that role (`DATABASE_APP_ROLE`, default
`videolens_api`) does not exist; offline (`--sql`) that check is skipped.

Apply BEFORE setting the STRIPE_* variables on a deployment. With billing
off nothing reads these tables, so applying it early is harmless.

Revision ID: 0004_billing
Revises: 0003_account_free_runs
Create Date: 2026-11-13
"""

import os
import re

import sqlalchemy as sa
from alembic import context, op

revision = "0004_billing"
down_revision = "0003_account_free_runs"
branch_labels = None
depends_on = None

TABLES = ("billing_accounts", "billing_events", "billing_extra_runs")


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
        "billing_accounts",
        sa.Column(
            "account_id", sa.String(36), sa.ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("stripe_customer_id", sa.String(255), nullable=False, unique=True),
        sa.Column("stripe_subscription_id", sa.String(255), nullable=True),
        sa.Column("status", sa.String(32), nullable=True),
        sa.Column("price_id", sa.String(255), nullable=True),
        sa.Column("interval", sa.String(8), nullable=True),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_at_period_end", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "billing_events",
        sa.Column("event_id", sa.String(255), primary_key=True),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_billing_events_received", "billing_events", ["received_at"])
    op.create_table(
        "billing_extra_runs",
        sa.Column("run_id", sa.String(36), primary_key=True),
        sa.Column("account_id", sa.String(36), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stripe_customer_id", sa.String(255), nullable=False),
        sa.Column("period", sa.String(7), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reported_at", sa.DateTime(timezone=True), nullable=True),
    )
    # The monthly cap counts by (account, period); the flush scans by state.
    op.create_index("ix_billing_extra_runs_account_period", "billing_extra_runs", ["account_id", "period"])
    op.create_index("ix_billing_extra_runs_state", "billing_extra_runs", ["state"])

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
    op.drop_index("ix_billing_extra_runs_state", table_name="billing_extra_runs")
    op.drop_index("ix_billing_extra_runs_account_period", table_name="billing_extra_runs")
    op.drop_table("billing_extra_runs")
    op.drop_index("ix_billing_events_received", table_name="billing_events")
    op.drop_table("billing_events")
    op.drop_table("billing_accounts")
