from __future__ import annotations

import discord

from highlight_manager.modules.common.enums import MatchPlayerResult, MatchResultPhase, MatchState, QueueState
from highlight_manager.modules.matches.types import (
    MatchReviewInboxItem,
    MatchRoomUpdateHistoryItem,
    MatchSnapshot,
    QueueSnapshot,
)
from highlight_manager.ui import theme
from highlight_manager.ui.brand import apply_embed_chrome


# â”€â”€ Status colors â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

# â”€â”€ Status emoji â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
_STATE_EMOJI = {
    QueueState.QUEUE_OPEN: "ðŸŸ¢",
    QueueState.FILLING: "ðŸ”µ",
    QueueState.READY_CHECK: "âš¡",
    QueueState.FULL_PENDING_ROOM_INFO: "ðŸ”‘",
    QueueState.QUEUE_CANCELLED: "ðŸ”´",
    QueueState.CONVERTED_TO_MATCH: "âœ…",
    MatchState.CREATED: "ðŸ”µ",
    MatchState.MOVING: "ðŸŸ ",
    MatchState.LIVE: "âš”ï¸",
    MatchState.RESULT_PENDING: "ðŸ—³ï¸",
    MatchState.CONFIRMED: "âœ…",
    MatchState.CANCELLED: "ðŸ”´",
    MatchState.EXPIRED: "ðŸŸ ",
    MatchState.FORCE_CLOSED: "ðŸ”´",
}


def _state_label(value: str) -> str:
    return value.replace("_", " ").title()


def _ruleset_label(raw_value: str) -> str:
    return raw_value.replace("_", " ").title()


def _ruleset_emoji(raw_value: str) -> str:
    mapping = {
        "apostado": "ðŸ’°",
        "highlight": "ðŸ”¦",
        "esport": "ðŸ†",
    }
    return mapping.get(raw_value, "âš”ï¸")


def _queue_cancel_reason_text(raw_value: str) -> str:
    mapping = {
        "empty_queue": "Queue cancelled because no players remained.",
        "host_left": "Queue cancelled because the host left before match creation.",
        "locked_queue_player_left": "Queue cancelled because a player left after teams were locked.",
        "Player left queue.": "Queue cancelled because a player left.",
        "queue_timeout": "Queue expired before enough players joined.",
        "ready_check_timeout": "Ready check expired before everyone pressed Ready.",
        "room_info_timeout": "Room info was not submitted before the deadline.",
    }
    return mapping.get(raw_value, raw_value)


def _team_value(player_ids: list[int], team_size: int, render_player, *, ready_ids: set[int] | None = None) -> str:
    if not player_ids:
        return "\n".join(f"`{i+1}.` â”€ â”€ â”€" for i in range(team_size))
    lines = []
    for i, player_id in enumerate(player_ids):
        ready_mark = ""
        if ready_ids is not None:
            ready_mark = " âœ…" if player_id in ready_ids else " â³"
        lines.append(f"`{i+1}.` {render_player(player_id)}{ready_mark}")
    remaining = max(team_size - len(player_ids), 0)
    for i in range(remaining):
        lines.append(f"`{len(player_ids)+i+1}.` â”€ â”€ â”€")
    return "\n".join(lines)


