from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC

import discord

from highlight_manager.config.logging import get_logger
from highlight_manager.models.common import BootstrapSummary, BootstrapThreshold
from highlight_manager.models.guild_config import GuildConfig
from highlight_manager.services.profile_service import ProfileService
from highlight_manager.utils.dates import utcnow


@dataclass(slots=True)
class BootstrapPreviewEntry:
    member_id: int
    display_name: str
    age_days: int
    rank: int
    starting_points: int


class BootstrapService:
    def __init__(self, profile_service: ProfileService) -> None:
        self.profile_service = profile_service
        self.logger = get_logger(__name__)

    def resolve_threshold(
        self,
        joined_at,
        thresholds: list[BootstrapThreshold],
    ) -> tuple[BootstrapThreshold, int]:
        age_days = max((utcnow() - (joined_at or utcnow())).days, 0)
        ordered = sorted(thresholds, key=lambda item: item.minimum_days, reverse=True)
        for threshold in ordered:
            if age_days >= threshold.minimum_days:
                return threshold, age_days
        fallback = ordered[-1]
        return fallback, age_days

    async def preview(self, guild: discord.Guild, config: GuildConfig) -> tuple[BootstrapSummary, list[BootstrapPreviewEntry]]:
        rank_counts: Counter[str] = Counter()
        preview_entries: list[BootstrapPreviewEntry] = []
        for member in guild.members:
            if member.bot:
                continue
            threshold, age_days = self.resolve_threshold(member.joined_at, config.bootstrap_thresholds)
            rank_counts[str(threshold.rank)] += 1
            preview_entries.append(
                BootstrapPreviewEntry(
                    member_id=member.id,
                    display_name=member.display_name,
                    age_days=age_days,
                    rank=threshold.rank,
                    starting_points=threshold.starting_points,
                ),
            )
        summary = BootstrapSummary(
            processed_members=len(preview_entries),
            rank_counts=dict(rank_counts),
            completed_at=utcnow(),
        )
        return summary, sorted(preview_entries, key=lambda item: item.age_days, reverse=True)

    async def run(self, guild: discord.Guild, config: GuildConfig) -> BootstrapSummary:
        rank_counts: Counter[str] = Counter()
        skipped_members: list[str] = []
        processed_members = 0

        for member in guild.members:
            if member.bot:
                continue
            processed_members += 1
            threshold, age_days = self.resolve_threshold(member.joined_at, config.bootstrap_thresholds)
            profile = await self.profile_service.ensure_profile(member.guild, member.id, config, sync_identity=False)
            if profile.rank0:
                skipped_members.append(f"{member.display_name}: skipped because Rank 0 is manual.")
                continue

            profile.rank0 = False
            profile.current_points = threshold.starting_points
            profile.lifetime_points = threshold.starting_points
            if member.joined_at is not None:
                profile.server_joined_at = (
                    member.joined_at.replace(tzinfo=UTC)
                    if member.joined_at.tzinfo is None
                    else member.joined_at.astimezone(UTC)
                )
            profile.updated_at = utcnow()
            await self.profile_service.repository.upsert(profile)
            rank_counts[str(threshold.rank)] += 1

            self.logger.info(
                "bootstrap_member_processed",
                guild_id=guild.id,
                user_id=member.id,
                age_days=age_days,
                rank=threshold.rank,
                points=threshold.starting_points,
            )

        sync_result = await self.profile_service.sync_all_member_identities(guild, config)

        return BootstrapSummary(
            processed_members=processed_members,
            rank_counts=dict(rank_counts),
            rename_successes=sync_result.nickname_updates,
            rename_failures=sync_result.nickname_failures,
            skipped_members=skipped_members,
            completed_at=utcnow(),
        )
