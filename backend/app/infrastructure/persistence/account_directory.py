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

from ...domain.entities import Account, Workspace, WorkspaceRole
from .database import Database, as_utc, utcnow
from .schema import accounts, workspace_members, workspaces

DEFAULT_WORKSPACE_NAME = "Personal"


class SqlAccountDirectory:
    def __init__(self, database: Database) -> None:
        self._db = database

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
            return await self._resolve(external_id, email)
        except IntegrityError:
            # Two first sign-ins for the same subject raced and the other
            # inserted the account first; it now exists, so read it.
            return await self._resolve(external_id, email)

    async def _resolve(self, external_id: str, email: str | None) -> Account:
        async with self._db.connect() as conn:
            row = (await conn.execute(select(accounts).where(accounts.c.external_id == external_id))).first()
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

    def __init__(self, *, enabled: bool = True) -> None:
        self._enabled = enabled
        self._accounts: dict[str, Account] = {}  # by external_id
        self._workspaces: dict[str, Workspace] = {}
        self._members: dict[tuple[str, str], str] = {}

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def resolve_account(self, external_id: str, email: str | None = None) -> Account:
        account = self._accounts.get(external_id)
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

    async def member_role(self, workspace_id: str, account_id: str) -> Optional[str]:
        if not self._enabled:
            return None
        return self._members.get((workspace_id, account_id))

    async def close(self) -> None:
        return None
