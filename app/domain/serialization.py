from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any


def to_json_ready(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if is_dataclass(value):
        return to_json_ready(asdict(value))
    if isinstance(value, dict):
        return {key: to_json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_json_ready(item) for item in value]
    return value
