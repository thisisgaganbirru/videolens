"""Identity tables: accounts, workspaces, workspace_members, api_keys.

On Postgres (Supabase) also: row level security on all four, a policy that
lets only the backend's own role through, grants for that role, and the
`auth.users` DELETE grant that account deletion (auth phase 3) needs, so
that phase ships without a second migration.

Run as `postgres` (the project owner), as a release step, after the backend
role exists (`docs/backend/auth.md`, "Storage"). The role name is
`DATABASE_APP_ROLE`, default `videolens_api`.

On Postgres the migration FAILS, before creating anything, if that role does
not exist. It used to skip the grants with a NOTICE, but asyncpg drops
notices unless a listener is registered, so the skip was silent, Alembic
recorded head anyway, and every signed-in request would later have failed
with permission denied on a migration that never re-runs.

The `auth.users` grant is different: Supabase may refuse it, and phase 3 can
do it from the dashboard instead. It does not fail the migration, but the
resulting privilege is checked afterwards with `has_table_privilege`, and a
missing one is reported at WARNING (log and Alembic's stdout).

Revision ID: 0001_identity
Revises:
Create Date: 2026-11-08
"""

import logging
import os
import re

import sqlalchemy as sa
from alembic import context, op

revision = "0001_identity"
down_revision = None
branch_labels = None
depends_on = None

TABLES = ("accounts", "workspaces", "workspace_members", "api_keys")

logger = logging.getLogger("alembic.migration.identity")


def _app_role() -> str:
    role = os.environ.get("DATABASE_APP_ROLE", "videolens_api").strip()
    # Keep: the role name is interpolated into DDL below, which is safe only
    # because it is a plain lowercase identifier.
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", role):
        raise ValueError(f"DATABASE_APP_ROLE {role!r} is not a plain lowercase identifier")
    return role


def _warn(message: str) -> None:
    logger.warning(message)
    context.config.print_stdout("WARNING: %s", message)


def _require_role(role: str) -> None:
    """Refuse to migrate a Postgres database whose backend role is missing.
    Offline (`--sql`) there is no connection to ask, and the operator reads
    the script, so the check is skipped there."""
    if context.is_offline_mode():
        return
    exists = op.get_bind().execute(sa.text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": role}).scalar()
    if not exists:
        raise RuntimeError(
            f"Role {role!r} (DATABASE_APP_ROLE) does not exist. Create it first "
            f"(CREATE ROLE {role} LOGIN PASSWORD '...'; see docs/backend/auth.md), or set "
            "DATABASE_APP_ROLE to the backend's role, then run `alembic upgrade head` again. "
            "Nothing was created."
        )


def _check_auth_users_grant(role: str) -> None:
    if context.is_offline_mode():
        return
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT to_regclass('auth.users')")).scalar() is None:
        return  # not a Supabase database: nothing for phase 3 to delete from
    granted = bind.execute(
        sa.text("SELECT has_table_privilege(:role, 'auth.users', 'DELETE')"), {"role": role}
    ).scalar()
    if not granted:
        _warn(
            f"{role} has no DELETE on auth.users. Account deletion (auth phase 3) will fail until "
            f"it is granted from the Supabase SQL editor: GRANT USAGE ON SCHEMA auth TO {role}; "
            f"GRANT SELECT (id), DELETE ON auth.users TO {role};"
        )


def upgrade() -> None:
    postgres = op.get_bind().dialect.name == "postgresql"
    role = _app_role() if postgres else ""
    if postgres:
        _require_role(role)

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
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "workspace_members",
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), primary_key=True),
        sa.Column("account_id", sa.String(36), sa.ForeignKey("accounts.id"), primary_key=True),
        sa.Column("role", sa.String(16), nullable=False, server_default="member"),
    )
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

    if not postgres:
        return

    # RLS on, so Supabase's `anon` and `authenticated` REST roles (which get
    # default grants on `public`) can read nothing here; the policy lets the
    # backend's role, and only it, through. The role exists (checked above).
    op.execute(f"GRANT USAGE ON SCHEMA public TO {role}")
    for table in TABLES:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON public.{table} TO {role}")
        op.execute(f"CREATE POLICY {role}_all ON public.{table} FOR ALL TO {role} USING (true) WITH CHECK (true)")

    # Account deletion (phase 3) removes the Supabase user with this role
    # rather than holding a service-role key. DELETE ... WHERE id = $1 also
    # needs SELECT on the column it filters by. A refusal is caught here and
    # reported by `_check_auth_users_grant`, which also catches a GRANT that
    # "succeeds" with only a WARNING (no grant option).
    op.execute(
        f"""
        DO $$
        BEGIN
          IF to_regclass('auth.users') IS NOT NULL THEN
            BEGIN
              GRANT USAGE ON SCHEMA auth TO {role};
              GRANT SELECT (id), DELETE ON auth.users TO {role};
            EXCEPTION WHEN insufficient_privilege THEN
              RAISE WARNING 'Not allowed to grant on auth.users; grant DELETE to {role} by hand before phase 3';
            END;
          END IF;
        END
        $$
        """
    )
    _check_auth_users_grant(role)


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        role = _app_role()
        op.execute(
            f"""
            DO $$
            BEGIN
              IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}')
                 AND to_regclass('auth.users') IS NOT NULL THEN
                BEGIN
                  REVOKE SELECT (id), DELETE ON auth.users FROM {role};
                EXCEPTION WHEN insufficient_privilege THEN
                  RAISE WARNING 'Not allowed to revoke on auth.users';
                END;
              END IF;
            END
            $$
            """
        )
    # Dropping a table drops its policies and grants with it.
    op.drop_index("ix_api_keys_workspace", table_name="api_keys")
    op.drop_table("api_keys")
    op.drop_table("workspace_members")
    op.drop_table("workspaces")
    op.drop_table("accounts")
