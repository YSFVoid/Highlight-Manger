from __future__ import annotations

from datetime import timedelta

from highlight_manager.modules.common.time import utcnow
from highlight_manager.modules.ranks.calculator import calculate_decay


class DecayWorker:
    """Daily task that applies inactivity decay to player ratings."""

    def __init__(self) -> None:
        self.last_summary: dict[str, int | str] = {
            "players_decayed": 0,
            "total_points_removed": 0,
        }

    async def process_decay(self, bot) -> None:
        players_decayed = 0
        total_points_removed = 0
        now = utcnow()
        grace_days = 7

        async with bot.runtime.session() as repos:
            # Get all active season players who haven't played recently
            guilds = await repos.guilds.list_all()
            for guild_record in guilds:
                settings_record = await repos.guilds.get_settings(guild_record.id)
                if settings_record is None:
                    continue
                season = await repos.seasons.get_active_season(guild_record.id)
                if season is None:
                    continue

                season_players = await repos.seasons.list_season_players_for_decay(
                    season.id, grace_days=grace_days
                )
                tiers = await bot.runtime.services.ranks.ensure_default_tiers(
                    repos.ranks, guild_record.id
                )

                for sp in season_players:
                    if sp.last_match_at is None:
                        continue
                    days_inactive = (now - sp.last_match_at).days
                    decay_amount = calculate_decay(days_inactive, sp.rating)
                    if decay_amount <= 0:
                        continue

                    sp.rating = max(800, sp.rating - decay_amount)
                    players_decayed += 1
                    total_points_removed += decay_amount

        self.last_summary = {
            "players_decayed": players_decayed,
            "total_points_removed": total_points_removed,
            "ran_at": now.isoformat(),
        }
