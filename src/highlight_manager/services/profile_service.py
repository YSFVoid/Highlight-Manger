from __future__ import annotations

from dataclasses import dataclass

import discord

from highlight_manager.config.logging import get_logger
from highlight_manager.models.common import MatchResultSummary, PlayerPointDelta
from highlight_manager.models.enums import ResultSource
from highlight_manager.models.guild_config import GuildConfig
from highlight_manager.models.match import MatchRecord
from highlight_manager.models.profile import PlayerProfile
from highlight_manager.repositories.profile_repository import ProfileRepository
from highlight_manager.services.rank_service import RankService
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
        if existing:
            return existing
        profile = PlayerProfile(
            guild_id=guild.id,
            user_id=user_id,
            current_rank=self.rank_service.resolve_rank(0, config.rank_thresholds),
        )
        profile = await self.repository.upsert(profile)
        member = guild.get_member(user_id)
        if member and sync_identity:
            await self.rank_service.sync_member_roles(member, profile, config)
        self.logger.info("profile_created", guild_id=guild.id, user_id=user_id)
        return profile

    async def ensure_member_profile(self, member: discord.Member, config: GuildConfig) -> PlayerProfile:
        return await self.ensure_profile(member.guild, member.id, config)

    async def set_blacklist(self, guild: discord.Guild, user_id: int, blacklisted: bool) -> PlayerProfile:
        config = GuildConfig(guild_id=guild.id)
        profile = await self.ensure_profile(guild, user_id, config)
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
        profile.current_rank = 0 if enabled else self.rank_service.resolve_rank(
            profile.current_points,
            config.rank_thresholds,
        )
        profile.updated_at = utcnow()
        profile = await self.repository.upsert(profile)
        member = guild.get_member(user_id)
        if member:
            await self.rank_service.sync_member_roles(member, profile, config)
        return profile

    async def set_rank(
        self,
        guild: discord.Guild,
        user_id: int,
        config: GuildConfig,
        rank: int,
    ) -> PlayerProfile:
        if rank < 1 or rank > 5:
            raise UserFacingError("Rank must be between 1 and 5.")
        profile = await self.ensure_profile(guild, user_id, config)
        profile.rank0 = False
        profile.current_rank = rank
        profile.updated_at = utcnow()
        profile = await self.repository.upsert(profile)
        member = guild.get_member(user_id)
        if member:
            await self.rank_service.sync_member_roles(member, profile, config)
        return profile

    async def set_points(
        self,
        guild: discord.Guild,
        user_id: int,
        config: GuildConfig,
        new_points: int,
    ) -> PointsUpdateResult:
        profile = await self.ensure_profile(guild, user_id, config)
        previous = profile.current_points
        delta = new_points - previous
        profile.current_points = new_points
        profile.lifetime_points += delta
        rank_before = profile.current_rank
        if not (profile.rank0 and config.features.preserve_rank0):
            profile.current_rank = self.rank_service.resolve_rank(profile.current_points, config.rank_thresholds)
        profile.updated_at = utcnow()
        profile = await self.repository.upsert(profile)
        member = guild.get_member(user_id)
        if member:
            await self.rank_service.sync_member_roles(member, profile, config)
        return PointsUpdateResult(
            profile=profile,
            previous_points=previous,
            new_points=profile.current_points,
            delta=delta,
            rank_before=rank_before,
            rank_after=profile.current_rank,
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

    async def list_leaderboard(self, guild_id: int, limit: int = 10) -> list[PlayerProfile]:
        return await self.repository.list_leaderboard(guild_id, limit=limit)

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
            profile = await self.ensure_profile(guild, user_id, config)
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
            if not (profile.rank0 and config.features.preserve_rank0):
                profile.current_rank = self.rank_service.resolve_rank(profile.current_points, config.rank_thresholds)
            profile.updated_at = utcnow()
            saved = await self.repository.upsert(profile)
            member = guild.get_member(user_id)
            if member:
                await self.rank_service.sync_member_roles(member, saved, config)
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
            profile = await self.ensure_profile(guild, user_id, config)
            previous_points = profile.current_points
            rank_before = profile.current_rank
            delta = timeout_rule.winner
            profile.current_points += delta
            profile.lifetime_points += delta
            profile.season_stats.matches_played += 1
            profile.lifetime_stats.matches_played += 1
            if not (profile.rank0 and config.features.preserve_rank0):
                profile.current_rank = self.rank_service.resolve_rank(profile.current_points, config.rank_thresholds)
            profile.updated_at = utcnow()
            saved = await self.repository.upsert(profile)
            member = guild.get_member(user_id)
            if member:
                await self.rank_service.sync_member_roles(member, saved, config)
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
        await self.repository.reset_for_new_season(guild.id, utcnow())
        for member in guild.members:
            if member.bot:
                continue
            profile = await self.ensure_profile(guild, member.id, config)
            if not profile.rank0:
                profile.current_rank = self.rank_service.resolve_rank(profile.current_points, config.rank_thresholds)
                profile.updated_at = utcnow()
                profile = await self.repository.upsert(profile)
            await self.rank_service.sync_member_roles(member, profile, config)

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
            profile = await self.ensure_profile(member.guild, member.id, config, sync_identity=False)
            sync_result = await self.rank_service.sync_member_roles(member, profile, config)
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