def build_queue_embed(snapshot: QueueSnapshot) -> discord.Embed:
    queue = snapshot.queue

    def render_player(player_id: int) -> str:
        discord_id = snapshot.player_discord_ids.get(player_id)
        return f"<@{discord_id}>" if discord_id else f"Player {player_id}"

    creator_discord_id = snapshot.player_discord_ids.get(queue.creator_player_id)
    creator_text = f"<@{creator_discord_id}>" if creator_discord_id else f"Player {queue.creator_player_id}"
    state_emoji = _STATE_EMOJI.get(queue.state, "â¬œ")
    ruleset_emoji = _ruleset_emoji(queue.ruleset_key.value)

    filled = len(snapshot.team1_ids) + len(snapshot.team2_ids)
    total_needed = queue.team_size * 2
    fill_bar = theme.progress_bar(filled, total_needed, length=12)

    status_line = {
        QueueState.QUEUE_OPEN: "Lobby is open â€” pick your side.",
        QueueState.FILLING: f"Filling up â€” `{filled}/{total_needed}` players.",
        QueueState.READY_CHECK: "All slots filled â€” waiting for everyone to press **Ready**.",
        QueueState.FULL_PENDING_ROOM_INFO: "Teams locked - host must submit **Room ID** + **Password**.",
        QueueState.QUEUE_CANCELLED: "This queue was cancelled.",
        QueueState.CONVERTED_TO_MATCH: "âœ… Converted into an official live match.",
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
        name=f"ðŸ”´ Team 1  [{len(snapshot.team1_ids)}/{queue.team_size}]",
        value=_team_value(snapshot.team1_ids, queue.team_size, render_player, ready_ids=ready_ids),
        inline=True,
    )
    embed.add_field(
        name=f"ðŸ”µ Team 2  [{len(snapshot.team2_ids)}/{queue.team_size}]",
        value=_team_value(snapshot.team2_ids, queue.team_size, render_player, ready_ids=ready_ids),
        inline=True,
    )

    detail_lines = [
        f"**Ruleset** `{_ruleset_label(queue.ruleset_key.value)}`",
        f"**Mode** `{queue.mode.value.upper()}`",
        f"**Slots** `{theme.slot_display(filled, total_needed)}`",
    ]
    embed.add_field(name="Queue Details", value="\n".join(detail_lines), inline=False)

    if queue.state == QueueState.READY_CHECK and queue.room_info_deadline_at:
        embed.add_field(
            name="Ready Check Deadline",
            value=f"Everyone must press **Ready** before <t:{int(queue.room_info_deadline_at.timestamp())}:R>.",
            inline=False,
        )
    elif queue.state == QueueState.FULL_PENDING_ROOM_INFO and queue.room_info_deadline_at:
        embed.add_field(
            name=f"{theme.EMOJI_KEY} Room Setup Deadline",
            value=(
                f"Host must submit **Room ID** + **Password** before <t:{int(queue.room_info_deadline_at.timestamp())}:R>.\n"
                "The **Key** field is optional. Use **Transfer Host** first if someone else should handle setup."
            ),
            inline=False,
        )
    if queue.cancel_reason:
        embed.add_field(name="âŒ Cancel Reason", value=_queue_cancel_reason_text(queue.cancel_reason), inline=False)
    return apply_embed_chrome(embed, footer="HIGHLIGHT MANGER  •  Buttons update live")


def build_public_match_embed(snapshot: MatchSnapshot) -> discord.Embed:
    match = snapshot.match

    def render_player(player_id: int) -> str:
        discord_id = snapshot.player_discord_ids.get(player_id)
        return f"<@{discord_id}>" if discord_id else f"Player {player_id}"

    state_emoji = _STATE_EMOJI.get(match.state, "â¬œ")
    ruleset_emoji = _ruleset_emoji(match.ruleset_key.value)

    title = (
        f"{ruleset_emoji} Match Started"
        if match.state in {MatchState.MOVING, MatchState.LIVE, MatchState.RESULT_PENDING}
        else f"{ruleset_emoji} Official Match #{match.match_number:03d}"
    )
    description = (
        f"**Ruleset** `{_ruleset_label(match.ruleset_key.value)}`  â€¢  **Mode** `{match.mode.value.upper()}`\n"
        f"{state_emoji} **{_state_label(match.state.value).upper()}**"
    )
    if match.state == MatchState.MOVING:
        description += f"\n{theme.EMOJI_PENDING} Building voice rooms and moving playersâ€¦"
    elif match.state in {MatchState.LIVE, MatchState.RESULT_PENDING}:
        description += f"\n{theme.EMOJI_SWORD} {_public_phase_summary(snapshot)}"
    elif match.state == MatchState.CONFIRMED:
        description += f"\n{theme.EMOJI_CHECK} Match confirmed â€” rewards applied."
    elif match.state == MatchState.CANCELLED:
        description += "\nâŒ Match cancelled by the creator."
    elif match.state == MatchState.FORCE_CLOSED:
        description += "\nðŸ”´ Match was force closed by staff."
    elif match.state == MatchState.EXPIRED:
        description += f"\n{theme.EMOJI_PENDING} Voting expired â€” staff review required."

    embed = discord.Embed(title=title, description=description, colour=STATUS_COLORS.get(match.state, theme.SURFACE))
    embed.add_field(
        name=f"ðŸ”´ Team 1  [{len(snapshot.team1_ids)}/{match.team_size}]",
        value=_team_value(snapshot.team1_ids, match.team_size, render_player),
        inline=True,
    )
    embed.add_field(
        name=f"ðŸ”µ Team 2  [{len(snapshot.team2_ids)}/{match.team_size}]",
        value=_team_value(snapshot.team2_ids, match.team_size, render_player),
        inline=True,
    )

    if match.state not in _TERMINAL_MATCH_STATES:
        live_lines: list[str] = []
        if match.team1_voice_channel_id:
            live_lines.append(f"ðŸ”´ Team 1 VC: <#{match.team1_voice_channel_id}>")
        if match.team2_voice_channel_id:
            live_lines.append(f"ðŸ”µ Team 2 VC: <#{match.team2_voice_channel_id}>")
        if match.result_channel_id:
            live_lines.append(f"ðŸ“‹ Result Room: <#{match.result_channel_id}>")
        if live_lines:
            embed.add_field(name="ðŸŽ® Live Rooms", value="\n".join(live_lines), inline=False)
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
            embed.add_field(name="âŒ Cancel Reason", value=match.cancel_reason, inline=False)
        if match.force_close_reason:
            embed.add_field(name="ðŸ”´ Staff Reason", value=match.force_close_reason, inline=False)
    return apply_embed_chrome(embed, footer="HIGHLIGHT MANGER  •  Official Match")


