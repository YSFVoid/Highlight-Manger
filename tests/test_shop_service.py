from __future__ import annotations

from dataclasses import dataclass, field

import pytest

import highlight_manager.services.shop_service as shop_service_module
from highlight_manager.models.enums import ShopSection
from highlight_manager.models.shop import ShopConfig, ShopItem
from highlight_manager.services.shop_service import ShopService


class FakeShopConfigRepository:
    def __init__(self) -> None:
        self.storage: dict[int, ShopConfig] = {}

    async def get(self, guild_id: int) -> ShopConfig | None:
        return self.storage.get(guild_id)

    async def upsert(self, config: ShopConfig) -> ShopConfig:
        self.storage[config.guild_id] = config
        return config


class FakeShopItemRepository:
    def __init__(self) -> None:
        self.storage: dict[tuple[int, int], ShopItem] = {}

    async def create(self, item: ShopItem) -> ShopItem:
        self.storage[(item.guild_id, item.item_id)] = item
        return item

    async def replace(self, item: ShopItem) -> ShopItem:
        self.storage[(item.guild_id, item.item_id)] = item
        return item

    async def get(self, guild_id: int, item_id: int) -> ShopItem | None:
        return self.storage.get((guild_id, item_id))

    async def get_latest_item(self, guild_id: int) -> ShopItem | None:
        items = [item for (stored_guild_id, _), item in self.storage.items() if stored_guild_id == guild_id]
        return max(items, key=lambda item: item.item_id, default=None)

    async def list_for_section(self, guild_id: int, section: str, *, active_only: bool = True) -> list[ShopItem]:
        items = [
            item
            for (stored_guild_id, _), item in self.storage.items()
            if stored_guild_id == guild_id and item.section.value == section and (item.active or not active_only)
        ]
        return sorted(items, key=lambda item: (item.display_order, item.item_id))

    async def list_coin_items(self, guild_id: int) -> list[ShopItem]:
        items = [
            item
            for (stored_guild_id, _), item in self.storage.items()
            if stored_guild_id == guild_id and item.active and item.coin_price is not None
        ]
        return sorted(items, key=lambda item: (item.section.value, item.display_order, item.item_id))


@dataclass
class FakeMessage:
    id: int
    content: str | None = None
    embed: object = None
    view: object = None
    edit_count: int = 0
    deleted: bool = False

    async def edit(self, *, content=None, embed=None, view=None) -> None:
        self.content = content
        self.embed = embed
        self.view = view
        self.edit_count += 1

    async def delete(self) -> None:
        self.deleted = True


@dataclass
class FakeCategoryChannel:
    id: int
    name: str


@dataclass
class FakeTextChannel:
    id: int
    name: str
    guild: "FakeGuild"
    category: FakeCategoryChannel | None = None
    messages: dict[int, FakeMessage] = field(default_factory=dict)

    @property
    def mention(self) -> str:
        return f"<#{self.id}>"

    def permissions_for(self, member) -> object:
        return type("Permissions", (), {"mention_everyone": self.guild.mention_everyone_allowed})()

    async def send(self, content=None, *, embed=None, view=None, allowed_mentions=None):
        message = FakeMessage(id=self.guild.next_message_id, content=content, embed=embed, view=view)
        self.guild.next_message_id += 1
        self.messages[message.id] = message
        return message

    async def fetch_message(self, message_id: int):
        return self.messages[message_id]


class FakeGuild:
    def __init__(self, *, mention_everyone_allowed: bool = True) -> None:
        self.id = 1
        self.channels: list[object] = []
        self.next_channel_id = 100
        self.next_message_id = 1000
        self.mention_everyone_allowed = mention_everyone_allowed
        self.me = object()

    def get_channel(self, channel_id: int | None):
        for channel in self.channels:
            if getattr(channel, "id", None) == channel_id:
                return channel
        return None

    async def create_category(self, name: str, reason: str | None = None) -> FakeCategoryChannel:
        category = FakeCategoryChannel(id=self.next_channel_id, name=name)
        self.next_channel_id += 1
        self.channels.append(category)
        return category

    async def create_text_channel(
        self,
        name: str,
        category: FakeCategoryChannel | None = None,
        reason: str | None = None,
        overwrites=None,
        topic: str | None = None,
    ) -> FakeTextChannel:
        channel = FakeTextChannel(id=self.next_channel_id, name=name, guild=self, category=category)
        self.next_channel_id += 1
        self.channels.append(channel)
        return channel


def active_messages(channel: FakeTextChannel) -> list[FakeMessage]:
    return [message for message in channel.messages.values() if not message.deleted]


