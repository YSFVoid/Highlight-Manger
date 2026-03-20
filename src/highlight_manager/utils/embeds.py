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


def _safe_relative(value) -> str:
    return format_relative(value) if value else "Not scheduled"


def _format_team(guild: discord.Guild | None, user_ids: Sequence[int], team_size: int) -> str:
    lines = [_member_label(guild, user_id) for user_id in user_ids]
    for _ in range(len(user_ids), team_size):
        lines.append("`Open Slot`")
    return "\n".join(lines) if lines else "`Open Slot`"


def _rank_label(profile: PlayerProfile) -> str:
    if profile.manual_rank_override is not None:
        return f"Rank {profile.manual_rank_override} (manual)"
    return f"Rank {profile.current_rank}"


def _match_colour(match: MatchRecord) -> discord.Colour:
    if match.status == MatchStatus.FINALIZED:
        return discord.Colour.green()
    if match.status in {MatchStatus.CANCELED, MatchStatus.EXPIRED}:
        return discord.Colour.red()
    if match.status in {MatchStatus.FULL, MatchStatus.IN_PROGRESS, MatchStatus.VOTING}:
        return discord.Colour.orange()
    return discord.Colour.blurple()


def _match_status_label(match: MatchRecord) -> str:
    if match.status == MatchStatus.OPEN and match.queue_opened_at is None:
        return "Waiting For Room Info"
    return {
        MatchStatus.OPEN: "Queue Open",
        MatchStatus.FULL: "Match Ready",
        MatchStatus.IN_PROGRESS: "In Progress",
        MatchStatus.VOTING: "Voting Open",
        MatchStatus.FINALIZED: "Finalized",
        MatchStatus.CANCELED: "Canceled",
        MatchStatus.EXPIRED: "Expired",
    }[match.status]


def _match_public_title(match: MatchRecord) -> str:
    match_name = f"{match.match_type.label} {match.mode.value}"
    if match.status == MatchStatus.OPEN and match.queue_opened_at is None:
        return f"{match_name} Match Setup"
    if match.status == MatchStatus.OPEN:
        return f"{match_name} Queue Open"
    if match.status in {MatchStatus.FULL, MatchStatus.IN_PROGRESS, MatchStatus.VOTING}:
        return f"{match_name} Match Started"
    if match.status == MatchStatus.CANCELED:
        return f"{match_name} Match Canceled"
    if match.status == MatchStatus.EXPIRED:
        return f"{match_name} Match Expired"
    return f"{match_name} Match Finished"


def _match_public_description(match: MatchRecord, guild: discord.Guild | None) -> str:
    base = [
        f"Match ID: **#{match.display_id}**",
        f"Host: {_member_label(guild, match.creator_id)}",
        f"Status: **{_match_status_label(match)}**",
    ]
    if match.status == MatchStatus.OPEN and match.queue_opened_at is None:
        base.append("Room access is still pending. The public queue will unlock after room info is submitted.")
    elif match.status == MatchStatus.OPEN:
        base.append("The queue is now live. Players can join a team below before the timer runs out.")
    elif match.status in {MatchStatus.FULL, MatchStatus.IN_PROGRESS, MatchStatus.VOTING}:
        base.append("Teams are locked. Players are moving through private match voice and result-room flow now.")
    elif match.status == MatchStatus.CANCELED:
        reason = match.metadata.get("cancel_reason")
        base.append("This match has been canceled and the queue is closed.")
        if reason:
            base.append(f"Reason: **{reason}**")
    elif match.status == MatchStatus.EXPIRED:
        base.append("Voting timed out. The match was closed and the configured timeout penalties were applied.")
    else:
        base.append("This match is finished. Final points and MVP results were posted in the private result room.")
    return "\n".join(base)


