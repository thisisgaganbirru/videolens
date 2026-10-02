"""Composition root: builds every concrete adapter once and wires them into
the use cases the interface layer (API routes, worker) calls. This is the
only place that is allowed to know about every layer at once - domain and
application code never import from here."""

from .application.api_keys import ManageApiKeysUseCase
from .application.billing import (
    ApplyBillingEventUseCase,
    OpenBillingPortalUseCase,
    StartCheckoutUseCase,
)
from .application.create_run import CreateRunUseCase
from .application.entitlements import EntitlementResolver
from .application.get_account import GetAccountUseCase
from .application.get_capabilities import GetCapabilitiesUseCase
from .application.get_releases import GetReleasesUseCase
from .application.get_run import GetRunUseCase
from .application.identify_caller import IdentifyCallerUseCase
from .application.list_runs import ListRunsUseCase
from .application.process_run import ProcessRunUseCase
from .application.record_usage import RecordUsageUseCase
from .application.search_library import SearchLibraryUseCase
from .infrastructure.ai.gemini_engine import GeminiEngine
from .infrastructure.auth.jwt_verifier import JwtVerifier
from .infrastructure.billing.stripe_gateway import StripeBillingGateway
from .infrastructure.byok.key_vault import ByokKeyStore
from .infrastructure.config import Settings, settings
from .infrastructure.health.probes import (
    AnalysisEngineProbe,
    DailyBudgetProbe,
    DatabaseProbe,
    MediaToolsProbe,
    ObjectStoreProbe,
    RunStoreProbe,
    UrlDownloadProbe,
)
from .infrastructure.media.service import MediaService
from .infrastructure.persistence.account_directory import PostgresAccountDirectory
from .infrastructure.persistence.api_key_repository import PostgresApiKeyRepository
from .infrastructure.persistence.database import Database
from .infrastructure.persistence.run_archive import PostgresRunArchive
from .infrastructure.persistence.run_repository import RunStore
from .infrastructure.persistence.tiered_run_repository import TieredRunRepository
from .infrastructure.persistence.usage_meter import PostgresUsageMeter
from .infrastructure.releases.github_releases import GithubReleaseCatalog
from .infrastructure.queue.job_queue import RunQueue
from .infrastructure.quota.daily_budget import DailyBudget
from .infrastructure.storage.s3_object_store import S3ObjectStore


class Container:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

        # Adapters (each owns its own connections; constructed once, shared
        # for the lifetime of the process - same lifecycle as the module
        # singletons this replaces).
        # Durable storage is one engine shared by four adapters. With no
        # DATABASE_URL every one of them reports itself disabled and the
        # tiered repository is a pass-through to the live store.
        self.database = Database(settings)
        self.run_store = RunStore(settings)
        self.run_archive = PostgresRunArchive(self.database)
        self.run_repository = TieredRunRepository(self.run_store, self.run_archive)
        self.accounts = PostgresAccountDirectory(self.database)
        self.usage_meter = PostgresUsageMeter(self.database)
        self.api_keys = PostgresApiKeyRepository(self.database)
        self.billing = StripeBillingGateway(settings)
        self.media = MediaService(settings)
        self.analysis_engine = GeminiEngine(settings)
        self.object_store = S3ObjectStore(settings)
        self.spend_cap = DailyBudget(settings)
        self.key_vault = ByokKeyStore(settings)
        self.jwt_verifier = JwtVerifier(settings)
        self.release_catalog = GithubReleaseCatalog(settings)

        # Use cases.
        self.entitlements = EntitlementResolver(
            accounts=self.accounts,
            usage=self.usage_meter,
            default_max_duration_seconds=settings.max_duration_seconds,
        )
        self.identify_caller_use_case = IdentifyCallerUseCase(
            accounts=self.accounts, api_keys=self.api_keys
        )
        self.record_usage_use_case = RecordUsageUseCase(
            usage=self.usage_meter, accounts=self.accounts, billing=self.billing
        )
        self.process_run_use_case = ProcessRunUseCase(
            runs=self.run_repository,
            media=self.media,
            storage=self.object_store,
            analysis=self.analysis_engine,
            usage=self.record_usage_use_case,
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
            entitlements=self.entitlements,
            distributed=settings.queue_enabled,
        )
        # A run that has not been touched in longer than a whole job could
        # take is treated as abandoned. Margin over the worker timeout so a
        # job that is merely slow is never declared dead.
        self.get_run_use_case = GetRunUseCase(
            runs=self.run_repository,
            stale_after_seconds=settings.worker_job_timeout_seconds + 120,
        )
        self.list_runs_use_case = ListRunsUseCase(runs=self.run_repository)
        self.search_library_use_case = SearchLibraryUseCase(
            runs=self.run_repository, archive=self.run_archive
        )
        self.get_account_use_case = GetAccountUseCase(
            accounts=self.accounts, billing=self.billing, entitlements=self.entitlements
        )
        self.start_checkout_use_case = StartCheckoutUseCase(accounts=self.accounts, billing=self.billing)
        self.open_billing_portal_use_case = OpenBillingPortalUseCase(
            accounts=self.accounts, billing=self.billing
        )
        self.apply_billing_event_use_case = ApplyBillingEventUseCase(
            accounts=self.accounts, billing=self.billing
        )
        self.manage_api_keys_use_case = ManageApiKeysUseCase(
            api_keys=self.api_keys, accounts=self.accounts, entitlements=self.entitlements
        )
        self.get_releases_use_case = GetReleasesUseCase(catalog=self.release_catalog)
        # Probe order is the order they appear in the response: the media
        # pipeline first, then the things a run depends on downstream.
        self.get_capabilities_use_case = GetCapabilitiesUseCase(
            probes=[
                MediaToolsProbe(settings),
                UrlDownloadProbe(settings),
                AnalysisEngineProbe(settings),
                RunStoreProbe(self.run_store, distributed=settings.queue_enabled),
                ObjectStoreProbe(self.object_store),
                DatabaseProbe(self.database),
                DailyBudgetProbe(self.spend_cap),
            ],
            mode="distributed" if settings.queue_enabled else "local",
        )

    async def prepare_database(self) -> None:
        """Bring durable storage up to date at startup, when configured.

        Runs from the API's lifespan and the worker's startup; Alembic's
        migrations are idempotent so two processes racing on boot is safe.
        """
        if not self.database.enabled:
            return
        if self.settings.db_auto_migrate:
            await self.database.migrate()
        await self.database.ping()

    async def close(self) -> None:
        await self.job_queue.close()
        await self.key_vault.close()
        await self.run_repository.close()
        await self.spend_cap.close()
        await self.database.close()


container = Container(settings)
