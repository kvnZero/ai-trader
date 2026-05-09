from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal

from app.domain import SentimentItem

FieldName = Literal["title", "content", "tags", "raw_reference"]

_NON_ALNUM_CJK_RE = re.compile(r"[^0-9a-z\u4e00-\u9fff]+")
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def normalize_text(value: str) -> str:
    """Lowercase text and replace separators with single spaces."""

    return _NON_ALNUM_CJK_RE.sub(" ", value.casefold()).strip()


def collapse_text(value: str) -> str:
    """Lowercase text and remove separators for substring matching."""

    return _NON_ALNUM_CJK_RE.sub("", value.casefold())


def is_token_keyword(value: str) -> bool:
    normalized = normalize_text(value)
    return bool(normalized) and " " not in normalized and normalized.isascii()


def normalize_lookup_key(value: str) -> str:
    if is_token_keyword(value):
        return normalize_text(value)
    return collapse_text(value)


@dataclass(frozen=True, slots=True)
class NormalizedTextField:
    name: FieldName
    raw: str
    normalized: str
    collapsed: str
    tokens: frozenset[str]

    @classmethod
    def from_raw(cls, name: FieldName, raw: str) -> NormalizedTextField:
        normalized = normalize_text(raw)
        collapsed = collapse_text(raw)
        tokens = frozenset(_TOKEN_RE.findall(normalized))
        return cls(
            name=name,
            raw=raw,
            normalized=normalized,
            collapsed=collapsed,
            tokens=tokens,
        )


@dataclass(frozen=True, slots=True)
class NormalizedSentimentItem:
    item: SentimentItem
    fields: tuple[NormalizedTextField, ...]

    @classmethod
    def from_item(cls, item: SentimentItem) -> NormalizedSentimentItem:
        raw_fields: tuple[tuple[FieldName, str], ...] = (
            ("title", item.title),
            ("content", item.content),
            ("tags", " ".join(item.tags)),
            ("raw_reference", item.raw_reference or ""),
        )
        fields = tuple(
            NormalizedTextField.from_raw(name=name, raw=raw)
            for name, raw in raw_fields
            if raw.strip()
        )
        return cls(item=item, fields=fields)

    def find_fields_for_keyword(self, keyword: str) -> tuple[FieldName, ...]:
        lookup_key = normalize_lookup_key(keyword)
        if not lookup_key:
            return ()

        matched_fields: list[FieldName] = []
        token_keyword = is_token_keyword(keyword)
        for field in self.fields:
            if token_keyword and lookup_key in field.tokens:
                matched_fields.append(field.name)
                continue
            if not token_keyword and lookup_key in field.collapsed:
                matched_fields.append(field.name)

        return tuple(matched_fields)
