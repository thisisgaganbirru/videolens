"""The identity schema, as SQLAlchemy Core metadata: the four identity tables
plus the two that count signed-in free runs (`0003_account_free_runs`), the
three of the paid plan (`0004_billing`) and the paid plan's saved runs
(`0006_saved_history`). Runs stay in Redis for delivery; history is the
browser's, except a paid account's results, which are saved here too
(docs/backend/saved-history.md). These are the only rows the backend keeps.

Core rather than ORM: the adapters build domain entities from rows and back,
and an ORM session's identity map is one more thing to reason about. The
Alembic migration under `migrations/versions` mirrors this and is the source
of truth for a deployed database.

Deliberately portable: no foreign key into Supabase's `auth` schema and no
Postgres-only types, so the tests run the same adapters on SQLite.
"""

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB

# jsonb on Postgres (smaller, indexable if it ever needs to be), plain JSON
# on SQLite so the tests run the same adapters.
JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")

# The fixed-value checks of migration 0008 (the migration is the source of
# truth for a deployed database; these keep the test schema in step). The
# `period` formats use a Postgres regular expression, so they are created on
# Postgres only.
_DAY_OR_MONTH = "period ~ '^[0-9]{4}-[0-9]{2}(-[0-9]{2})?$'"
_MONTH = "period ~ '^[0-9]{4}-[0-9]{2}$'"


def _postgres_check(condition: str, name: str) -> CheckConstraint:
    return CheckConstraint(condition, name=name).ddl_if(dialect="postgresql")

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
    # The deletion hold (0006): set by DELETE /api/me, cleared by a restore;
    # the cleanup job removes the account once `purge_at` has passed.
    Column("deleted_at", DateTime(timezone=True), nullable=True),
    Column("purge_at", DateTime(timezone=True), nullable=True),
    # When the account's saved runs are removed, set once the paid plan has
    # ended (0006); cleared by a resubscribe.
    Column("saved_runs_expire_at", DateTime(timezone=True), nullable=True),
    Index("ix_accounts_purge_at", "purge_at"),
    Index("ix_accounts_saved_runs_expire_at", "saved_runs_expire_at"),
)

