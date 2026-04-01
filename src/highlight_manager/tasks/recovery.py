from __future__ import annotations

from datetime import timedelta

from highlight_manager.modules.common.enums import AuditAction, AuditEntityType
from highlight_manager.modules.common.time import utcnow


class RecoveryCoordinator:
    BACKOFF_STEPS = [15, 30, 60, 120, 300]

    def __init__(self) -> None:
        self._voice_backoff_index: dict[int, int] = {}
        self._voice_next_retry_at = {}

    async def restore_views(self, bot) -> None:
        async with bot.runtime.session() as repos:
            for queue in await repos.matches.list_active_queues():
                if queue.public_message_id:
                    bot.add_view(bot.build_queue_view(queue.id), message_id=queue.public_message_id)
            for match in await repos.matches.list_active_matches():
                if match.public_message_id:
                    bot.add_view(bot.build_match_view(match.id), message_id=match.public_message_id)

    async def restore_persistent_voice(self, bot) -> None:
        async with bot.runtime.session() as repos:
            for guild in bot.guilds:
                bundle = await bot.runtime.services.guilds.get_bundle(repos.guilds, guild.id)
                if bundle is None:
                    continue
                settings = bundle.settings
                if not settings.persistent_voice_enabled or not settings.persistent_voice_channel_id:
                    continue
                next_retry_at = self._voice_next_retry_at.get(guild.id)
                if next_retry_at and utcnow() < next_retry_at:
                    continue
                channel = guild.get_channel(settings.persistent_voice_channel_id)
                if channel is None or not hasattr(channel, "connect"):
                    settings.persistent_voice_enabled = False
                    await bot.runtime.services.moderation.audit(
                        repos.moderation,
                        guild_id=bundle.guild.id,
                        action=AuditAction.PERSISTENT_VOICE_INVALID,
                        entity_type=AuditEntityType.CONFIG,
                        entity_id=str(bundle.guild.id),
                        reason="Configured voice channel no longer exists.",
                    )
                    continue
                me = guild.me
                if me is None:
                    continue
                permissions = channel.permissions_for(me)
                if not permissions.view_channel or not permissions.connect:
                    settings.persistent_voice_enabled = False
                    await bot.runtime.services.moderation.audit(
                        repos.moderation,
                        guild_id=bundle.guild.id,
                        action=AuditAction.PERSISTENT_VOICE_INVALID,
                        entity_type=AuditEntityType.CONFIG,
                        entity_id=str(bundle.guild.id),
                        reason="Bot lacks voice permissions for configured channel.",
                    )
                    continue
                try:
                    voice_client = guild.voice_client
                    if voice_client and voice_client.channel and voice_client.channel.id == channel.id:
                        current_voice_state = me.voice
                        if (
                            settings.persistent_voice_self_deaf
                            and current_voice_state is not None
                            and not current_voice_state.self_deaf
                        ):
                            await voice_client.guild.change_voice_state(channel=channel, self_deaf=True)
                        self._voice_backoff_index[guild.id] = 0
                        self._voice_next_retry_at.pop(guild.id, None)
                        continue
                    if voice_client is None:
                        await channel.connect(self_deaf=settings.persistent_voice_self_deaf)
                    else:
                        await voice_client.move_to(channel)
                    self._voice_backoff_index[guild.id] = 0
                    self._voice_next_retry_at.pop(guild.id, None)
                    bot.logger.info(
                        "persistent_voice_connected",
                        guild_id=guild.id,
                        channel_id=channel.id,
                    )
                except Exception as exc:
                    current_index = self._voice_backoff_index.get(guild.id, 0)
                    delay = self.BACKOFF_STEPS[min(current_index, len(self.BACKOFF_STEPS) - 1)]
                    self._voice_backoff_index[guild.id] = min(current_index + 1, len(self.BACKOFF_STEPS) - 1)
                    self._voice_next_retry_at[guild.id] = utcnow() + timedelta(seconds=delay)
                    bot.logger.warning(
                        "persistent_voice_connect_failed",
                        guild_id=guild.id,
                        channel_id=settings.persistent_voice_channel_id,
                        retry_in_seconds=delay,
                        error=str(exc),
                    )