@pytest.mark.asyncio
async def test_shop_setup_reuses_existing_resources_and_posts_refresh_in_place(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shop_service_module.discord, "TextChannel", FakeTextChannel)
    monkeypatch.setattr(shop_service_module.discord, "CategoryChannel", FakeCategoryChannel)

    config_repository = FakeShopConfigRepository()
    item_repository = FakeShopItemRepository()
    service = ShopService(config_repository, item_repository)
    guild = FakeGuild()

    first_setup = await service.setup(guild)  # type: ignore[arg-type]
    second_setup = await service.setup(guild)  # type: ignore[arg-type]

    assert len(first_setup.created_resources) == 8
    assert len(first_setup.published_sections) == 6
    assert not second_setup.created_resources
    assert len(second_setup.reused_resources) == 8
    assert len(second_setup.published_sections) == 6

    await service.set_section_image(guild.id, ShopSection.DEVELOPE, "https://example.com/hero.png")
    await service.set_section_description(guild.id, ShopSection.DEVELOPE, "Custom development showcase.")
    item = await service.create_item(
        guild.id,
        section=ShopSection.DEVELOPE,
        title="Premium Bot Source",
        description="Competitive bot source package.",
        image_url="https://example.com/item.png",
        metadata_text="March 2026",
        category_label="Development",
        cash_price_text="$50",
        coin_price=120,
    )

    result = await service.post_section(guild, ShopSection.DEVELOPE)  # type: ignore[arg-type]
    config = result.config
    first_showcase_id = config.section_showcase_message_ids[ShopSection.DEVELOPE.value]

    await service.edit_item(guild.id, item.item_id, description="Updated description.")
    result = await service.post_section(guild, ShopSection.DEVELOPE)  # type: ignore[arg-type]
    config = result.config
    channel = await service.get_section_channel(guild, ShopSection.DEVELOPE)  # type: ignore[arg-type]

    assert config.section_showcase_message_ids[ShopSection.DEVELOPE.value] == first_showcase_id
    assert config.section_featured_message_ids[ShopSection.DEVELOPE.value] == []
    assert channel is not None
    assert channel.messages[first_showcase_id].edit_count == 1
    assert len(active_messages(channel)) == 1
    assert [listed.item_id for listed in await service.list_coin_items(guild.id)] == [item.item_id]


@pytest.mark.asyncio
async def test_publish_section_update_sends_everyone_announcement(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shop_service_module.discord, "TextChannel", FakeTextChannel)
    monkeypatch.setattr(shop_service_module.discord, "CategoryChannel", FakeCategoryChannel)

    config_repository = FakeShopConfigRepository()
    item_repository = FakeShopItemRepository()
    service = ShopService(config_repository, item_repository)
    guild = FakeGuild()

    await service.setup(guild)  # type: ignore[arg-type]
    result = await service.publish_section_update(guild, ShopSection.DEVELOPE)  # type: ignore[arg-type]
    channel = await service.get_section_channel(guild, ShopSection.DEVELOPE)  # type: ignore[arg-type]

    assert result.announcement_warning is None
    assert channel is not None
    announcement = active_messages(channel)[0]
    assert announcement.content == "@everyone Develope shop updated."


@pytest.mark.asyncio
async def test_publish_section_update_warns_when_everyone_ping_not_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shop_service_module.discord, "TextChannel", FakeTextChannel)
    monkeypatch.setattr(shop_service_module.discord, "CategoryChannel", FakeCategoryChannel)

    config_repository = FakeShopConfigRepository()
    item_repository = FakeShopItemRepository()
    service = ShopService(config_repository, item_repository)
    guild = FakeGuild(mention_everyone_allowed=False)

    await service.setup(guild)  # type: ignore[arg-type]
    result = await service.publish_section_update(guild, ShopSection.DEVELOPE)  # type: ignore[arg-type]
    channel = await service.get_section_channel(guild, ShopSection.DEVELOPE)  # type: ignore[arg-type]

    assert result.announcement_warning is not None
    assert channel is not None
    assert len(active_messages(channel)) == 1
    assert active_messages(channel)[0].content is None


@pytest.mark.asyncio
async def test_shop_setup_auto_binds_existing_shop_channels(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shop_service_module.discord, "TextChannel", FakeTextChannel)
    monkeypatch.setattr(shop_service_module.discord, "CategoryChannel", FakeCategoryChannel)

    config_repository = FakeShopConfigRepository()
    item_repository = FakeShopItemRepository()
    service = ShopService(config_repository, item_repository)
    guild = FakeGuild()

    shop_category = FakeCategoryChannel(id=guild.next_channel_id, name="SHOP")
    guild.next_channel_id += 1
    guild.channels.append(shop_category)
    for channel_name in [
        "DEVELOPE",
        "OPTIMIZE-TOOL",
        "VIDEO-EDIT",
        "SENSI-PC",
        "SENSI-IPHONE",
        "SENSI-ANDROID",
    ]:
        guild.channels.append(FakeTextChannel(id=guild.next_channel_id, name=channel_name, guild=guild, category=shop_category))
        guild.next_channel_id += 1

    result = await service.setup(guild)  # type: ignore[arg-type]
    config = await service.get_or_create_config(guild.id)

    assert result.created_resources == ["Ticket Category: **Shop Tickets**"]
    assert len(result.reused_resources) == 7
    assert set(result.published_sections) == {section.label for section in ShopSection}
    assert set(config.section_channel_ids) == {section.value for section in ShopSection}
    for section in ShopSection:
        channel = await service.get_section_channel(guild, section)  # type: ignore[arg-type]
        assert channel is not None
        assert len(active_messages(channel)) == 1
