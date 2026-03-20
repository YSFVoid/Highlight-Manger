from __future__ import annotations

from datetime import UTC, datetime, timedelta


def utcnow() -> datetime:
    return datetime.now(UTC)


def minutes_from_now(minutes: int) -> datetime:
    return utcnow() + timedelta(minutes=minutes)


def seconds_from_now(seconds: int) -> datetime:
    return utcnow() + timedelta(seconds=seconds)


def format_dt(value: datetime | None) -> str:
    if value is None:
        return "N/A"
    return f"<t:{int(value.timestamp())}:f>"


def format_relative(value: datetime | None) -> str:
    if value is None:
        return "N/A"
    return f"<t:{int(value.timestamp())}:R>"