def build_result_match_embed(snapshot: MatchSnapshot) -> discord.Embed:
    match = snapshot.match

    def render_player(player_id: int) -> str:
        discord_id = snapshot.player_discord_ids.get(player_id)
        return f"<@{discord_id}>" if discord_id else f"Player {player_id}"

    state_emoji = _STATE_EMOJI.get(match.state, "â¬œ")
    embed = discord.Embed(
        title=f"ðŸ“‹ Result Room â€” Match #{match.match_number:03d}",
        description=(
            f"**Ruleset** `{_ruleset_label(match.ruleset_key.value)}`  â€¢  **Mode** `{match.mode.value.upper()}`\n"
            f"{state_emoji} **{_state_label(match.state.value).upper()}**\n"
            f"**Flow** {_result_room_flow_text(snapshot)}"
        ),
        colour=STATUS_COLORS.get(match.state, theme.SURFACE),
    )
    embed.add_field(
        name=f"ðŸ”´ Team 1  [{len(snapshot.team1_ids)}/{match.team_size}]",
        value=_team_value(snapshot.team1_ids, match.team_size, render_player),
        inline=True,
    )
    embed.add_field(
        name=f"ðŸ”µ Team 2  [{len(snapshot.team2_ids)}/{match.team_size}]",
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
        name=f"ðŸ—³ï¸ Result Progress  [{voted}/{needed}]",
        value=f"```{vote_bar}```\n" + ("\n".join(vote_indicators) if vote_indicators else "No active voters."),
        inline=False,
    )

    if match.state in _TERMINAL_MATCH_STATES:
        summary_text = _build_match_summary(snapshot)
        if summary_text:
            embed.add_field(name=f"{theme.EMOJI_TROPHY} Summary", value=summary_text, inline=False)
    elif snapshot.result_phase == MatchResultPhase.STAFF_REVIEW:
        apply_embed_chrome(embed, footer="HIGHLIGHT MANGER  •  Player voting closed - staff review required")
    elif not snapshot.votes:
        apply_embed_chrome(embed, footer="HIGHLIGHT MANGER  •  Vote Result to submit the match outcome")
    else:
        apply_embed_chrome(embed, footer="HIGHLIGHT MANGER  •  Votes open - room info locked after first vote")
    return embed


def build_match_review_inbox_embed(
    items: list[MatchReviewInboxItem],
    *,
    limit: int = 10,
) -> discord.Embed:
    display_limit = min(max(limit, 1), 25)
    display_items = items[:display_limit]
    embed = discord.Embed(
        title="Unresolved Match Review Inbox",
        colour=theme.WARNING if display_items else theme.SUCCESS,
    )
    if not display_items:
        embed.description = "No unresolved matches need staff review right now."
        apply_embed_chrome(embed, footer="HIGHLIGHT MANGER  •  Staff review inbox")
        return embed

    embed.description = (
        f"Showing **{len(display_items)}** unresolved match"
        f"{'' if len(display_items) == 1 else 'es'} needing staff attention."
    )
    for item in display_items:
        snapshot = item.snapshot
        match = snapshot.match
        ruleset = _ruleset_label(match.ruleset_key.value)
        mode = match.mode.value.upper()
        state = _state_label(match.state.value)
        phase = _state_label(snapshot.result_phase.value)
        vote_progress = f"{len(snapshot.phase_votes)}/{len(snapshot.active_voter_ids)}"
        result_room = f"<#{match.result_channel_id}>" if match.result_channel_id else "`Not recorded`"
        value = "\n".join(
            [
                f"**{ruleset} {mode}** | `{state}` / `{phase}`",
                f"Reason: **{item.reason_label}**",
                *(["Detail: " + item.staff_detail] if item.staff_detail else []),
                f"Votes: `{vote_progress}`",
                f"Result room: {result_room}",
                (
                    "Resolve: "
                    f"`/match force-result match_number:{match.match_number}` or "
                    f"`/match force-close match_number:{match.match_number}`"
                ),
            ]
        )
        embed.add_field(
            name=f"Match #{match.match_number:03d} - {item.reason_label}",
            value=value,
            inline=False,
        )
    return apply_embed_chrome(embed, footer="HIGHLIGHT MANGER  •  Staff-only, read-only inbox")


