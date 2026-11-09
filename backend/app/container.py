"""Composition root: builds every concrete adapter once and wires them into
the use cases the interface layer (API routes, worker) calls. This is the
only place that is allowed to know about every layer at once - domain and
application code never import from here."""

from .application.create_api_key import CreateApiKeyUseCase
from .application.create_run import CreateRunUseCase
from .application.delete_account import DeleteAccountUseCase
from .application.entitlements import EntitlementResolver
from .application.get_account import GetAccountUseCase
from .application.get_free_runs import GetFreeRunsUseCase
from .application.get_capabilities import GetCapabilitiesUseCase
from .application.get_releases import GetReleasesUseCase
from .application.get_run import GetRunUseCase
from .application.identify_caller import IdentifyCallerUseCase
from .application.list_api_keys import ListApiKeysUseCase
from .application.list_runs import ListRunsUseCase
from .application.process_run import ProcessRunUseCase
from .application.revoke_api_key import RevokeApiKeyUseCase
from .infrastructure.ai.gemini_engine import GeminiEngine
from .infrastructure.auth.jwt_verifier import JwtVerifier
from .infrastructure.byok.key_vault import ByokKeyStore
from .infrastructure.config import Settings, settings
from .infrastructure.health.probes import (
    AnalysisEngineProbe,
    AuthProbe,
    DailyBudgetProbe,
    DatabaseProbe,
    MediaToolsProbe,
    ObjectStoreProbe,
    RunStoreProbe,
    UrlDownloadProbe,
)
from .infrastructure.media.service import MediaService
from .infrastructure.persistence.account_deleter import InMemoryAccountDeleter, SqlAccountDeleter
from .infrastructure.persistence.account_directory import InMemoryAccountDirectory, SqlAccountDirectory
from .infrastructure.persistence.api_key_repository import InMemoryApiKeyRepository, SqlApiKeyRepository
from .infrastructure.persistence.database import Database
from .infrastructure.persistence.identity_users import AlwaysPresentIdentityProviderUsers, SqlIdentityProviderUsers
from .infrastructure.persistence.run_repository import RunStore
from .infrastructure.releases.github_releases import GithubReleaseCatalog
from .infrastructure.queue.job_queue import RunQueue
from .infrastructure.quota.daily_budget import DailyBudget
from .infrastructure.quota.device_tokens import HmacDeviceTokens
from .infrastructure.quota.free_run_allowance import FreeRunAllowanceStore
from .infrastructure.storage.s3_object_store import S3ObjectStore


