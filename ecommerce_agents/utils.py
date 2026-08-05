"""Small conversion helpers shared by agents and verifier."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, TypeVar

T = TypeVar("T")
CENT = Decimal("0.01")
TOLERANCE = Decimal("0.10")
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"


def decimal_value(value: str | int | float | Decimal | None) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    return Decimal(str(value))


def rounded_decimal(value: Decimal) -> Decimal:
    result = value.quantize(CENT, rounding=ROUND_HALF_UP)
    return Decimal("0.00") if result == 0 else result


def money(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return float(rounded_decimal(value))


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.strptime(value, TIMESTAMP_FORMAT)


def variance_hours(later: str | None, earlier: str | None) -> float | None:
    later_dt = parse_timestamp(later)
    earlier_dt = parse_timestamp(earlier)
    if later_dt is None or earlier_dt is None:
        return None
    hours = Decimal(str((later_dt - earlier_dt).total_seconds())) / Decimal("3600")
    return money(hours)


def stable_unique(values: Iterable[T]) -> list[T]:
    seen: set[T] = set()
    result: list[T] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
