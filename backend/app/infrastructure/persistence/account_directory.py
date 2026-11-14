"""AccountDirectory adapters: accounts, their default workspace, membership.

Sign-up is implicit: the first verified token for a `sub` creates the account
and a "Personal" workspace it owns. No trigger on Supabase's `auth.users` and
no foreign key into it, so this schema stays portable (SQLite in tests).

`SqlAccountDirectory` is the deployed one (Postgres via asyncpg, or SQLite).
`InMemoryAccountDirectory` is what a local `uvicorn` with no `DATABASE_URL`
gets; constructed with `enabled=False` it is the "no account store" stand-in
for a distributed deployment without a database.
"""

import uuid
from typing import Optional

from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError

from ...domain.entities import Account, PendingAccountPurge, Workspace, WorkspaceRole
from ...domain.errors import AuthenticationError
from ...domain.ports import IdentityProviderUsers
from .database import Database, as_utc, utcnow
from .schema import accounts, workspace_members, workspaces

DEFAULT_WORKSPACE_NAME = "Personal"


class _FirstSight(Exception):
    """Raised out of `_resolve`'s transaction (rolling back a read-only
    transaction) when the subject has no account yet and the identity
    provider has not been asked whether the user still exists."""


class SqlAccountDirectory:
    def __init__(self, database: Database, users: IdentityProviderUsers | None = None) -> None:
        self._db = database
        # None skips the check (tests that predate it). The container always
        # passes one.
        self._users = users

    @property
    def enabled(self) -> bool:
        return self._db.enabled

    @staticmethod
    def _account(row) -> Account:
        return Account(
            account_id=row.id,
            external_id=row.external_id,
            email=row.email,
            default_workspace_id=row.default_workspace_id,
            created_at=as_utc(row.created_at),
            deleted_at=as_utc(row.deleted_at),
            purge_at=as_utc(row.purge_at),
        )

    @staticmethod
    def _workspace(row) -> Workspace:
        return Workspace(
            workspace_id=row.id,
            name=row.name,
            owner_account_id=row.owner_account_id,
            created_at=as_utc(row.created_at),
        )

    async def resolve_account(self, external_id: str, email: str | None = None) -> Account:
        try:
            return await self._resolve_once(external_id, email)
        except IntegrityError:
            # Two first sign-ins for the same subject raced and the other
            # inserted the account first; it now exists, so read it.
            return await self._resolve_once(external_id, email)

    async def _resolve_once(self, external_id: str, email: str | None) -> Account:
        try:
            return await self._resolve(external_id, email, user_confirmed=self._users is None)
        except _FirstSight:
            # First sight of this subject: create rows only if the identity
            # provider still has the user. A token outlives a deleted user by
            # up to an hour and would otherwise re-create the account (and
            # could then mint a key nobody can ever revoke). Asked here only,
            # so an existing account's reads cost no extra query.
            if not await self._users.exists(external_id):
                raise AuthenticationError("Invalid access token.") from None
            return await self._resolve(external_id, email, user_confirmed=True)

    async def _resolve(self, external_id: str, email: str | None, *, user_confirmed: bool) -> Account:
        async with self._db.connect() as conn:
            row = (await conn.execute(select(accounts).where(accounts.c.external_id == external_id))).first()
            if row is None and not user_confirmed:
                raise _FirstSight()
            if row is None:
                now = utcnow()
                account_id = str(uuid.uuid4())
                await conn.execute(
                    insert(accounts).values(
                        id=account_id, external_id=external_id, email=email, default_workspace_id=None, created_at=now
                    )
                )
                account = Account(account_id=account_id, external_id=external_id, email=email, created_at=now)
            else:
                account = self._account(row)
                if email and account.email != email:
                    await conn.execute(update(accounts).where(accounts.c.id == account.account_id).values(email=email))
                    account.email = email
            if not account.default_workspace_id:
                # New, or an account left without one (a failed first sign-in).
                workspace_id = await self._create_default_workspace(conn, account.account_id)
                await conn.execute(
                    update(accounts)
                    .where(accounts.c.id == account.account_id)
                    .values(default_workspace_id=workspace_id)
                )
                account.default_workspace_id = workspace_id
            return account

    @staticmethod
    async def _create_default_workspace(conn, account_id: str) -> str:
        workspace_id = str(uuid.uuid4())
        await conn.execute(
            insert(workspaces).values(
                id=workspace_id, name=DEFAULT_WORKSPACE_NAME, owner_account_id=account_id, created_at=utcnow()
            )
        )
        await conn.execute(
            insert(workspace_members).values(
                workspace_id=workspace_id, account_id=account_id, role=WorkspaceRole.OWNER.value
            )
        )
        return workspace_id

    async def get_workspace(self, workspace_id: str) -> Optional[Workspace]:
        if not self.enabled:
            return None
        async with self._db.connect() as conn:
            row = (await conn.execute(select(workspaces).where(workspaces.c.id == workspace_id))).first()
        return self._workspace(row) if row is not None else None

    async def get_account(self, account_id: str) -> Optional[Account]:
        if not self.enabled:
            return None
        async with self._db.connect() as conn:
            row = (await conn.execute(select(accounts).where(accounts.c.id == account_id))).first()
        return self._account(row) if row is not None else None

    async def member_role(self, workspace_id: str, account_id: str) -> Optional[str]:
        if not self.enabled:
            return None
        async with self._db.connect() as conn:
            return await conn.scalar(
                select(workspace_members.c.role).where(
                    workspace_members.c.workspace_id == workspace_id,
                    workspace_members.c.account_id == account_id,
                )
            )

    async def ping(self) -> bool:
        return await self._db.ping()

    async def close(self) -> None:
        await self._db.close()