class Container:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

        # Adapters (each owns its own connections; constructed once, shared
        # for the lifetime of the process - same lifecycle as the module
        # singletons this replaces).
        self.run_repository = RunStore(settings)
        self.media = MediaService(settings)
        self.analysis_engine = GeminiEngine(settings)
        self.object_store = S3ObjectStore(settings)
        self.spend_cap = DailyBudget(settings)
        self.free_runs = FreeRunAllowanceStore(settings)
        self.device_tokens = HmacDeviceTokens(settings)
        self.key_vault = ByokKeyStore(settings)
        self.jwt_verifier = JwtVerifier(settings)
        self.release_catalog = GithubReleaseCatalog(settings)

        # Identity store. One engine shared by both SQL adapters; nothing
        # connects until the first query. With no DATABASE_URL, a local API
        # keeps accounts and keys in process memory (lost on restart, fine
        # for a laptop), while a distributed one runs with no account store
        # at all: replicas would each hold different keys. Signed-in callers
        # are then bare `user:<sub>` principals, as before accounts existed.
        self.database = Database(settings)
        if self.database.enabled:
            # Asked before rows are created for a subject, so a token that
            # outlived its deleted Supabase user cannot re-create the account.
            self.identity_users = SqlIdentityProviderUsers(settings, self.database)
            self.accounts = SqlAccountDirectory(self.database, users=self.identity_users)
            self.api_keys = SqlApiKeyRepository(self.database)
            self.account_deleter = SqlAccountDeleter(settings, self.database)
        else:
            in_process = not settings.queue_enabled
            self.identity_users = AlwaysPresentIdentityProviderUsers(settings)
            memory_accounts = InMemoryAccountDirectory(enabled=in_process, users=self.identity_users)
            memory_keys = InMemoryApiKeyRepository(enabled=in_process)
            self.accounts = memory_accounts
            self.api_keys = memory_keys
            self.account_deleter = InMemoryAccountDeleter(settings, accounts=memory_accounts, api_keys=memory_keys)

        # Use cases.
        self.identify_caller_use_case = IdentifyCallerUseCase(
            accounts=self.accounts,
            api_keys=self.api_keys,
            verifier=self.jwt_verifier,
            allow_anonymous=settings.allow_anonymous,
        )
        self.entitlements = EntitlementResolver(
            max_duration_seconds=settings.max_duration_seconds,
            max_file_size_mb=settings.max_file_size_mb,
        )
        self.get_account_use_case = GetAccountUseCase(accounts=self.accounts, entitlements=self.entitlements)
        self.create_api_key_use_case = CreateApiKeyUseCase(
            api_keys=self.api_keys,
            accounts=self.accounts,
            max_active=settings.api_keys_per_workspace,
            users=self.identity_users,
        )
        self.list_api_keys_use_case = ListApiKeysUseCase(api_keys=self.api_keys, accounts=self.accounts)
        self.revoke_api_key_use_case = RevokeApiKeyUseCase(api_keys=self.api_keys, accounts=self.accounts)
        self.delete_account_use_case = DeleteAccountUseCase(
            accounts=self.accounts, deleter=self.account_deleter, api_keys=self.api_keys, runs=self.run_repository
        )
        self.process_run_use_case = ProcessRunUseCase(
            runs=self.run_repository,
            media=self.media,
            storage=self.object_store,
            analysis=self.analysis_engine,
            free_runs=self.free_runs,
        )
        self.job_queue = RunQueue(
            settings, local_runner=self.process_run_use_case.execute, key_vault=self.key_vault
        )
        self.create_run_use_case = CreateRunUseCase(
            runs=self.run_repository,
            media=self.media,
            storage=self.object_store,
            queue=self.job_queue,
            spend_cap=self.spend_cap,
            free_runs=self.free_runs,
            device_tokens=self.device_tokens,
            distributed=settings.queue_enabled,
        )
        self.get_free_runs_use_case = GetFreeRunsUseCase(
            free_runs=self.free_runs, device_tokens=self.device_tokens
        )
        # A run that has not been touched in longer than a whole job could
        # take is treated as abandoned. Margin over the worker timeout so a
        # job that is merely slow is never declared dead.
        self.get_run_use_case = GetRunUseCase(
            runs=self.run_repository,
            stale_after_seconds=settings.worker_job_timeout_seconds + 120,
        )
        self.list_runs_use_case = ListRunsUseCase(runs=self.run_repository)
        self.get_releases_use_case = GetReleasesUseCase(catalog=self.release_catalog)
        # Probe order is the order they appear in the response: the media
        # pipeline first, then the things a run depends on downstream.
        self.get_capabilities_use_case = GetCapabilitiesUseCase(
            probes=[
                MediaToolsProbe(settings),
                UrlDownloadProbe(settings),
                AnalysisEngineProbe(settings),
                RunStoreProbe(self.run_repository, distributed=settings.queue_enabled),
                ObjectStoreProbe(self.object_store),
                DailyBudgetProbe(self.spend_cap),
                AuthProbe(self.jwt_verifier),
                DatabaseProbe(self.database, distributed=settings.queue_enabled),
            ],
            mode="distributed" if settings.queue_enabled else "local",
        )

    async def close(self) -> None:
        await self.job_queue.close()
        await self.key_vault.close()
        await self.run_repository.close()
        await self.spend_cap.close()
        await self.free_runs.close()
        await self.database.close()


container = Container(settings)
