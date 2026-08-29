"""Composition root: builds every concrete adapter once and wires them into
the use cases the interface layer (API routes, worker) calls. This is the
only place that is allowed to know about every layer at once - domain and
application code never import from here."""

from .application.create_run import CreateRunUseCase
from .application.get_capabilities import GetCapabilitiesUseCase
from .application.get_run import GetRunUseCase
from .application.list_runs import ListRunsUseCase
from .application.process_run import ProcessRunUseCase
from .infrastructure.ai.gemini_engine import GeminiEngine
from .infrastructure.auth.jwt_verifier import JwtVerifier
from .infrastructure.byok.key_vault import ByokKeyStore
from .infrastructure.config import Settings, settings
from .infrastructure.health.probes import (
    AnalysisEngineProbe,
    DailyBudgetProbe,
    MediaToolsProbe,
    ObjectStoreProbe,
    RunStoreProbe,
    UrlDownloadProbe,
)
from .infrastructure.media.service import MediaService
from .infrastructure.persistence.run_repository import RunStore
from .infrastructure.queue.job_queue import RunQueue
from .infrastructure.quota.daily_budget import DailyBudget
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
        self.key_vault = ByokKeyStore(settings)
        self.jwt_verifier = JwtVerifier(settings)

        # Use cases.
        self.process_run_use_case = ProcessRunUseCase(
            runs=self.run_repository,
            media=self.media,
            storage=self.object_store,
            analysis=self.analysis_engine,
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
            distributed=settings.queue_enabled,
        )
        self.get_run_use_case = GetRunUseCase(runs=self.run_repository)
        self.list_runs_use_case = ListRunsUseCase(runs=self.run_repository)
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
            ],
            mode="distributed" if settings.queue_enabled else "local",
        )

    async def close(self) -> None:
        await self.job_queue.close()
        await self.key_vault.close()
        await self.run_repository.close()
        await self.spend_cap.close()


container = Container(settings)