class InMemoryAccountDirectory:
    """Process-local accounts for a deployment with no `DATABASE_URL`. Same
    semantics as the SQL adapter; everything is gone on restart."""

    def __init__(self, *, enabled: bool = True, users: IdentityProviderUsers | None = None) -> None:
        self._enabled = enabled
        # Same first-sight check as the SQL adapter. The container passes an
        # always-present one (no identity provider to ask locally); tests
        # pass a fake to exercise the refusal.
        self._users = users
        self._accounts: dict[str, Account] = {}  # by external_id
        self._workspaces: dict[str, Workspace] = {}
        self._members: dict[tuple[str, str], str] = {}

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def resolve_account(self, external_id: str, email: str | None = None) -> Account:
        account = self._accounts.get(external_id)
        if account is None and self._users is not None and not await self._users.exists(external_id):
            raise AuthenticationError("Invalid access token.")
        account = self._accounts.get(external_id)  # re-read: the check awaited
        if account is None:
            account = Account(
                account_id=str(uuid.uuid4()), external_id=external_id, email=email, created_at=utcnow()
            )
            self._accounts[external_id] = account
        elif email:
            account.email = email
        if not account.default_workspace_id:
            workspace = Workspace(
                workspace_id=str(uuid.uuid4()),
                name=DEFAULT_WORKSPACE_NAME,
                owner_account_id=account.account_id,
                created_at=utcnow(),
            )
            self._workspaces[workspace.workspace_id] = workspace
            self._members[(workspace.workspace_id, account.account_id)] = WorkspaceRole.OWNER.value
            account.default_workspace_id = workspace.workspace_id
        return account.model_copy()

    async def get_workspace(self, workspace_id: str) -> Optional[Workspace]:
        if not self._enabled:
            return None
        workspace = self._workspaces.get(workspace_id)
        return workspace.model_copy() if workspace else None

    async def get_account(self, account_id: str) -> Optional[Account]:
        if not self._enabled:
            return None
        account = next((a for a in self._accounts.values() if a.account_id == account_id), None)
        return account.model_copy() if account else None

    async def member_role(self, workspace_id: str, account_id: str) -> Optional[str]:
        if not self._enabled:
            return None
        return self._members.get((workspace_id, account_id))

    # The deletion hold, for `InMemoryAccountDeleter` (the SQL adapter keeps
    # it in `accounts.deleted_at` / `purge_at`).

    def schedule_deletion(self, external_id: str, now, purge_at):
        account = self._accounts.get(external_id)
        if account is None:
            return None
        if account.purge_at is None:
            account.deleted_at, account.purge_at = now, purge_at
        return account.purge_at

    def restore(self, external_id: str, now):
        account = self._accounts.get(external_id)
        if account is None:
            return None
        if account.purge_at is None:
            return False
        if account.purge_at <= now:
            return None
        account.deleted_at = account.purge_at = None
        return True

    def due_for_purge(self, now, limit: int) -> list[str]:
        due = sorted(
            (a for a in self._accounts.values() if a.purge_at is not None and a.purge_at <= now),
            key=lambda a: a.purge_at,
        )
        return [PendingAccountPurge(account_id=a.account_id, external_id=a.external_id) for a in due[:limit]]

    def is_pending(self, account_id: str) -> bool:
        return any(a.account_id == account_id and a.purge_at is not None for a in self._accounts.values())

    def is_due(self, external_id: str, now) -> bool:
        account = self._accounts.get(external_id)
        return account is not None and account.purge_at is not None and account.purge_at <= now

    def account_id_for(self, external_id: str) -> str | None:
        account = self._accounts.get(external_id)
        return account.account_id if account else None

    def forget_account(self, external_id: str) -> set[str] | None:
        """Account deletion (`InMemoryAccountDeleter`): drop the account, the
        workspaces it owns and every membership in them or held by it. Returns
        the dropped workspace ids, or None when there was no such account."""
        account = self._accounts.pop(external_id, None)
        if account is None:
            return None
        owned = {
            workspace_id
            for workspace_id, workspace in self._workspaces.items()
            if workspace.owner_account_id == account.account_id
        }
        for workspace_id in owned:
            del self._workspaces[workspace_id]
        self._members = {
            (workspace_id, member_id): role
            for (workspace_id, member_id), role in self._members.items()
            if workspace_id not in owned and member_id != account.account_id
        }
        return owned

    async def close(self) -> None:
        return None
