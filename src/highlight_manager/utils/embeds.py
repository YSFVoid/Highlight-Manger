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


def _member_name(guild: discord.Guild | None, user_id: int) -> str:
    if guild is None:
        return f"User {user_id}"
    member = guild.get_member(user_id)
    if member is None:
        return f"User {user_id}"
    return member.display_name


def _format_team(guild: discord.Guild | None, user_ids: Sequence[int], team_size: int) -> str:
    lines = [_member_label(guild, user_id) for user_id in user_ids]
    for _ in range(len(user_ids), team_size):
        lines.append("`Open Slot`")
    return "\n".join(lines) if lines else "`Open Slot`"


def _match_colour(match: MatchRecord) -> discord.Colour:
    if match.status == MatchStatus.FINALIZED:
        return discord.Colour.green()
    if match.status in {MatchStatus.CANCELED, MatchStatus.EXPIRED}:
        return discord.Colour.red()
    if match.status in {MatchStatus.FULL, MatchStatus.IN_PROGRESS, MatchStatus.VOTING}:
        return discord.Colour.orange()
    return discord.Colour.blurple()


def _match_status_label(match: MatchRecord) -> str:
    return {
        MatchStatus.OPEN: "Queue Open",
        MatchStatus.FULL: "Match Ready",
        MatchStatus.IN_PROGRESS: "In Progress",
        MatchStatus.VOTING: "Voting Open",
        MatchStatus.FINALIZED: "Finalized",
        MatchStatus.CANCELED: "Canceled",
        MatchStatus.EXPIRED: "Expired",
    }[match.status]


def _room_info_state(match: MatchRecord) -> str:
    if match.room_info is None:
        return "Pending from creator or staff"
    return "Shared privately with players"


def _rank_label(profile: PlayerProfile) -> str:
    if profile.manual_rank_override is not None:
        return f"Rank {profile.manual_rank_override} (manual override)"
    return f"Rank {profile.current_rank}"


def _metric_label(metric: str) -> str:
    return {
        "points": "Season Points",
        "wins": "Season Wins",
        "mvp": "Season MVP",
    }.get(metric, "Season Points")


def _metric_value(profile: PlayerProfile, metric: str) -> str:
    if metric == "wins":
        return f"{profile.season_stats.wins} wins"
    if metric == "mvp":
        total_mvp = profile.season_stats.mvp_wins + profile.season_stats.mvp_losses
        return f"{total_mvp} MVP"
    return f"{profile.current_points} pts"


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


def _role_label(guild: discord.Guild | None, role_id: int | None) -> str:
    if not role_id:
        return "Not configured"
    role = guild.get_role(role_id) if guild else None
    return role.mention if role else f"`{role_id}`"


