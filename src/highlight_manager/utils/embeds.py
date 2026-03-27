from __future__ import annotations

from collections.abc import Sequence

import discord

from highlight_manager.models.enums import MatchStatus
from highlight_manager.models.guild_config import GuildConfig
from highlight_manager.models.match import MatchRecord
from highlight_manager.models.profile import PlayerProfile
from highlight_manager.models.vote import MatchVote
from highlight_manager.utils.dates import format_dt, format_relative


def _member_label(guild: discord.Guild | None, user_id: int) -> str:
    if guild is None:
        return f"<@{user_id}>"
    member = guild.get_member(user_id)
    return member.mention if member else f"<@{user_id}>"


def _format_team(guild: discord.Guild | None, user_ids: Sequence[int], team_size: int) -> str:
    lines = [_member_label(guild, user_id) for user_id in user_ids]
    for _ in range(len(user_ids), team_size):
        lines.append("`[open slot]`")
    return "\n".join(lines) if lines else "`[open slot]`"


def build_match_embed(match: MatchRecord, guild: discord.Guild | None) -> discord.Embed:
    embed = discord.Embed(
        title=f"Match #{match.display_id} | {match.match_type.label}",
        colour=discord.Colour.blurple(),
    )
    embed.add_field(name="Mode", value=match.mode.value, inline=True)
    embed.add_field(name="Status", value=match.status.value, inline=True)
    embed.add_field(name="Creator", value=_member_label(guild, match.creator_id), inline=True)
    embed.add_field(name="Created", value=format_dt(match.created_at), inline=True)
    embed.add_field(
        name="Queue Expires",
        value=format_relative(match.queue_expires_at) if match.queue_expires_at else "Not scheduled",
        inline=True,
    )
    embed.add_field(
        name="Vote Deadline",
        value=format_relative(match.vote_expires_at) if match.vote_expires_at else "Not started",
        inline=True,
    )
    embed.add_field(
        name=f"Team 1 ({len(match.team1_player_ids)}/{match.team_size})",
        value=_format_team(guild, match.team1_player_ids, match.team_size),
        inline=True,
    )
    embed.add_field(
        name=f"Team 2 ({len(match.team2_player_ids)}/{match.team_size})",
        value=_format_team(guild, match.team2_player_ids, match.team_size),
        inline=True,
    )
    return embed


def build_vote_status_embed(
    match: MatchRecord,
    guild: discord.Guild | None,
    votes: Sequence[MatchVote],
) -> discord.Embed:
    embed = discord.Embed(
        title=f"Voting Status | Match #{match.display_id}",
        colour=discord.Colour.orange(),
    )
    players = set(match.all_player_ids)
    submitted = {vote.user_id for vote in votes}
    embed.description = (
        f"Submitted: **{len(votes)}/{len(players)}**\n"
        f"Deadline: {format_relative(match.vote_expires_at)}"
    )
    pending = [_member_label(guild, user_id) for user_id in players - submitted]
    embed.add_field(
        name="Pending Players",
        value="\n".join(pending) if pending else "All votes submitted",
        inline=False,
    )
    if votes:
        lines = []
        for vote in votes:
            winner = "Team 1" if vote.winner_team == 1 else "Team 2"
            line = f"{_member_label(guild, vote.user_id)} -> {winner}"
            if vote.winner_mvp_id:
                line += f" | Winner MVP: {_member_label(guild, vote.winner_mvp_id)}"
            if vote.loser_mvp_id:
                line += f" | Loser MVP: {_member_label(guild, vote.loser_mvp_id)}"
            lines.append(line)
        embed.add_field(name="Votes", value="\n".join(lines), inline=False)
    return embed


def build_profile_embed(
    guild: discord.Guild | None,
    profile: PlayerProfile,
    season_name: str | None = None,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"Profile | {_member_label(guild, profile.user_id)}",
        colour=discord.Colour.green(),
    )
    embed.add_field(name="Current Points", value=str(profile.current_points), inline=True)
    embed.add_field(name="Lifetime Points", value=str(profile.lifetime_points), inline=True)
    embed.add_field(name="Current Rank", value=f"Rank {profile.current_rank}", inline=True)
    embed.add_field(name="Coins", value=str(profile.coins_balance), inline=True)
    embed.add_field(name="Coins Earned", value=str(profile.lifetime_coins_earned), inline=True)
    embed.add_field(name="Coins Spent", value=str(profile.lifetime_coins_spent), inline=True)
    embed.add_field(
        name="Season",
        value=season_name or "Active season",
        inline=False,
    )
    embed.add_field(
        name="Season Stats",
        value=(
            f"Matches: {profile.season_stats.matches_played}\n"
            f"Wins: {profile.season_stats.wins}\n"
            f"Losses: {profile.season_stats.losses}\n"
            f"MVP Wins: {profile.season_stats.mvp_wins}\n"
            f"MVP Losses: {profile.season_stats.mvp_losses}"
        ),
        inline=True,
    )
    embed.add_field(
        name="Lifetime Stats",
        value=(
            f"Matches: {profile.lifetime_stats.matches_played}\n"
            f"Wins: {profile.lifetime_stats.wins}\n"
            f"Losses: {profile.lifetime_stats.losses}\n"
            f"MVP Wins: {profile.lifetime_stats.mvp_wins}\n"
            f"MVP Losses: {profile.lifetime_stats.mvp_losses}"
        ),
        inline=True,
    )
    return embed


