from __future__ import annotations

from datetime import UTC, datetime, timedelta


def utcnow() -> datetime:
    return datetime.now(tz=UTC)


def seconds_from_now(seconds: int) -> datetime:
    return utcnow() + timedelta(seconds=seconds)
