from __future__ import annotations

from datetime import timedelta

from highlight_manager.modules.common.time import utcnow


class SchedulerWorker:
    def __init__(self) -> None:
        self.last_summary: dict[str, int | str] = {
            "room_info_reminders": 0,
            "room_info_timeouts": 0,
            "result_timeouts": 0,
        }

    async def process_deadlines(self, bot) -> None:
        queue_refreshes: list[tuple[int, object]] = []
        match_refreshes: list[tuple[int, object]] = []
        reminder_count = 0
        room_info_timeouts = 0
        result_timeouts = 0
        async with bot.runtime.session() as repos:
            now = utcnow()
            reminder_threshold = now + timedelta(seconds=30)
            for queue in await repos.matches.list_due_room_info_reminders(reminder_threshold):
                if queue.room_info_deadline_at is None or queue.room_info_reminder_sent_at is not None:
                    continue
                guild_record = await repos.guilds.get_by_id(queue.guild_id)
                guild = bot.get_guild(guild_record.discord_guild_id) if guild_record is not None else None
                if guild is None or queue.source_channel_id is None:
                    continue
                channel = guild.get_channel(queue.source_channel_id)
                creator = await repos.profiles.get_player_by_id(queue.creator_player_id)
                creator_text = f"<@{creator.discord_user_id}>" if creator is not None else "The queue creator"
                if hasattr(channel, "send"):
                    await channel.send(
                        embed=bot.build_notice_embed(
                            "Room info reminder",
                            f"{creator_text} has 30 seconds left to enter room info.",
                        )
                    )
                queue.room_info_reminder_sent_at = now
                reminder_count += 1

            for queue in await repos.matches.list_due_room_info_timeouts(now):
                snapshot = await bot.runtime.services.matches.cancel_queue(
                    repos.matches,
                    repos.profiles,
                    repos.moderation,
                    queue_id=queue.id,
                    actor_player_id=None,
                    reason="room_info_timeout",
                )
                guild_record = await repos.guilds.get_by_id(snapshot.queue.guild_id)
                if guild_record is not None:
                    queue_refreshes.append((guild_record.discord_guild_id, snapshot))
                room_info_timeouts += 1

            for match in await repos.matches.list_due_result_timeouts(now):
                snapshot = await bot.runtime.services.matches.expire_match(
                    repos.matches,
                    repos.moderation,
                    match_id=match.id,
                )
                guild_record = await repos.guilds.get_by_id(snapshot.match.guild_id)
                if guild_record is not None:
                    match_refreshes.append((guild_record.discord_guild_id, snapshot))
                result_timeouts += 1

        self.last_summary = {
            "room_info_reminders": reminder_count,
            "room_info_timeouts": room_info_timeouts,
            "result_timeouts": result_timeouts,
            "ran_at": now.isoformat(),
        }

        for discord_guild_id, snapshot in queue_refreshes:
            guild = bot.get_guild(discord_guild_id)
            if guild is not None:
                await bot.refresh_queue_public_message(guild, snapshot)

        for discord_guild_id, snapshot in match_refreshes:
            guild = bot.get_guild(discord_guild_id)
            if guild is not None:
                await bot.refresh_match_messages(guild, snapshot)
