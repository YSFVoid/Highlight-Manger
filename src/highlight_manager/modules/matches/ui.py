from __future__ import annotations

import discord

from highlight_manager.modules.common.enums import MatchPlayerResult, MatchResultPhase, MatchState, QueueState
from highlight_manager.modules.matches.types import MatchSnapshot, QueueSnapshot
from highlight_manager.modules.ranks.calculator import resolve_tier, tier_emoji
from highlight_manager.ui import theme


# ── Status colors ────────────────────────────────────────────────────
STATUS_COLORS = {
    QueueState.QUEUE_OPEN: theme.SURFACE,
    QueueState.FILLING: theme.PRIMARY,
    QueueState.READY_CHECK: theme.ACCENT,
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

_TERMINAL_MATCH_STATES = {
    MatchState.CONFIRMED,
    MatchState.CANCELLED,
    MatchState.FORCE_CLOSED,
    MatchState.EXPIRED,
}

# ── Status emoji ─────────────────────────────────────────────────────
_STATE_EMOJI = {
    QueueState.QUEUE_OPEN: "🟢",
    QueueState.FILLING: "🔵",
    QueueState.READY_CHECK: "⚡",
    QueueState.FULL_PENDING_ROOM_INFO: "🔑",
    QueueState.QUEUE_CANCELLED: "🔴",
    QueueState.CONVERTED_TO_MATCH: "✅",
    MatchState.CREATED: "🔵",
    MatchState.MOVING: "🟠",
    MatchState.LIVE: "⚔️",
    MatchState.RESULT_PENDING: "🗳️",
    MatchState.CONFIRMED: "✅",
    MatchState.CANCELLED: "🔴",
    MatchState.EXPIRED: "🟠",
    MatchState.FORCE_CLOSED: "🔴",
}


def _state_label(value: str) -> str:
    return value.replace("_", " ").title()


def _ruleset_label(raw_value: str) -> str:
    return raw_value.replace("_", " ").title()


def _ruleset_emoji(raw_value: str) -> str:
    mapping = {
        "apostado": "💰",
        "highlight": "🔦",
        "esport": "🏆",
    }
    return mapping.get(raw_value, "⚔️")


def _team_value(player_ids: list[int], team_size: int, render_player, *, ready_ids: set[int] | None = None) -> str:
    if not player_ids:
        return "\n".join(f"`{i+1}.` ─ ─ ─" for i in range(team_size))
    lines = []
    for i, player_id in enumerate(player_ids):
        ready_mark = ""
        if ready_ids is not None:
            ready_mark = " ✅" if player_id in ready_ids else " ⏳"
        lines.append(f"`{i+1}.` {render_player(player_id)}{ready_mark}")
    remaining = max(team_size - len(player_ids), 0)
    for i in range(remaining):
        lines.append(f"`{len(player_ids)+i+1}.` ─ ─ ─")
    return "\n".join(lines)


def build_queue_embed(snapshot: QueueSnapshot) -> discord.Embed:
    queue = snapshot.queue

    def render_player(player_id: int) -> str:
        discord_id = snapshot.player_discord_ids.get(player_id)
        return f"<@{discord_id}>" if discord_id else f"Player {player_id}"

    creator_discord_id = snapshot.player_discord_ids.get(queue.creator_player_id)
    creator_text = f"<@{creator_discord_id}>" if creator_discord_id else f"Player {queue.creator_player_id}"
    state_emoji = _STATE_EMOJI.get(queue.state, "⬜")
    ruleset_emoji = _ruleset_emoji(queue.ruleset_key.value)

    filled = len(snapshot.team1_ids) + len(snapshot.team2_ids)
    total_needed = queue.team_size * 2
    fill_bar = theme.progress_bar(filled, total_needed, length=12)

    status_line = {
        QueueState.QUEUE_OPEN: "Lobby is open — pick your side.",
        QueueState.FILLING: f"Filling up — `{filled}/{total_needed}` players.",
        QueueState.READY_CHECK: "All slots filled — waiting for everyone to press **Ready**.",
        QueueState.FULL_PENDING_ROOM_INFO: "Teams locked — host must submit **Room ID** + **Password**.",
        QueueState.QUEUE_CANCELLED: "This queue was cancelled.",
        QueueState.CONVERTED_TO_MATCH: "✅ Converted into an official live match.",
    }[queue.state]

    embed = discord.Embed(
        title=f"{ruleset_emoji} {_ruleset_label(queue.ruleset_key.value)} {queue.mode.value.upper()} Lobby",
        description=(
            f"{state_emoji} **{_state_label(queue.state.value).upper()}**\n"
            f"```{fill_bar}  {filled}/{total_needed}```\n"
            f"**Host** {creator_text}\n"
            f"{status_line}"
        ),
        colour=STATUS_COLORS.get(queue.state, theme.SURFACE),
    )

    # Show ready marks only during ready check
    ready_ids = snapshot.ready_player_ids if queue.state == QueueState.READY_CHECK else None

    embed.add_field(
        name=f"🔴 Team 1  [{len(snapshot.team1_ids)}/{queue.team_size}]",
        value=_team_value(snapshot.team1_ids, queue.team_size, render_player, ready_ids=ready_ids),
        inline=True,
    )
    embed.add_field(
        name=f"🔵 Team 2  [{len(snapshot.team2_ids)}/{queue.team_size}]",
        value=_team_value(snapshot.team2_ids, queue.team_size, render_player, ready_ids=ready_ids),
        inline=True,
    )

    detail_lines = [
        f"**Ruleset** `{_ruleset_label(queue.ruleset_key.value)}`",
        f"**Mode** `{queue.mode.value.upper()}`",
        f"**Slots** `{theme.slot_display(filled, total_needed)}`",
    ]
    embed.add_field(name="Queue Details", value="\n".join(detail_lines), inline=False)

    if queue.room_info_deadline_at:
        embed.add_field(
            name=f"{theme.EMOJI_KEY} Room Setup Deadline",
            value=(
                f"Host must submit **Room ID** + **Password** before <t:{int(queue.room_info_deadline_at.timestamp())}:R>.\n"
                "The **Key** field is optional."
            ),
            inline=False,
        )
    if queue.cancel_reason:
        embed.add_field(name="❌ Cancel Reason", value=queue.cancel_reason, inline=False)
    embed.set_footer(text="Highlight Manger  •  Buttons update live")
    return embed


def build_public_match_embed(snapshot: MatchSnapshot) -> discord.Embed:
    match = snapshot.match

    def render_player(player_id: int) -> str:
        discord_id = snapshot.player_discord_ids.get(player_id)
        return f"<@{discord_id}>" if discord_id else f"Player {player_id}"

    state_emoji = _STATE_EMOJI.get(match.state, "⬜")
    ruleset_emoji = _ruleset_emoji(match.ruleset_key.value)

    title = (
        f"{ruleset_emoji} Match Started"
        if match.state in {MatchState.MOVING, MatchState.LIVE, MatchState.RESULT_PENDING}
        else f"{ruleset_emoji} Official Match #{match.match_number:03d}"
    )
    description = (
        f"**Ruleset** `{_ruleset_label(match.ruleset_key.value)}`  •  **Mode** `{match.mode.value.upper()}`\n"
        f"{state_emoji} **{_state_label(match.state.value).upper()}**"
    )
    if match.state == MatchState.MOVING:
        description += f"\n{theme.EMOJI_PENDING} Building voice rooms and moving players…"
    elif match.state in {MatchState.LIVE, MatchState.RESULT_PENDING}:
        description += f"\n{theme.EMOJI_SWORD} {_public_phase_summary(snapshot)}"
    elif match.state == MatchState.CONFIRMED:
        description += f"\n{theme.EMOJI_CHECK} Match confirmed — rewards applied."
    elif match.state == MatchState.CANCELLED:
        description += "\n❌ Match cancelled by the creator."
    elif match.state == MatchState.FORCE_CLOSED:
        description += "\n🔴 Match was force closed by staff."
    elif match.state == MatchState.EXPIRED:
        description += f"\n{theme.EMOJI_PENDING} Voting expired — staff review required."

    embed = discord.Embed(title=title, description=description, colour=STATUS_COLORS.get(match.state, theme.SURFACE))
    embed.add_field(
        name=f"🔴 Team 1  [{len(snapshot.team1_ids)}/{match.team_size}]",
        value=_team_value(snapshot.team1_ids, match.team_size, render_player),
        inline=True,
    )
    embed.add_field(
        name=f"🔵 Team 2  [{len(snapshot.team2_ids)}/{match.team_size}]",
        value=_team_value(snapshot.team2_ids, match.team_size, render_player),
        inline=True,
    )

    if match.state not in _TERMINAL_MATCH_STATES:
        live_lines: list[str] = []
        if match.team1_voice_channel_id:
            live_lines.append(f"🔴 Team 1 VC: <#{match.team1_voice_channel_id}>")
        if match.team2_voice_channel_id:
            live_lines.append(f"🔵 Team 2 VC: <#{match.team2_voice_channel_id}>")
        if match.result_channel_id:
            live_lines.append(f"📋 Result Room: <#{match.result_channel_id}>")
        if live_lines:
            embed.add_field(name="🎮 Live Rooms", value="\n".join(live_lines), inline=False)
        if match.room_code:
            room_lines = [f"```Room ID   : {match.room_code}"]
            if match.room_password:
                room_lines.append(f"Password  : {match.room_password}")
            if match.room_notes:
                room_lines.append(f"Key       : {match.room_notes}")
            room_lines.append("```")
            embed.add_field(name=f"{theme.EMOJI_KEY} Room Access", value="\n".join(room_lines), inline=False)
    else:
        summary_text = _build_match_summary(snapshot)
        if summary_text:
            embed.add_field(name=f"{theme.EMOJI_TROPHY} Final Summary", value=summary_text, inline=False)
        if match.cancel_reason:
            embed.add_field(name="❌ Cancel Reason", value=match.cancel_reason, inline=False)
        if match.force_close_reason:
            embed.add_field(name="🔴 Staff Reason", value=match.force_close_reason, inline=False)
    embed.set_footer(text="Highlight Manger  •  Official Match")
    return embed


def build_result_match_embed(snapshot: MatchSnapshot) -> discord.Embed:
    match = snapshot.match

    def render_player(player_id: int) -> str:
        discord_id = snapshot.player_discord_ids.get(player_id)
        return f"<@{discord_id}>" if discord_id else f"Player {player_id}"

    state_emoji = _STATE_EMOJI.get(match.state, "⬜")
    embed = discord.Embed(
        title=f"📋 Result Room — Match #{match.match_number:03d}",
        description=(
            f"**Ruleset** `{_ruleset_label(match.ruleset_key.value)}`  •  **Mode** `{match.mode.value.upper()}`\n"
            f"{state_emoji} **{_state_label(match.state.value).upper()}**\n"
            f"**Flow** {_result_room_flow_text(snapshot)}"
        ),
        colour=STATUS_COLORS.get(match.state, theme.SURFACE),
    )
    embed.add_field(
        name=f"🔴 Team 1  [{len(snapshot.team1_ids)}/{match.team_size}]",
        value=_team_value(snapshot.team1_ids, match.team_size, render_player),
        inline=True,
    )
    embed.add_field(
        name=f"🔵 Team 2  [{len(snapshot.team2_ids)}/{match.team_size}]",
        value=_team_value(snapshot.team2_ids, match.team_size, render_player),
        inline=True,
    )

    if match.room_code:
        room_lines = [f"```Room ID   : {match.room_code}"]
        if match.room_password:
            room_lines.append(f"Password  : {match.room_password}")
        if match.room_notes:
            room_lines.append(f"Key       : {match.room_notes}")
        room_lines.append("```")
        embed.add_field(name=f"{theme.EMOJI_KEY} Room Access", value="\n".join(room_lines), inline=False)

    authority_value = _result_room_authority_value(snapshot)
    if authority_value:
        embed.add_field(name=f"{theme.EMOJI_CROWN} Voting Authority", value=authority_value, inline=False)

    if match.state in {MatchState.LIVE, MatchState.RESULT_PENDING}:
        phase_deadline = _phase_deadline(snapshot)
        if phase_deadline is not None:
            phase_label = f"{theme.EMOJI_PENDING} Captain Window" if snapshot.result_phase == MatchResultPhase.CAPTAIN else f"{theme.EMOJI_PENDING} Fallback Window"
            embed.add_field(
                name=phase_label,
                value=f"Decision window closes <t:{int(phase_deadline.timestamp())}:R>.",
                inline=False,
            )
    if match.result_deadline_at and match.state in {MatchState.LIVE, MatchState.RESULT_PENDING}:
        embed.add_field(
            name=f"{theme.EMOJI_BELL} Final Staff Deadline",
            value=f"Player voting closes <t:{int(match.result_deadline_at.timestamp())}:R>.",
            inline=False,
        )

    # Vote progress with visual indicators
    voted = len(snapshot.phase_votes)
    needed = len(snapshot.active_voter_ids)
    vote_bar = theme.progress_bar(voted, needed, length=8)
    vote_indicators = []
    voted_ids = {v.player_id for v in snapshot.phase_votes}
    for pid in snapshot.active_voter_ids:
        mark = theme.EMOJI_CHECK if pid in voted_ids else theme.EMOJI_PENDING
        vote_indicators.append(f"{mark} {render_player(pid)}")

    embed.add_field(
        name=f"🗳️ Result Progress  [{voted}/{needed}]",
        value=f"```{vote_bar}```\n" + ("\n".join(vote_indicators) if vote_indicators else "No active voters."),
        inline=False,
    )

    if match.state in _TERMINAL_MATCH_STATES:
        summary_text = _build_match_summary(snapshot)
        if summary_text:
            embed.add_field(name=f"{theme.EMOJI_TROPHY} Summary", value=summary_text, inline=False)
    elif snapshot.result_phase == MatchResultPhase.STAFF_REVIEW:
        embed.set_footer(text="Highlight Manger  •  Player voting closed — staff review required")
    elif not snapshot.votes:
        embed.set_footer(text="Highlight Manger  •  Vote Result to submit the match outcome")
    else:
        embed.set_footer(text="Highlight Manger  •  Votes open — room info locked after first vote")
    return embed


def build_match_embed(snapshot: MatchSnapshot) -> discord.Embed:
    return build_public_match_embed(snapshot)


def _build_match_summary(snapshot: MatchSnapshot) -> str | None:
    match = snapshot.match
    if match.state == MatchState.CONFIRMED:
        winner_team = _winner_team_number(snapshot)
        winner_mvp = _find_flagged_player(snapshot, winner=True)
        loser_mvp = _find_flagged_player(snapshot, winner=False)
        lines = [f"{theme.EMOJI_TROPHY} **Winner:** `Team {winner_team}`" if winner_team is not None else f"{theme.EMOJI_TROPHY} **Winner:** `Unknown`"]
        if winner_mvp:
            lines.append(f"{theme.EMOJI_STAR} **Winner MVP:** {winner_mvp}")
        if loser_mvp:
            lines.append(f"{theme.EMOJI_MEDAL} **Loser MVP:** {loser_mvp}")

        # Show per-player rating changes if available
        rating_lines = []
        for row in snapshot.players:
            if row.rating_delta is not None and row.rating_delta != 0:
                arrow = theme.EMOJI_UP if row.rating_delta > 0 else theme.EMOJI_DOWN
                delta_text = f"+{row.rating_delta}" if row.rating_delta > 0 else str(row.rating_delta)
                player_text = _render_snapshot_player(snapshot, row.player_id)
                rating_lines.append(f"{arrow} {player_text} `{delta_text}` ({row.rating_after})")
        if rating_lines:
            lines.append("")
            lines.append("**Rating Changes:**")
            lines.extend(rating_lines)

        # Show coin rewards if available
        if snapshot.coins_summary:
            coin_lines = []
            for player_id, rewards in snapshot.coins_summary.items():
                total = sum(rewards.values())
                if total > 0:
                    player_text = _render_snapshot_player(snapshot, player_id)
                    breakdown = " + ".join(f"{v} {k}" for k, v in rewards.items() if v > 0)
                    coin_lines.append(f"{theme.EMOJI_COIN} {player_text} `+{total}` ({breakdown})")
            if coin_lines:
                lines.append("")
                lines.append("**Coin Rewards:**")
                lines.extend(coin_lines[:6])  # Cap display at 6 players
                if len(coin_lines) > 6:
                    lines.append(f"… and {len(coin_lines) - 6} more")

        return "\n".join(lines)
    if match.state == MatchState.CANCELLED:
        return "❌ Match cancelled by the creator before results were finalized."
    if match.state == MatchState.FORCE_CLOSED:
        return "🔴 Match force closed by staff."
    if match.state == MatchState.EXPIRED:
        return f"{theme.EMOJI_PENDING} Voting expired — staff review required."
    return None


def _winner_team_number(snapshot: MatchSnapshot) -> int | None:
    winning_rows = [row for row in snapshot.players if row.result == MatchPlayerResult.WIN]
    if not winning_rows:
        return None
    return winning_rows[0].team_number


def _find_flagged_player(snapshot: MatchSnapshot, *, winner: bool) -> str | None:
    for row in snapshot.players:
        if winner and row.is_winner_mvp:
            return _render_snapshot_player(snapshot, row.player_id)
        if not winner and row.is_loser_mvp:
            return _render_snapshot_player(snapshot, row.player_id)
    return None


def _render_snapshot_player(snapshot: MatchSnapshot, player_id: int) -> str:
    discord_id = snapshot.player_discord_ids.get(player_id)
    return f"<@{discord_id}>" if discord_id else f"Player {player_id}"


def _public_phase_summary(snapshot: MatchSnapshot) -> str:
    if snapshot.result_phase == MatchResultPhase.CAPTAIN:
        return "Team captains are handling the result room."
    if snapshot.result_phase == MatchResultPhase.FALLBACK:
        return "Full-team backup voting is open."
    if snapshot.result_phase == MatchResultPhase.STAFF_REVIEW:
        return "Waiting for staff review."
    return "The official match is live."


def _result_room_flow_text(snapshot: MatchSnapshot) -> str:
    if snapshot.result_phase == MatchResultPhase.CAPTAIN:
        return f"{theme.EMOJI_CROWN} Captains decide the winner + MVPs first."
    if snapshot.result_phase == MatchResultPhase.FALLBACK:
        return f"{theme.EMOJI_BOOM} Captain voting failed — full-team backup voting is open."
    return f"{theme.EMOJI_LOCK} Player voting is closed — staff must resolve."


def _result_room_authority_value(snapshot: MatchSnapshot) -> str | None:
    if snapshot.result_phase == MatchResultPhase.CAPTAIN:
        team1_captain = (
            _render_snapshot_player(snapshot, snapshot.team1_captain_player_id)
            if snapshot.team1_captain_player_id is not None
            else "`Unassigned`"
        )
        team2_captain = (
            _render_snapshot_player(snapshot, snapshot.team2_captain_player_id)
            if snapshot.team2_captain_player_id is not None
            else "`Unassigned`"
        )
        return f"🔴 Team 1 Captain: {team1_captain}\n🔵 Team 2 Captain: {team2_captain}"
    if snapshot.result_phase == MatchResultPhase.FALLBACK:
        return "All match participants can vote in the backup phase."
    if snapshot.result_phase == MatchResultPhase.STAFF_REVIEW:
        return "Staff members only."
    return None


def _phase_deadline(snapshot: MatchSnapshot):
    if snapshot.result_phase == MatchResultPhase.CAPTAIN:
        return snapshot.match.captain_deadline_at
    if snapshot.result_phase == MatchResultPhase.FALLBACK:
        return snapshot.match.fallback_deadline_at
    return None
