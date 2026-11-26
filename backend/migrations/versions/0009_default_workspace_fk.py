"""Foreign key for `accounts.default_workspace_id`, ON DELETE SET NULL.

0001 left it without one to avoid an `accounts <-> workspaces` cycle. The
cycle is safe in the form chosen here, because of how the rows are written
and removed:

- Creation (`SqlAccountDirectory._resolve`, one transaction): the account is
  inserted with `default_workspace_id` NULL, then the workspace and the
  owner membership, then the account is updated to point at the workspace.
  Every statement sees an existing referenced row, so the key need not be
  deferred. An account left without a default (a failed first sign-in) gets
  one the same way on its next request.
- Purge (`SqlAccountDeleter.delete_account`, one transaction): workspaces
  are deleted before the account. SET NULL clears the account's pointer as
  its workspace goes, then the account row goes. A plain (NO ACTION) key
  would fail that order; SET NULL is what makes it work unchanged. A direct
  `DELETE FROM accounts` also works: it cascades to the workspaces (0007),
  whose SET NULL then has no account row left to update.
- Restore and the deletion hold touch only `deleted_at` / `purge_at`.

Not DEFERRABLE: nothing writes the pointer before its workspace exists, and
an immediate key reports a bad write at the statement that made it.

Postgres only. `ADD CONSTRAINT ... FOREIGN KEY` validates the existing rows
under a SHARE ROW EXCLUSIVE lock on both tables; an account whose
`default_workspace_id` names a missing workspace fails the migration, so
check first (`SELECT count(*) FROM accounts a WHERE a.default_workspace_id IS
NOT NULL AND NOT EXISTS (SELECT 1 FROM workspaces w WHERE w.id =
a.default_workspace_id)` must be 0). SQLite (tests only) is skipped: its
test schema comes from `schema.py`, which declares the same key. RLS,
policies and grants are untouched; the SET NULL action runs as the table
owner, so the backend role needs nothing new.

Downgrade drops the key.

Revision ID: 0009_default_workspace_fk
Revises: 0008_value_checks
Create Date: 2026-11-14
"""

from alembic import op

revision = "0009_default_workspace_fk"
down_revision = "0008_value_checks"
branch_labels = None
depends_on = None

NAME = "fk_accounts_default_workspace_id"


def _postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _postgres():
        return
    op.create_foreign_key(NAME, "accounts", "workspaces", ["default_workspace_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    if not _postgres():
        return
    op.drop_constraint(NAME, "accounts", type_="foreignkey")
