"""The identity schema, as SQLAlchemy Core metadata: four tables and nothing
else. Runs stay in Redis and history in the browser; these are the only rows
the backend keeps.

Core rather than ORM: the adapters build domain entities from rows and back,
and an ORM session's identity map is one more thing to reason about. The
Alembic migration under `migrations/versions` mirrors this and is the source
of truth for a deployed database.

Deliberately portable: no foreign key into Supabase's `auth` schema and no
Postgres-only types, so the tests run the same adapters on SQLite. Plan,
seat and billing columns are subscription work and come with its migration.
"""

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Index, MetaData, String, Table

metadata = MetaData()

accounts = Table(
    "accounts",
    metadata,
    Column("id", String(36), primary_key=True),
    # The identity provider's `sub`.
    Column("external_id", String(255), nullable=False, unique=True),
    Column("email", String(320), nullable=True),
    # Not a foreign key: workspaces reference accounts, and a cycle would
    # need deferred constraints on Postgres for nothing.
    Column("default_workspace_id", String(36), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

workspaces = Table(
    "workspaces",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("name", String(120), nullable=False),
    Column("owner_account_id", String(36), ForeignKey("accounts.id"), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

workspace_members = Table(
    "workspace_members",
    metadata,
    Column("workspace_id", String(36), ForeignKey("workspaces.id"), primary_key=True),
    Column("account_id", String(36), ForeignKey("accounts.id"), primary_key=True),
    Column("role", String(16), nullable=False, default="member"),
)

api_keys = Table(
    "api_keys",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("workspace_id", String(36), ForeignKey("workspaces.id"), nullable=False),
    Column("name", String(80), nullable=False),
    Column("prefix", String(24), nullable=False),
    # sha256 hex of the full secret. Unique, and the only lookup path.
    Column("key_hash", String(64), nullable=False, unique=True),
    Column("scopes", JSON, nullable=False, default=list),
    Column("active", Boolean, nullable=False, default=True),
    Column("last_used_at", DateTime(timezone=True), nullable=True),
    Column("revoked_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Index("ix_api_keys_workspace", "workspace_id"),
)

IDENTITY_TABLES = ("accounts", "workspaces", "workspace_members", "api_keys")
