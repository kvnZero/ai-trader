from __future__ import annotations

from app.domain import CompanyReference

_FALLBACK_STOCK_SAMPLE = (
    {
        "symbol": "600519",
        "company_name": "贵州茅台",
        "exchange": "SSE",
        "industry": "白酒",
        "themes": ["高端消费"],
    },
    {
        "symbol": "000858",
        "company_name": "五粮液",
        "exchange": "SZSE",
        "industry": "白酒",
        "themes": ["消费升级"],
    },
    {
        "symbol": "300750",
        "company_name": "宁德时代",
        "exchange": "SZSE",
        "industry": "动力电池",
        "themes": ["新能源汽车", "储能"],
    },
    {
        "symbol": "601012",
        "company_name": "隆基绿能",
        "exchange": "SSE",
        "industry": "光伏设备",
        "themes": ["光伏"],
    },
    {
        "symbol": "688981",
        "company_name": "中芯国际",
        "exchange": "SSE",
        "industry": "半导体",
        "themes": ["芯片", "国产替代"],
    },
    {
        "symbol": "300059",
        "company_name": "东方财富",
        "exchange": "SZSE",
        "industry": "互联网金融",
        "themes": ["券商", "金融科技"],
    },
)


def get_fallback_stock_sample(*, limit: int) -> list[CompanyReference]:
    clamped_limit = max(0, limit)
    return [
        CompanyReference(
            symbol=record["symbol"],
            company_name=record["company_name"],
            exchange=record["exchange"],
            industry=record["industry"],
            themes=list(record["themes"]),
        )
        for record in _FALLBACK_STOCK_SAMPLE[:clamped_limit]
    ]
