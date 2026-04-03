from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from highlight_manager.modules.common.enums import AuditAction, AuditEntityType
from highlight_manager.modules.common.time import utcnow


@dataclass(slots=True)
class VoiceAnchorStatus:
    enabled: bool
    channel_id: int | None
    state: str
    reason: str | None = None
    retry_in_seconds: int | None = None
    next_retry_at: datetime | None = None
    connected_channel_id: int | None = None


class RecoveryCoordinator:
    BACKOFF_STEPS = [15, 30, 60, 120, 300]

    def __init__(self) -> None:
        self._voice_backoff_index: dict[int, int] = {}
        self._voice_next_retry_at: dict[int, datetime] = {}
        self._voice_status: dict[int, VoiceAnchorStatus] = {}
        self._voice_last_logged_signature: dict[int, tuple[str, str | None]] = {}
        self._voice_last_logged_at: dict[int, datetime] = {}

    @property
    def connected_guild_count(self) -> int:
        return sum(1 for status in self._voice_status.values() if status.state == "connected")

    def get_voice_status(self, guild_id: int) -> VoiceAnchorStatus | None:
        return self._voice_status.get(guild_id)

    def voice_dependency_available(self) -> bool:
        try:
            import nacl  # noqa: F401
        except ImportError:
            return False
        return True

    def _set_voice_status(
        self,
        guild_id: int,
        *,
        enabled: bool,
        channel_id: int | None,
        state: str,
        reason: str | None = None,
        retry_in_seconds: int | None = None,
        next_retry_at: datetime | None = None,
        connected_channel_id: int | None = None,
    ) -> None:
        self._voice_status[guild_id] = VoiceAnchorStatus(
            enabled=enabled,
            channel_id=channel_id,
            state=state,
            reason=reason,
            retry_in_seconds=retry_in_seconds,
            next_retry_at=next_retry_at,
            connected_channel_id=connected_channel_id,
        )

    def _log_voice_failure(
        self,
        bot,
        *,
        guild_id: int,
        channel_id: int | None,
        state: str,
        reason: str,
        retry_in_seconds: int | None,
    ) -> None:
        now = utcnow()
        signature = (state, reason)
        last_signature = self._voice_last_logged_signature.get(guild_id)
        last_logged_at = self._voice_last_logged_at.get(guild_id)
        if last_signature == signature and last_logged_at is not None and now - last_logged_at < timedelta(minutes=15):
            return
        self._voice_last_logged_signature[guild_id] = signature
        self._voice_last_logged_at[guild_id] = now
        bot.logger.warning(
            "persistent_voice_connect_failed",
            guild_id=guild_id,
            channel_id=channel_id,
            state=state,
            retry_in_seconds=retry_in_seconds,
            error=reason,
        )

    async def restore_views(self, bot) -> int:
        restored_count = 0
        async with bot.runtime.session() as repos:
            for queue in await repos.matches.list_active_queues():
                if not queue.public_message_id:
                    continue
                snapshot = await repos.matches.get_queue_snapshot(queue.id)
                if snapshot is None:
                    continue
                bot.add_view(
                    bot.build_queue_view(queue.id, snapshot=snapshot),
                    message_id=queue.public_message_id,
                )
                restored_count += 1
            for match in await repos.matches.list_active_matches():
                snapshot = await repos.matches.get_match_snapshot(match.id)
                if snapshot is None:
                    continue
                if match.public_message_id:
                    bot.add_view(
                        bot.build_match_view(match.id, snapshot=snapshot),
                        message_id=match.public_message_id,
                    )
                    restored_count += 1
                if match.result_message_id:
                    bot.add_view(
                        bot.build_match_view(match.id, snapshot=snapshot),
                        message_id=match.result_message_id,
                    )
                    restored_count += 1
        return restored_count

    async def restore_persistent_voice(self, bot) -> None:
        async with bot.runtime.session() as repos:
            for guild in bot.guilds:
                bundle = await bot.runtime.services.guilds.get_bundle(repos.guilds, guild.id)
                if bundle is None:
                    continue
                settings = bundle.settings
                if not settings.persistent_voice_enabled or not settings.persistent_voice_channel_id:
                    self._set_voice_status(
                        guild.id,
                        enabled=False,
                        channel_id=settings.persistent_voice_channel_id,
                        state="disabled",
                        reason="Persistent bot voice is not configured.",
                    )
                    continue
                next_retry_at = self._voice_next_retry_at.get(guild.id)
                if next_retry_at and utcnow() < next_retry_at:
                    self._set_voice_status(
                        guild.id,
                        enabled=True,
                        channel_id=settings.persistent_voice_channel_id,
                        state="retrying",
                        reason=self._voice_status.get(guild.id).reason if self._voice_status.get(guild.id) else None,
                        retry_in_seconds=max(int((next_retry_at - utcnow()).total_seconds()), 0),
                        next_retry_at=next_retry_at,
                    )
                    continue
                if not self.voice_dependency_available():
                    current_index = self._voice_backoff_index.get(guild.id, 0)
                    delay = self.BACKOFF_STEPS[min(current_index, len(self.BACKOFF_STEPS) - 1)]
                    self._voice_backoff_index[guild.id] = min(current_index + 1, len(self.BACKOFF_STEPS) - 1)
                    retry_at = utcnow() + timedelta(seconds=delay)
                    self._voice_next_retry_at[guild.id] = retry_at
                    reason = "PyNaCl is not installed, so Discord voice is unavailable."
                    self._set_voice_status(
                        guild.id,
                        enabled=True,
                        channel_id=settings.persistent_voice_channel_id,
                        state="dependency_missing",
                        reason=reason,
                        retry_in_seconds=delay,
                        next_retry_at=retry_at,
                    )
                    self._log_voice_failure(
                        bot,
                        guild_id=guild.id,
                        channel_id=settings.persistent_voice_channel_id,
                        state="dependency_missing",
                        reason=reason,
                        retry_in_seconds=delay,
                    )
                    continue
                channel = guild.get_channel(settings.persistent_voice_channel_id)
                if channel is None or not hasattr(channel, "connect"):
                    settings.persistent_voice_enabled = False
                    reason = "Configured voice channel no longer exists."
                    self._set_voice_status(
                        guild.id,
                        enabled=False,
                        channel_id=settings.persistent_voice_channel_id,
                        state="config_invalid",
                        reason=reason,
                    )
                    await bot.runtime.services.moderation.audit(
                        repos.moderation,
                        guild_id=bundle.guild.id,
                        action=AuditAction.PERSISTENT_VOICE_INVALID,
                        entity_type=AuditEntityType.CONFIG,
                        entity_id=str(bundle.guild.id),
                        reason=reason,
                    )
                    continue
                me = guild.me
                if me is None:
                    self._set_voice_status(
                        guild.id,
                        enabled=True,
                        channel_id=settings.persistent_voice_channel_id,
                        state="waiting_for_member_state",
                        reason="Guild member cache is not ready yet.",
                    )
                    continue
                permissions = channel.permissions_for(me)
                if not permissions.view_channel or not permissions.connect:
                    settings.persistent_voice_enabled = False
                    reason = "Bot lacks View Channel or Connect permission for the configured voice."
                    self._set_voice_status(
                        guild.id,
                        enabled=False,
                        channel_id=settings.persistent_voice_channel_id,
                        state="permission_missing",
                        reason=reason,
                    )
                    await bot.runtime.services.moderation.audit(
                        repos.moderation,
                        guild_id=bundle.guild.id,
                        action=AuditAction.PERSISTENT_VOICE_INVALID,
                        entity_type=AuditEntityType.CONFIG,
                        entity_id=str(bundle.guild.id),
                        reason=reason,
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
                        self._set_voice_status(
                            guild.id,
                            enabled=True,
                            channel_id=channel.id,
                            state="connected",
                            connected_channel_id=channel.id,
                        )
                        continue
                    if voice_client is None:
                        await channel.connect(self_deaf=settings.persistent_voice_self_deaf)
                    else:
                        await voice_client.move_to(channel)
                    self._voice_backoff_index[guild.id] = 0
                    self._voice_next_retry_at.pop(guild.id, None)
                    self._set_voice_status(
                        guild.id,
                        enabled=True,
                        channel_id=channel.id,
                        state="connected",
                        connected_channel_id=channel.id,
                    )
                    bot.logger.info(
                        "persistent_voice_connected",
                        guild_id=guild.id,
                        channel_id=channel.id,
                    )
                except Exception as exc:
                    current_index = self._voice_backoff_index.get(guild.id, 0)
                    delay = self.BACKOFF_STEPS[min(current_index, len(self.BACKOFF_STEPS) - 1)]
                    self._voice_backoff_index[guild.id] = min(current_index + 1, len(self.BACKOFF_STEPS) - 1)
                    retry_at = utcnow() + timedelta(seconds=delay)
                    self._voice_next_retry_at[guild.id] = retry_at
                    reason = str(exc)
                    self._set_voice_status(
                        guild.id,
                        enabled=True,
                        channel_id=settings.persistent_voice_channel_id,
                        state="retrying",
                        reason=reason,
                        retry_in_seconds=delay,
                        next_retry_at=retry_at,
                    )
                    self._log_voice_failure(
                        bot,
                        guild_id=guild.id,
                        channel_id=settings.persistent_voice_channel_id,
                        state="retrying",
                        reason=reason,
                        retry_in_seconds=delay,
                    )
