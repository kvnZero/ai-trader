from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.config import Settings
from app.modules.entity_mapping import build_default_entity_mapping_service
from app.modules.market_data import build_default_market_data_service
from app.modules.recommendation_engine import build_default_recommendation_engine_service
from app.modules.sentiment_ingestion import build_default_sentiment_service
from app.modules.technical_analysis import build_default_technical_analysis_service
from app.persistence.alerts import AlertRepository
from app.persistence.recommendation_events import RecommendationEventRepository
from app.persistence.watchlist import WatchlistRepository, WatchlistRow


@dataclass(frozen=True, slots=True)
class RefreshOutcome:
    symbol: str
    changed: bool
    recommendation: str
    confidence: float
    reason: str
    status: str
    status_label: str
    analysis_at: str
    alert_created: bool
    source: str


class WatchlistRefreshService:
    MIN_REFRESH_GAP_SECONDS = 180
    LOW_CONFIDENCE_FLOOR = 0.34
    NO_TRADE_CONFIDENCE_FLOOR = 0.20

    def __init__(
        self,
        *,
        settings: Settings,
        watchlist_repository: WatchlistRepository,
        alert_repository: AlertRepository,
        recommendation_event_repository: RecommendationEventRepository,
    ):
        self.settings = settings
        self.watchlist_repository = watchlist_repository
        self.alert_repository = alert_repository
        self.recommendation_event_repository = recommendation_event_repository
        self.market_service = build_default_market_data_service()
        self.technical_service = build_default_technical_analysis_service()
        self.sentiment_service = build_default_sentiment_service()
        self.entity_mapping_service = build_default_entity_mapping_service()
        self.recommendation_engine = build_default_recommendation_engine_service()
        self._last_refresh_at: dict[str, datetime] = {}

    def refresh_symbol(self, symbol: str, *, source: str) -> RefreshOutcome | None:
        target_row = self.watchlist_repository.get_row(symbol)
        if target_row is None:
            return None

        now = datetime.now(ZoneInfo(self.settings.market_timezone))
        last_refresh_at = self._last_refresh_at.get(target_row.symbol)
        if (
            last_refresh_at is not None
            and (now - last_refresh_at).total_seconds() < self.MIN_REFRESH_GAP_SECONDS
        ):
            return RefreshOutcome(
                symbol=target_row.symbol,
                changed=False,
                recommendation=target_row.latest_recommendation,
                confidence=target_row.latest_confidence,
                reason="刷新间隔过短，已跳过重复分析。",
                status=target_row.status,
                status_label=target_row.status_label,
                analysis_at=self._now_label(),
                alert_created=False,
                source=source,
            )

        outcome = self._refresh_row(target_row, source=source)
        self._last_refresh_at[target_row.symbol] = now
        return outcome

    def refresh_enabled(self, *, source: str) -> list[RefreshOutcome]:
        outcomes: list[RefreshOutcome] = []
        for symbol in self.watchlist_repository.list_enabled_symbols():
            outcome = self.refresh_symbol(symbol, source=source)
            if outcome is not None:
                outcomes.append(outcome)
        return outcomes

    def _refresh_row(self, row: WatchlistRow, *, source: str) -> RefreshOutcome:
        snapshot_result = self.market_service.get_latest_snapshot(row.symbol)
        previous_recommendation = row.latest_recommendation

        if snapshot_result.data is None:
            outcome = RefreshOutcome(
                symbol=row.symbol,
                changed=False,
                recommendation=previous_recommendation,
                confidence=0.0,
                reason="实时行情暂时不可用，保留最近一次建议。",
                status="paused",
                status_label="等待开市",
                analysis_at=self._now_label(),
                alert_created=False,
                source=source,
            )
            self.watchlist_repository.record_analysis_run(
                row.symbol,
                status=source,
                stale=True,
                detail=outcome.reason,
            )
            return outcome

        bars_result = self.market_service.get_daily_bars(
            row.symbol,
            start_date=date.today() - date.resolution * 180,
            end_date=date.today(),
            limit=90,
        )
        if not bars_result.data:
            reason = "缺少足够K线数据，建议继续观察。"
            outcome = RefreshOutcome(
                symbol=row.symbol,
                changed=False,
                recommendation="watch",
                confidence=0.35,
                reason=reason,
                status="active",
                status_label="监控中",
                analysis_at=self._now_label(),
                alert_created=False,
                source=source,
            )
            self._persist_row_refresh(row, outcome, previous_recommendation, source)
            return outcome

        analysis_result = self.technical_service.analyze_bars(bars_result.data)
        sentiment_result = self.sentiment_service.ingest()
        company_matches = []
        sentiment_items = []
        for item in sentiment_result.items:
            matches = self.entity_mapping_service.map_sentiment_item(item, min_confidence=0.18, max_matches=3)
            for match in matches:
                if match.company.symbol == row.symbol:
                    sentiment_items.append(item)
                    company_matches.append(match)
                    break

        bundle = self.recommendation_engine.build_recommendation_bundle(
            symbol=row.symbol,
            technical_signals=list(analysis_result.signals),
            sentiment_items=sentiment_items,
            company_matches=company_matches,
            evaluation_at=snapshot_result.data.captured_at,
        )
        recommendation = bundle.recommendation.action.value
        confidence = bundle.recommendation.confidence
        reason = bundle.recommendation.summary

        if confidence < self.NO_TRADE_CONFIDENCE_FLOOR:
            recommendation = "avoid"
            reason = f"信号质量不足，不执行交易：{reason}"
        elif confidence < self.LOW_CONFIDENCE_FLOOR:
            recommendation = "watch" if recommendation != "sell" else "avoid"
            reason = f"信号质量不足，降级处理：{reason}"

        outcome = RefreshOutcome(
            symbol=row.symbol,
            changed=recommendation != previous_recommendation,
            recommendation=recommendation,
            confidence=confidence,
            reason=reason,
            status="active",
            status_label="监控中",
            analysis_at=self._now_label(),
            alert_created=False,
            source=source,
        )
        self._persist_row_refresh(row, outcome, previous_recommendation, source)
        return outcome

    def _persist_row_refresh(
        self,
        row: WatchlistRow,
        outcome: RefreshOutcome,
        previous_recommendation: str,
        source: str,
    ) -> None:
        self.watchlist_repository.record_refresh(
            row.symbol,
            latest_recommendation=outcome.recommendation,
            latest_confidence=outcome.confidence,
            latest_reason=outcome.reason,
            status=outcome.status,
            status_label=outcome.status_label,
            last_analysis_at=outcome.analysis_at,
        )
        self.watchlist_repository.record_analysis_run(
            row.symbol,
            status=source,
            stale=False,
            detail=outcome.reason,
        )
        if outcome.recommendation != previous_recommendation:
            self.recommendation_event_repository.create_event(
                symbol=row.symbol,
                previous_action=previous_recommendation,
                current_action=outcome.recommendation,
                confidence=outcome.confidence,
                summary=outcome.reason,
            )
            self.alert_repository.create_alert(
                symbol=row.symbol,
                title=f"{row.name}建议从 {previous_recommendation.upper()} 调整为 {outcome.recommendation.upper()}",
                summary=outcome.reason,
                level="high" if outcome.recommendation in {"buy", "sell"} else "medium",
            )

    def _now_label(self) -> str:
        timezone = ZoneInfo(self.settings.market_timezone)
        return datetime.now(timezone).strftime("%H:%M")
