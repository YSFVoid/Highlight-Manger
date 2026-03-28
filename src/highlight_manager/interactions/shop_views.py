from __future__ import annotations

import discord

from highlight_manager.models.enums import AuditAction, ShopSection
from highlight_manager.utils.exceptions import HighlightError
from highlight_manager.utils.response_helpers import send_interaction_response


class ShopOrderView(discord.ui.View):
    def __init__(self, *, section: ShopSection, label: str = "Buy here") -> None:
        super().__init__(timeout=None)
        self.section = section
        self.order_button.custom_id = f"shop:buy:{section.value}"
        self.order_button.label = label

    @discord.ui.button(label="Buy here", style=discord.ButtonStyle.success, custom_id="placeholder")
    async def order_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.guild is None:
            return await send_interaction_response(interaction, "This only works inside the server.", error=True, ephemeral=True)
        shop_service = getattr(interaction.client, "shop_service", None)
        if shop_service is None:
            return await send_interaction_response(interaction, "Shop service is not available right now.", error=True, ephemeral=True)
        await interaction.response.send_modal(ShopPurchaseModal(self.section))


class ShopPurchaseModal(discord.ui.Modal):
    def __init__(self, section: ShopSection) -> None:
        super().__init__(title=f"{section.label} Purchase")
        self.section = section
        self.requested_item = discord.ui.TextInput(
            label="What do you want to buy?",
            placeholder=_section_requested_placeholder(section),
            max_length=150,
        )
        prompt = _section_detail_prompt(section)
        self.details = discord.ui.TextInput(
            label=prompt["label"],
            placeholder=prompt["placeholder"],
            style=discord.TextStyle.paragraph,
            max_length=500,
        )
        self.add_item(self.requested_item)
        self.add_item(self.details)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await send_interaction_response(interaction, "This only works inside the server.", error=True, ephemeral=True)
        shop_service = getattr(interaction.client, "shop_service", None)
        if shop_service is None:
            return await send_interaction_response(interaction, "Shop service is not available right now.", error=True, ephemeral=True)
        try:
            await interaction.response.defer(ephemeral=True, thinking=True)
        except discord.NotFound:
            return
        matched_item = await shop_service.resolve_requested_item(
            interaction.guild.id,
            self.section,
            str(self.requested_item),
        )

        balance_text: str | None = None
        coins_service = getattr(interaction.client, "coins_service", None)
        audit_service = getattr(interaction.client, "audit_service", None)
        if matched_item is not None and matched_item.coin_price is not None:
            if coins_service is None:
                return await send_interaction_response(interaction, "Coins service is not available right now.", error=True, ephemeral=True)
            try:
                purchase = await coins_service.purchase_shop_item(interaction.guild, interaction.user.id, matched_item)
            except HighlightError as exc:
                return await send_interaction_response(interaction, str(exc), error=True, ephemeral=True)
            balance_text = str(purchase.new_balance)
        try:
            ticket_channel = await shop_service.create_purchase_ticket(
                interaction.guild,
                interaction.user,
                section=self.section,
                item=matched_item,
                requested_text=str(self.requested_item),
                details=str(self.details),
                remaining_balance=balance_text,
            )
        except HighlightError as exc:
            if matched_item is not None and matched_item.coin_price is not None and coins_service is not None:
                await coins_service.adjust_balance(interaction.guild, interaction.user.id, matched_item.coin_price)
            return await send_interaction_response(interaction, str(exc), error=True, ephemeral=True)
        except discord.HTTPException:
            if matched_item is not None and matched_item.coin_price is not None and coins_service is not None:
                await coins_service.adjust_balance(interaction.guild, interaction.user.id, matched_item.coin_price)
            return await send_interaction_response(
                interaction,
                "I could not open a private shop ticket right now. Your coins were not kept.",
                ephemeral=True,
                error=True,
            )
        if matched_item is not None and matched_item.coin_price is not None and audit_service is not None:
            await audit_service.log(
                interaction.guild,
                AuditAction.COINS_UPDATED,
                f"{interaction.user.mention} bought shop item #{matched_item.item_id} ({matched_item.title}) for {matched_item.coin_price} coins.",
                actor_id=interaction.user.id,
                target_id=interaction.user.id,
                metadata={
                    "item_id": matched_item.item_id,
                    "section": self.section.value,
                    "title": matched_item.title,
                    "coin_price": matched_item.coin_price,
                    "source": "shop_button",
                },
            )
        if matched_item is not None and matched_item.coin_price is not None:
            return await send_interaction_response(
                interaction,
                f"Bought **{matched_item.title}** for **{matched_item.coin_price}** coins. "
                f"Your private ticket is {ticket_channel.mention}. Remaining balance: **{balance_text}**.",
                ephemeral=True,
            )
        await send_interaction_response(
            interaction,
            f"Your private ticket is {ticket_channel.mention}. Staff will continue there.",
            ephemeral=True,
        )


def build_order_view(
    guild_id: int,
    order_channel_id: int | None,
    *,
    section: ShopSection,
    label: str = "Buy here",
) -> discord.ui.View | None:
    return ShopOrderView(section=section, label=label)


def _section_detail_prompt(section: ShopSection) -> dict[str, str]:
    prompts = {
        ShopSection.DEVELOPE: {
            "label": "Project Requirements",
            "placeholder": "Tell us what bot, source code, or website you want.",
        },
        ShopSection.OPTIMIZE_TOOL: {
            "label": "Windows / PC Notes",
            "placeholder": "Tell us your Windows version, PC details, and what optimization you want.",
        },
        ShopSection.VIDEO_EDIT: {
            "label": "Video / Edit Notes",
            "placeholder": "Tell us the video type, length, style, and what edit you want.",
        },
        ShopSection.SENSI_PC: {
            "label": "DPI / Emulator / X-Y Details",
            "placeholder": "Tell us your DPI, emulator version, X/Y preferences, and current setup.",
        },
        ShopSection.SENSI_IPHONE: {
            "label": "Device / Sensitivity Notes",
            "placeholder": "Tell us your iPhone model and the sensitivity style you want.",
        },
        ShopSection.SENSI_ANDROID: {
            "label": "Device / Sensitivity Notes",
            "placeholder": "Tell us your Android device and the sensitivity style you want.",
        },
    }
    return prompts[section]


def _section_requested_placeholder(section: ShopSection) -> str:
    examples = {
        ShopSection.DEVELOPE: "Discord bot source code, portfolio website, or custom bot system",
        ShopSection.OPTIMIZE_TOOL: "Windows optimization tool or aggressive performance setup",
        ShopSection.VIDEO_EDIT: "TikTok edit, 5 to 9 minute edit, or 10 to 30 minute edit",
        ShopSection.SENSI_PC: "PC sensitivity setup for Free Fire",
        ShopSection.SENSI_IPHONE: "iPhone sensitivity setup for Free Fire",
        ShopSection.SENSI_ANDROID: "Android sensitivity setup for Free Fire",
    }
    return examples[section]
