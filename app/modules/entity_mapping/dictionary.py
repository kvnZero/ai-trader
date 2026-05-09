from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from app.domain import CompanyReference
from app.modules.entity_mapping.normalization import normalize_lookup_key


@dataclass(frozen=True, slots=True)
class CompanyDictionaryEntry:
    company: CompanyReference
    aliases: tuple[str, ...] = ()
    industry_keywords: tuple[str, ...] = ()
    theme_keywords: tuple[str, ...] = ()
    symbol_keywords: tuple[str, ...] = ()


class CompanyDictionary:
    """Static company dictionary with keyword overlap accounting."""

    def __init__(self, entries: Iterable[CompanyDictionaryEntry]):
        self.entries = tuple(entries)
        self._keyword_counts = {
            "symbol": Counter(),
            "company_name": Counter(),
            "alias": Counter(),
            "industry": Counter(),
            "theme": Counter(),
        }

        for entry in self.entries:
            for category, keywords in self.iter_keywords(entry).items():
                seen_keys: set[str] = set()
                for keyword in keywords:
                    lookup_key = normalize_lookup_key(keyword)
                    if not lookup_key or lookup_key in seen_keys:
                        continue
                    self._keyword_counts[category][lookup_key] += 1
                    seen_keys.add(lookup_key)

    def iter_keywords(self, entry: CompanyDictionaryEntry) -> dict[str, tuple[str, ...]]:
        return {
            "symbol": entry.symbol_keywords,
            "company_name": (entry.company.company_name,),
            "alias": entry.aliases,
            "industry": entry.industry_keywords,
            "theme": entry.theme_keywords,
        }

    def shared_count(self, category: str, keyword: str) -> int:
        lookup_key = normalize_lookup_key(keyword)
        if not lookup_key:
            return 0
        return self._keyword_counts[category][lookup_key]


