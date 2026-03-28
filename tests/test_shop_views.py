from __future__ import annotations

import pytest

from highlight_manager.interactions.shop_views import ShopPurchaseModal
from highlight_manager.models.enums import ShopSection


class FakeMember:
    def __init__(self, user_id: int) -> None:
        self.id = user_id
        self.mention = f"<@{user_id}>"


class FakeTicketChannel:
    def __init__(self, channel_id: int) -> None:
        self.id = channel_id
        self.mention = f"<#{channel_id}>"


class FakeShopService:
    def __init__(self) -> None:
        self.resolve_calls = []
        self.ticket_calls = []

    async def resolve_requested_item(self, guild_id, section, requested_text):
        self.resolve_calls.append((guild_id, section, requested_text))
        return None

    async def create_purchase_ticket(self, guild, buyer, *, section, item, requested_text, details, remaining_balance=None):
        self.ticket_calls.append((guild.id, buyer.id, section, requested_text, details, remaining_balance))
        return FakeTicketChannel(99)


class FakeResponse:
    def __init__(self) -> None:
        self.deferred = False

    async def defer(self, *, ephemeral: bool, thinking: bool) -> None:
        self.deferred = ephemeral and thinking

    async def send_message(self, content: str, *, ephemeral: bool) -> None:
        self.sent_message = (content, ephemeral)


class FakeFollowup:
    def __init__(self) -> None:
        self.messages = []

    async def send(self, content: str, *, ephemeral: bool) -> None:
        self.messages.append((content, ephemeral))


class FakeGuild:
    def __init__(self, guild_id: int) -> None:
        self.id = guild_id


class FakeClient:
    def __init__(self, shop_service) -> None:
        self.shop_service = shop_service
        self.coins_service = None
        self.audit_service = None


class FakeInteraction:
    def __init__(self, shop_service) -> None:
        self.guild = FakeGuild(1)
        self.user = FakeMember(10)
        self.client = FakeClient(shop_service)
        self.response = FakeResponse()
        self.followup = FakeFollowup()


@pytest.mark.asyncio
async def test_shop_purchase_modal_defers_then_uses_followup_message() -> None:
    shop_service = FakeShopService()
    interaction = FakeInteraction(shop_service)
    modal = ShopPurchaseModal(ShopSection.DEVELOPE)
    modal.requested_item._value = "Discord Bot Source Code"
    modal.details._value = "Need a custom match bot."

    await modal.on_submit(interaction)  # type: ignore[arg-type]

    assert interaction.response.deferred is True
    assert shop_service.resolve_calls == [(1, ShopSection.DEVELOPE, "Discord Bot Source Code")]
    assert shop_service.ticket_calls == [
        (1, 10, ShopSection.DEVELOPE, "Discord Bot Source Code", "Need a custom match bot.", None)
    ]
    assert interaction.followup.messages == [
        ("Your private ticket is <#99>. Staff will continue there.", True)
    ]