def _match_public_footer(match: MatchRecord) -> str:
    if match.status == MatchStatus.OPEN and match.queue_opened_at is None:
        return "Use Enter Room Info to unlock the queue safely."
    if match.status == MatchStatus.OPEN:
        return "Join Team 1 or Team 2 below before the queue expires."
    if match.status in {MatchStatus.FULL, MatchStatus.IN_PROGRESS, MatchStatus.VOTING}:
        return "Join buttons are disabled because the match is already live."
    if match.status == MatchStatus.CANCELED:
        return "This match was canceled. The public queue card is now locked."
    if match.status == MatchStatus.EXPIRED:
        return "This match expired before a valid result was completed."
    return "This match is closed. Check the private result room for the final summary."


def _room_info_state(match: MatchRecord) -> str:
    if match.room_info is None:
        return "Pending"
    return "Secured In Private Match Room"


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


def _apply_member_art(embed: discord.Embed, guild: discord.Guild | None, user_id: int) -> None:
    if guild is None:
        return
    member = guild.get_member(user_id)
    avatar_url = getattr(getattr(member, "display_avatar", None), "url", None)
    if avatar_url:
        embed.set_thumbnail(url=avatar_url)


def _top_rank_badge(index: int) -> str:
    badges = {1: "1st", 2: "2nd", 3: "3rd"}
    return badges.get(index, f"{index}th")


def build_help_embed(prefix: str) -> discord.Embed:
    embed = discord.Embed(
        title="Prefix Command Guide",
        description=(
            "Use these member commands for queueing, rank checks, and player stats.\n"
            "Match commands use the configured play rooms and Waiting Voice rules."
        ),
        colour=discord.Colour.blurple(),
    )
    embed.add_field(
        name="Match Queue",
        value=(
            f"`{prefix}play <mode> <type>`\n"
            "Examples:\n"
            f"`{prefix}play 1v1 apos`\n"
            f"`{prefix}play 2v2 high`\n"
            f"`{prefix}play 4v4 apostado`"
        ),
        inline=False,
    )
    embed.add_field(
        name="Player Commands",
        value=(
            f"`{prefix}profile`\n"
            f"`{prefix}rank`\n"
            f"`{prefix}r`\n"
            f"`{prefix}leaderboard`\n"
            f"`{prefix}top`\n"
            f"`{prefix}stats [user]`"
        ),
        inline=False,
    )
    embed.set_footer(text="Type the command exactly as shown with your server prefix.")
    return embed


def build_match_room_setup_embed(match: MatchRecord, guild: discord.Guild | None) -> discord.Embed:
    embed = discord.Embed(
        title=_match_public_title(match),
        description=(
            f"Match ID: **#{match.display_id}**\n"
            f"Host: {_member_label(guild, match.creator_id)}\n\n"
            "Submit the room details first so the queue can open safely.\n"
            "Room ID, password, and match key stay private in the match room."
        ),
        colour=discord.Colour.dark_teal(),
        timestamp=match.created_at,
    )
    embed.add_field(
        name="Queue Status",
        value="Waiting for the creator or staff to submit room info.",
        inline=False,
    )
    embed.add_field(
        name="Team Preview",
        value=(
            f"Team 1\n{_format_team(guild, match.team1_player_ids, match.team_size)}\n\n"
            f"Team 2\n{_format_team(guild, match.team2_player_ids, match.team_size)}"
        )[:1024],
        inline=False,
    )
    embed.set_footer(text="Press Enter Room Info to unlock the public queue.")
    _apply_member_art(embed, guild, match.creator_id)
    return embed


def build_match_embed(match: MatchRecord, guild: discord.Guild | None) -> discord.Embed:
    filled_slots = len(match.all_player_ids)
    embed = discord.Embed(
        title=_match_public_title(match),
        description=_match_public_description(match, guild),
        colour=_match_colour(match),
        timestamp=match.created_at,
    )
    embed.add_field(
        name="Match Info",
        value=(
            f"Capacity: **{filled_slots}/{match.total_slots}**\n"
            f"Queue Deadline: **{_safe_relative(match.queue_expires_at)}**\n"
            f"Vote Deadline: **{_safe_relative(match.vote_expires_at)}**\n"
            f"Room Access: **{_room_info_state(match)}**"
        ),
        inline=False,
    )
    embed.add_field(
        name=f"Team 1 ({len(match.team1_player_ids)}/{match.team_size})",
        value=_format_team(guild, match.team1_player_ids, match.team_size),
        inline=False,
    )
    embed.add_field(
        name=f"Team 2 ({len(match.team2_player_ids)}/{match.team_size})",
        value=_format_team(guild, match.team2_player_ids, match.team_size),
        inline=False,
    )
    embed.set_footer(text=_match_public_footer(match))
    _apply_member_art(embed, guild, match.creator_id)
    return embed


