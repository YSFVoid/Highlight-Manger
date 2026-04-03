from __future__ import annotations

from datetime import datetime
from typing import Any

from enum import Enum as PyEnum

from sqlalchemy import Enum, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.sqltypes import DateTime

from highlight_manager.modules.common.time import utcnow


def enum_column(enum_type: type[PyEnum], *, nullable: bool = False, default: Any | None = None):
    kwargs: dict[str, Any] = {
        "native_enum": False,
        "validate_strings": True,
        "values_callable": lambda enum_cls: [member.value for member in enum_cls],
    }
    if default is not None:
        return mapped_column(Enum(enum_type, **kwargs), nullable=nullable, default=default)
    return mapped_column(Enum(enum_type, **kwargs), nullable=nullable)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        onupdate=utcnow,
    )
