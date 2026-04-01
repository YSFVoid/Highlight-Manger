from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from highlight_manager.db.models.core import GuildModel, GuildSettingModel, GuildStaffRoleModel
from highlight_manager.modules.common.enums import RoleKind


@dataclass(slots=True)
class GuildBundle:
    guild: GuildModel
    settings: GuildSettingModel


class GuildRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_discord_id(self, discord_guild_id: int) -> GuildModel | None:
        return await self.session.scalar(
            select(GuildModel).where(GuildModel.discord_guild_id == discord_guild_id)
        )

    async def get_by_id(self, guild_id: int) -> GuildModel | None:
        return await self.session.get(GuildModel, guild_id)

    async def ensure_guild(
        self,
        discord_guild_id: int,
        *,
        name: str | None,
        default_prefix: str,
        queue_timeout_seconds: int,
        room_info_timeout_seconds: int,
        result_timeout_seconds: int,
    ) -> GuildBundle:
        guild = await self.get_by_discord_id(discord_guild_id)
        if guild is None:
            guild = GuildModel(discord_guild_id=discord_guild_id, name=name)
            self.session.add(guild)
            await self.session.flush()
        elif name and guild.name != name:
            guild.name = name

        settings = await self.session.get(GuildSettingModel, guild.id)
        if settings is None:
            settings = GuildSettingModel(
                guild_id=guild.id,
                prefix=default_prefix,
                queue_timeout_seconds=queue_timeout_seconds,
                room_info_timeout_seconds=room_info_timeout_seconds,
                result_timeout_seconds=result_timeout_seconds,
            )
            self.session.add(settings)
            await self.session.flush()
        return GuildBundle(guild=guild, settings=settings)

    async def get_bundle_by_discord_id(self, discord_guild_id: int) -> GuildBundle | None:
        guild = await self.get_by_discord_id(discord_guild_id)
        if guild is None:
            return None
        settings = await self.session.get(GuildSettingModel, guild.id)
        if settings is None:
            return None
        return GuildBundle(guild=guild, settings=settings)

    async def replace_staff_roles(
        self,
        guild_id: int,
        *,
        admin_role_ids: set[int],
        moderator_role_ids: set[int],
    ) -> None:
        await self.session.execute(delete(GuildStaffRoleModel).where(GuildStaffRoleModel.guild_id == guild_id))
        for role_id in sorted(admin_role_ids):
            self.session.add(
                GuildStaffRoleModel(guild_id=guild_id, role_id=role_id, role_kind=RoleKind.ADMIN)
            )
        for role_id in sorted(moderator_role_ids):
            self.session.add(
                GuildStaffRoleModel(guild_id=guild_id, role_id=role_id, role_kind=RoleKind.MODERATOR)
            )
        await self.session.flush()

    async def list_staff_roles(self, guild_id: int) -> list[GuildStaffRoleModel]:
        result = await self.session.scalars(
            select(GuildStaffRoleModel).where(GuildStaffRoleModel.guild_id == guild_id)
        )
        return list(result.all())

    async def update_settings(self, guild_id: int, **fields) -> GuildSettingModel:
        settings = await self.session.get(GuildSettingModel, guild_id)
        if settings is None:
            raise ValueError("Guild settings do not exist.")
        for key, value in fields.items():
            setattr(settings, key, value)
        await self.session.flush()
        return settings
