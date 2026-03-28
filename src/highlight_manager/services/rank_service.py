from __future__ import annotations

import re
from dataclasses import dataclass

import discord

from highlight_manager.config.logging import get_logger
from highlight_manager.models.common import RankThreshold
from highlight_manager.models.guild_config import GuildConfig
from highlight_manager.models.profile import PlayerProfile


@dataclass(slots=True)
class RankSyncResult:
    role_updated: bool = False
    nickname_updated: bool = False
    nickname_failed: bool = False
    skipped_reason: str | None = None


class RankService:
    PREFIX_PATTERNS = [
        re.compile(r"^\s*rank\s+\d+\s*(?:\|\s*)?(?:high\s+)?", flags=re.IGNORECASE),
        re.compile(r"^\s*high\s+", flags=re.IGNORECASE),
    ]

    def __init__(self) -> None:
        self.logger = get_logger(__name__)

    def resolve_rank(self, points: int, thresholds: list[RankThreshold]) -> int:
        for threshold in sorted(
            thresholds,
            key=lambda item: (item.min_points if item.min_points is not None else -10**9),
        ):
            min_ok = threshold.min_points is None or points >= threshold.min_points
            max_ok = threshold.max_points is None or points <= threshold.max_points
            if min_ok and max_ok:
                return threshold.rank
        highest = max(thresholds, key=lambda item: item.rank, default=RankThreshold(rank=1))
        return highest.rank

    async def sync_member_roles(
        self,
        member: discord.Member,
        profile: PlayerProfile,
        config: GuildConfig,
    ) -> RankSyncResult:
        result = RankSyncResult()
        if member.bot:
            return result
        rank_role_ids = {int(role_id) for role_id in config.rank_role_map.values()}
        if rank_role_ids:
            if profile.rank0 and config.features.preserve_rank0:
                target_role_id = config.rank_role_map.get("0")
            else:
                target_role_id = config.rank_role_map.get(str(profile.current_rank))

            target_role = member.guild.get_role(int(target_role_id)) if target_role_id else None
            removable_roles = [role for role in member.roles if role.id in rank_role_ids and role != target_role]
            needs_add = bool(target_role and target_role not in member.roles)
            try:
                if removable_roles:
                    await member.remove_roles(*removable_roles, reason="Rank sync")
                if needs_add and target_role:
                    await member.add_roles(target_role, reason="Rank sync")
                result.role_updated = bool(removable_roles or needs_add)
                self.logger.info(
                    "rank_roles_synced",
                    guild_id=member.guild.id,
                    user_id=member.id,
                    target_role_id=target_role.id if target_role else None,
                )
            except discord.Forbidden:
                self.logger.warning(
                    "rank_role_sync_forbidden",
                    guild_id=member.guild.id,
                    user_id=member.id,
                    target_role_id=target_role.id if target_role else None,
                )
                result.skipped_reason = "Missing Manage Roles or higher role position."
            except discord.HTTPException as exc:
                self.logger.warning(
                    "rank_role_sync_failed",
                    guild_id=member.guild.id,
                    user_id=member.id,
                    error=str(exc),
                )
                result.skipped_reason = f"Role sync failed: {exc}"

        nickname_result = await self.sync_member_nickname(member, profile, config)
        if nickname_result.nickname_updated:
            result.nickname_updated = True
        if nickname_result.nickname_failed:
            result.nickname_failed = True
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
        if not config.features.nickname_rank_sync:
            return result
        me = member.guild.me
        if me is None or not me.guild_permissions.manage_nicknames:
            result.skipped_reason = "Missing Manage Nicknames permission."
            return result
        if member == member.guild.owner or member.top_role >= me.top_role:
            result.skipped_reason = "Skipped nickname update due to role hierarchy."
            return result

        base_name = self.strip_rank_prefix(member.nick or member.global_name or member.name)
        target_nickname = self.build_rank_nickname(profile.current_rank, base_name)
        if member.nick == target_nickname:
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
            result.skipped_reason = "Could not rename member due to permissions or role hierarchy."
            self.logger.warning("rank_nickname_sync_forbidden", guild_id=member.guild.id, user_id=member.id)
        except discord.HTTPException as exc:
            result.nickname_failed = True
            result.skipped_reason = f"Nickname update failed: {exc}"
            self.logger.warning("rank_nickname_sync_failed", guild_id=member.guild.id, user_id=member.id, error=str(exc))
        return result

    def strip_rank_prefix(self, name: str) -> str:
        cleaned = name.strip()
        while True:
            original = cleaned
            for pattern in self.PREFIX_PATTERNS:
                cleaned = pattern.sub("", cleaned).strip()
            if cleaned == original:
                break
        return cleaned or "Player"

    def build_rank_nickname(self, rank: int, base_name: str) -> str:
        prefix = f"Rank {rank} "
        remaining = 32 - len(prefix)
        truncated_base = base_name[:remaining].strip() or "Player"
        return f"{prefix}{truncated_base}"
