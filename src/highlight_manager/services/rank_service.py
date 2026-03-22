from __future__ import annotations

import re
from dataclasses import dataclass

import discord

from highlight_manager.config.logging import get_logger
from highlight_manager.models.guild_config import GuildConfig
from highlight_manager.models.profile import PlayerProfile


@dataclass(slots=True)
class RankSyncResult:
    nickname_attempted: bool = False
    nickname_updated: bool = False
    nickname_already_correct: bool = False
    nickname_failed: bool = False
    failure_category: str | None = None
    skipped_reason: str | None = None


class RankService:
    PREFIX_PATTERN = re.compile(r"^Rank\s+\d+\s*(?:\|\s*)?", flags=re.IGNORECASE)

    def __init__(self) -> None:
        self.logger = get_logger(__name__)

    def sort_profiles_for_ranking(self, profiles: list[PlayerProfile]) -> list[PlayerProfile]:
        return sorted(
            profiles,
            key=lambda profile: (
                -profile.current_points,
                -profile.season_stats.wins,
                -profile.season_stats.mvp_wins,
                profile.joined_at or profile.created_at,
                profile.user_id,
            ),
        )

    def display_rank_for_profile(self, profile: PlayerProfile) -> int:
        return profile.manual_rank_override if profile.manual_rank_override is not None else profile.current_rank

    async def sync_member_rank(
        self,
        member: discord.Member,
        profile: PlayerProfile,
        config: GuildConfig,
    ) -> RankSyncResult:
        result = RankSyncResult()
        if member.bot:
            return result
        nickname_result = await self.sync_member_nickname(member, profile, config)
        result.nickname_attempted = nickname_result.nickname_attempted
        if nickname_result.nickname_updated:
            result.nickname_updated = True
        if nickname_result.nickname_already_correct:
            result.nickname_already_correct = True
        if nickname_result.nickname_failed:
            result.nickname_failed = True
        if nickname_result.failure_category:
            result.failure_category = nickname_result.failure_category
        if nickname_result.skipped_reason and result.skipped_reason is None:
            result.skipped_reason = nickname_result.skipped_reason
        return result

    async def sync_member_nickname(
        self,
        member: discord.Member,
        profile: PlayerProfile,
        config: GuildConfig,
    ) -> RankSyncResult:
        result = RankSyncResult()
        result.nickname_attempted = True
        me = member.guild.me
        if me is None or not me.guild_permissions.manage_nicknames:
            result.nickname_failed = True
            result.failure_category = "missing_permission"
            result.skipped_reason = "Missing Manage Nicknames permission."
            return result
        if member == member.guild.owner or member.top_role >= me.top_role:
            result.nickname_failed = True
            result.failure_category = "hierarchy"
            result.skipped_reason = "Skipped nickname update due to role hierarchy."
            return result

        base_name = self.strip_rank_prefix(member.nick or member.global_name or member.name)
        target_nickname = self.build_rank_nickname(self.display_rank_for_profile(profile), base_name)
        if member.nick == target_nickname:
            result.nickname_already_correct = True
            return result
        try:
            await member.edit(nick=target_nickname, reason="Rank nickname sync")
            result.nickname_updated = True
            self.logger.info(
                "rank_nickname_synced",
                guild_id=member.guild.id,
                user_id=member.id,
                nickname=target_nickname,
            )
        except discord.Forbidden:
            result.nickname_failed = True
            result.failure_category = "other"
            result.skipped_reason = "Could not rename member because Discord rejected the nickname change."
            self.logger.warning("rank_nickname_sync_forbidden", guild_id=member.guild.id, user_id=member.id)
        except discord.HTTPException as exc:
            result.nickname_failed = True
            result.failure_category = "other"
            result.skipped_reason = f"Nickname update failed: {exc}"
            self.logger.warning("rank_nickname_sync_failed", guild_id=member.guild.id, user_id=member.id, error=str(exc))
        return result

    def needs_nickname_sync(
        self,
        member: discord.Member,
        profile: PlayerProfile,
    ) -> bool:
        if member.bot:
            return False
        nickname = getattr(member, "nick", None)
        global_name = getattr(member, "global_name", None)
        username = getattr(member, "name", None) or f"User {member.id}"
        base_name = self.strip_rank_prefix(nickname or global_name or username)
        target_nickname = self.build_rank_nickname(self.display_rank_for_profile(profile), base_name)
        return nickname != target_nickname

    def strip_rank_prefix(self, name: str) -> str:
        cleaned = self.PREFIX_PATTERN.sub("", name).strip()
        return cleaned or "Player"

    def build_rank_nickname(self, rank: int, base_name: str) -> str:
        prefix = f"RANK {rank} | "
        remaining = 32 - len(prefix)
        truncated_base = base_name[:remaining].strip() or "Player"
        return f"{prefix}{truncated_base}"
