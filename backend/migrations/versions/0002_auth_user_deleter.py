"""Account deletion's way into `auth.users`: two SECURITY DEFINER helpers.

Supabase's `postgres` holds `DELETE` on `auth.users` without grant option, so
0001's direct grant to the backend role never takes (verified on
`videolens-dev`, 2026-11-08). Instead this creates
`videolens_private.delete_auth_user(uuid)`, owned by whoever runs Alembic
(`postgres`): it runs with the owner's rights, so it can delete the row,
and only the backend role may execute it. The backend therefore still holds
no Supabase API key (auth plan, decision 2).

`videolens_private.auth_user_exists(uuid)` is its read-only partner, same
rules: the backend asks it before creating rows for a subject it has not
seen (and before minting an API key), because a deleted person's access
token still verifies for up to an hour and would otherwise re-create the
account and could mint a key nobody can sign in to revoke.

- `videolens_private` is a schema of its own, never added to PostgREST's
  exposed schemas, so the function is not reachable over the REST API.
- `SET search_path = ''` is Supabase's hardening rule for DEFINER functions:
  the body names `auth.users` fully, and nothing a caller puts on its search
  path can shadow it.
- `PUBLIC` loses the default `EXECUTE` on the function and `USAGE` on the
  schema; the backend role gets exactly those two.

Online, the migration fails (and Alembic does not record it) if the role
does not exist, or if it ends up unable to execute the function, or if
Supabase's `anon` / `authenticated` roles can reach the schema. Offline
(`--sql`) there is no connection to ask, so those checks are skipped.

SQLite (tests, single-machine use) has no `auth` schema: a no-op.

Revision ID: 0002_auth_user_deleter
Revises: 0001_identity
Create Date: 2026-11-08
"""

import logging
import os
import re

import sqlalchemy as sa
from alembic import context, op

revision = "0002_auth_user_deleter"
down_revision = "0001_identity"
branch_labels = None
depends_on = None

SCHEMA = "videolens_private"
FUNCTION = f"{SCHEMA}.delete_auth_user(uuid)"
EXISTS_FUNCTION = f"{SCHEMA}.auth_user_exists(uuid)"
FUNCTIONS = (FUNCTION, EXISTS_FUNCTION)
# Supabase's REST roles. Neither may reach the schema.
REST_ROLES = ("anon", "authenticated")

logger = logging.getLogger("alembic.migration.auth_user_deleter")


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


def _verify(role: str) -> None:
    """Fail the migration (rolling it back) unless the backend role can run
    the helper and the REST roles cannot reach it."""
    if context.is_offline_mode():
        return
    bind = op.get_bind()
    for function in FUNCTIONS:
        can_execute = bind.execute(
            sa.text("SELECT has_function_privilege(:role, :function, 'EXECUTE')"),
            {"role": role, "function": function},
        ).scalar()
        if not can_execute:
            raise RuntimeError(f"{role} cannot execute {function} after the grant; nothing was recorded.")
    for rest_role in REST_ROLES:
        exists = bind.execute(
            sa.text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": rest_role}
        ).scalar()
        if not exists:
            continue
        reachable = bind.execute(
            sa.text("SELECT has_schema_privilege(:role, :schema, 'USAGE')"),
            {"role": rest_role, "schema": SCHEMA},
        ).scalar()
        if reachable:
            raise RuntimeError(f"{rest_role} has USAGE on {SCHEMA}; it must not. Nothing was recorded.")
    logger.info("%s can execute %s; REST roles cannot reach %s", role, ", ".join(FUNCTIONS), SCHEMA)


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    role = _app_role()
    _require_role(role)

    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    op.execute(f"REVOKE ALL ON SCHEMA {SCHEMA} FROM PUBLIC")
    op.execute(f"GRANT USAGE ON SCHEMA {SCHEMA} TO {role}")
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {SCHEMA}.delete_auth_user(target uuid)
          RETURNS void
          LANGUAGE sql
          SECURITY DEFINER
          SET search_path = ''
          AS $$ DELETE FROM auth.users WHERE id = target $$
        """
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {SCHEMA}.auth_user_exists(target uuid)
          RETURNS boolean
          LANGUAGE sql
          STABLE
          SECURITY DEFINER
          SET search_path = ''
          AS $$ SELECT EXISTS (SELECT 1 FROM auth.users WHERE id = target) $$
        """
    )
    for function in FUNCTIONS:
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO {role}")
    _verify(role)


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for function in FUNCTIONS:
        op.execute(f"DROP FUNCTION IF EXISTS {function}")
    # RESTRICT (the default): if anything else ever lands in the schema,
    # the downgrade stops rather than dropping it unseen.
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA}")
