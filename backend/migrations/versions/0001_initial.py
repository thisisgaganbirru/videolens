"""Accounts, workspaces, archived runs, usage events and API keys.

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-17
"""

from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("external_id", sa.String(255), nullable=False, unique=True),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("default_workspace_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "workspaces",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("owner_account_id", sa.String(36), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("plan", sa.String(16), nullable=False, server_default="free"),
        sa.Column("seats", sa.Integer, nullable=False, server_default="1"),
        sa.Column("stripe_customer_id", sa.String(255), nullable=True),
        sa.Column("stripe_subscription_id", sa.String(255), nullable=True),
        sa.Column("minutes_included", sa.Integer, nullable=False, server_default="0"),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("max_duration_seconds", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_workspaces_stripe_customer_id", "workspaces", ["stripe_customer_id"])
    op.create_table(
        "workspace_members",
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), primary_key=True),
        sa.Column("account_id", sa.String(36), sa.ForeignKey("accounts.id"), primary_key=True),
        sa.Column("role", sa.String(16), nullable=False, server_default="member"),
    )
    op.create_table(
        "runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(160), nullable=False),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=True),
        sa.Column("plan", sa.String(16), nullable=False, server_default="free"),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("stage", sa.String(32), nullable=True),
        sa.Column("source_url", sa.Text, nullable=True),
        sa.Column("platform", sa.String(64), nullable=True),
        sa.Column("title", sa.Text, nullable=True),
        sa.Column("duration_seconds", sa.Float, nullable=True),
        sa.Column("max_duration_seconds", sa.Integer, nullable=True),
        sa.Column("completeness", sa.String(16), nullable=False, server_default="full"),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("input_tokens", sa.Integer, nullable=True),
        sa.Column("output_tokens", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_runs_owner_created", "runs", ["owner_id", "created_at"])
    op.create_index("ix_runs_workspace_created", "runs", ["workspace_id", "created_at"])
    op.create_table(
        "run_results",
        sa.Column("run_id", sa.String(36), sa.ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("summary", sa.Text, nullable=False, server_default=""),
        sa.Column("transcript", sa.Text, nullable=False, server_default=""),
        sa.Column("screen_text", sa.Text, nullable=False, server_default=""),
        sa.Column("markdown", sa.Text, nullable=False, server_default=""),
        sa.Column("transcript_segments", sa.JSON, nullable=False),
        sa.Column("screen_text_segments", sa.JSON, nullable=False),
        sa.Column("source_metadata", sa.JSON, nullable=True),
    )
    op.create_table(
        "usage_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("minutes_billed", sa.Numeric(12, 2), nullable=False),
        sa.Column("input_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cost_estimate_usd", sa.Numeric(12, 4), nullable=False, server_default="0"),
        sa.Column("meter_event_id", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", name="uq_usage_events_run_id"),
    )
    op.create_index("ix_usage_events_workspace_created", "usage_events", ["workspace_id", "created_at"])
    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("prefix", sa.String(24), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("scopes", sa.JSON, nullable=False),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_api_keys_workspace", "api_keys", ["workspace_id"])

    # Full-text search over what a run says and shows. Postgres only: it is
    # the same expression `PostgresRunArchive.search` filters by, so the
    # planner can use the index. SQLite (tests) falls back to LIKE.
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            CREATE INDEX ix_run_results_search ON run_results USING GIN (
                to_tsvector('english',
                    concat_ws(' ', coalesce(summary, ''), coalesce(screen_text, ''), coalesce(transcript, ''))
                )
            )
            """
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_run_results_search")
    op.drop_index("ix_api_keys_workspace", table_name="api_keys")
    op.drop_table("api_keys")
    op.drop_index("ix_usage_events_workspace_created", table_name="usage_events")
    op.drop_table("usage_events")
    op.drop_table("run_results")
    op.drop_index("ix_runs_workspace_created", table_name="runs")
    op.drop_index("ix_runs_owner_created", table_name="runs")
    op.drop_table("runs")
    op.drop_table("workspace_members")
    op.drop_index("ix_workspaces_stripe_customer_id", table_name="workspaces")
    op.drop_table("workspaces")
    op.drop_table("accounts")