def build_leaderboard_embed(
    guild: discord.Guild | None,
    profiles: Sequence[PlayerProfile],
    title: str = "Leaderboard",
) -> discord.Embed:
    embed = discord.Embed(title=title, colour=discord.Colour.gold())
    if not profiles:
        embed.description = "No profiles found yet."
        return embed
    lines = []
    for index, profile in enumerate(profiles, start=1):
        lines.append(
            f"**{index}.** {_member_label(guild, profile.user_id)} | "
            f"{profile.current_points} pts | Rank {profile.current_rank}"
        )
    embed.description = "\n".join(lines)
    return embed


def build_config_embed(config: GuildConfig, guild: discord.Guild | None) -> discord.Embed:
    embed = discord.Embed(title="Guild Configuration", colour=discord.Colour.blue())
    embed.add_field(name="Prefix", value=config.prefix, inline=True)
    embed.add_field(name="Apostado Play", value=_channel_label(guild, config.apostado_channel_id), inline=True)
    embed.add_field(name="Highlight Play", value=_channel_label(guild, config.highlight_channel_id), inline=True)
    embed.add_field(name="Waiting Voice", value=_channel_label(guild, config.waiting_voice_channel_id), inline=True)
    embed.add_field(
        name="Temp Voice Category",
        value=_channel_label(guild, config.temp_voice_category_id),
        inline=True,
    )
    embed.add_field(
        name="Results Parent",
        value=_channel_label(guild, config.result_category_id),
        inline=True,
    )
    embed.add_field(name="Log Channel", value=_channel_label(guild, config.log_channel_id), inline=True)
    embed.add_field(
        name="Admins / Staff",
        value=(
            f"Admins: {_roles_label(guild, config.admin_role_ids)}\n"
            f"Staff: {_roles_label(guild, config.staff_role_ids)}"
        ),
        inline=False,
    )
    ranks = []
    for threshold in config.rank_thresholds:
        role_id = config.rank_role_map.get(str(threshold.rank))
        role_label = f"<@&{role_id}>" if role_id else "Not mapped"
        lower = threshold.min_points if threshold.min_points is not None else "-inf"
        upper = threshold.max_points if threshold.max_points is not None else "+inf"
        ranks.append(f"Rank {threshold.rank}: {lower} to {upper} -> {role_label}")
    rank0_role = config.rank_role_map.get("0")
    if rank0_role:
        ranks.insert(0, f"Rank 0: <@&{rank0_role}>")
    embed.add_field(name="Rank Roles", value="\n".join(ranks) if ranks else "None", inline=False)
    embed.add_field(
        name="Result Behavior",
        value=f"{config.result_channel_behavior.value} after {config.result_channel_delete_delay_seconds}s",
        inline=False,
    )
    bootstrap_summary = config.bootstrap_last_summary
    if bootstrap_summary:
        rank_lines = [
            f"Rank {rank}: {count}"
            for rank, count in sorted(bootstrap_summary.rank_counts.items(), key=lambda item: int(item[0]))
        ]
        embed.add_field(
            name="Bootstrap",
            value=(
                f"Completed: {'Yes' if config.bootstrap_completed else 'No'}\n"
                f"Processed: {bootstrap_summary.processed_members}\n"
                f"Renamed: {bootstrap_summary.rename_successes}\n"
                f"Rename Failures: {bootstrap_summary.rename_failures}\n"
                f"Ranks: {', '.join(rank_lines) if rank_lines else 'N/A'}"
            ),
            inline=False,
        )
    else:
        embed.add_field(name="Bootstrap", value=f"Completed: {'Yes' if config.bootstrap_completed else 'No'}", inline=False)
    return embed


def build_result_summary_embed(match: MatchRecord, guild: discord.Guild | None) -> discord.Embed:
    summary = match.result_summary
    embed = discord.Embed(
        title=f"Match #{match.display_id} Final Summary",
        colour=discord.Colour.green() if match.status == MatchStatus.FINALIZED else discord.Colour.red(),
    )
    embed.add_field(name="Mode", value=match.mode.value, inline=True)
    embed.add_field(name="Type", value=match.match_type.label, inline=True)
    embed.add_field(name="Status", value=match.status.value, inline=True)
    if summary is None:
        embed.description = "No result summary available."
        return embed
    winner = "Timeout / Failed Report" if summary.winner_team is None else f"Team {summary.winner_team}"
    embed.add_field(name="Winner", value=winner, inline=True)
    embed.add_field(
        name="Winner MVP",
        value=_member_label(guild, summary.winner_mvp_id) if summary.winner_mvp_id else "N/A",
        inline=True,
    )
    embed.add_field(
        name="Loser MVP",
        value=_member_label(guild, summary.loser_mvp_id) if summary.loser_mvp_id else "N/A",
        inline=True,
    )
    lines = []
    for delta in summary.point_deltas:
        prefix = "+" if delta.delta >= 0 else ""
        lines.append(
            f"{_member_label(guild, delta.user_id)} | "
            f"{delta.previous_points} -> {delta.new_points} ({prefix}{delta.delta})"
        )
    embed.add_field(name="Point Changes", value="\n".join(lines) if lines else "None", inline=False)
    if summary.notes:
        embed.add_field(name="Notes", value=summary.notes, inline=False)
    return embed


def _channel_label(guild: discord.Guild | None, channel_id: int | None) -> str:
    if not channel_id:
        return "Not configured"
    channel = guild.get_channel(channel_id) if guild else None
    return f"{channel.mention} (`{channel_id}`)" if isinstance(channel, discord.abc.GuildChannel) else f"`{channel_id}`"


def _roles_label(guild: discord.Guild | None, role_ids: Sequence[int]) -> str:
    if not role_ids:
        return "Not configured"
    if guild is None:
        return ", ".join(str(role_id) for role_id in role_ids)
    labels = []
    for role_id in role_ids:
        role = guild.get_role(role_id)
        labels.append(role.mention if role else f"`{role_id}`")
    return ", ".join(labels)
