from __future__ import annotations

from datetime import datetime

from pydantic import Field

from highlight_manager.models.base import AppModel
from highlight_manager.models.enums import ShopSection
from highlight_manager.utils.dates import utcnow


class ShopConfig(AppModel):
    guild_id: int
    category_channel_id: int | None = None
    order_channel_id: int | None = None
    ticket_category_id: int | None = None
    section_channel_ids: dict[str, int] = Field(default_factory=dict)
    section_showcase_message_ids: dict[str, int] = Field(default_factory=dict)
    section_featured_message_ids: dict[str, list[int]] = Field(default_factory=dict)
    section_image_urls: dict[str, str] = Field(default_factory=dict)
    section_descriptions: dict[str, str] = Field(default_factory=dict)
    next_item_id: int = 1
    next_ticket_number: int = 1


class ShopItem(AppModel):
    guild_id: int
    item_id: int
    section: ShopSection
    title: str
    description: str
    image_url: str | None = None
    metadata_text: str | None = None
    category_label: str | None = None
    cash_price_text: str | None = None
    coin_price: int | None = None
    active: bool = True
    display_order: int = 0
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
