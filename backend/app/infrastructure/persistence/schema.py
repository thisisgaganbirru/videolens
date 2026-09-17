"""The durable schema, as SQLAlchemy Core metadata.

Core rather than ORM on purpose: the adapters build rows from domain
entities and back, and an ORM session's identity map is one more thing to
reason about across an async worker. Alembic reads this metadata to
autogenerate migrations; the initial migration under `migrations/versions`
was generated from it and is the source of truth for a deployed database.

Search: Postgres gets a GIN index over a `tsvector` expression added in the
migration (SQLite, which the tests use, has no such thing). The archive's
`search` picks the expression by dialect at query time.
"""

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
)

metadata = MetaData()

accounts = Table(
    "accounts",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("external_id", String(255), nullable=False, unique=True),
    Column("email", String(320), nullable=True),
    Column("default_workspace_id", String(36), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

workspaces = Table(
    "workspaces",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("name", String(120), nullable=False),
    Column("owner_account_id", String(36), ForeignKey("accounts.id"), nullable=False),
    Column("plan", String(16), nullable=False, default="free"),
    Column("seats", Integer, nullable=False, default=1),
    Column("stripe_customer_id", String(255), nullable=True),
    Column("stripe_subscription_id", String(255), nullable=True),
    Column("minutes_included", Integer, nullable=False, default=0),
    Column("period_start", DateTime(timezone=True), nullable=False),
    Column("period_end", DateTime(timezone=True), nullable=False),
    Column("max_duration_seconds", Integer, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Index("ix_workspaces_stripe_customer_id", "stripe_customer_id"),
)

workspace_members = Table(
    "workspace_members",
    metadata,
    Column("workspace_id", String(36), ForeignKey("workspaces.id"), primary_key=True),
    Column("account_id", String(36), ForeignKey("accounts.id"), primary_key=True),
    Column("role", String(16), nullable=False, default="member"),
)

runs = Table(
    "runs",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("owner_id", String(160), nullable=False),
    Column("workspace_id", String(36), ForeignKey("workspaces.id"), nullable=True),
    Column("plan", String(16), nullable=False, default="free"),
    Column("status", String(16), nullable=False),
    Column("stage", String(32), nullable=True),
    Column("source_url", Text, nullable=True),
    Column("platform", String(64), nullable=True),
    Column("title", Text, nullable=True),
    Column("duration_seconds", Float, nullable=True),
    Column("max_duration_seconds", Integer, nullable=True),
    Column("completeness", String(16), nullable=False, default="full"),
    Column("error", Text, nullable=True),
    Column("input_tokens", Integer, nullable=True),
    Column("output_tokens", Integer, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    Index("ix_runs_owner_created", "owner_id", "created_at"),
    Index("ix_runs_workspace_created", "workspace_id", "created_at"),
)

run_results = Table(
    "run_results",
    metadata,
    Column("run_id", String(36), ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True),
    Column("summary", Text, nullable=False, default=""),
    Column("transcript", Text, nullable=False, default=""),
    Column("screen_text", Text, nullable=False, default=""),
    Column("markdown", Text, nullable=False, default=""),
    Column("transcript_segments", JSON, nullable=False, default=list),
    Column("screen_text_segments", JSON, nullable=False, default=list),
    Column("source_metadata", JSON, nullable=True),
)

usage_events = Table(
    "usage_events",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("workspace_id", String(36), ForeignKey("workspaces.id"), nullable=False),
    Column("run_id", String(36), nullable=False),
    Column("minutes_billed", Numeric(12, 2), nullable=False),
    Column("input_tokens", Integer, nullable=False, default=0),
    Column("output_tokens", Integer, nullable=False, default=0),
    Column("cost_estimate_usd", Numeric(12, 4), nullable=False, default=0),
    Column("meter_event_id", String(255), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Index("ix_usage_events_workspace_created", "workspace_id", "created_at"),
    UniqueConstraint("run_id", name="uq_usage_events_run_id"),
)

api_keys = Table(
    "api_keys",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("workspace_id", String(36), ForeignKey("workspaces.id"), nullable=False),
    Column("name", String(80), nullable=False),
    Column("prefix", String(24), nullable=False),
    Column("key_hash", String(64), nullable=False, unique=True),
    Column("scopes", JSON, nullable=False, default=list),
    Column("active", Boolean, nullable=False, default=True),
    Column("last_used_at", DateTime(timezone=True), nullable=True),
    Column("revoked_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Index("ix_api_keys_workspace", "workspace_id"),
)
