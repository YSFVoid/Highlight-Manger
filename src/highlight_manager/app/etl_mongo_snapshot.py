from __future__ import annotations

import asyncio
from dataclasses import dataclass

from pymongo import MongoClient

import highlight_manager.db.models  # noqa: F401
from highlight_manager.app.config import get_settings
from highlight_manager.db.base import Base
from highlight_manager.db.session import create_engine, create_session_factory, session_scope
from highlight_manager.modules.economy.repository import EconomyRepository
from highlight_manager.modules.economy.service import EconomyService
from highlight_manager.modules.guilds.repository import GuildRepository
from highlight_manager.modules.guilds.service import GuildService
from highlight_manager.modules.profiles.repository import ProfileRepository
from highlight_manager.modules.profiles.service import ProfileService
from highlight_manager.modules.ranks.calculator import soft_reset_seed
from highlight_manager.modules.ranks.repository import RankRepository
from highlight_manager.modules.ranks.service import RankService
from highlight_manager.modules.seasons.repository import SeasonRepository
from highlight_manager.modules.seasons.service import SeasonService


@dataclass(slots=True)
class LegacyProfileSnapshot:
    user_id: int
    display_name: str | None
    current_points: int
    current_rank: int
    coins_balance: int
    blacklisted: bool
    season_matches_played: int
    season_wins: int
    season_losses: int


async def migrate() -> None:
    settings = get_settings()
    if not settings.mongodb_uri:
        raise RuntimeError("MONGODB_URI is required for the legacy Season 1 snapshot migration.")

    engine = create_engine(settings.require_database_url())
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = create_session_factory(engine)

    guild_service = GuildService(settings)
    profile_service = ProfileService()
    season_service = SeasonService()
    rank_service = RankService()
    economy_service = EconomyService()

    mongo = MongoClient(settings.mongodb_uri)
    legacy_db = mongo.get_database("highlight_manager")
    legacy_guild_configs = legacy_db["guild_configs"]
    legacy_profiles = legacy_db["player_profiles"]
    legacy_seasons = legacy_db["seasons"]

    async with session_scope(session_factory) as session:
        guilds = GuildRepository(session)
        profiles = ProfileRepository(session)
        seasons = SeasonRepository(session)
        ranks = RankRepository(session)
        economy = EconomyRepository(session)

        for legacy_config in legacy_guild_configs.find({}):
            discord_guild_id = int(legacy_config["guild_id"])
            bundle = await guild_service.ensure_guild(guilds, discord_guild_id, None)
            await guilds.update_settings(
                bundle.guild.id,
                prefix=legacy_config.get("prefix", settings.default_prefix),
                log_channel_id=legacy_config.get("log_channel_id"),
                result_category_id=legacy_config.get("result_category_id"),
                match_category_id=legacy_config.get("temp_voice_category_id"),
                waiting_voice_channel_id=legacy_config.get("waiting_voice_channel_id"),
            )
            active_legacy_season = legacy_seasons.find_one({"guild_id": discord_guild_id}, sort=[("season_number", -1)])
            archived_season_number = int(active_legacy_season["season_number"]) if active_legacy_season else 1
            archived_season = await seasons.create(
                bundle.guild.id,
                name=f"Season {archived_season_number}",
                season_number=archived_season_number,
            )
            archived_season.status = "archived"
            seed_rows: list[tuple[int, int]] = []
            player_docs = list(legacy_profiles.find({"guild_id": discord_guild_id}))
            ranked_docs = sorted(
                player_docs,
                key=lambda item: (
                    -int(item.get("current_points", 0)),
                    -int(item.get("season_stats", {}).get("wins", 0)),
                    item.get("user_id", 0),
                ),
            )
            total_players = max(1, len(ranked_docs))
            await rank_service.ensure_default_tiers(ranks, bundle.guild.id)
            for placement, legacy_profile in enumerate(ranked_docs, start=1):
                snapshot = LegacyProfileSnapshot(
                    user_id=int(legacy_profile["user_id"]),
                    display_name=legacy_profile.get("display_name"),
                    current_points=int(legacy_profile.get("current_points", 0)),
                    current_rank=int(legacy_profile.get("current_rank", placement)),
                    coins_balance=int(legacy_profile.get("coins_balance", 0)),
                    blacklisted=bool(legacy_profile.get("blacklisted", False)),
                    season_matches_played=int(legacy_profile.get("season_stats", {}).get("matches_played", 0)),
                    season_wins=int(legacy_profile.get("season_stats", {}).get("wins", 0)),
                    season_losses=int(legacy_profile.get("season_stats", {}).get("losses", 0)),
                )
                player = await profile_service.ensure_player(
                    profiles,
                    bundle.guild.id,
                    snapshot.user_id,
                    display_name=snapshot.display_name,
                )
                player.is_blacklisted = snapshot.blacklisted
                wallet = await economy.ensure_wallet(player.id)
                wallet.balance = snapshot.coins_balance
                seed_rating = soft_reset_seed(final_rank=placement, total_players=total_players)
                season_player = await season_service.ensure_player(
                    seasons,
                    archived_season.id,
                    player.id,
                    seed_rating=seed_rating,
                    legacy_points=snapshot.current_points,
                    legacy_rank=snapshot.current_rank,
                )
                season_player.matches_played = snapshot.season_matches_played
                season_player.wins = snapshot.season_wins
                season_player.losses = snapshot.season_losses
                season_player.final_leaderboard_rank = placement
                seed_rows.append((player.id, seed_rating))

            next_season = await season_service.start_next_season(
                seasons,
                bundle.guild.id,
                bundle.settings,
                name=f"Season {archived_season_number + 1}",
            )
            for player_id, seed_rating in seed_rows:
                await season_service.ensure_player(seasons, next_season.id, player_id, seed_rating=seed_rating)

    await engine.dispose()
    mongo.close()


def main() -> None:
    asyncio.run(migrate())


if __name__ == "__main__":
    main()