def build_match_embed(match: MatchRecord, guild: discord.Guild | None) -> discord.Embed:
    filled_slots = len(match.all_player_ids)
    embed = discord.Embed(
        title=f"Match #{match.display_id} • {match.match_type.label} {match.mode.value}",
        description=(
            f"**Match Info**\n"
            f"Creator: {_member_label(guild, match.creator_id)}\n"
            f"Status: **{_match_status_label(match)}**\n"
            f"Capacity: **{filled_slots}/{match.total_slots}**\n"
            f"Queue Timer: {format_relative(match.queue_expires_at)}\n"
            f"Vote Deadline: {format_relative(match.vote_expires_at) if match.vote_expires_at else 'Not started'}\n"
            f"Room Info: **{_room_info_state(match)}**"
        ),
        colour=_match_colour(match),
        timestamp=match.created_at,
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
    footer_text = "Use the buttons below to join, leave, or cancel this match."
    if match.status in {MatchStatus.FULL, MatchStatus.IN_PROGRESS, MatchStatus.VOTING}:
        footer_text = "Players are moving into voice. Room details stay private for match participants."
    embed.set_footer(text=footer_text)
    if guild is not None:
        creator = guild.get_member(match.creator_id)
        creator_avatar = getattr(getattr(creator, "display_avatar", None), "url", None)
        if creator_avatar:
            embed.set_thumbnail(url=creator_avatar)
    return embed


def build_match_ready_embed(match: MatchRecord, guild: discord.Guild | None) -> discord.Embed:
    embed = discord.Embed(
        title="Match Ready!",
        description=(
            f"**{match.match_type.label} {match.mode.value}** is full and ready to play.\n"
            "Players are being moved to their team voice channels.\n"
            "The creator or staff can use **Enter Room Info** to share the private room details."
        ),
        colour=discord.Colour.green(),
    )
    embed.add_field(
        name="Match Info",
        value=(
            f"Match ID: **#{match.display_id}**\n"
            f"Creator: {_member_label(guild, match.creator_id)}\n"
            f"Room Info: **{_room_info_state(match)}**"
        ),
        inline=False,
    )
    embed.add_field(
        name="Team 1",
        value=_format_team(guild, match.team1_player_ids, match.team_size),
        inline=True,
    )
    embed.add_field(
        name="Team 2",
        value=_format_team(guild, match.team2_player_ids, match.team_size),
        inline=True,
    )
    embed.set_footer(text="Sensitive room details are shared only in the private match room.")
    return embed


def build_result_room_embed(match: MatchRecord, guild: discord.Guild | None) -> discord.Embed:
    embed = discord.Embed(
        title=f"Private Match Room • #{match.display_id}",
        description=(
            "This private room is only for the players in this match and configured staff.\n"
            "Use it for room details, voting, result discussion, and the final summary."
        ),
        colour=discord.Colour.orange(),
    )
    embed.add_field(
        name="Match Info",
        value=(
            f"Type: **{match.match_type.label}**\n"
            f"Mode: **{match.mode.value}**\n"
            f"Vote Deadline: {format_relative(match.vote_expires_at)}\n"
            f"Room Info: **{_room_info_state(match)}**"
        ),
        inline=False,
    )
    embed.add_field(
        name="Players",
        value="\n".join(_member_label(guild, user_id) for user_id in match.all_player_ids),
        inline=False,
    )
    embed.set_footer(text="Only the creator or staff can add or edit room info.")
    return embed


def build_room_info_embed(match: MatchRecord, guild: discord.Guild | None) -> discord.Embed:
    room_info = match.room_info
    embed = discord.Embed(
        title=f"Room Info • Match #{match.display_id}",
        description="Private room access details for this match.",
        colour=discord.Colour.teal(),
    )
    if room_info is None:
        embed.description = "Room info has not been submitted yet."
        return embed
    embed.add_field(name="Room ID", value=f"`{room_info.room_id}`", inline=True)
    embed.add_field(name="Password", value=f"`{room_info.password}`" if room_info.password else "`Not set`", inline=True)
    embed.add_field(
        name="Match Key",
        value=f"`{room_info.private_match_key}`" if room_info.private_match_key else "`Not set`",
        inline=True,
    )
    embed.add_field(
        name="Submitted By",
        value=_member_label(guild, room_info.submitted_by),
        inline=True,
    )
    embed.add_field(name="Submitted At", value=format_dt(room_info.submitted_at), inline=True)
    if room_info.updated_at is not None and room_info.updated_by is not None:
        embed.add_field(
            name="Last Edit",
            value=f"{_member_label(guild, room_info.updated_by)} at {format_dt(room_info.updated_at)}",
            inline=False,
        )
    embed.set_footer(text="Keep this information inside the private match room.")
    return embed


def build_vote_status_embed(
    match: MatchRecord,
    guild: discord.Guild | None,
    votes: Sequence[MatchVote],
) -> discord.Embed:
    embed = discord.Embed(
        title=f"Voting Status • Match #{match.display_id}",
        description=(
            f"Status: **{_match_status_label(match)}**\n"
            f"Submitted Votes: **{len(votes)}/{len(match.all_player_ids)}**\n"
            f"Vote Deadline: {format_relative(match.vote_expires_at)}"
        ),
        colour=discord.Colour.orange(),
    )
    players = set(match.all_player_ids)
    submitted = {vote.user_id for vote in votes}
    pending = [_member_label(guild, user_id) for user_id in players - submitted]
    embed.add_field(
        name="Pending Players",
        value="\n".join(pending) if pending else "All players have voted.",
        inline=False,
    )
    if votes:
        lines = []
        for vote in votes:
            line = f"{_member_label(guild, vote.user_id)} • Winner: Team {vote.winner_team}"
            if vote.winner_mvp_id:
                line += f" • Winner MVP: {_member_name(guild, vote.winner_mvp_id)}"
            if vote.loser_mvp_id:
                line += f" • Loser MVP: {_member_name(guild, vote.loser_mvp_id)}"
            lines.append(line)
        embed.add_field(name="Submitted Votes", value="\n".join(lines), inline=False)
    return embed


def build_profile_embed(
    guild: discord.Guild | None,
    profile: PlayerProfile,
    season_name: str | None = None,
) -> discord.Embed:
    embed = discord.Embed(
        title="Player Profile",
        description=(
            f"Member: {_member_label(guild, profile.user_id)}\n"
            f"Rank: **{_rank_label(profile)}**\n"
            f"Season: **{season_name or 'Active Season'}**"
        ),
        colour=discord.Colour.green(),
    )
    embed.add_field(
        name="Current Season",
        value=(
            f"Points: **{profile.current_points}**\n"
            f"Matches: **{profile.season_stats.matches_played}**\n"
            f"Wins: **{profile.season_stats.wins}**\n"
            f"Losses: **{profile.season_stats.losses}**"
        ),
        inline=True,
    )
    embed.add_field(
        name="MVP",
        value=(
            f"Winner MVP: **{profile.mvp_winner_count}**\n"
            f"Loser MVP: **{profile.mvp_loser_count}**\n"
            f"Season MVP Wins: **{profile.season_stats.mvp_wins}**\n"
            f"Season MVP Losses: **{profile.season_stats.mvp_losses}**"
        ),
        inline=True,
    )
    embed.add_field(
        name="Lifetime Summary",
        value=(
            f"Lifetime Points: **{profile.lifetime_points}**\n"
            f"Matches: **{profile.lifetime_stats.matches_played}**\n"
            f"Wins: **{profile.lifetime_stats.wins}**\n"
            f"Losses: **{profile.lifetime_stats.losses}**"
        ),
        inline=False,
    )
    if profile.blacklisted:
        embed.add_field(name="Status", value="Blacklisted from match participation", inline=False)
    if guild is not None:
        member = guild.get_member(profile.user_id)
        member_avatar = getattr(getattr(member, "display_avatar", None), "url", None)
        if member_avatar:
            embed.set_thumbnail(url=member_avatar)
    embed.set_footer(text="Season stats reset each season. Lifetime stats stay permanent.")
    return embed


def build_rank_embed(
    guild: discord.Guild | None,
    profile: PlayerProfile,
    season_name: str | None = None,
) -> discord.Embed:
    embed = discord.Embed(
        title="Rank Overview",
        description=(
            f"{_member_label(guild, profile.user_id)} is currently **{_rank_label(profile)}**.\n"
            f"Season: **{season_name or 'Active Season'}**"
        ),
        colour=discord.Colour.blurple(),
    )
    embed.add_field(name="Points", value=str(profile.current_points), inline=True)
    embed.add_field(
        name="Record",
        value=f"{profile.season_stats.wins}W / {profile.season_stats.losses}L",
        inline=True,
    )
    embed.add_field(
        name="MVP",
        value=f"{profile.mvp_winner_count} winner / {profile.mvp_loser_count} loser",
        inline=True,
    )
    embed.add_field(
        name="Matches Played",
        value=str(profile.season_stats.matches_played),
        inline=True,
    )
    embed.add_field(
        name="Lifetime Points",
        value=str(profile.lifetime_points),
        inline=True,
    )
    embed.add_field(
        name="Rank Mode",
        value="Manual Rank 0 override" if profile.manual_rank_override == 0 else "Season leaderboard placement",
        inline=True,
    )
    return embed


def build_leaderboard_embed(
    guild: discord.Guild | None,
    profiles: Sequence[PlayerProfile],
    *,
    title: str = "Leaderboard",
    metric: str = "points",
    page: int = 1,
    total_pages: int = 1,
    page_size: int = 10,
    season_name: str | None = None,
) -> discord.Embed:
    embed = discord.Embed(
        title=title,
        description=f"Metric: **{_metric_label(metric)}**\nSeason: **{season_name or 'Active Season'}**",
        colour=discord.Colour.gold(),
    )
    if not profiles:
        embed.add_field(name="Leaderboard", value="No ranked players found yet.", inline=False)
        return embed

    lines = []
    start_index = (page - 1) * page_size
    for index, profile in enumerate(profiles, start=start_index + 1):
        lines.append(
            "\n".join(
                [
                    f"**#{index}** {_member_label(guild, profile.user_id)}",
                    (
                        f"{_metric_value(profile, metric)} • "
                        f"{profile.season_stats.wins}W-{profile.season_stats.losses}L • "
                        f"{_rank_label(profile)}"
                    ),
                ]
            )
        )
    embed.add_field(name="Top Players", value="\n\n".join(lines)[:1024], inline=False)
    embed.set_footer(text=f"Page {page}/{total_pages} • Use the buttons below to change pages or view")
    return embed


def build_config_embed(config: GuildConfig, guild: discord.Guild | None) -> discord.Embed:
    embed = discord.Embed(
        title="Guild Configuration",
        description=(
            "Highlight Manager setup overview.\n"
            "Rank is stored as internal placement plus nickname sync only."
        ),
        colour=discord.Colour.blue(),
    )
    embed.add_field(
        name="Core Setup",
        value=(
            f"Prefix: **{config.prefix}**\n"
            f"Apostado Play: {_channel_label(guild, config.apostado_play_channel_id)}\n"
            f"Highlight Play: {_channel_label(guild, config.highlight_play_channel_id)}\n"
            f"Waiting Voice: {_channel_label(guild, config.waiting_voice_channel_id)}"
        ),
        inline=False,
    )
    embed.add_field(
        name="Match Rooms",
        value=(
            f"Temp Voice Category: {_channel_label(guild, config.temp_voice_category_id)}\n"
            f"Results Parent: {_channel_label(guild, config.result_category_id)}\n"
            f"Logs Channel: {_channel_label(guild, config.log_channel_id)}\n"
            f"Result Cleanup: **{config.result_channel_behavior.value}** after **{config.result_channel_delete_delay_seconds}s**"
        ),
        inline=False,
    )
    embed.add_field(
        name="Announcements",
        value=(
            f"@here on Create: **{'Enabled' if config.ping_here_on_match_create else 'Disabled'}**\n"
            f"@here on Ready: **{'Enabled' if config.ping_here_on_match_ready else 'Disabled'}**\n"
            f"Private Match Key Required: **{'Yes' if config.private_match_key_required else 'No'}**"
        ),
        inline=False,
    )
    embed.add_field(
        name="Rewards",
        value=(
            f"Mvp: {_role_label(guild, config.mvp_reward_role_id)}\n"
            f"Mvp Requirements: Winner **{config.mvp_winner_requirement}** / Loser **{config.mvp_loser_requirement}**\n"
            f"Season Reward: {_role_label(guild, config.season_reward_role_id)}\n"
            f"Season Reward Top Count: **{config.season_reward_top_count}**"
        ),
        inline=False,
    )
    embed.add_field(
        name="Staff Access",
        value=(
            f"Admins: {_roles_label(guild, config.admin_role_ids)}\n"
            f"Staff: {_roles_label(guild, config.staff_role_ids)}"
        ),
        inline=False,
    )
    embed.add_field(
        name="Default Resource Names",
        value=(
            f"Apostado Play: {config.resource_names.apostado_play_channel}\n"
            f"Highlight Play: {config.resource_names.highlight_play_channel}\n"
            f"Waiting Voice: {config.resource_names.waiting_voice}\n"
            f"Temp Voices: {config.resource_names.temp_voice_category}\n"
            f"Results: {config.resource_names.result_category}\n"
            f"Logs: {config.resource_names.log_channel}"
        )[:1024],
        inline=False,
    )
    bootstrap_summary = config.bootstrap_last_summary
    if bootstrap_summary:
        assigned_range = (
            f"Rank {bootstrap_summary.first_assigned_rank} to Rank {bootstrap_summary.last_assigned_rank}"
            if bootstrap_summary.first_assigned_rank and bootstrap_summary.last_assigned_rank
            else "N/A"
        )
        embed.add_field(
            name="Bootstrap",
            value=(
                f"Completed: {'Yes' if config.bootstrap_completed else 'No'}\n"
                f"Processed: {bootstrap_summary.processed_members}\n"
                f"Assigned Range: {assigned_range}\n"
                f"Renamed: {bootstrap_summary.renamed_members}\n"
                f"Rename Failures: {bootstrap_summary.rename_failures}\n"
                f"Already Correct: {bootstrap_summary.rename_already_correct}\n"
                f"Hierarchy Skips: {bootstrap_summary.rename_skipped_due_to_hierarchy}\n"
                f"Missing Permission Skips: {bootstrap_summary.rename_skipped_due_to_missing_permission}\n"
                f"Other Skips: {bootstrap_summary.rename_skipped_other}"
            ),
            inline=False,
        )
    else:
        embed.add_field(name="Bootstrap", value=f"Completed: {'Yes' if config.bootstrap_completed else 'No'}", inline=False)
    return embed


def build_result_summary_embed(match: MatchRecord, guild: discord.Guild | None) -> discord.Embed:
    summary = match.result_summary
    embed = discord.Embed(
        title=f"Final Result • Match #{match.display_id}",
        colour=discord.Colour.green() if match.status == MatchStatus.FINALIZED else discord.Colour.red(),
    )
    embed.add_field(name="Type", value=match.match_type.label, inline=True)
    embed.add_field(name="Mode", value=match.mode.value, inline=True)
    embed.add_field(name="Status", value=_match_status_label(match), inline=True)
    if summary is None:
        embed.description = "No result summary is available for this match yet."
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
            (
                f"{_member_label(guild, delta.user_id)}\n"
                f"{delta.previous_points} -> {delta.new_points} ({prefix}{delta.delta}) "
                f"• Rank {delta.rank_before} -> Rank {delta.rank_after}"
            )
        )
    embed.add_field(name="Point Changes", value="\n\n".join(lines)[:1024] if lines else "None", inline=False)
    if summary.notes:
        embed.add_field(name="Notes", value=summary.notes[:1024], inline=False)
    embed.set_footer(text=f"Finalized at {format_dt(summary.finalized_at)}")
    return embed
