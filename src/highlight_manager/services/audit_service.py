from __future__ import annotations

from typing import Any

import discord

from highlight_manager.config.logging import get_logger
from highlight_manager.models.audit_log import AuditLogRecord
from highlight_manager.models.enums import AuditAction
from highlight_manager.repositories.audit_repository import AuditRepository


class AuditService:
    def __init__(self, repository: AuditRepository, config_service) -> None:
        self.repository = repository
        self.config_service = config_service
        self.logger = get_logger(__name__)

    async def log(
        self,
        guild: discord.Guild,
        action: AuditAction,
        message: str,
        *,
        actor_id: int | None = None,
        target_id: int | None = None,
        metadata: dict[str, Any] | None = None,
        notify_discord: bool = True,
    ) -> None:
        record = AuditLogRecord(
            guild_id=guild.id,
            action=action,
            actor_id=actor_id,
            target_id=target_id,
            message=message,
            metadata=metadata or {},
        )
        await self.repository.create(record)
        self.logger.info(
            "audit_logged",
            guild_id=guild.id,
            action=action.value,
            actor_id=actor_id,
            target_id=target_id,
            message=message,
            metadata=metadata or {},
        )
        if not notify_discord:
            return
        try:
            config = await self.config_service.get_or_create(guild.id)
            if not config.log_channel_id:
                return
            channel = guild.get_channel(config.log_channel_id)
            if not isinstance(channel, discord.TextChannel):
                return
            embed = discord.Embed(title=f"Audit | {action.value}", description=message, colour=discord.Colour.dark_teal())
            if actor_id:
                embed.add_field(name="Actor", value=f"<@{actor_id}>", inline=True)
            if target_id:
                embed.add_field(name="Target", value=f"<@{target_id}>", inline=True)
            if metadata:
                pretty = "\n".join(f"**{key}:** {value}" for key, value in metadata.items())
                embed.add_field(name="Metadata", value=pretty[:1024], inline=False)
            await channel.send(embed=embed)
        except Exception as exc:
            self.logger.warning("audit_notify_failed", guild_id=guild.id, action=action.value, error=str(exc))