def build_default_company_dictionary() -> CompanyDictionary:
    """Build a first-pass A-share company dictionary for deterministic mapping."""

    entries = (
        _entry(
            symbol="600519",
            company_name="贵州茅台",
            exchange="SSE",
            industry="白酒",
            aliases=("茅台", "飞天茅台"),
            themes=("高端消费", "消费升级"),
            theme_keywords=("白酒龙头", "高端白酒"),
        ),
        _entry(
            symbol="000858",
            company_name="五粮液",
            exchange="SZSE",
            industry="白酒",
            aliases=("五粮液酒",),
            themes=("次高端消费", "消费升级"),
            theme_keywords=("浓香白酒",),
        ),
        _entry(
            symbol="300750",
            company_name="宁德时代",
            exchange="SZSE",
            industry="动力电池",
            aliases=("宁王", "CATL"),
            themes=("新能源汽车", "储能", "锂电池", "固态电池"),
            theme_keywords=("电池龙头", "动力电池龙头"),
        ),
        _entry(
            symbol="002594",
            company_name="比亚迪",
            exchange="SZSE",
            industry="新能源汽车",
            aliases=("BYD",),
            themes=("动力电池", "智能驾驶", "汽车出海"),
            theme_keywords=("刀片电池", "整车制造"),
        ),
        _entry(
            symbol="601012",
            company_name="隆基绿能",
            exchange="SSE",
            industry="光伏设备",
            aliases=("隆基", "隆基股份"),
            themes=("光伏", "BC电池", "硅片"),
            theme_keywords=("光伏龙头", "N型电池"),
        ),
        _entry(
            symbol="300274",
            company_name="阳光电源",
            exchange="SZSE",
            industry="电力设备",
            aliases=("阳光储能",),
            themes=("光伏", "储能", "逆变器"),
            theme_keywords=("储能系统", "逆变器龙头"),
        ),
        _entry(
            symbol="600438",
            company_name="通威股份",
            exchange="SSE",
            industry="光伏材料",
            aliases=("通威",),
            themes=("光伏", "硅料", "电池片"),
            theme_keywords=("高纯硅", "一体化组件"),
        ),
        _entry(
            symbol="688981",
            company_name="中芯国际",
            exchange="SSE",
            industry="半导体",
            aliases=("中芯", "SMIC"),
            themes=("芯片", "晶圆代工", "国产替代"),
            theme_keywords=("先进制程", "晶圆厂"),
        ),
        _entry(
            symbol="002371",
            company_name="北方华创",
            exchange="SZSE",
            industry="半导体设备",
            aliases=("华创设备",),
            themes=("芯片", "半导体设备", "国产替代"),
            theme_keywords=("刻蚀设备", "薄膜沉积"),
        ),
        _entry(
            symbol="688256",
            company_name="寒武纪",
            exchange="SSE",
            industry="AI芯片",
            aliases=("寒武纪科技",),
            themes=("人工智能", "AI芯片", "算力", "大模型"),
            theme_keywords=("推理芯片", "训练芯片"),
        ),
        _entry(
            symbol="603986",
            company_name="兆易创新",
            exchange="SSE",
            industry="集成电路",
            aliases=("兆易",),
            themes=("存储芯片", "MCU", "国产替代"),
            theme_keywords=("NOR Flash", "控制芯片"),
        ),
        _entry(
            symbol="000725",
            company_name="京东方A",
            exchange="SZSE",
            industry="面板显示",
            aliases=("京东方",),
            themes=("面板", "柔性屏", "OLED"),
            theme_keywords=("显示面板", "折叠屏"),
        ),
        _entry(
            symbol="000100",
            company_name="TCL科技",
            exchange="SZSE",
            industry="面板显示",
            aliases=("TCL",),
            themes=("面板", "半导体显示", "光电显示"),
            theme_keywords=("大尺寸面板",),
        ),
        _entry(
            symbol="601138",
            company_name="工业富联",
            exchange="SSE",
            industry="电子制造",
            aliases=("富联", "富士康工业互联网"),
            themes=("AI服务器", "苹果产业链", "服务器", "算力"),
            theme_keywords=("服务器代工", "工业互联网"),
        ),
        _entry(
            symbol="002475",
            company_name="立讯精密",
            exchange="SZSE",
            industry="消费电子",
            aliases=("立讯",),
            themes=("苹果产业链", "消费电子", "AI眼镜"),
            theme_keywords=("精密制造", "声学模组"),
        ),
        _entry(
            symbol="002241",
            company_name="歌尔股份",
            exchange="SZSE",
            industry="消费电子",
            aliases=("歌尔",),
            themes=("VR", "AR", "苹果产业链", "声学"),
            theme_keywords=("智能穿戴", "声学器件"),
        ),
        _entry(
            symbol="002230",
            company_name="科大讯飞",
            exchange="SZSE",
            industry="软件服务",
            aliases=("讯飞",),
            themes=("人工智能", "大模型", "教育信息化"),
            theme_keywords=("语音识别", "办公大模型"),
        ),
        _entry(
            symbol="300308",
            company_name="中际旭创",
            exchange="SZSE",
            industry="光模块",
            aliases=("旭创",),
            themes=("CPO", "光模块", "AI算力", "数据中心"),
            theme_keywords=("800G光模块", "高速互联"),
        ),
        _entry(
            symbol="603019",
            company_name="中科曙光",
            exchange="SSE",
            industry="服务器",
            aliases=("曙光",),
            themes=("算力", "信创", "服务器", "液冷"),
            theme_keywords=("国产服务器", "高性能计算"),
        ),
        _entry(
            symbol="300059",
            company_name="东方财富",
            exchange="SZSE",
            industry="互联网金融",
            aliases=("东财",),
            themes=("券商", "金融科技", "互联网金融"),
            theme_keywords=("证券交易", "基金代销"),
        ),
        _entry(
            symbol="600030",
            company_name="中信证券",
            exchange="SSE",
            industry="证券",
            aliases=("中信券商",),
            themes=("券商", "资本市场", "投行业务"),
            theme_keywords=("龙头券商", "并购重组"),
        ),
        _entry(
            symbol="601318",
            company_name="中国平安",
            exchange="SSE",
            industry="保险",
            aliases=("平安保险",),
            themes=("保险", "金融", "红利资产"),
            theme_keywords=("寿险", "财险"),
        ),
        _entry(
            symbol="600036",
            company_name="招商银行",
            exchange="SSE",
            industry="银行",
            aliases=("招行",),
            themes=("银行", "财富管理", "高股息"),
            theme_keywords=("零售银行", "股份制银行"),
        ),
        _entry(
            symbol="601888",
            company_name="中国中免",
            exchange="SSE",
            industry="旅游零售",
            aliases=("中免",),
            themes=("免税", "旅游消费", "离岛免税"),
            theme_keywords=("机场免税", "旅游复苏"),
        ),
        _entry(
            symbol="300760",
            company_name="迈瑞医疗",
            exchange="SZSE",
            industry="医疗器械",
            aliases=("迈瑞",),
            themes=("医疗器械", "高端医疗", "出海医疗"),
            theme_keywords=("体外诊断", "监护设备"),
        ),
        _entry(
            symbol="600276",
            company_name="恒瑞医药",
            exchange="SSE",
            industry="创新药",
            aliases=("恒瑞",),
            themes=("创新药", "集采", "肿瘤药"),
            theme_keywords=("PD-1", "仿创结合"),
        ),
        _entry(
            symbol="603259",
            company_name="药明康德",
            exchange="SSE",
            industry="CXO",
            aliases=("药明", "WuXi AppTec"),
            themes=("CXO", "医药外包", "创新药"),
            theme_keywords=("研发外包", "医药服务"),
        ),
        _entry(
            symbol="002714",
            company_name="牧原股份",
            exchange="SZSE",
            industry="生猪养殖",
            aliases=("牧原",),
            themes=("猪周期", "养殖", "饲料成本"),
            theme_keywords=("仔猪", "生猪价格"),
        ),
        _entry(
            symbol="000333",
            company_name="美的集团",
            exchange="SZSE",
            industry="家电",
            aliases=("美的",),
            themes=("白电", "家电", "机器人"),
            theme_keywords=("智能家居", "工业机器人"),
        ),
        _entry(
            symbol="002415",
            company_name="海康威视",
            exchange="SZSE",
            industry="安防设备",
            aliases=("海康",),
            themes=("安防", "AI视觉", "机器视觉"),
            theme_keywords=("视频监控", "边缘感知"),
        ),
    )
    return CompanyDictionary(entries=entries)


