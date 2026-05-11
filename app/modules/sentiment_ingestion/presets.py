from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Iterable

from app.modules.sentiment_ingestion.contracts import (
    RawSentimentPayload,
    SentimentSourceCategory,
    SentimentSourceDefinition,
    SentimentSourceMetadata,
)


_SAMPLE_FEED_BLUEPRINTS: dict[str, tuple[dict[str, Any], ...]] = {
    "eastmoney_fast_news": (
        {
            "source_item_id": "em-fast-001",
            "title": "工信部推进智能制造场景开放 机器人概念盘前关注度升温",
            "content": "工信部表示将推动智能制造示范工厂建设，机器人与工业软件产业链关注度提升。",
            "minutes_ago": 25,
            "url": "https://kuaixun.eastmoney.com/sample/em-fast-001",
            "sentiment_score": 0.62,
            "tags": ["policy", "robotics", "industrial-upgrade"],
        },
        {
            "source_item_id": "em-fast-002",
            "title": "北向资金尾盘回流银行与高股息方向",
            "content": "尾盘资金净流入银行、电力等高股息板块，市场避险偏好有所抬升。",
            "minutes_ago": 95,
            "url": "https://kuaixun.eastmoney.com/sample/em-fast-002",
            "sentiment_score": 0.21,
            "tags": ["capital-flow", "high-dividend"],
        },
        {
            "source_item_id": "em-fast-003",
            "title": "港口航运运价指数回升 集运链条景气度再受关注",
            "content": "最新运价指数回升带动港口航运板块讨论升温，但该消息已在日内早盘被市场部分消化。",
            "hours_ago": 10,
            "url": "https://kuaixun.eastmoney.com/sample/em-fast-003",
            "sentiment_score": 0.18,
            "tags": ["shipping", "cyclical"],
        },
    ),
    "yicai_market_news": (
        {
            "source_item_id": "yc-news-101",
            "title": "工信部推进智能制造场景开放 机器人概念盘前关注度升温",
            "content": "工信部表示将推动智能制造示范工厂建设，机器人与工业软件产业链关注度提升。",
            "minutes_ago": 24,
            "url": "https://www.yicai.com/sample/yc-news-101",
            "sentiment_score": 0.58,
            "tags": ["policy", "robotics"],
        },
        {
            "source_item_id": "yc-news-102",
            "title": "光伏玻璃报价继续走弱 组件企业下修排产预期",
            "content": "行业报价延续回落，组件企业下修短期排产，产业链情绪偏谨慎。",
            "hours_ago": 2,
            "url": "https://www.yicai.com/sample/yc-news-102",
            "sentiment_score": -0.54,
            "tags": ["solar", "supply-chain"],
        },
        {
            "source_item_id": "yc-news-103",
            "title": "央行开展逆回购操作 短端流动性维持合理充裕",
            "content": "公开市场操作延续平稳，短端利率预期保持稳定，利好高杠杆板块估值修复。",
            "hours_ago": 13,
            "url": "https://www.yicai.com/sample/yc-news-103",
            "sentiment_score": 0.16,
            "tags": ["macro", "liquidity"],
        },
    ),
}


def build_default_sample_sources() -> list[SentimentSourceDefinition]:
    return [
        SentimentSourceDefinition(
            metadata=SentimentSourceMetadata(
                source_id="eastmoney-stock-news-live",
                source_name="Eastmoney Stock News Live",
                category=SentimentSourceCategory.FINANCE_NEWS,
                base_url="https://so.eastmoney.com/news/",
                tags=["akshare", "eastmoney", "live-news"],
                notes="Live A-share stock news feed via AkShare stock_news_em.",
            ),
            adapter_name="akshare_stock_news_em",
            max_item_age=timedelta(hours=24),
            default_item_tags=["a-share", "news", "live"],
            parameters={
                "symbols": ["600519", "300750", "688981", "300059"],
                "max_items_per_symbol": 4,
            },
        ),
        SentimentSourceDefinition(
            metadata=SentimentSourceMetadata(
                source_id="eastmoney-fast-news-sample",
                source_name="Eastmoney Fast News Sample",
                category=SentimentSourceCategory.FAST_NEWS,
                base_url="https://kuaixun.eastmoney.com/",
                tags=["sample", "eastmoney", "fast-news"],
                notes="Sample payloads for local development and contract verification.",
            ),
            adapter_name="sample",
            max_item_age=timedelta(hours=6),
            default_item_tags=["a-share", "intraday"],
            parameters={"sample_feed": "eastmoney_fast_news"},
        ),
        SentimentSourceDefinition(
            metadata=SentimentSourceMetadata(
                source_id="yicai-market-news-sample",
                source_name="Yicai Market News Sample",
                category=SentimentSourceCategory.FINANCE_NEWS,
                base_url="https://www.yicai.com/",
                tags=["sample", "yicai", "news"],
                notes="Sample payloads for local development and contract verification.",
            ),
            adapter_name="sample",
            max_item_age=timedelta(hours=24),
            default_item_tags=["a-share", "news"],
            parameters={"sample_feed": "yicai_market_news"},
        ),
    ]


def build_static_source_definition(
    *,
    source_id: str,
    source_name: str,
    items: Iterable[RawSentimentPayload | dict[str, Any]],
    category: SentimentSourceCategory = SentimentSourceCategory.FINANCE_NEWS,
    base_url: str | None = None,
    max_item_age: timedelta | None = None,
    default_item_tags: list[str] | None = None,
    source_tags: list[str] | None = None,
    notes: str | None = None,
    enabled: bool = True,
) -> SentimentSourceDefinition:
    return SentimentSourceDefinition(
        metadata=SentimentSourceMetadata(
            source_id=source_id,
            source_name=source_name,
            category=category,
            base_url=base_url,
            tags=list(source_tags or []),
            notes=notes,
        ),
        adapter_name="static",
        enabled=enabled,
        max_item_age=max_item_age,
        default_item_tags=list(default_item_tags or []),
        parameters={"items": list(items)},
    )


def get_sample_feed_items(
    feed_name: str,
    *,
    now: datetime,
) -> list[RawSentimentPayload]:
    blueprints = _SAMPLE_FEED_BLUEPRINTS.get(feed_name, ())
    return [_build_sample_payload(blueprint=blueprint, now=now) for blueprint in blueprints]


def _build_sample_payload(
    *,
    blueprint: dict[str, Any],
    now: datetime,
) -> RawSentimentPayload:
    published_at = now - timedelta(
        minutes=blueprint.get("minutes_ago", 0),
        hours=blueprint.get("hours_ago", 0),
        days=blueprint.get("days_ago", 0),
    )
    return RawSentimentPayload(
        title=str(blueprint["title"]),
        content=str(blueprint["content"]),
        published_at=published_at,
        url=str(blueprint["url"]) if blueprint.get("url") else None,
        sentiment_score=(
            float(blueprint["sentiment_score"])
            if blueprint.get("sentiment_score") is not None
            else None
        ),
        tags=[str(tag) for tag in blueprint.get("tags", ())],
        source_item_id=(
            str(blueprint["source_item_id"])
            if blueprint.get("source_item_id")
            else None
        ),
        raw_payload=dict(blueprint),
    )
