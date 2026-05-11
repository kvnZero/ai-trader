from __future__ import annotations

import logging
import signal
import threading
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import Settings, get_settings
from app.modules.sentiment_ingestion import build_default_sentiment_service
from app.modules.sentiment_ingestion.contracts import SentimentSourceDefinition
from app.modules.sentiment_ingestion.presets import build_default_sample_sources
from app.persistence import SentimentRepository, init_database


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SentimentWorkerCycleResult:
    run_id: int | None
    started_at: str
    completed_at: str
    status: str
    records_written: int
    source_failures: int
    skipped: bool
    message: str


class SentimentWorker:
    def __init__(
        self,
        *,
        settings: Settings,
        interval_seconds: int = 300,
        keep_recent_items: int = 200,
        sources: list[SentimentSourceDefinition] | None = None,
    ) -> None:
        self.settings = settings
        self.interval_seconds = interval_seconds
        self.keep_recent_items = keep_recent_items
        self._stop_event = threading.Event()
        self._database = init_database(settings.database_path)
        self._repository = SentimentRepository(self._database)
        self._service = build_default_sentiment_service()
        self._sources = list(sources) if sources is not None else build_default_sample_sources()
        self._last_cycle: SentimentWorkerCycleResult | None = None

    def request_stop(self, *_: object) -> None:
        self._stop_event.set()

    def run_once(self) -> SentimentWorkerCycleResult:
        timezone = ZoneInfo(self.settings.market_timezone)
        started_at = datetime.now(timezone)
        started_label = started_at.isoformat()
        run_id = self._repository.start_run(started_at=started_at)
        if run_id is None:
            completed_at = datetime.now(timezone)
            cycle = SentimentWorkerCycleResult(
                run_id=None,
                started_at=started_label,
                completed_at=completed_at.isoformat(),
                status="skipped",
                records_written=0,
                source_failures=0,
                skipped=True,
                message="已有活跃舆情任务，跳过本轮。",
            )
            self._last_cycle = cycle
            LOGGER.info(cycle.message)
            return cycle

        try:
            self._repository.record_heartbeat(run_id=run_id, heartbeat_at=started_at)
            seen_dedup_keys = self._repository.list_recent_dedup_keys(
                limit=max(self.keep_recent_items * 5, 1000)
            )
            result = self._service.ingest(
                self._sources,
                now=started_at,
                seen_dedup_keys=seen_dedup_keys,
            )
            completed_at = datetime.now(timezone)
            self._repository.record_success(
                run_id=run_id,
                result=result,
                completed_at=completed_at,
                keep_recent_items=self.keep_recent_items,
            )
            status = "degraded" if result.source_failures else "succeeded"
            cycle = SentimentWorkerCycleResult(
                run_id=run_id,
                started_at=started_label,
                completed_at=completed_at.isoformat(),
                status=status,
                records_written=len(result.records),
                source_failures=len(result.source_failures),
                skipped=False,
                message=f"舆情采集完成：{len(result.records)} 条 items，{len(result.source_failures)} 个 source 失败。",
            )
            self._last_cycle = cycle
            LOGGER.info(cycle.message)
            return cycle
        except Exception as exc:
            failed_at = datetime.now(timezone)
            self._repository.record_failure(
                run_id=run_id,
                failed_at=failed_at,
                error_message=str(exc),
            )
            cycle = SentimentWorkerCycleResult(
                run_id=run_id,
                started_at=started_label,
                completed_at=failed_at.isoformat(),
                status="failed",
                records_written=0,
                source_failures=0,
                skipped=False,
                message=f"舆情采集失败：{exc}",
            )
            self._last_cycle = cycle
            LOGGER.exception("sentiment worker cycle failed")
            return cycle

    def run_forever(self) -> None:
        while not self._stop_event.is_set():
            self.run_once()
            if self._stop_event.wait(self.interval_seconds):
                break

    @property
    def last_cycle(self) -> SentimentWorkerCycleResult | None:
        return self._last_cycle


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = get_settings()
    worker = SentimentWorker(
        settings=settings,
        interval_seconds=max(60, settings.sentiment_cache_ttl_seconds),
    )

    signal.signal(signal.SIGINT, worker.request_stop)
    signal.signal(signal.SIGTERM, worker.request_stop)

    LOGGER.info("sentiment worker started")
    worker.run_forever()
    LOGGER.info("sentiment worker stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

