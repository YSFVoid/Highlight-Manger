from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from highlight_manager.models.enums import AuditAction
from highlight_manager.utils.economy_embeds import build_balance_embed
from highlight_manager.utils.exceptions import HighlightError
from highlight_manager.utils.shop_embeds import build_coinshop_embed

if TYPE_CHECKING:
    from highlight_manager.bot import HighlightBot


class EconomyCog(commands.Cog):
    def __init__(self, bot: "HighlightBot") -> None:
        self.bot = bot

    @commands.command(name="coins", aliases=["balance"])
    async def coins(self, ctx: commands.Context) -> None:
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            return await ctx.reply("This command can only be used inside the server.")
        profile = await self.bot.coins_service.get_profile(ctx.guild, ctx.author.id)
        await ctx.reply(embed=build_balance_embed(profile))

    @commands.command(name="coinshop")
    async def coinshop(self, ctx: commands.Context) -> None:
        if not ctx.guild:
            return await ctx.reply("This command can only be used inside the server.")
        items = await self.bot.shop_service.list_coin_items(ctx.guild.id)
        lines = [
            f"**#{item.item_id} {item.title}** | {item.coin_price} coins | {item.section.label}"
            for item in items[:20]
            if item.coin_price is not None
        ]
        await ctx.reply(embed=build_coinshop_embed(lines))

    @commands.command(name="buy")
    async def buy(self, ctx: commands.Context, item_id: int) -> None:
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            return await ctx.reply("This command can only be used inside the server.")
        try:
            item = await self.bot.shop_service.require_item(ctx.guild.id, item_id)
            result = await self.bot.coins_service.purchase_shop_item(ctx.guild, ctx.author.id, item)
        except HighlightError as exc:
            return await ctx.reply(str(exc))
        try:
            ticket_channel = await self.bot.shop_service.create_purchase_ticket(
                ctx.guild,
                ctx.author,
                section=item.section,
                item=item,
                requested_text=item.title,
                details="Bought with !buy command.",
                remaining_balance=str(result.new_balance),
            )
        except HighlightError as exc:
            await self.bot.coins_service.adjust_balance(ctx.guild, ctx.author.id, item.coin_price or 0)
            return await ctx.reply(f"{exc} Your coins were refunded.")
        except discord.HTTPException:
            await self.bot.coins_service.adjust_balance(ctx.guild, ctx.author.id, item.coin_price or 0)
            return await ctx.reply("I could not open a private shop ticket right now. Your coins were refunded.")
        await self.bot.audit_service.log(
            ctx.guild,
            AuditAction.COINS_UPDATED,
            f"{ctx.author.mention} bought shop item #{item.item_id} ({item.title}) for {item.coin_price} coins.",
            actor_id=ctx.author.id,
            target_id=ctx.author.id,
            metadata={"item_id": item.item_id, "title": item.title, "coin_price": item.coin_price},
        )
        await ctx.reply(
            f"Bought **{item.title}** for **{item.coin_price}** coins. "
            f"Private ticket: {ticket_channel.mention}. Remaining balance: **{result.new_balance}**."
        )

    @commands.command(name="coinsadd")
    async def coinsadd(self, ctx: commands.Context, member: discord.Member, amount: int) -> None:
        await self._handle_admin_coin_update(ctx, member, abs(amount), mode="add")

    @commands.command(name="coinsremove")
    async def coinsremove(self, ctx: commands.Context, member: discord.Member, amount: int) -> None:
        await self._handle_admin_coin_update(ctx, member, abs(amount), mode="remove")

    @commands.command(name="coinsset")
    async def coinsset(self, ctx: commands.Context, member: discord.Member, amount: int) -> None:
        await self._handle_admin_coin_update(ctx, member, max(amount, 0), mode="set")

    async def _handle_admin_coin_update(
        self,
        ctx: commands.Context,
        member: discord.Member,
        amount: int,
        *,
        mode: str,
    ) -> None:
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            return await ctx.reply("This command can only be used inside the server.")
        if not await self.bot.config_service.is_staff(ctx.author):
            return await ctx.reply("You do not have permission to use this command.")
        try:
            if mode == "add":
                result = await self.bot.coins_service.adjust_balance(ctx.guild, member.id, amount)
                action_text = f"Added {amount} coins"
            elif mode == "remove":
                result = await self.bot.coins_service.adjust_balance(ctx.guild, member.id, -amount)
                action_text = f"Removed {amount} coins"
            else:
                result = await self.bot.coins_service.set_balance(ctx.guild, member.id, amount)
                action_text = f"Set coins to {amount}"
        except HighlightError as exc:
            return await ctx.reply(str(exc))
        await self.bot.audit_service.log(
            ctx.guild,
            AuditAction.COINS_UPDATED,
            f"{action_text} for {member.mention}.",
            actor_id=ctx.author.id,
            target_id=member.id,
        )
        await ctx.reply(f"{member.mention}: {result.previous_balance} -> {result.new_balance} coins.")


async def setup(bot: "HighlightBot") -> None:
    await bot.add_cog(EconomyCog(bot))