def build_match_ready_embed(match: MatchRecord, guild: discord.Guild | None) -> discord.Embed:
    embed = discord.Embed(
        title="Match Ready",
        description=(
            f"{match.match_type.label} {match.mode.value} is full.\n"
            "Players are being moved to their team voice channels now."
        ),
        colour=discord.Colour.green(),
        timestamp=match.created_at,
    )
    embed.add_field(
        name="Match Info",
        value=(
            f"Match ID: **#{match.display_id}**\n"
            f"Host: {_member_label(guild, match.creator_id)}\n"
            f"Room Access: **{_room_info_state(match)}**"
        ),
        inline=False,
    )
    embed.add_field(
        name="Team 1",
        value=_format_team(guild, match.team1_player_ids, match.team_size),
        inline=False,
    )
    embed.add_field(
        name="Team 2",
        value=_format_team(guild, match.team2_player_ids, match.team_size),
        inline=False,
    )
    embed.set_footer(text="Room details were already shared privately with players and staff.")
    return embed


def build_result_room_embed(match: MatchRecord, guild: discord.Guild | None) -> discord.Embed:
    embed = discord.Embed(
        title=f"Private Match Room #{match.display_id}",
        description=(
            "This room is private.\n"
            "Only players in this match plus configured Highlight admins or staff can see it.\n"
            "Use it for room access, voting, result discussion, and the final summary."
        ),
        colour=discord.Colour.orange(),
        timestamp=match.created_at,
    )
    embed.add_field(
        name="Match Info",
        value=(
            f"Type: **{match.match_type.label}**\n"
            f"Mode: **{match.mode.value}**\n"
            f"Status: **{_match_status_label(match)}**\n"
            f"Vote Deadline: **{_safe_relative(match.vote_expires_at)}**"
        ),
        inline=False,
    )
    players = "\n".join(_member_label(guild, user_id) for user_id in match.all_player_ids) or "Only the host is here so far."
    embed.add_field(name="Players", value=players, inline=False)
    embed.set_footer(text="Sensitive room details stay here and are removed automatically after the match closes.")
    return embed


