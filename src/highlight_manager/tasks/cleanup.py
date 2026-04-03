from __future__ import annotations

from highlight_manager.modules.common.enums import MatchState
from highlight_manager.modules.common.time import utcnow


class CleanupWorker:
    def __init__(self) -> None:
        self.last_summary: dict[str, int | str] = {
            "cleared_orphaned_activities": 0,
            "missing_match_resources": 0,
            "repaired_matches": 0,
            "reconciled_wallets": 0,
        }

    async def run(self, bot) -> None:
        cleared_orphaned_activities = 0
        missing_match_resources = 0
        repaired_matches = 0
        reconciled_wallets = 0
        repair_targets: list[tuple[int, object]] = []
        async with bot.runtime.session() as repos:
            active_queues = await repos.matches.list_active_queues()
            active_matches = await repos.matches.list_active_matches()
            active_queue_ids = {queue.id for queue in active_queues}
            active_match_ids = {match.id for match in active_matches}
            stale_player_ids: list[int] = []
            for activity in await repos.profiles.list_non_idle_activities():
                if activity.queue_id is not None and activity.queue_id not in active_queue_ids:
                    stale_player_ids.append(activity.player_id)
                    continue
                if activity.match_id is not None and activity.match_id not in active_match_ids:
                    stale_player_ids.append(activity.player_id)
            if stale_player_ids:
                unique_player_ids = list(dict.fromkeys(stale_player_ids))
                await bot.runtime.services.profiles.clear_activity(repos.profiles, unique_player_ids)
                cleared_orphaned_activities = len(unique_player_ids)

            guild_records: dict[int, object | None] = {}
            for match in active_matches:
                if match.guild_id not in guild_records:
                    guild_records[match.guild_id] = await repos.guilds.get_by_id(match.guild_id)
                guild_record = guild_records[match.guild_id]
                guild = bot.get_guild(guild_record.discord_guild_id) if guild_record is not None else None
                result_channel_missing = bool(match.result_channel_id and guild is not None and guild.get_channel(match.result_channel_id) is None)
                team1_voice_missing = bool(
                    match.team1_voice_channel_id and guild is not None and guild.get_channel(match.team1_voice_channel_id) is None
                )
                team2_voice_missing = bool(
                    match.team2_voice_channel_id and guild is not None and guild.get_channel(match.team2_voice_channel_id) is None
                )
                if result_channel_missing:
                    missing_match_resources += 1
                if team1_voice_missing:
                    missing_match_resources += 1
                if team2_voice_missing:
                    missing_match_resources += 1
                needs_live_repair = match.state in {MatchState.CREATED, MatchState.MOVING} and (
                    match.result_channel_id is None
                    or match.result_message_id is None
                    or match.team1_voice_channel_id is None
                    or match.team2_voice_channel_id is None
                    or result_channel_missing
                    or team1_voice_missing
                    or team2_voice_missing
                )
                if needs_live_repair and guild is not None:
                    repair_targets.append((guild.id, match.id))

            for wallet in await repos.economy.list_wallets():
                balance, lifetime_earned, lifetime_spent = await repos.economy.summarize_wallet_transactions(wallet.id)
                if (
                    wallet.balance != balance
                    or wallet.lifetime_earned != lifetime_earned
                    or wallet.lifetime_spent != lifetime_spent
                ):
                    await repos.economy.update_wallet_totals(
                        wallet,
                        balance=balance,
                        lifetime_earned=lifetime_earned,
                        lifetime_spent=lifetime_spent,
                    )
                    reconciled_wallets += 1

        for guild_id, match_id in repair_targets:
            guild = bot.get_guild(guild_id)
            if guild is None or not hasattr(bot, "provision_match_resources"):
                continue
            try:
                async with bot.runtime.session() as repos:
                    snapshot = await repos.matches.get_match_snapshot(match_id, for_update=True)
                if snapshot is None or snapshot.match.state not in {MatchState.CREATED, MatchState.MOVING}:
                    continue
                live_snapshot = await bot.provision_match_resources(guild, snapshot)
                if hasattr(bot, "announce_match_created"):
                    await bot.announce_match_created(guild, live_snapshot)
                if hasattr(bot, "refresh_match_messages"):
                    await bot.refresh_match_messages(guild, live_snapshot)
                repaired_matches += 1
            except Exception as exc:
                bot.logger.warning(
                    "cleanup_match_repair_failed",
                    guild_id=guild_id,
                    match_id=str(match_id),
                    error=str(exc),
                )

        self.last_summary = {
            "cleared_orphaned_activities": cleared_orphaned_activities,
            "missing_match_resources": missing_match_resources,
            "repaired_matches": repaired_matches,
            "reconciled_wallets": reconciled_wallets,
            "ran_at": utcnow().isoformat(),
        }
        if cleared_orphaned_activities or missing_match_resources or repaired_matches or reconciled_wallets:
            bot.logger.info(
                "cleanup_reconciled",
                cleared_orphaned_activities=cleared_orphaned_activities,
                missing_match_resources=missing_match_resources,
                repaired_matches=repaired_matches,
                reconciled_wallets=reconciled_wallets,
            )