def build_match_rehost_history_embed(
    snapshot: MatchSnapshot,
    items: list[MatchRoomUpdateHistoryItem],
    *,
    limit: int = 10,
) -> discord.Embed:
    match = snapshot.match
    display_limit = min(max(limit, 1), 10)
    display_items = items[:display_limit]
    embed = discord.Embed(
        title=f"Match Rehost History - Match #{match.match_number:03d}",
        description=(
            f"**Ruleset** `{_ruleset_label(match.ruleset_key.value)}`  |  "
            f"**Mode** `{match.mode.value.upper()}`\n"
            f"**State** `{_state_label(match.state.value)}`  |  "
            f"**Rehost Count** `{match.rehost_count}`"
        ),
        colour=theme.WARNING if display_items else STATUS_COLORS.get(match.state, theme.SURFACE),
    )
    if not display_items:
        embed.add_field(
            name="History",
            value="No room-info edits have been recorded for this match.",
            inline=False,
        )
        apply_embed_chrome(embed, footer="HIGHLIGHT MANGER  •  Staff-only, read-only rehost history")
        return embed

    for index, item in enumerate(display_items, start=1):
        relative_time = f"<t:{int(item.created_at.timestamp())}:R>"
        if item.actor_discord_id is not None:
            actor_text = f"<@{item.actor_discord_id}>"
        elif item.actor_player_id is not None:
            actor_text = f"Player {item.actor_player_id}"
        else:
            actor_text = "Unknown"

        lines = [f"Actor: {actor_text}"]
        if item.rehost_count_before is not None and item.rehost_count_after is not None:
            lines.append(f"Rehost count: `{item.rehost_count_before} -> {item.rehost_count_after}`")
        if item.legacy:
            lines.append("Detailed room changes were not recorded for this older update.")
        else:
            lines.extend(
                [
                    "**Before**",
                    _render_room_history_block(
                        item.before_room_code,
                        item.before_room_password,
                        item.before_room_notes,
                    ),
                    "**After**",
                    _render_room_history_block(
                        item.after_room_code,
                        item.after_room_password,
                        item.after_room_notes,
                    ),
                ]
            )
        embed.add_field(
            name=f"Edit {index} - {relative_time}",
            value="\n".join(lines),
            inline=False,
        )

    return apply_embed_chrome(embed, footer="HIGHLIGHT MANGER  •  Staff-only, read-only rehost history")


def build_match_embed(snapshot: MatchSnapshot) -> discord.Embed:
    return build_public_match_embed(snapshot)


def _render_room_history_block(room_code: str | None, room_password: str | None, room_notes: str | None) -> str:
    return "\n".join(
        [
            f"```Room ID   : {room_code or 'â€”'}",
            f"Password  : {room_password or 'â€”'}",
            f"Key       : {room_notes or 'â€”'}",
            "```",
        ]
    )


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
                    lines.append(f"â€¦ and {len(coin_lines) - 6} more")

        return "\n".join(lines)
    if match.state == MatchState.CANCELLED:
        return "âŒ Match cancelled by the creator before results were finalized."
    if match.state == MatchState.FORCE_CLOSED:
        return "ðŸ”´ Match force closed by staff."
    if match.state == MatchState.EXPIRED:
        return f"{theme.EMOJI_PENDING} Voting expired â€” staff review required."
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
        return f"{theme.EMOJI_BOOM} Captain voting failed â€” full-team backup voting is open."
    return f"{theme.EMOJI_LOCK} Player voting is closed â€” staff must resolve."


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
        return f"ðŸ”´ Team 1 Captain: {team1_captain}\nðŸ”µ Team 2 Captain: {team2_captain}"
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

