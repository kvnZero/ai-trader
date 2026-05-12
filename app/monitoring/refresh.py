from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from app.config import Settings
from app.domain import SentimentItem
from app.modules.entity_mapping import build_default_entity_mapping_service
from app.modules.market_data import build_default_market_data_service
from app.modules.recommendation_engine import build_default_recommendation_engine_service
from app.modules.sentiment_ingestion import build_default_sentiment_service
from app.modules.technical_analysis import build_default_technical_analysis_service
from app.persistence.alerts import AlertRepository
from app.persistence.issues import IssueLedgerRepository
from app.persistence.recommendation_events import RecommendationEventRepository
from app.persistence.recommendation_snapshots import RecommendationSnapshotRepository
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
    LOW_LIQUIDITY_TURNOVER_FLOOR = 5_000_000

    def __init__(
        self,
        *,
        settings: Settings,
        watchlist_repository: WatchlistRepository,
        alert_repository: AlertRepository,
        issue_repository: IssueLedgerRepository | None = None,
        recommendation_event_repository: RecommendationEventRepository,
        recommendation_snapshot_repository: RecommendationSnapshotRepository | None = None,
        sentiment_cache_reader: object | None = None,
    ):
        self.settings = settings
        self.watchlist_repository = watchlist_repository
        self.alert_repository = alert_repository
        self.issue_repository = issue_repository
        self.recommendation_event_repository = recommendation_event_repository
        self.recommendation_snapshot_repository = recommendation_snapshot_repository
        self.sentiment_cache_reader = sentiment_cache_reader
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
            self._record_issue(
                issue_type="market_data_unavailable",
                severity="high",
                symbol=row.symbol,
                message=outcome.reason,
                details={"source": source, "status": outcome.status},
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
            self._persist_row_refresh(
                row,
                outcome,
                previous_recommendation,
                source,
                market_regime=None,
                market_regime_label=None,
                confirmation_score=None,
                sentiment_count=0,
                company_match_count=0,
                turnover=snapshot_result.data.turnover,
            )
            self._record_issue(
                issue_type="insufficient_history",
                severity="medium",
                symbol=row.symbol,
                message=reason,
                details={"source": source, "status": outcome.status},
            )
            return outcome

        analysis_result = self.technical_service.analyze_bars(bars_result.data)
        available_sentiment_items = self._load_sentiment_items(row.symbol)
        company_matches = []
        sentiment_items: list[SentimentItem] = []
        for item in available_sentiment_items:
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
        confirmation_score = analysis_result.confirmation_score
        confidence = round(
            bundle.recommendation.confidence * (0.7 + 0.3 * confirmation_score),
            3,
        )
        reason = bundle.recommendation.summary

        if confirmation_score < 0.35:
            recommendation = "avoid" if recommendation == "sell" else "watch"
            reason = f"技术确认度不足，降级处理：{reason}"
        elif confidence < self.NO_TRADE_CONFIDENCE_FLOOR:
            recommendation = "avoid"
            reason = f"信号质量不足，不执行交易：{reason}"
        elif confidence < self.LOW_CONFIDENCE_FLOOR:
            recommendation = "watch" if recommendation != "sell" else "avoid"
            reason = f"信号质量不足，降级处理：{reason}"

        turnover = snapshot_result.data.turnover or 0.0
        if turnover < self.LOW_LIQUIDITY_TURNOVER_FLOOR and recommendation in {"buy", "sell"}:
            recommendation = "watch"
            reason = f"流动性偏弱，建议保守处理：{reason}"
            confidence = round(confidence * 0.85, 3)
            self._record_issue(
                issue_type="low_liquidity_downgrade",
                severity="medium",
                symbol=row.symbol,
                message=reason,
                details={
                    "source": source,
                    "turnover": turnover,
                    "recommendation": recommendation,
                },
            )

        if (
            recommendation == "avoid"
            or confidence < self.NO_TRADE_CONFIDENCE_FLOOR
            or "信号质量不足" in reason
            or "流动性偏弱" in reason
            or "技术确认度不足" in reason
        ):
            self._record_issue(
                issue_type="low_quality_signal",
                severity="low" if recommendation == "watch" else "medium",
                symbol=row.symbol,
                message=reason,
                details={
                    "source": source,
                    "recommendation": recommendation,
                    "confidence": confidence,
                    "market_regime": analysis_result.market_regime,
                    "market_regime_label": analysis_result.market_regime_label,
                },
            )

        mapping_average_confidence = (
            sum(match.confidence for match in company_matches) / len(company_matches)
            if company_matches
            else 0.0
        )
        if sentiment_items and not company_matches:
            self._record_issue(
                issue_type="entity_mapping_missing",
                severity="medium",
                symbol=row.symbol,
                message="sentiment evidence lacks supporting company mappings",
                details={
                    "source": source,
                    "sentiment_count": len(sentiment_items),
                },
            )
        elif company_matches and mapping_average_confidence < 0.45:
            self._record_issue(
                issue_type="entity_mapping_low_confidence",
                severity="medium",
                symbol=row.symbol,
                message="company mappings are low-confidence for sentiment attribution",
                details={
                    "source": source,
                    "mapping_average_confidence": round(mapping_average_confidence, 3),
                    "company_match_count": len(company_matches),
                },
            )

        if bundle.decision_trace.risk_flags:
            self._record_decision_risk_issues(
                row=row,
                source=source,
                risk_flags=list(bundle.decision_trace.risk_flags),
                decision_action=bundle.recommendation.action.value,
                decision_confidence=bundle.decision_trace.final_confidence,
            )

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
        self._persist_row_refresh(
            row,
            outcome,
            previous_recommendation,
            source,
            market_regime=analysis_result.market_regime,
            market_regime_label=analysis_result.market_regime_label,
            confirmation_score=analysis_result.confirmation_score,
            sentiment_count=len(sentiment_items),
            company_match_count=len(company_matches),
            turnover=snapshot_result.data.turnover,
        )
        return outcome

    def _persist_row_refresh(
        self,
        row: WatchlistRow,
        outcome: RefreshOutcome,
        previous_recommendation: str,
        source: str,
        *,
        market_regime: str | None,
        market_regime_label: str | None,
        confirmation_score: float | None,
        sentiment_count: int,
        company_match_count: int,
        turnover: float | None,
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
        if self.recommendation_snapshot_repository is not None:
            self.recommendation_snapshot_repository.create_snapshot(
                symbol=row.symbol,
                source=source,
                recommendation=outcome.recommendation,
                confidence=outcome.confidence,
                market_regime=market_regime,
                market_regime_label=market_regime_label,
                confirmation_score=confirmation_score,
                sentiment_count=sentiment_count,
                company_match_count=company_match_count,
                turnover=turnover,
                reason=outcome.reason,
                created_at=datetime.now(UTC).isoformat(timespec="minutes"),
            )
        if outcome.changed:
            self._record_issue(
                issue_type="recommendation_change",
                severity="high" if outcome.recommendation in {"buy", "sell"} else "medium",
                symbol=row.symbol,
                message=outcome.reason,
                details={
                    "source": source,
                    "previous_recommendation": previous_recommendation,
                    "current_recommendation": outcome.recommendation,
                    "confidence": outcome.confidence,
                },
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

    def _load_sentiment_items(self, symbol: str) -> list[SentimentItem]:
        cache_reader = self.sentiment_cache_reader
        if cache_reader is not None and hasattr(cache_reader, "read_latest"):
            try:
                snapshot = cache_reader.read_latest(symbols=[symbol])
            except TypeError:
                snapshot = cache_reader.read_latest()
            except Exception:
                snapshot = None
            if snapshot:
                cached_items = self._snapshot_items(snapshot)
                if cached_items:
                    return cached_items

        return self.sentiment_service.ingest().items

    def _snapshot_items(self, payload: object) -> list[SentimentItem]:
        if isinstance(payload, dict):
            items = payload.get("items")
            return list(items) if isinstance(items, list) else []
        return list(getattr(payload, "items", []) or [])

    def _record_issue(
        self,
        *,
        issue_type: str,
        severity: str,
        symbol: str | None,
        message: str,
        details: dict[str, object],
    ) -> None:
        if self.issue_repository is None:
            return

        self.issue_repository.create_issue(
            issue_type=issue_type,
            severity=severity,
            status="open",
            symbol=symbol,
            source="monitoring_refresh",
            origin_worker="monitoring_worker",
            message=message,
            details=details,
        )

    def _record_decision_risk_issues(
        self,
        *,
        row: WatchlistRow,
        source: str,
        risk_flags: list[str],
        decision_action: str,
        decision_confidence: float,
    ) -> None:
        for risk_flag in risk_flags[:6]:
            issue_type, severity = self._classify_risk_flag_issue(risk_flag, decision_action)
            self._record_issue(
                issue_type=issue_type,
                severity=severity,
                symbol=row.symbol,
                message=risk_flag,
                details={
                    "source": source,
                    "decision_action": decision_action,
                    "decision_confidence": decision_confidence,
                    "risk_flag": risk_flag,
                },
            )

    def _classify_risk_flag_issue(self, risk_flag: str, decision_action: str) -> tuple[str, str]:
        normalized = risk_flag.lower()
        if "technical signals" in normalized or "technical coverage" in normalized:
            return "technical_coverage_unavailable", "high"
        if "sentiment coverage is unavailable" in normalized:
            return "sentiment_coverage_unavailable", "medium"
        if (
            ("sentiment inputs" in normalized and "stale" in normalized)
            or "stale relative to the decision time" in normalized
        ):
            return "sentiment_data_stale", "medium"
        if "technical and sentiment" in normalized or "disagree" in normalized:
            return "signal_conflict", "high" if decision_action in {"buy", "sell"} else "medium"
        if "company mappings are low-confidence" in normalized:
            return "entity_mapping_low_confidence", "medium"
        if "sentiment evidence lacks supporting company mappings" in normalized:
            return "entity_mapping_missing", "medium"
        return "recommendation_risk_flag", "low" if decision_action == "watch" else "medium"

    def _now_label(self) -> str:
        timezone = ZoneInfo(self.settings.market_timezone)
        return datetime.now(timezone).strftime("%H:%M")
