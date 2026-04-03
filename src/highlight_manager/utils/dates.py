from __future__ import annotations

from datetime import UTC, datetime, timedelta


def utcnow() -> datetime:
    return datetime.now(UTC)


def minutes_from_now(minutes: int) -> datetime:
    return utcnow() + timedelta(minutes=minutes)


def seconds_from_now(seconds: int) -> datetime:
    return utcnow() + timedelta(seconds=seconds)


def parse_datetime_input(value: str) -> datetime:
    normalized = value.strip().replace("T", " ").replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def format_dt(value: datetime | None) -> str:
    if value is None:
        return "N/A"
    return f"<t:{int(value.timestamp())}:f>"


def format_relative(value: datetime | None) -> str:
    if value is None:
        return "N/A"
    return f"<t:{int(value.timestamp())}:R>"
