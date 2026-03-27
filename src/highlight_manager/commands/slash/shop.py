from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands

from highlight_manager.models.enums import AuditAction, ShopSection
from highlight_manager.utils.exceptions import HighlightError

if TYPE_CHECKING:
    from highlight_manager.bot import HighlightBot


def register_shop_commands(bot: "HighlightBot") -> None:
    async def defer_ephemeral(interaction: discord.Interaction) -> None:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)

    async def send_ephemeral(interaction: discord.Interaction, message: str) -> None:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    async def publish_and_respond(
        interaction: discord.Interaction,
        section: ShopSection,
        *,
        success_message: str,
    ) -> None:
        await defer_ephemeral(interaction)
        result = await bot.shop_service.publish_section_update(interaction.guild, section)
        message = success_message
        if result.announcement_warning:
            message += f"\nWarning: {result.announcement_warning}"
        await send_ephemeral(interaction, message)

    async def ensure_staff(interaction: discord.Interaction) -> bool:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            if not interaction.response.is_done():
                await interaction.response.send_message("This command can only be used inside the server.", ephemeral=True)
            return False
        if not await bot.config_service.is_staff(interaction.user):
            if not interaction.response.is_done():
                await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
            return False
        return True

    shop = app_commands.Group(name="shop", description="Shop management")

    @shop.command(name="setup", description="Auto-configure shop channels and publish all sections")
    async def shop_setup(interaction: discord.Interaction) -> None:
        if not await ensure_staff(interaction):
            return
        await defer_ephemeral(interaction)
        result = await bot.shop_service.setup(interaction.guild)
        await bot.audit_service.log(
            interaction.guild,
            AuditAction.SHOP_UPDATED,
            "Shop setup completed.",
            actor_id=interaction.user.id,
            metadata={"created": result.created_resources, "reused": result.reused_resources},
        )
        await send_ephemeral(
            interaction,
            "Shop setup complete.\n"
            f"Created: {', '.join(result.created_resources) if result.created_resources else 'None'}\n"
            f"Reused: {', '.join(result.reused_resources) if result.reused_resources else 'None'}\n"
            f"Published: {', '.join(result.published_sections) if result.published_sections else 'None'}",
        )

    @shop.command(name="post", description="Post or refresh a shop section")
    async def shop_post(interaction: discord.Interaction, section: ShopSection) -> None:
        if not await ensure_staff(interaction):
            return
        await defer_ephemeral(interaction)
        result = await bot.shop_service.publish_section_update(interaction.guild, section)
        await bot.audit_service.log(
            interaction.guild,
            AuditAction.SHOP_UPDATED,
            f"Posted shop section {section.label}.",
            actor_id=interaction.user.id,
            metadata={"section": section.value},
        )
        message = f"Posted **{section.label}** showcase."
        if result.announcement_warning:
            message += f"\nWarning: {result.announcement_warning}"
        await send_ephemeral(interaction, message)

    @shop.command(name="refresh", description="Refresh an existing shop section post")
    async def shop_refresh(interaction: discord.Interaction, section: ShopSection) -> None:
        if not await ensure_staff(interaction):
            return
        await publish_and_respond(interaction, section, success_message=f"Refreshed **{section.label}** showcase.")

    @shop.command(name="set-channel", description="Bind an existing channel to a shop section")
    async def shop_set_channel(
        interaction: discord.Interaction,
        section: ShopSection,
        channel: discord.TextChannel,
    ) -> None:
        if not await ensure_staff(interaction):
            return
        await bot.shop_service.set_section_channel(interaction.guild.id, section, channel.id)
        await interaction.response.send_message(
            f"Bound **{section.label}** to {channel.mention}. Use `/shop post` to publish the showcase.",
            ephemeral=True,
        )

    @shop.command(name="set-order-channel", description="Bind the channel used for manual orders")
    async def shop_set_order_channel(
        interaction: discord.Interaction,
        channel: discord.TextChannel,
    ) -> None:
        if not await ensure_staff(interaction):
            return
        await bot.shop_service.set_order_channel(interaction.guild.id, channel.id)
        await interaction.response.send_message(
            f"Order channel set to {channel.mention}.",
            ephemeral=True,
        )

    @shop.command(name="set-ticket-category", description="Bind the category used for private shop tickets")
    async def shop_set_ticket_category(
        interaction: discord.Interaction,
        category: discord.CategoryChannel,
    ) -> None:
        if not await ensure_staff(interaction):
            return
        await bot.shop_service.set_ticket_category(interaction.guild.id, category.id)
        await interaction.response.send_message(
            f"Shop ticket category set to **{category.name}**.",
            ephemeral=True,
        )

    @shop.command(name="set-image", description="Set a hero image for a shop section")
    async def shop_set_image(
        interaction: discord.Interaction,
        section: ShopSection,
        image: discord.Attachment | None = None,
        image_url: str | None = None,
    ) -> None:
        if not await ensure_staff(interaction):
            return
        resolved_url = image.url if image else image_url
        if not resolved_url:
            return await interaction.response.send_message("Provide an attachment or image URL.", ephemeral=True)
        await bot.shop_service.set_section_image(interaction.guild.id, section, resolved_url)
        await publish_and_respond(interaction, section, success_message=f"Updated image for **{section.label}**.")

    @shop.command(name="set-description", description="Set the showcase description for a shop section")
    async def shop_set_description(
        interaction: discord.Interaction,
        section: ShopSection,
        description: str,
    ) -> None:
        if not await ensure_staff(interaction):
            return
        await bot.shop_service.set_section_description(interaction.guild.id, section, description)
        await publish_and_respond(interaction, section, success_message=f"Updated description for **{section.label}**.")

    @shop.command(name="item-add", description="Add a featured shop item")
    async def shop_item_add(
        interaction: discord.Interaction,
        section: ShopSection,
        title: str,
        description: str,
        category_label: str | None = None,
        cash_price_text: str | None = None,
        coin_price: int | None = None,
        metadata_text: str | None = None,
        image: discord.Attachment | None = None,
        image_url: str | None = None,
        display_order: int | None = None,
    ) -> None:
        if not await ensure_staff(interaction):
            return
        item = await bot.shop_service.create_item(
            interaction.guild.id,
            section=section,
            title=title,
            description=description,
            image_url=image.url if image else image_url,
            metadata_text=metadata_text,
            category_label=category_label,
            cash_price_text=cash_price_text,
            coin_price=coin_price,
            display_order=display_order,
        )
        await publish_and_respond(
            interaction,
            section,
            success_message=f"Created shop item #{item.item_id} in **{section.label}**.",
        )

    @shop.command(name="item-edit", description="Edit a featured shop item")
    async def shop_item_edit(
        interaction: discord.Interaction,
        item_id: int,
        title: str | None = None,
        description: str | None = None,
        category_label: str | None = None,
        cash_price_text: str | None = None,
        coin_price: int | None = None,
        metadata_text: str | None = None,
        image: discord.Attachment | None = None,
        image_url: str | None = None,
        display_order: int | None = None,
        active: bool | None = None,
    ) -> None:
        if not await ensure_staff(interaction):
            return
        item = await bot.shop_service.edit_item(
            interaction.guild.id,
            item_id,
            title=title,
            description=description,
            image_url=image.url if image else image_url,
            metadata_text=metadata_text,
            category_label=category_label,
            cash_price_text=cash_price_text,
            coin_price=coin_price,
            active=active,
            display_order=display_order,
        )
        await publish_and_respond(
            interaction,
            item.section,
            success_message=f"Updated shop item #{item.item_id}.",
        )

    @shop.command(name="item-archive", description="Archive a shop item")
    async def shop_item_archive(interaction: discord.Interaction, item_id: int) -> None:
        if not await ensure_staff(interaction):
            return
        item = await bot.shop_service.archive_item(interaction.guild.id, item_id)
        await publish_and_respond(
            interaction,
            item.section,
            success_message=f"Archived shop item #{item.item_id}.",
        )

    bot.tree.add_command(shop)
