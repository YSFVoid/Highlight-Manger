from __future__ import annotations

import discord

from highlight_manager.modules.common.enums import MatchState, QueueState
from highlight_manager.modules.diagnostics.types import AdminDiagnosticsSnapshot
from highlight_manager.ui import theme
from highlight_manager.ui.brand import apply_embed_chrome


QUEUE_STATE_ORDER = [
    QueueState.QUEUE_OPEN,
    QueueState.FILLING,
    QueueState.READY_CHECK,
    QueueState.FULL_PENDING_ROOM_INFO,
]
MATCH_STATE_ORDER = [
    MatchState.CREATED,
    MatchState.MOVING,
    MatchState.LIVE,
    MatchState.RESULT_PENDING,
    MatchState.EXPIRED,
]


def build_admin_diagnostics_embed(snapshot: AdminDiagnosticsSnapshot) -> discord.Embed:
    embed = discord.Embed(
        title="Admin System Diagnostics",
        description=f"Aggregate operational health collected <t:{int(snapshot.collected_at.timestamp())}:R>.",
        colour=_status_colour(snapshot),
    )
    unresolved = snapshot.unresolved_matches
    embed.add_field(
        name="Unresolved Matches",
        value=(
            f"Staff review: **{unresolved.staff_review}**\n"
            f"Overdue: **{unresolved.overdue}**\n"
            f"Disputed: **{unresolved.disputed}**\n"
            f"Total: **{unresolved.total}**"
        ),
        inline=True,
    )
    embed.add_field(
        name="Active Queues",
        value=_format_state_counts(snapshot.queue_counts, QUEUE_STATE_ORDER),
        inline=True,
    )
    embed.add_field(
        name="Active Matches",
        value=_format_state_counts(snapshot.match_counts, MATCH_STATE_ORDER),
        inline=True,
    )
    backlog = snapshot.backlog
    embed.add_field(
        name="Backlog",
        value=(
            f"Room reminders due: **{backlog.room_info_reminders}**\n"
            f"Room timeouts due: **{backlog.room_info_timeouts}**\n"
            f"Captain fallback due: **{backlog.captain_fallback_opens}**\n"
            f"Result expirations due: **{backlog.result_timeouts}**\n"
            f"Stale activity rows: **{backlog.stale_activity_rows}**\n"
            f"Missing match resources: **{backlog.missing_match_resources}**"
        ),
        inline=False,
    )
    embed.add_field(
        name="Runtime",
        value=_runtime_value(snapshot),
        inline=False,
    )
    embed.add_field(
        name="Persistent Voice",
        value=_voice_value(snapshot),
        inline=True,
    )
    embed.add_field(
        name="Schema",
        value=_schema_value(snapshot),
        inline=True,
    )
    return apply_embed_chrome(embed, footer="HIGHLIGHT MANGER  •  Aggregate admin diagnostics")


def _format_state_counts(counts: dict, order: list) -> str:
    lines = [f"{_state_label(state.value)}: **{counts.get(state, 0)}**" for state in order]
    lines.append(f"Total: **{sum(counts.get(state, 0) for state in order)}**")
    return "\n".join(lines)


def _runtime_value(snapshot: AdminDiagnosticsSnapshot) -> str:
    startup = snapshot.startup_health
    command_sync = snapshot.command_sync_status
    scheduler = snapshot.scheduler_summary
    cleanup = snapshot.cleanup_summary
    return (
        f"DB ready: **{_bool_text(startup.get('db_ready'))}**\n"
        f"Views restored: **{startup.get('views_restored', 'unknown')}**\n"
        f"Assets warmed: **{_bool_text(startup.get('assets_warmed'))}**\n"
        f"Command sync: `{command_sync.get('scope', 'unknown')}` / "
        f"success=`{command_sync.get('success', 'unknown')}` / "
        f"count=`{command_sync.get('count', 'unknown')}`\n"
        f"Scheduler last run: `{scheduler.get('ran_at', 'not yet')}`\n"
        f"Cleanup last run: `{cleanup.get('ran_at', 'not yet')}`"
    )


def _voice_value(snapshot: AdminDiagnosticsSnapshot) -> str:
    voice = snapshot.voice
    if voice is None:
        return "State: `unknown`"
    lines = [
        f"Enabled: **{_bool_text(voice.enabled)}**",
        f"State: `{voice.state}`",
        f"Configured channel: {_channel_text(voice.channel_id)}",
    ]
    if voice.connected_channel_id:
        lines.append(f"Connected channel: {_channel_text(voice.connected_channel_id)}")
    if voice.retry_in_seconds is not None:
        lines.append(f"Retry in: **{voice.retry_in_seconds}s**")
    if voice.reason:
        lines.append(f"Reason: {voice.reason}")
    return "\n".join(lines)


def _schema_value(snapshot: AdminDiagnosticsSnapshot) -> str:
    schema = snapshot.schema
    if schema is None:
        return "Status: `unknown`"
    revision = schema.revision or "unknown"
    return f"Status: `{schema.status}`\nRevision: `{revision}`\n{schema.details}"


def _status_colour(snapshot: AdminDiagnosticsSnapshot) -> int:
    if snapshot.schema and snapshot.schema.status == "warning":
        return theme.WARNING
    if snapshot.unresolved_matches.total or snapshot.backlog.stale_activity_rows:
        return theme.WARNING
    if snapshot.voice and snapshot.voice.state not in {"connected", "disabled", "unknown"}:
        return theme.WARNING
    return theme.SUCCESS


def _state_label(value: str) -> str:
    return value.replace("_", " ").title()


def _bool_text(value: object) -> str:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return "unknown"


def _channel_text(channel_id: int | None) -> str:
    return f"<#{channel_id}>" if channel_id else "Not configured"
