from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

import discord

from highlight_manager.config.logging import get_logger
from highlight_manager.models.common import MatchResultSummary, PlayerPointDelta
from highlight_manager.models.enums import ResultSource
from highlight_manager.models.guild_config import GuildConfig
from highlight_manager.models.match import MatchRecord
from highlight_manager.models.profile import PlayerProfile
from highlight_manager.repositories.profile_repository import ProfileRepository
from highlight_manager.services.rank_service import RankService, RankSyncResult
from highlight_manager.utils.dates import utcnow
from highlight_manager.utils.exceptions import UserFacingError


@dataclass(slots=True)
class PointsUpdateResult:
    profile: PlayerProfile
    previous_points: int
    new_points: int
    delta: int
    rank_before: int
    rank_after: int


@dataclass(slots=True)
class IdentitySyncBatchResult:
    processed_members: int = 0
    role_updates: int = 0
    nickname_updates: int = 0
    nickname_failures: int = 0
    skipped_members: int = 0


class ProfileService:
    IDENTITY_SYNC_CONCURRENCY = 5

    def __init__(self, repository: ProfileRepository, rank_service: RankService) -> None:
        self.repository = repository
        self.rank_service = rank_service
        self.logger = get_logger(__name__)

    async def get(self, guild_id: int, user_id: int) -> PlayerProfile | None:
        return await self.repository.get(guild_id, user_id)

    async def ensure_profile(
        self,
        guild: discord.Guild,
        user_id: int,
        config: GuildConfig,
        *,
        sync_identity: bool = True,
    ) -> PlayerProfile:
        existing = await self.repository.get(guild.id, user_id)
        joined_at = self._resolve_member_joined_at(guild, user_id)
        if existing:
            if joined_at is not None and existing.server_joined_at != joined_at:
                existing.server_joined_at = joined_at
                existing.updated_at = utcnow()
                existing = await self.repository.upsert(existing)
            return existing
        profile = PlayerProfile(
            guild_id=guild.id,
            user_id=user_id,
            current_rank=1,
            server_joined_at=joined_at,
        )
        profile = await self.repository.upsert(profile)
        if sync_identity:
            ranked_profiles = await self.recalculate_live_ranks(guild, config, sync_members=True)
            profile = ranked_profiles.get(user_id, profile)
        self.logger.info("profile_created", guild_id=guild.id, user_id=user_id)
        return profile

    async def ensure_member_profile(self, member: discord.Member, config: GuildConfig) -> PlayerProfile:
        return await self.ensure_profile(member.guild, member.id, config)

    async def set_blacklist(self, guild: discord.Guild, user_id: int, blacklisted: bool) -> PlayerProfile:
        profile = await self.repository.get(guild.id, user_id)
        if profile is None:
            profile = PlayerProfile(
                guild_id=guild.id,
                user_id=user_id,
                current_rank=1,
                server_joined_at=self._resolve_member_joined_at(guild, user_id),
            )
        elif profile.server_joined_at is None:
            profile.server_joined_at = self._resolve_member_joined_at(guild, user_id)
        profile.blacklisted = blacklisted
        profile.updated_at = utcnow()
        return await self.repository.upsert(profile)

    async def set_rank0(
        self,
        guild: discord.Guild,
        user_id: int,
        config: GuildConfig,
        enabled: bool,
    ) -> PlayerProfile:
        profile = await self.ensure_profile(guild, user_id, config)
        profile.rank0 = enabled
        profile.updated_at = utcnow()
        await self.repository.upsert(profile)
        ranked_profiles = await self.recalculate_live_ranks(guild, config, sync_members=True)
        return ranked_profiles.get(user_id, profile)

    async def set_rank(
        self,
        guild: discord.Guild,
        user_id: int,
        config: GuildConfig,
        rank: int,
    ) -> PlayerProfile:
        raise UserFacingError("Manual rank set is disabled. Rank is now live placement. Use points or Rank 0.")

    async def set_points(
        self,
        guild: discord.Guild,
        user_id: int,
        config: GuildConfig,
        new_points: int,
    ) -> PointsUpdateResult:
        profile = await self.ensure_profile(guild, user_id, config, sync_identity=False)
        previous = profile.current_points
        delta = new_points - previous
        profile.current_points = new_points
        profile.lifetime_points += delta
        rank_before = profile.current_rank
        profile.updated_at = utcnow()
        await self.repository.upsert(profile)
        ranked_profiles = await self.recalculate_live_ranks(guild, config, sync_members=True)
        updated_profile = ranked_profiles.get(user_id, profile)
        return PointsUpdateResult(
            profile=updated_profile,
            previous_points=previous,
            new_points=updated_profile.current_points,
            delta=delta,
            rank_before=rank_before,
            rank_after=updated_profile.current_rank,
        )

    async def adjust_points(
        self,
        guild: discord.Guild,
        user_id: int,
        config: GuildConfig,
        delta: int,
    ) -> PointsUpdateResult:
        profile = await self.ensure_profile(guild, user_id, config)
        return await self.set_points(guild, user_id, config, profile.current_points + delta)

    async def list_leaderboard(self, guild: discord.Guild, config: GuildConfig, limit: int = 10) -> list[PlayerProfile]:
        await self.recalculate_live_ranks(guild, config, sync_members=False)
        return await self.repository.list_leaderboard(guild.id, limit=limit)

    async def apply_match_outcome(
        self,
        guild: discord.Guild,
        match: MatchRecord,
        config: GuildConfig,
        *,
        winner_team: int,
        winner_mvp_id: int | None,
        loser_mvp_id: int | None,
        source: ResultSource,
        notes: str | None = None,
    ) -> MatchResultSummary:
        rule = config.point_rules[match.match_type.value][match.mode.value]
        if winner_team == 1:
            winner_ids = list(match.team1_player_ids)
            loser_ids = list(match.team2_player_ids)
        else:
            winner_ids = list(match.team2_player_ids)
            loser_ids = list(match.team1_player_ids)

        deltas: list[PlayerPointDelta] = []
        for user_id in match.all_player_ids:
            profile = await self.ensure_profile(guild, user_id, config, sync_identity=False)
            previous_points = profile.current_points
            rank_before = profile.current_rank
            if user_id in winner_ids:
                delta = rule.winner_mvp if winner_mvp_id == user_id and rule.winner_mvp is not None else rule.winner
                profile.season_stats.wins += 1
                profile.lifetime_stats.wins += 1
                if winner_mvp_id == user_id:
                    profile.season_stats.mvp_wins += 1
                    profile.lifetime_stats.mvp_wins += 1
            else:
                delta = rule.loser_mvp if loser_mvp_id == user_id and rule.loser_mvp is not None else rule.loser
                profile.season_stats.losses += 1
                profile.lifetime_stats.losses += 1
                if loser_mvp_id == user_id:
                    profile.season_stats.mvp_losses += 1
                    profile.lifetime_stats.mvp_losses += 1

            profile.current_points += delta
            profile.lifetime_points += delta
            profile.season_stats.matches_played += 1
            profile.lifetime_stats.matches_played += 1
            profile.updated_at = utcnow()
            saved = await self.repository.upsert(profile)
            deltas.append(
                PlayerPointDelta(
                    user_id=user_id,
                    previous_points=previous_points,
                    delta=delta,
                    new_points=saved.current_points,
                    rank_before=rank_before,
                    rank_after=saved.current_rank,
                ),
            )
        ranked_profiles = await self.recalculate_live_ranks(guild, config, sync_members=True)
        for delta in deltas:
            refreshed_profile = ranked_profiles.get(delta.user_id)
            if refreshed_profile is not None:
                delta.rank_after = refreshed_profile.current_rank
        return MatchResultSummary(
            winner_team=winner_team,
            winner_player_ids=winner_ids,
            loser_player_ids=loser_ids,
            winner_mvp_id=winner_mvp_id,
            loser_mvp_id=loser_mvp_id,
            source=source.value,
            point_deltas=deltas,
            notes=notes,
            finalized_at=utcnow(),
        )

    async def apply_vote_timeout_penalty(
        self,
        guild: discord.Guild,
        match: MatchRecord,
        config: GuildConfig,
        *,
        notes: str | None = None,
    ) -> MatchResultSummary:
        timeout_rule = config.point_rules[match.match_type.value]["timeout_penalty"]
        deltas: list[PlayerPointDelta] = []
        for user_id in match.all_player_ids:
            profile = await self.ensure_profile(guild, user_id, config, sync_identity=False)
            previous_points = profile.current_points
            rank_before = profile.current_rank
            delta = timeout_rule.winner
            profile.current_points += delta
            profile.lifetime_points += delta
            profile.season_stats.matches_played += 1
            profile.lifetime_stats.matches_played += 1
            profile.updated_at = utcnow()
            saved = await self.repository.upsert(profile)
            deltas.append(
                PlayerPointDelta(
                    user_id=user_id,
                    previous_points=previous_points,
                    delta=delta,
                    new_points=saved.current_points,
                    rank_before=rank_before,
                    rank_after=saved.current_rank,
                ),
            )
        ranked_profiles = await self.recalculate_live_ranks(guild, config, sync_members=True)
        for delta in deltas:
            refreshed_profile = ranked_profiles.get(delta.user_id)
            if refreshed_profile is not None:
                delta.rank_after = refreshed_profile.current_rank
        return MatchResultSummary(
            winner_team=None,
            winner_player_ids=[],
            loser_player_ids=[],
            winner_mvp_id=None,
            loser_mvp_id=None,
            source=ResultSource.VOTE_TIMEOUT.value,
            point_deltas=deltas,
            notes=notes,
            finalized_at=utcnow(),
        )

    async def reset_for_new_season(self, guild: discord.Guild, config: GuildConfig) -> None:
        for member in guild.members:
            if member.bot:
                continue
            await self.ensure_profile(guild, member.id, config, sync_identity=False)
        await self.repository.reset_for_new_season(guild.id, utcnow())
        await self.recalculate_live_ranks(guild, config, sync_members=True)

    async def require_not_blacklisted(
        self,
        guild: discord.Guild,
        user_id: int,
        config: GuildConfig,
    ) -> PlayerProfile:
        profile = await self.ensure_profile(guild, user_id, config)
        if profile.blacklisted:
            raise UserFacingError("You are blacklisted from match participation.")
        return profile

    async def sync_all_member_identities(
        self,
        guild: discord.Guild,
        config: GuildConfig,
    ) -> IdentitySyncBatchResult:
        result = IdentitySyncBatchResult()
        for member in guild.members:
            if member.bot:
                continue
            await self.ensure_profile(member.guild, member.id, config, sync_identity=False)
        ranked_profiles = await self.recalculate_live_ranks(guild, config, sync_members=False)
        sync_targets = [
            (member, profile)
            for member in guild.members
            if not member.bot and (profile := ranked_profiles.get(member.id)) is not None
        ]
        for sync_result in await self._sync_member_batch(sync_targets, config):
            result.processed_members += 1
            if sync_result.role_updated:
                result.role_updates += 1
            if sync_result.nickname_updated:
                result.nickname_updates += 1
            if sync_result.nickname_failed:
                result.nickname_failures += 1
            if sync_result.skipped_reason:
                result.skipped_members += 1
        return result

    async def recalculate_live_ranks(
        self,
        guild: discord.Guild,
        config: GuildConfig,
        *,
        sync_members: bool,
    ) -> dict[int, PlayerProfile]:
        profiles = await self.repository.list_for_guild(guild.id)
        if not profiles:
            return {}

        live_ranks = self.rank_service.assign_live_ranks(profiles)
        updated_profiles: dict[int, PlayerProfile] = {}
        for profile in profiles:
            joined_at = self._resolve_member_joined_at(guild, profile.user_id) or profile.server_joined_at
            target_rank = 0 if profile.rank0 and config.features.preserve_rank0 else live_ranks.get(profile.user_id, 1)
            needs_update = profile.current_rank != target_rank or profile.server_joined_at != joined_at
            if needs_update:
                profile.current_rank = target_rank
                profile.server_joined_at = joined_at
                profile.updated_at = utcnow()
                profile = await self.repository.upsert(profile)
            updated_profiles[profile.user_id] = profile

        if sync_members:
            sync_targets = [
                (member, profile)
                for profile in updated_profiles.values()
                if (member := guild.get_member(profile.user_id)) is not None
            ]
            await self._sync_member_batch(sync_targets, config)
        return updated_profiles

    async def _sync_member_batch(
        self,
        sync_targets: list[tuple[discord.Member, PlayerProfile]],
        config: GuildConfig,
    ) -> list[RankSyncResult]:
        semaphore = asyncio.Semaphore(self.IDENTITY_SYNC_CONCURRENCY)

        async def run_one(member: discord.Member, profile: PlayerProfile) -> RankSyncResult:
            async with semaphore:
                return await self.rank_service.sync_member_roles(member, profile, config)

        return await asyncio.gather(*(run_one(member, profile) for member, profile in sync_targets))

    def _resolve_member_joined_at(self, guild: discord.Guild, user_id: int) -> datetime | None:
        member = guild.get_member(user_id)
        if member is None or member.joined_at is None:
            return None
        if member.joined_at.tzinfo is None:
            return member.joined_at.replace(tzinfo=UTC)
        return member.joined_at.astimezone(UTC)
