from __future__ import annotations

import discord

from highlight_manager.config.logging import get_logger
from highlight_manager.models.enums import AuditAction
from highlight_manager.models.guild_config import GuildConfig
from highlight_manager.models.profile import PlayerProfile


class RewardService:
    def __init__(self, config_service, audit_service) -> None:
        self.config_service = config_service
        self.audit_service = audit_service
        self.logger = get_logger(__name__)

    def get_mvp_qualification_reason(self, profile: PlayerProfile, config: GuildConfig) -> str | None:
        if profile.mvp_winner_count >= config.mvp_winner_requirement:
            return f"MVP Winner count reached {profile.mvp_winner_count}."
        if profile.mvp_loser_count >= config.mvp_loser_requirement:
            return f"MVP Loser count reached {profile.mvp_loser_count}."
        return None

    async def sync_mvp_role_if_qualified(
        self,
        guild: discord.Guild,
        profile: PlayerProfile,
        config: GuildConfig,
    ) -> bool:
        reason = self.get_mvp_qualification_reason(profile, config)
        if reason is None:
            return False

        member = guild.get_member(profile.user_id)
        if member is None:
            self.logger.warning(
                "mvp_reward_member_missing",
                guild_id=guild.id,
                user_id=profile.user_id,
                mvp_winner_count=profile.mvp_winner_count,
                mvp_loser_count=profile.mvp_loser_count,
            )
            return False

        config, role, _ = await self.config_service.ensure_mvp_reward_role(
            guild,
            config,
            create_missing=True,
        )
        if role is None:
            self.logger.warning("mvp_reward_role_unavailable", guild_id=guild.id)
            return False
        if role in member.roles:
            return False

        me = guild.me
        if me is None or not me.guild_permissions.manage_roles:
            self.logger.warning(
                "mvp_reward_assignment_missing_permission",
                guild_id=guild.id,
                user_id=member.id,
                role_id=role.id,
            )
            return False
        if role >= me.top_role:
            self.logger.warning(
                "mvp_reward_assignment_role_hierarchy",
                guild_id=guild.id,
                user_id=member.id,
                role_id=role.id,
            )
            return False
        if member.top_role >= me.top_role or member == guild.owner:
            self.logger.warning(
                "mvp_reward_assignment_member_hierarchy",
                guild_id=guild.id,
                user_id=member.id,
                role_id=role.id,
            )
            return False

        try:
            await member.add_roles(role, reason="Highlight Manager MVP achievement reward")
        except discord.Forbidden:
            self.logger.warning(
                "mvp_reward_assignment_forbidden",
                guild_id=guild.id,
                user_id=member.id,
                role_id=role.id,
            )
            return False
        except discord.HTTPException as exc:
            self.logger.warning(
                "mvp_reward_assignment_failed",
                guild_id=guild.id,
                user_id=member.id,
                role_id=role.id,
                error=str(exc),
            )
            return False

        self.logger.info(
            "mvp_reward_granted",
            guild_id=guild.id,
            user_id=member.id,
            role_id=role.id,
            mvp_winner_count=profile.mvp_winner_count,
            mvp_loser_count=profile.mvp_loser_count,
            qualification_reason=reason,
        )
        await self.audit_service.log(
            guild,
            AuditAction.REWARD_GRANTED,
            f"Granted {role.mention} to {member.mention}.",
            target_id=member.id,
            metadata={
                "role": role.name,
                "mvp_winner_count": profile.mvp_winner_count,
                "mvp_loser_count": profile.mvp_loser_count,
                "qualification_reason": reason,
            },
        )
        return True