def _entry(
    *,
    symbol: str,
    company_name: str,
    exchange: str,
    industry: str,
    aliases: tuple[str, ...] = (),
    themes: tuple[str, ...] = (),
    industry_keywords: tuple[str, ...] = (),
    theme_keywords: tuple[str, ...] = (),
) -> CompanyDictionaryEntry:
    cleaned_themes = _unique_strings(themes)
    return CompanyDictionaryEntry(
        company=CompanyReference(
            symbol=symbol,
            company_name=company_name,
            exchange=exchange,
            industry=industry,
            themes=list(cleaned_themes),
        ),
        aliases=_unique_strings(aliases),
        industry_keywords=_unique_strings((industry, *industry_keywords)),
        theme_keywords=_unique_strings((*cleaned_themes, *theme_keywords)),
        symbol_keywords=_build_symbol_keywords(symbol=symbol, exchange=exchange),
    )


def _build_symbol_keywords(symbol: str, exchange: str) -> tuple[str, ...]:
    exchange_prefix = "sh" if exchange.upper() == "SSE" else "sz"
    return _unique_strings((symbol, f"{exchange_prefix}{symbol}"))


def _unique_strings(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    unique_values: list[str] = []
    for value in values:
        cleaned = value.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        unique_values.append(cleaned)
    return tuple(unique_values)
