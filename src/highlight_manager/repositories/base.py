from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Generic, TypeVar

from highlight_manager.models.base import AppModel

ModelT = TypeVar("ModelT", bound=AppModel)


class BaseRepository(Generic[ModelT]):
    def __init__(self, collection, model_type: type[ModelT]) -> None:
        self.collection = collection
        self.model_type = model_type

    def _normalize_datetimes(self, value):
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=UTC)
            return value.astimezone(UTC)
        if isinstance(value, dict):
            return {key: self._normalize_datetimes(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._normalize_datetimes(item) for item in value]
        return value

    def _to_model(self, document: dict | None) -> ModelT | None:
        if document is None:
            return None
        document.pop("_id", None)
        return self.model_type.model_validate(self._normalize_datetimes(document))

    def _to_models(self, documents: Iterable[dict]) -> list[ModelT]:
        return [model for document in documents if (model := self._to_model(document)) is not None]
