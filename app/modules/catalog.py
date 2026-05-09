from __future__ import annotations

from app.config import Settings
from app.domain import ModuleCapability


def build_capability_catalog(settings: Settings) -> list[ModuleCapability]:
    return [
        ModuleCapability(
            slug="market-data",
            title="A-share Market Data",
            description="AKShare-backed market data and K-line query services.",
            owner_module="app.modules.market_data",
            enabled=True,
        ),
        ModuleCapability(
            slug="technical-analysis",
            title="Technical Analysis",
            description="Indicators, pattern recognition, and trend scoring for A-share bars.",
            owner_module="app.modules.technical_analysis",
            enabled=True,
        ),
        ModuleCapability(
            slug="sentiment-ingestion",
            title="Sentiment Ingestion",
            description="Collect finance news, fast-news items, and normalized sentiment signals.",
            owner_module="app.modules.sentiment_ingestion",
            enabled=settings.enable_sentiment_ingestion,
        ),
        ModuleCapability(
            slug="entity-mapping",
            title="Entity Mapping",
            description="Map sentiment and events to listed companies, sectors, and themes.",
            owner_module="app.modules.entity_mapping",
            enabled=True,
        ),
        ModuleCapability(
            slug="trader-agent",
            title="Trader Agent",
            description="LLM-backed trader reasoning over structured market and sentiment evidence.",
            owner_module="app.modules.trader_agent",
            enabled=settings.enable_trader_agent,
        ),
        ModuleCapability(
            slug="recommendation-engine",
            title="Recommendation Engine",
            description="Fuse deterministic and agent signals into explainable recommendations.",
            owner_module="app.modules.recommendation_engine",
            enabled=settings.enable_recommendation_engine,
        ),
    ]