def build_room_info_embed(match: MatchRecord, guild: discord.Guild | None) -> discord.Embed:
    room_info = match.room_info
    embed = discord.Embed(
        title=f"Room Access - Match #{match.display_id}",
        description="Use these private room details to enter the Free Fire lobby.",
        colour=discord.Colour.teal(),
    )
    if room_info is None:
        embed.description = "Room details have not been submitted yet."
        return embed
    embed.add_field(name="Room ID", value=f"`{room_info.room_id}`", inline=False)
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
        title=f"Voting Status - Match #{match.display_id}",
        description=(
            f"Status: **{_match_status_label(match)}**\n"
            f"Votes In: **{len(votes)}/{len(match.all_player_ids)}**\n"
            f"Vote Deadline: **{_safe_relative(match.vote_expires_at)}**"
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
            line = f"{_member_label(guild, vote.user_id)} - Winner Team {vote.winner_team}"
            if vote.winner_mvp_id:
                line += f" - Winner MVP: {_member_name(guild, vote.winner_mvp_id)}"
            if vote.loser_mvp_id:
                line += f" - Loser MVP: {_member_name(guild, vote.loser_mvp_id)}"
            lines.append(line)
        embed.add_field(name="Submitted Votes", value="\n".join(lines)[:1024], inline=False)
    return embed


def build_profile_embed(
    guild: discord.Guild | None,
    profile: PlayerProfile,
    season_name: str | None = None,
) -> discord.Embed:
    display_name = _member_name(guild, profile.user_id)
    embed = discord.Embed(
        title=f"{display_name} - Profile",
        description=(
            f"{_member_label(guild, profile.user_id)}\n"
            f"Rank: **{_rank_label(profile)}**\n"
            f"Season: **{season_name or 'Active Season'}**"
        ),
        colour=discord.Colour.green(),
    )
    embed.add_field(
        name="Current Season",
        value=(
            f"Points: **{profile.current_points}**\n"
            f"Record: **{profile.season_stats.wins}W / {profile.season_stats.losses}L**\n"
            f"Matches: **{profile.season_stats.matches_played}**\n"
            f"Winner MVP: **{profile.mvp_winner_count}**\n"
            f"Loser MVP: **{profile.mvp_loser_count}**"
        ),
        inline=False,
    )
    embed.add_field(
        name="Lifetime",
        value=(
            f"Points: **{profile.lifetime_points}**\n"
            f"Record: **{profile.lifetime_stats.wins}W / {profile.lifetime_stats.losses}L**\n"
            f"Matches: **{profile.lifetime_stats.matches_played}**\n"
            f"MVP Wins: **{profile.lifetime_stats.mvp_wins}**\n"
            f"MVP Losses: **{profile.lifetime_stats.mvp_losses}**"
        ),
        inline=False,
    )
    status_lines = []
    if profile.manual_rank_override == 0:
        status_lines.append("Manual Rank 0 override is active.")
    if profile.blacklisted:
        status_lines.append("Blacklisted from match participation.")
    if status_lines:
        embed.add_field(name="Status", value="\n".join(status_lines), inline=False)
    embed.set_footer(text="Season stats reset between seasons. Lifetime stats remain permanent.")
    _apply_member_art(embed, guild, profile.user_id)
    return embed


def build_rank_embed(
    guild: discord.Guild | None,
    profile: PlayerProfile,
    season_name: str | None = None,
) -> discord.Embed:
    display_name = _member_name(guild, profile.user_id)
    embed = discord.Embed(
        title=f"{display_name} - Rank Card",
        description=(
            f"{_member_label(guild, profile.user_id)}\n"
            f"Placement: **{_rank_label(profile)}**\n"
            f"Season: **{season_name or 'Active Season'}**"
        ),
        colour=discord.Colour.blurple(),
    )
    embed.add_field(
        name="Season Snapshot",
        value=(
            f"Points: **{profile.current_points}**\n"
            f"Record: **{profile.season_stats.wins}W / {profile.season_stats.losses}L**\n"
            f"Matches: **{profile.season_stats.matches_played}**"
        ),
        inline=False,
    )
    embed.add_field(
        name="MVP Snapshot",
        value=(
            f"Winner MVP: **{profile.mvp_winner_count}**\n"
            f"Loser MVP: **{profile.mvp_loser_count}**\n"
            f"Lifetime Points: **{profile.lifetime_points}**"
        ),
        inline=False,
    )
    if profile.manual_rank_override == 0 or profile.blacklisted:
        flags = []
        if profile.manual_rank_override == 0:
            flags.append("Manual Rank 0 override")
        if profile.blacklisted:
            flags.append("Blacklisted")
        embed.add_field(name="Status", value="\n".join(flags), inline=False)
    embed.set_footer(text="Rank updates from live season placement. Nicknames stay synced.")
    _apply_member_art(embed, guild, profile.user_id)
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
        description=(
            f"Season: **{season_name or 'Active Season'}**\n"
            f"View: **{_metric_label(metric)}**"
        ),
        colour=discord.Colour.gold(),
    )
    if not profiles:
        embed.add_field(name="Top Players", value="No ranked players found yet.", inline=False)
        return embed

    lines = []
    start_index = (page - 1) * page_size
    for index, profile in enumerate(profiles, start=start_index + 1):
        lines.append(
            "\n".join(
                [
                    f"**{_top_rank_badge(index)}** {_member_label(guild, profile.user_id)}",
                    f"{_metric_value(profile, metric)} - {profile.season_stats.wins}W/{profile.season_stats.losses}L - {_rank_label(profile)}",
                ]
            )
        )
    embed.add_field(name="Top Players", value="\n\n".join(lines)[:1024], inline=False)
    embed.set_footer(text=f"Page {page}/{total_pages} - Use the controls below to switch page or metric.")
    return embed


