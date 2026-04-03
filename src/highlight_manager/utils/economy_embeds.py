from __future__ import annotations

import discord

from highlight_manager.models.economy import CoinSpendRequest
from highlight_manager.models.profile import PlayerProfile


def build_balance_embed(profile: PlayerProfile) -> discord.Embed:
    embed = discord.Embed(
        title="Coins Balance",
        colour=discord.Colour.gold(),
    )
    embed.add_field(name="Balance", value=str(profile.coins_balance), inline=True)
    embed.add_field(name="Lifetime Earned", value=str(profile.lifetime_coins_earned), inline=True)
    embed.add_field(name="Lifetime Spent", value=str(profile.lifetime_coins_spent), inline=True)
    embed.set_footer(text="Highlight Manager Economy")
    return embed


def build_pending_requests_embed(requests: list[CoinSpendRequest]) -> discord.Embed:
    embed = discord.Embed(
        title="Pending Coin Requests",
        description=(
            "\n".join(
                f"#{request.request_number} | <@{request.user_id}> | {request.coin_amount} coins | {request.requested_item_text}"
                for request in requests[:10]
            )
            if requests
            else "No pending requests."
        ),
        colour=discord.Colour.orange(),
    )
    return embed
