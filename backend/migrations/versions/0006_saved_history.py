"""Paid saved history and the 30-day account deletion hold.

Owner decisions 2026-11-14 (docs/backend/saved-history.md), which reverse
"no server-side persistence for runs or results":

- `saved_runs`: a paid account's run results, saved automatically once a
  run succeeds, no cap on how many. Result text (title, summary, notes,
  transcript, on-screen text, their segments) and a source descriptor
  (kind, platform, public link, publisher title, duration, size) only:
  never the media, never the poster image, never a key. `(account_id,
  run_id)` is unique, which is what makes saving idempotent.
- `accounts.saved_runs_expire_at`: set once the account's paid plan has
  ended; the saved runs stay readable and deletable until then, and the
  cleanup job removes them after it. A resubscribe clears it.
- `accounts.deleted_at` / `accounts.purge_at`: `DELETE /api/me` is now a
  hold. The account is refused everywhere (except the restore) while
  `purge_at` is set; after it, the cleanup job removes the Supabase user
  and every row for good.

Postgres: the three new `accounts` columns are nullable with no default, so
`ADD COLUMN` changes the catalog only (no rewrite). `saved_runs` gets row
level security, the backend role's policy and grants, exactly as 0001, 0003
and 0004 do; the RLS and policy already on `accounts` cover its new
columns. The migration FAILS before creating anything if that role
(`DATABASE_APP_ROLE`, default `videolens_api`) does not exist; offline
(`--sql`) that check is skipped.

Apply BEFORE deploying the code that reads these columns: without them
every signed-in request fails on Postgres (column does not exist).

Downgrade drops `saved_runs` (every saved result is lost) and the three
columns (every pending deletion is forgotten, so those accounts come back
as if never deleted). Run it only together with the code that predates it.

Revision ID: 0006_saved_history
Revises: 0005_account_daily_free_runs
Create Date: 2026-11-14
"""

import os
import re

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision = "0006_saved_history"
down_revision = "0005_account_daily_free_runs"
branch_labels = None
depends_on = None

TABLES = ("saved_runs",)
ACCOUNT_COLUMNS = ("deleted_at", "purge_at", "saved_runs_expire_at")


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

    for column in ACCOUNT_COLUMNS:
        op.add_column("accounts", sa.Column(column, sa.DateTime(timezone=True), nullable=True))
    # The cleanup job's two scans.
    op.create_index("ix_accounts_purge_at", "accounts", ["purge_at"])
    op.create_index("ix_accounts_saved_runs_expire_at", "accounts", ["saved_runs_expire_at"])

    document = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    op.create_table(
        "saved_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("account_id", sa.String(36), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("summary_snippet", sa.String(400), nullable=True),
        sa.Column("completeness", sa.String(16), nullable=False),
        sa.Column("source", document, nullable=False),
        sa.Column("result", document, nullable=False),
        sa.Column("result_bytes", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("account_id", "run_id", name="uq_saved_runs_account_run"),
    )
    # The list: newest first per account, keyset on (created_at, id).
    op.create_index("ix_saved_runs_account_created", "saved_runs", ["account_id", "created_at", "id"])

    if not postgres:
        return

    # Same posture as 0001/0003/0004: Supabase's REST roles see nothing, the
    # backend role and only it gets through.
    for table in TABLES:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON public.{table} TO {role}")
        op.execute(f"CREATE POLICY {role}_all ON public.{table} FOR ALL TO {role} USING (true) WITH CHECK (true)")


def downgrade() -> None:
    # Dropping a table drops its policies and grants with it.
    op.drop_index("ix_saved_runs_account_created", table_name="saved_runs")
    op.drop_table("saved_runs")
    op.drop_index("ix_accounts_saved_runs_expire_at", table_name="accounts")
    op.drop_index("ix_accounts_purge_at", table_name="accounts")
    # Batch mode: a plain ALTER on Postgres, the copy-and-move SQLite needs.
    with op.batch_alter_table("accounts") as batch:
        for column in reversed(ACCOUNT_COLUMNS):
            batch.drop_column(column)
