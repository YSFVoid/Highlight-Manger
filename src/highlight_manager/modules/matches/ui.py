from __future__ import annotations

import discord

from highlight_manager.modules.common.enums import MatchState, QueueState
from highlight_manager.modules.matches.types import MatchSnapshot, QueueSnapshot
from highlight_manager.ui import theme


STATUS_COLORS = {
    QueueState.QUEUE_OPEN: theme.SURFACE,
    QueueState.FILLING: theme.PRIMARY,
    QueueState.FULL_PENDING_ROOM_INFO: theme.ACCENT,
    QueueState.QUEUE_CANCELLED: theme.ERROR,
    QueueState.CONVERTED_TO_MATCH: theme.SUCCESS,
    MatchState.CREATED: theme.PRIMARY,
    MatchState.MOVING: theme.WARNING,
    MatchState.LIVE: theme.ACCENT,
    MatchState.RESULT_PENDING: theme.ACCENT,
    MatchState.CONFIRMED: theme.SUCCESS,
    MatchState.CANCELLED: theme.ERROR,
    MatchState.EXPIRED: theme.WARNING,
    MatchState.FORCE_CLOSED: theme.ERROR,
}


def _state_label(value: str) -> str:
    return value.replace("_", " ").title()


def _ruleset_label(raw_value: str) -> str:
    return raw_value.replace("_", " ").title()


def _team_value(player_ids: list[int], team_size: int, render_player) -> str:
    if not player_ids:
        open_slots = "\n".join("`OPEN SLOT`" for _ in range(team_size))
        return open_slots
    lines = [render_player(player_id) for player_id in player_ids]
    remaining = max(team_size - len(player_ids), 0)
    lines.extend("`OPEN SLOT`" for _ in range(remaining))
    return "\n".join(lines)


def build_queue_embed(snapshot: QueueSnapshot) -> discord.Embed:
    queue = snapshot.queue

    def render_player(player_id: int) -> str:
        discord_id = snapshot.player_discord_ids.get(player_id)
        return f"<@{discord_id}>" if discord_id else f"Player {player_id}"

    creator_discord_id = snapshot.player_discord_ids.get(queue.creator_player_id)
    creator_text = f"<@{creator_discord_id}>" if creator_discord_id else f"Player {queue.creator_player_id}"
    status_line = {
        QueueState.QUEUE_OPEN: "Queue opened. Players can join either side.",
        QueueState.FILLING: "Lobby is filling. Pick a side and lock the teams in.",
        QueueState.FULL_PENDING_ROOM_INFO: "Teams are locked. Host must submit Room ID, Password, and Key (optional).",
        QueueState.QUEUE_CANCELLED: "Queue closed before an official match was created.",
        QueueState.CONVERTED_TO_MATCH: "Queue converted into an official live match.",
    }[queue.state]
    embed = discord.Embed(
        title=f"{_ruleset_label(queue.ruleset_key.value)} {queue.mode.value.upper()} Match Lobby",
        description=(
            f"**Status**  `{_state_label(queue.state.value).upper()}`\n"
            f"**Host**  {creator_text}\n"
            f"**Flow**  {status_line}"
        ),
        colour=STATUS_COLORS[queue.state],
    )
    embed.add_field(
        name=f"Team 1  [{len(snapshot.team1_ids)}/{queue.team_size}]",
        value=_team_value(snapshot.team1_ids, queue.team_size, render_player),
        inline=True,
    )
    embed.add_field(
        name=f"Team 2  [{len(snapshot.team2_ids)}/{queue.team_size}]",
        value=_team_value(snapshot.team2_ids, queue.team_size, render_player),
        inline=True,
    )
    embed.add_field(
        name="Queue Details",
        value=(
            f"Ruleset: `{_ruleset_label(queue.ruleset_key.value)}`\n"
            f"Mode: `{queue.mode.value.upper()}`\n"
            f"Players needed: `{queue.team_size * 2}`"
        ),
        inline=False,
    )
    if queue.room_info_deadline_at:
        embed.add_field(
            name="Room Setup Deadline",
            value=(
                f"Host must submit **Room ID** + **Password** before <t:{int(queue.room_info_deadline_at.timestamp())}:R>.\n"
                "The **Key** field is optional."
            ),
            inline=False,
        )
    if queue.cancel_reason:
        embed.add_field(name="Cancel Reason", value=queue.cancel_reason, inline=False)
    embed.set_footer(text="Buttons update live. Official match creation only happens after room info is locked.")
    return embed


def build_match_embed(snapshot: MatchSnapshot) -> discord.Embed:
    match = snapshot.match

    def render_player(player_id: int) -> str:
        discord_id = snapshot.player_discord_ids.get(player_id)
        return f"<@{discord_id}>" if discord_id else f"Player {player_id}"

    title = "Match Ready" if match.state == MatchState.MOVING else f"Official Match #{match.match_number:03d}"
    description = (
        f"**Ruleset**  `{_ruleset_label(match.ruleset_key.value)}`\n"
        f"**Mode**  `{match.mode.value.upper()}`\n"
        f"**Status**  `{_state_label(match.state.value).upper()}`"
    )
    if match.state == MatchState.MOVING:
        description += "\n**Live Step**  Building voice rooms and moving players now."
    embed = discord.Embed(
        title=title,
        description=description,
        colour=STATUS_COLORS[match.state],
    )
    embed.add_field(
        name=f"Team 1  [{len(snapshot.team1_ids)}/{match.team_size}]",
        value=_team_value(snapshot.team1_ids, match.team_size, render_player),
        inline=True,
    )
    embed.add_field(
        name=f"Team 2  [{len(snapshot.team2_ids)}/{match.team_size}]",
        value=_team_value(snapshot.team2_ids, match.team_size, render_player),
        inline=True,
    )
    live_lines: list[str] = []
    if match.team1_voice_channel_id:
        live_lines.append(f"Team 1 VC: <#{match.team1_voice_channel_id}>")
    if match.team2_voice_channel_id:
        live_lines.append(f"Team 2 VC: <#{match.team2_voice_channel_id}>")
    if match.result_channel_id:
        live_lines.append(f"Result Room: <#{match.result_channel_id}>")
    if live_lines:
        embed.add_field(name="Live Rooms", value="\n".join(live_lines), inline=False)
    if match.room_code:
        room_lines = [f"Room ID: `{match.room_code}`"]
        if match.room_password:
            room_lines.append(f"Password: `{match.room_password}`")
        if match.room_notes:
            room_lines.append(f"Key: `{match.room_notes}`")
        embed.add_field(name="Room Access", value="\n".join(room_lines), inline=False)
    if match.result_deadline_at and match.state in {MatchState.LIVE, MatchState.RESULT_PENDING}:
        embed.add_field(
            name="Result Window",
            value=f"Vote closes <t:{int(match.result_deadline_at.timestamp())}:R>.",
            inline=False,
        )
    embed.add_field(
        name="Result Progress",
        value=f"Votes submitted: `{len(snapshot.votes)}/{len(snapshot.players)}`",
        inline=False,
    )
    embed.set_footer(text="Use the result buttons below to submit, confirm, or force-resolve the match outcome.")
    return embed