def build_config_embed(config: GuildConfig, guild: discord.Guild | None) -> discord.Embed:
    embed = discord.Embed(
        title="Guild Configuration",
        description="Runtime resource lookups use Discord IDs, so renaming channels and roles will not break the bot.",
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
        name="Match Resources",
        value=(
            f"Temp Voice Category: {_channel_label(guild, config.temp_voice_category_id)}\n"
            f"Results Parent: {_channel_label(guild, config.result_category_id)}\n"
            f"Logs Channel: {_channel_label(guild, config.log_channel_id)}\n"
            f"Cleanup: **{config.result_channel_behavior.value}** after **{config.result_channel_delete_delay_seconds}s**"
        ),
        inline=False,
    )
    embed.add_field(
        name="Announcements",
        value=(
            f"@here On Queue Open: **{'Enabled' if config.ping_here_on_match_create else 'Disabled'}**\n"
            f"@here On Ready: **{'Enabled' if config.ping_here_on_match_ready else 'Disabled'}**\n"
            f"Private Match Key Required: **{'Yes' if config.private_match_key_required else 'No'}**"
        ),
        inline=False,
    )
    embed.add_field(
        name="Roles",
        value=(
            f"Mvp: {_role_label(guild, config.mvp_reward_role_id)}\n"
            f"Season Reward: {_role_label(guild, config.season_reward_role_id)}\n"
            f"Admins: {_roles_label(guild, config.admin_role_ids)}\n"
            f"Staff: {_roles_label(guild, config.staff_role_ids)}"
        ),
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
                f"Completed: **{'Yes' if config.bootstrap_completed else 'No'}**\n"
                f"Processed: **{bootstrap_summary.processed_members}**\n"
                f"Assigned Range: **{assigned_range}**\n"
                f"Renamed: **{bootstrap_summary.renamed_members}**\n"
                f"Rename Failures: **{bootstrap_summary.rename_failures}**\n"
                f"Already Correct: **{bootstrap_summary.rename_already_correct}**\n"
                f"Hierarchy Skips: **{bootstrap_summary.rename_skipped_due_to_hierarchy}**\n"
                f"Missing Permission Skips: **{bootstrap_summary.rename_skipped_due_to_missing_permission}**\n"
                f"Other Skips: **{bootstrap_summary.rename_skipped_other}**"
            ),
            inline=False,
        )
    else:
        embed.add_field(
            name="Bootstrap",
            value=f"Completed: **{'Yes' if config.bootstrap_completed else 'No'}**",
            inline=False,
        )
    embed.set_footer(text="Stored resource IDs are shown beside mentions where available.")
    return embed


def build_result_summary_embed(match: MatchRecord, guild: discord.Guild | None) -> discord.Embed:
    summary = match.result_summary
    embed = discord.Embed(
        title=f"Final Result - Match #{match.display_id}",
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
            f"{_member_label(guild, delta.user_id)} - {delta.previous_points} -> {delta.new_points} ({prefix}{delta.delta}) - Rank {delta.rank_before} -> Rank {delta.rank_after}"
        )
    embed.add_field(name="Point Changes", value="\n".join(lines)[:1024] if lines else "None", inline=False)
    if summary.notes:
        embed.add_field(name="Notes", value=summary.notes[:1024], inline=False)
    embed.set_footer(text=f"Finalized at {format_dt(summary.finalized_at)}")
    return embed
