from __future__ import annotations

from dataclasses import dataclass

import discord

from highlight_manager.config.logging import get_logger
from highlight_manager.models.common import BootstrapSummary, PlayerStats
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

    def sorted_members_by_server_age(self, guild: discord.Guild) -> list[discord.Member]:
        return sorted(
            [member for member in guild.members if not member.bot],
            key=lambda member: (
                member.joined_at or utcnow(),
                member.id,
            ),
        )

    async def preview(self, guild: discord.Guild, config: GuildConfig) -> tuple[BootstrapSummary, list[BootstrapPreviewEntry]]:
        preview_entries: list[BootstrapPreviewEntry] = []
        for position, member in enumerate(self.sorted_members_by_server_age(guild), start=1):
            age_days = max((utcnow() - (member.joined_at or utcnow())).days, 0)
            preview_entries.append(
                BootstrapPreviewEntry(
                    member_id=member.id,
                    display_name=member.display_name,
                    age_days=age_days,
                    rank=position,
                    starting_points=0,
                ),
            )
        summary = BootstrapSummary(
            processed_members=len(preview_entries),
            first_assigned_rank=1 if preview_entries else None,
            last_assigned_rank=len(preview_entries) if preview_entries else None,
            completed_at=utcnow(),
        )
        return summary, preview_entries

    async def run(self, guild: discord.Guild, config: GuildConfig) -> BootstrapSummary:
        renamed_members = 0
        rename_failures = 0
        rename_already_correct = 0
        rename_skipped_due_to_hierarchy = 0
        rename_skipped_due_to_missing_permission = 0
        rename_skipped_other = 0
        skipped_members: list[str] = []
        processed_members = 0

        ordered_members = self.sorted_members_by_server_age(guild)
        for position, member in enumerate(ordered_members, start=1):
            processed_members += 1
            profile = await self.profile_service.ensure_profile(member.guild, member.id, config, sync_identity=False)
            age_days = max((utcnow() - (member.joined_at or utcnow())).days, 0)
            profile.current_rank = position
            profile.current_points = 0
            profile.season_stats = PlayerStats()
            profile.joined_at = member.joined_at or profile.joined_at or utcnow()
            profile.updated_at = utcnow()
            saved = await self.profile_service.repository.upsert(profile)
            sync_result = await self.profile_service.rank_service.sync_member_rank(member, saved, config)

            if sync_result.nickname_updated:
                renamed_members += 1
            elif sync_result.nickname_already_correct:
                rename_already_correct += 1
            elif sync_result.nickname_failed:
                rename_failures += 1
                if sync_result.failure_category == "hierarchy":
                    rename_skipped_due_to_hierarchy += 1
                elif sync_result.failure_category == "missing_permission":
                    rename_skipped_due_to_missing_permission += 1
                else:
                    rename_skipped_other += 1
            if sync_result.skipped_reason:
                skipped_members.append(f"{member.display_name}: {sync_result.skipped_reason}")

            self.logger.info(
                "bootstrap_member_processed",
                guild_id=guild.id,
                user_id=member.id,
                age_days=age_days,
                rank=position,
                points=0,
            )

        return BootstrapSummary(
            processed_members=processed_members,
            first_assigned_rank=1 if processed_members else None,
            last_assigned_rank=processed_members if processed_members else None,
            renamed_members=renamed_members,
            rename_failures=rename_failures,
            rename_already_correct=rename_already_correct,
            rename_skipped_due_to_hierarchy=rename_skipped_due_to_hierarchy,
            rename_skipped_due_to_missing_permission=rename_skipped_due_to_missing_permission,
            rename_skipped_other=rename_skipped_other,
            skipped_members=skipped_members,
            completed_at=utcnow(),
        )
