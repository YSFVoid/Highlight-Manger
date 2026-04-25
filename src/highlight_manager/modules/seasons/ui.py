from __future__ import annotations

from datetime import datetime

import discord

from highlight_manager.db.models.competitive import SeasonModel, SeasonPlayerModel
from highlight_manager.modules.common.enums import SeasonStatus
from highlight_manager.ui.brand import apply_embed_chrome


def _format_date(value: datetime | None) -> str:
    if value is None:
        return "Unknown"
    return discord.utils.format_dt(value, style="D")


def _season_status_label(status: SeasonStatus) -> str:
    return {
        SeasonStatus.ACTIVE: "Active",
        SeasonStatus.ENDED: "Ended",
        SeasonStatus.ARCHIVED: "Archived",
        SeasonStatus.PLANNED: "Planned",
    }.get(status, status.value.title())


def _season_marker(season: SeasonModel) -> str:
    if season.archived_at is not None:
        return f"Archived: {_format_date(season.archived_at)}"
    if season.ends_at is not None:
        return f"Ended: {_format_date(season.ends_at)}"
    return f"Started: {_format_date(season.starts_at)}"


def build_season_history_embed(seasons: list[SeasonModel], *, prefix: str) -> discord.Embed:
    embed = discord.Embed(
        title="Season History",
        description="Browse current and archived ranked seasons without changing the live ladder.",
        colour=discord.Colour.from_rgb(95, 112, 255),
    )
    if not seasons:
        embed.description = "No seasons are available yet."
        return embed

    current = next((season for season in seasons if season.status == SeasonStatus.ACTIVE), None)
    if current is not None:
        embed.add_field(
            name="Current Season",
            value=(
                f"**Season {current.season_number} — {current.name}**\n"
                f"Status: **{_season_status_label(current.status)}**\n"
                f"{_season_marker(current)}\n"
                f"Use `{prefix}leaderboard` or `{prefix}profile` for the live view."
            ),
            inline=False,
        )

    archived = [season for season in seasons if season.status != SeasonStatus.ACTIVE]
    archived_lines = []
    for season in archived:
        archived_lines.append(
            f"`#{season.season_number}` **{season.name}** — {_season_status_label(season.status)}\n"
            f"{_season_marker(season)}"
        )
    embed.add_field(
        name="Archived Seasons",
        value="\n\n".join(archived_lines) if archived_lines else "No archived seasons yet.",
        inline=False,
    )
    embed.add_field(
        name="Examples",
        value=(
            f"`{prefix}leaderboard 1` View archived standings\n"
            f"`{prefix}profile 1` View your Season 1 stats\n"
            f"`{prefix}rank 1` View your Season 1 rank snapshot"
        ),
        inline=False,
    )
    return apply_embed_chrome(embed, section="Season History")


def build_archived_profile_embed(
    *,
    display_name: str,
    season: SeasonModel,
    season_player: SeasonPlayerModel,
    leaderboard_rank: int | None,
    avatar_url: str | None = None,
) -> discord.Embed:
    matches_played = season_player.matches_played
    winrate = (season_player.wins / matches_played * 100.0) if matches_played else 0.0
    winrate_text = f"{winrate:.1f}%" if not winrate.is_integer() else f"{int(winrate)}%"
    placement_text = f"#{leaderboard_rank}" if leaderboard_rank is not None else "Unranked"
    embed = discord.Embed(
        title=f"Archived Season Profile — {display_name}",
        description=(
            f"**Season {season.season_number} — {season.name}**\n"
            f"Status: **{_season_status_label(season.status)}**\n"
            f"{_season_marker(season)}"
        ),
        colour=discord.Colour.from_rgb(95, 112, 255),
    )
    if avatar_url:
        embed.set_thumbnail(url=avatar_url)
    embed.add_field(name="Final Points", value=f"**{season_player.rating}**", inline=True)
    embed.add_field(name="Peak Rating", value=f"**{season_player.peak_rating}**", inline=True)
    embed.add_field(name="Final Placement", value=f"**{placement_text}**", inline=True)
    embed.add_field(name="Wins", value=f"**{season_player.wins}**", inline=True)
    embed.add_field(name="Losses", value=f"**{season_player.losses}**", inline=True)
    embed.add_field(name="Winrate", value=f"**{winrate_text}**", inline=True)
    embed.add_field(name="Matches", value=f"**{matches_played}**", inline=True)
    return apply_embed_chrome(embed, section="Archived season snapshot")


def build_archived_profile_empty_embed(
    *,
    display_name: str,
    season: SeasonModel,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"Archived Season Profile — {display_name}",
        description=(
            f"No ranked record was found for **Season {season.season_number} — {season.name}**.\n"
            "This archived view is read-only and only shows seasons where you played ranked matches."
        ),
        colour=discord.Colour.from_rgb(95, 112, 255),
    )
    return apply_embed_chrome(embed, section="Archived season snapshot")
