from __future__ import annotations

import discord

from highlight_manager.db.models.moderation import AuditLogModel
from highlight_manager.ui import theme
from highlight_manager.ui.brand import apply_embed_chrome


def build_phase4_evidence_embed(audits: list[AuditLogModel], *, limit: int = 10) -> discord.Embed:
    embed = discord.Embed(
        title="Phase 4 Evidence Log",
        description=(
            "Recent evidence-backed post-launch improvement notes. "
            "Use these to choose Phase 4 work without feature drift."
        ),
        colour=theme.PRIMARY,
    )
    if not audits:
        embed.add_field(
            name="No evidence recorded",
            value="Use `/admin record-phase4-evidence` after live staff/player feedback or diagnostics evidence appears.",
            inline=False,
        )
        return apply_embed_chrome(embed, section="Phase 4 Evidence")

    for index, audit in enumerate(audits[: max(limit, 1)], start=1):
        metadata = audit.metadata_json or {}
        area = _metadata_value(metadata, "area", "unknown")
        impact = _metadata_value(metadata, "impact", "unknown")
        frequency = _metadata_value(metadata, "frequency", "unknown")
        action = _metadata_value(metadata, "recommended_action", "observe")
        evidence = _metadata_value(metadata, "evidence", "No evidence details recorded.")
        summary = audit.reason or _metadata_value(metadata, "summary", "No summary recorded.")
        field_value = (
            f"Area: **{area}**\n"
            f"Impact: **{impact}** | Frequency: **{frequency}**\n"
            f"Action: **{action}**\n"
            f"Summary: {summary}\n"
            f"Evidence: {_truncate(evidence, 220)}"
        )
        embed.add_field(
            name=f"#{index} - <t:{int(audit.created_at.timestamp())}:R>",
            value=field_value,
            inline=False,
        )
    return apply_embed_chrome(embed, footer="HIGHLIGHT MANGER  •  Phase 4 evidence first")


def _metadata_value(metadata: dict, key: str, fallback: str) -> str:
    value = metadata.get(key)
    if value is None:
        return fallback
    rendered = str(value).strip()
    return rendered or fallback


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return f"{value[: limit - 1].rstrip()}..."
