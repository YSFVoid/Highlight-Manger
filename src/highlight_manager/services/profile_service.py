from __future__ import annotations

from dataclasses import dataclass

import discord

from highlight_manager.config.logging import get_logger
from highlight_manager.models.common import MatchResultSummary, PlayerPointDelta
from highlight_manager.models.enums import MatchStatus, ResultSource
from highlight_manager.models.guild_config import GuildConfig
from highlight_manager.models.match import MatchRecord
from highlight_manager.models.profile import PlayerProfile
from highlight_manager.repositories.profile_repository import ProfileRepository
from highlight_manager.services.rank_service import RankService
from highlight_manager.utils.dates import utcnow
from highlight_manager.utils.exceptions import StateTransitionError, UserFacingError


@dataclass(slots=True)
class PointsUpdateResult:
    profile: PlayerProfile
    previous_points: int
    new_points: int
    delta: int
    rank_before: int
    rank_after: int


class ProfileService:
    def __init__(self, repository: ProfileRepository, rank_service: RankService, reward_service=None) -> None:
        self.repository = repository
        self.rank_service = rank_service
        self.reward_service = reward_service
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
            member = guild.get_member(user_id)
            if existing.joined_at is None and member and member.joined_at:
                existing.joined_at = member.joined_at
                existing.updated_at = utcnow()
                existing = await self.repository.upsert(existing)
            return existing
        member = guild.get_member(user_id)
        next_rank = await self.repository.count_ranked_for_guild(guild.id) + 1
        profile = PlayerProfile(
            guild_id=guild.id,
            user_id=user_id,
            current_points=0,
            current_rank=next_rank,
            joined_at=member.joined_at if member and member.joined_at else utcnow(),
        )
        profile = await self.repository.upsert(profile)
        if member and sync_identity:
            await self.rank_service.sync_member_rank(member, profile, config)
        self.logger.info("profile_created", guild_id=guild.id, user_id=user_id)
        return profile

    async def ensure_member_profile(self, member: discord.Member, config: GuildConfig) -> PlayerProfile:
        return await self.ensure_profile(member.guild, member.id, config)

    async def handle_member_join(self, member: discord.Member, config: GuildConfig) -> PlayerProfile:
        profile = await self.repository.get(member.guild.id, member.id)
        if profile is None:
            profile = await self.ensure_profile(member.guild, member.id, config, sync_identity=False)
            profile.joined_at = member.joined_at or profile.joined_at or utcnow()
            profile.updated_at = utcnow()
            profile = await self.repository.upsert(profile)
        elif profile.joined_at is None and member.joined_at:
            profile.joined_at = member.joined_at
            profile.updated_at = utcnow()
            profile = await self.repository.upsert(profile)
        await self.rank_service.sync_member_rank(member, profile, config)
        return profile

    async def set_blacklist(self, guild: discord.Guild, user_id: int, blacklisted: bool) -> PlayerProfile:
        config = GuildConfig(guild_id=guild.id)
        profile = await self.ensure_profile(guild, user_id, config)
        profile.blacklisted = blacklisted
        profile.updated_at = utcnow()
        return await self.repository.upsert(profile)

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
        rank_before = self.rank_service.display_rank_for_profile(profile)
        profile.updated_at = utcnow()
        profile = await self.repository.upsert(profile)
        ranked_profiles = await self.recalculate_rank_positions(guild, config)
        updated_profile = next((item for item in ranked_profiles if item.user_id == user_id), profile)
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

    async def list_leaderboard(
        self,
        guild_id: int,
        limit: int = 10,
        *,
        metric: str = "points",
        offset: int = 0,
        include_manual_overrides: bool = False,
    ) -> list[PlayerProfile]:
        profiles = await self.list_leaderboard_snapshot(
            guild_id,
            metric=metric,
            include_manual_overrides=include_manual_overrides,
        )
        return profiles[offset : offset + limit]

    async def list_leaderboard_snapshot(
        self,
        guild_id: int,
        *,
        metric: str = "points",
        include_manual_overrides: bool = False,
    ) -> list[PlayerProfile]:
        profiles = await self.repository.list_for_ranking(guild_id)
        filtered = [
            profile
            for profile in profiles
            if include_manual_overrides or profile.manual_rank_override is None
        ]
        if metric == "wins":
            return sorted(
                filtered,
                key=lambda profile: (
                    -profile.season_stats.wins,
                    -profile.current_points,
                    -profile.season_stats.mvp_wins,
                    profile.joined_at or profile.created_at,
                    profile.user_id,
                ),
            )
        if metric == "mvp":
            return sorted(
                filtered,
                key=lambda profile: (
                    -(profile.season_stats.mvp_wins + profile.season_stats.mvp_losses),
                    -profile.season_stats.mvp_wins,
                    -profile.season_stats.wins,
                    -profile.current_points,
                    profile.joined_at or profile.created_at,
                    profile.user_id,
                ),
            )
        return self.rank_service.sort_profiles_for_ranking(filtered)

    async def set_manual_rank_override(
        self,
        guild: discord.Guild,
        user_id: int,
        config: GuildConfig,
        *,
        manual_rank_override: int | None,
    ) -> PlayerProfile:
        profile = await self.ensure_profile(guild, user_id, config, sync_identity=False)
        profile.manual_rank_override = manual_rank_override
        if manual_rank_override is not None:
            profile.current_rank = manual_rank_override
            profile.updated_at = utcnow()
            profile = await self.repository.upsert(profile)
            member = guild.get_member(user_id)
            if member is not None:
                await self.rank_service.sync_member_rank(member, profile, config)
            return profile

        profile.updated_at = utcnow()
        profile = await self.repository.upsert(profile)
        ranked_profiles = await self.recalculate_rank_positions(guild, config)
        return next((item for item in ranked_profiles if item.user_id == user_id), profile)

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
        self._ensure_match_updates_allowed(match)
        rule = config.point_rules[match.match_type.value][match.mode.value]
        if winner_team == 1:
            winner_ids = list(match.team1_player_ids)
            loser_ids = list(match.team2_player_ids)
        else:
            winner_ids = list(match.team2_player_ids)
            loser_ids = list(match.team1_player_ids)

        deltas: list[PlayerPointDelta] = []
        updated_profiles: dict[int, PlayerProfile] = {}
        for user_id in match.all_player_ids:
            profile = await self.ensure_profile(guild, user_id, config)
            previous_points = profile.current_points
            rank_before = self.rank_service.display_rank_for_profile(profile)
            if user_id in winner_ids:
                delta = rule.winner_mvp if winner_mvp_id == user_id and rule.winner_mvp is not None else rule.winner
                profile.season_stats.wins += 1
                profile.lifetime_stats.wins += 1
                if winner_mvp_id == user_id:
                    profile.season_stats.mvp_wins += 1
                    profile.lifetime_stats.mvp_wins += 1
                    profile.mvp_winner_count += 1
            else:
                delta = rule.loser_mvp if loser_mvp_id == user_id and rule.loser_mvp is not None else rule.loser
                profile.season_stats.losses += 1
                profile.lifetime_stats.losses += 1
                if loser_mvp_id == user_id:
                    profile.season_stats.mvp_losses += 1
                    profile.lifetime_stats.mvp_losses += 1
                    profile.mvp_loser_count += 1

            profile.current_points += delta
            profile.lifetime_points += delta
            profile.season_stats.matches_played += 1
            profile.lifetime_stats.matches_played += 1
            profile.updated_at = utcnow()
            saved = await self.repository.upsert(profile)
            updated_profiles[user_id] = saved
            deltas.append(
                PlayerPointDelta(
                    user_id=user_id,
                    previous_points=previous_points,
                    delta=delta,
                    new_points=saved.current_points,
                    rank_before=rank_before,
                    rank_after=rank_before,
                ),
            )
        ranked_profiles = await self.recalculate_rank_positions(guild, config, sync_nicknames=False)
        ranked_by_user_id = {profile.user_id: profile for profile in ranked_profiles}
        for delta in deltas:
            ranked_profile = ranked_by_user_id.get(delta.user_id)
            if ranked_profile is not None:
                delta.rank_after = ranked_profile.current_rank
                delta.new_points = ranked_profile.current_points
        if self.reward_service:
            for candidate_id in {winner_mvp_id, loser_mvp_id} - {None}:
                ranked_profile = ranked_by_user_id.get(candidate_id)
                if ranked_profile is not None:
                    await self.reward_service.sync_mvp_role_if_qualified(guild, ranked_profile, config)
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
        self._ensure_match_updates_allowed(match)
        timeout_rule = config.point_rules[match.match_type.value]["timeout_penalty"]
        deltas: list[PlayerPointDelta] = []
        for user_id in match.all_player_ids:
            profile = await self.ensure_profile(guild, user_id, config)
            previous_points = profile.current_points
            rank_before = self.rank_service.display_rank_for_profile(profile)
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
                    rank_after=rank_before,
                ),
            )
        ranked_profiles = await self.recalculate_rank_positions(guild, config, sync_nicknames=False)
        ranked_by_user_id = {profile.user_id: profile for profile in ranked_profiles}
        for delta in deltas:
            ranked_profile = ranked_by_user_id.get(delta.user_id)
            if ranked_profile is not None:
                delta.rank_after = ranked_profile.current_rank
                delta.new_points = ranked_profile.current_points
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
            await self.ensure_profile(guild, member.id, config, sync_identity=False)
        await self.recalculate_rank_positions(guild, config)

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

    async def recalculate_rank_positions(
        self,
        guild: discord.Guild,
        config: GuildConfig,
        *,
        sync_nicknames: bool = True,
    ) -> list[PlayerProfile]:
        profiles = await self.repository.list_for_ranking(guild.id)
        if not profiles:
            return []

        for profile in profiles:
            member = guild.get_member(profile.user_id)
            if profile.joined_at is None and member and member.joined_at:
                profile.joined_at = member.joined_at
                profile.updated_at = utcnow()
                await self.repository.upsert(profile)

        manual_profiles = [profile for profile in profiles if profile.manual_rank_override is not None]
        ranked_profiles = [profile for profile in profiles if profile.manual_rank_override is None]

        saved_profiles: list[PlayerProfile] = []
        for profile in manual_profiles:
            desired_rank = profile.manual_rank_override or 0
            rank_changed = profile.current_rank != desired_rank
            profile.current_rank = desired_rank
            if rank_changed:
                profile.updated_at = utcnow()
                saved = await self.repository.upsert(profile)
            else:
                saved = profile
            saved_profiles.append(saved)
            if sync_nicknames:
                member = guild.get_member(saved.user_id)
                if member is not None and (rank_changed or self.rank_service.needs_nickname_sync(member, saved)):
                    await self.rank_service.sync_member_rank(member, saved, config)

        ordered = self.rank_service.sort_profiles_for_ranking(ranked_profiles)
        for position, profile in enumerate(ordered, start=1):
            rank_changed = profile.current_rank != position
            profile.current_rank = position
            if rank_changed:
                profile.updated_at = utcnow()
                saved = await self.repository.upsert(profile)
            else:
                saved = profile
            saved_profiles.append(saved)
            if sync_nicknames:
                member = guild.get_member(saved.user_id)
                if member is not None and (rank_changed or self.rank_service.needs_nickname_sync(member, saved)):
                    await self.rank_service.sync_member_rank(member, saved, config)
        return saved_profiles

    async def sync_rank_identities_for_guild(
        self,
        guild: discord.Guild,
        config: GuildConfig,
    ) -> None:
        profiles = await self.repository.list_for_ranking(guild.id)
        for profile in profiles:
            member = guild.get_member(profile.user_id)
            if member is None:
                continue
            if self.rank_service.needs_nickname_sync(member, profile):
                await self.rank_service.sync_member_rank(member, profile, config)

    def _ensure_match_updates_allowed(self, match: MatchRecord) -> None:
        if match.status == MatchStatus.CANCELED:
            raise StateTransitionError("Canceled matches do not change points or profile stats.")
        if match.metadata.get("close_requested") or match.metadata.get("stats_skipped_due_to_cancel"):
            raise StateTransitionError("That match is closing and can no longer change profile stats.")
