"""Identity foreign keys cascade on delete.

0001 created the four identity foreign keys with no ON DELETE action:

- `workspaces.owner_account_id -> accounts(id)`
- `workspace_members.workspace_id -> workspaces(id)`
- `workspace_members.account_id -> accounts(id)`
- `api_keys.workspace_id -> workspaces(id)`

Every other table that references `accounts` (0003, 0004, 0006) already
cascades. This makes the four match, so a delete of an account row takes its
workspaces, their members and API keys, and its own memberships with it.

The purge (`SqlAccountDeleter.delete_account`) did not depend on this: it
deletes the children by hand, children first, in one transaction, and keeps
doing so (SQLite, which the tests run, does not enforce foreign keys unless
asked). The cascade is the safety net for any other delete path and for an
operator deleting by hand.

Postgres only. 0001 declared the keys inline without names, so Postgres named
them `<table>_<column>_fkey`; this drops those and re-adds them under the same
names with `ON DELETE CASCADE`. Check the names on the target database before
applying (`SELECT conname FROM pg_constraint WHERE contype = 'f' AND conrelid
IN ('public.workspaces'::regclass, 'public.workspace_members'::regclass,
'public.api_keys'::regclass)`). Re-adding a key validates the existing rows
under a SHARE ROW EXCLUSIVE lock on both tables; they already satisfy the key,
and the tables are small. RLS, policies and grants are properties of the
tables and are not touched. No grants: nothing new is created for the role.

SQLite (tests only): nothing to do. The test schema comes from `schema.py`
(`Database.create_all`), which declares the cascade, and SQLite would need a
table rebuild to change an unnamed key for no behaviour change.

Downgrade restores the four keys with no ON DELETE action.

Revision ID: 0007_identity_cascades
Revises: 0006_saved_history
Create Date: 2026-11-14
"""

from alembic import op

revision = "0007_identity_cascades"
down_revision = "0006_saved_history"
branch_labels = None
depends_on = None

# (constraint name, table, column, referenced table)
KEYS = (
    ("workspaces_owner_account_id_fkey", "workspaces", "owner_account_id", "accounts"),
    ("workspace_members_workspace_id_fkey", "workspace_members", "workspace_id", "workspaces"),
    ("workspace_members_account_id_fkey", "workspace_members", "account_id", "accounts"),
    ("api_keys_workspace_id_fkey", "api_keys", "workspace_id", "workspaces"),
)


def _replace(ondelete: str | None) -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for name, table, column, referenced in KEYS:
        op.drop_constraint(name, table, type_="foreignkey")
        op.create_foreign_key(name, table, referenced, [column], ["id"], ondelete=ondelete)


def upgrade() -> None:
    _replace("CASCADE")


def downgrade() -> None:
    _replace(None)