workspaces = Table(
    "workspaces",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("name", String(120), nullable=False),
    # ON DELETE CASCADE since 0007 for this and the three keys below; the
    # Postgres names are the ones 0001's inline keys got.
    Column(
        "owner_account_id",
        String(36),
        ForeignKey("accounts.id", name="workspaces_owner_account_id_fkey", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

workspace_members = Table(
    "workspace_members",
    metadata,
    Column(
        "workspace_id",
        String(36),
        ForeignKey("workspaces.id", name="workspace_members_workspace_id_fkey", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "account_id",
        String(36),
        ForeignKey("accounts.id", name="workspace_members_account_id_fkey", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("role", String(16), nullable=False, default="member"),
    CheckConstraint("role IN ('owner', 'member')", name="ck_workspace_members_role"),
)

api_keys = Table(
    "api_keys",
    metadata,
    Column("id", String(36), primary_key=True),
    Column(
        "workspace_id",
        String(36),
        ForeignKey("workspaces.id", name="api_keys_workspace_id_fkey", ondelete="CASCADE"),
        nullable=False,
    ),
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

# Signed-in free runs: one row per account per counter period it has used
# any: "YYYY-MM-DD" (UTC day: the free plan and the paid plan's included runs,
# since 2026-11-14) or "YYYY-MM" (UTC month, rows from before then). varchar(10) since 0005. ON DELETE CASCADE so deleting the account always takes its usage
# with it (the deleter also removes these explicitly: SQLite does not
# enforce foreign keys unless asked).
account_free_runs = Table(
    "account_free_runs",
    metadata,
    Column("account_id", String(36), ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True),
    Column("period", String(10), primary_key=True),
    Column("used", Integer, nullable=False, default=0),
    _postgres_check(_DAY_OR_MONTH, "ck_account_free_runs_period"),
)

# Which account run a queued run took, so the pipeline can hand it back
# (`AccountFreeRunAllowance.hold`/`release`); the account counterpart of
# the Redis `videolens:free:held:*` keys. Rows older than two days are
# pruned on the next hold, like those keys' TTL.
account_free_run_holds = Table(
    "account_free_run_holds",
    metadata,
    Column("run_id", String(36), primary_key=True),
    Column("account_id", String(36), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
    Column("period", String(10), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Index("ix_account_free_run_holds_created", "created_at"),
    Index("ix_account_free_run_holds_account", "account_id"),
    _postgres_check(_DAY_OR_MONTH, "ck_account_free_run_holds_period"),
)

# The paid plan (`0004_billing`, docs/backend/billing.md). One row per
# account that has ever started a checkout: its Stripe customer, and the
# subscription it holds or last held, as Stripe last reported it.
billing_accounts = Table(
    "billing_accounts",
    metadata,
    Column("account_id", String(36), ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True),
    Column("stripe_customer_id", String(255), nullable=False, unique=True),
    Column("stripe_subscription_id", String(255), nullable=True),
    # `status` and `interval` are Stripe's, copied verbatim by the webhook:
    # deliberately no check constraint (0008), so a value Stripe adds can
    # never make the database reject a webhook.
    Column("status", String(32), nullable=True),
    Column("price_id", String(255), nullable=True),
    Column("interval", String(8), nullable=True),
    Column("current_period_end", DateTime(timezone=True), nullable=True),
    Column("cancel_at_period_end", Boolean, nullable=False, default=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

# Stripe event ids already handled, for webhook idempotency. Not tied to an
# account (an event can outlive it); pruned after 30 days.
billing_events = Table(
    "billing_events",
    metadata,
    Column("event_id", String(255), primary_key=True),
    Column("event_type", String(100), nullable=False),
    Column("received_at", DateTime(timezone=True), nullable=False),
    Index("ix_billing_events_received", "received_at"),
)

# Paid runs past the included ones: held at admission, due once the run
# completed, reported once Stripe took the meter event, or void when the run
# did not complete. The run id is the meter event's identifier.
billing_extra_runs = Table(
    "billing_extra_runs",
    metadata,
    Column("run_id", String(36), primary_key=True),
    Column("account_id", String(36), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
    Column("stripe_customer_id", String(255), nullable=False),
    Column("period", String(10), nullable=False),
    Column("state", String(16), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    Column("reported_at", DateTime(timezone=True), nullable=True),
    Index("ix_billing_extra_runs_account_period", "account_id", "period"),
    Index("ix_billing_extra_runs_state", "state"),
    CheckConstraint("state IN ('held', 'due', 'reported', 'void')", name="ck_billing_extra_runs_state"),
    _postgres_check(_MONTH, "ck_billing_extra_runs_period"),
)

# A paid account's saved run results (0006, docs/backend/saved-history.md).
# Result text, a source descriptor and the run's small poster thumbnail
# (the same <=20 KB JPEG data URL the live run exposes as `thumbnail`): never
# other media, never a key. (account_id, run_id) is unique, so saving is
# idempotent.
saved_runs = Table(
    "saved_runs",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("account_id", String(36), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
    Column("run_id", String(36), nullable=False),
    Column("title", String(500), nullable=False),
    Column("summary_snippet", String(400), nullable=True),
    Column("completeness", String(16), nullable=False),
    Column("source", JSON_DOCUMENT, nullable=False),
    Column("result", JSON_DOCUMENT, nullable=False),
    Column("result_bytes", Integer, nullable=False),
    Column("thumbnail", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("account_id", "run_id", name="uq_saved_runs_account_run"),
    CheckConstraint("completeness IN ('full', 'captions_only')", name="ck_saved_runs_completeness"),
    # The list: newest first per account, keyset on (created_at, id).
    Index("ix_saved_runs_account_created", "account_id", "created_at", "id"),
)

IDENTITY_TABLES = ("accounts", "workspaces", "workspace_members", "api_keys")
FREE_RUN_TABLES = ("account_free_runs", "account_free_run_holds")
BILLING_TABLES = ("billing_accounts", "billing_events", "billing_extra_runs")
SAVED_HISTORY_TABLES = ("saved_runs",)
