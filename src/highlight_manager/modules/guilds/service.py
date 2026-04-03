from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from highlight_manager.app.config import Settings
from highlight_manager.modules.common.cache import SimpleTTLCache
from highlight_manager.modules.common.enums import RoleKind
from highlight_manager.modules.guilds.repository import GuildBundle, GuildRepository


@dataclass(slots=True)
class StaffRoleSet:
    admin_role_ids: set[int]
    moderator_role_ids: set[int]


class GuildService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._settings_cache = SimpleTTLCache(maxsize=128, ttl=60)
        self._staff_cache = SimpleTTLCache(maxsize=128, ttl=60)

    async def ensure_guild(self, repository: GuildRepository, discord_guild_id: int, name: str | None) -> GuildBundle:
        cached = self._settings_cache.get(str(discord_guild_id))
        if isinstance(cached, GuildBundle):
            return cached
        bundle = await repository.ensure_guild(
            discord_guild_id,
            name=name,
            default_prefix=self.settings.default_prefix,
            queue_timeout_seconds=self.settings.queue_timeout_seconds,
            room_info_timeout_seconds=self.settings.room_info_timeout_seconds,
            result_timeout_seconds=self.settings.result_timeout_seconds,
        )
        self._settings_cache.set(str(discord_guild_id), bundle)
        return bundle

    async def get_bundle(self, repository: GuildRepository, discord_guild_id: int) -> GuildBundle | None:
        cached = self._settings_cache.get(str(discord_guild_id))
        if cached is not None:
            return cached
        bundle = await repository.get_bundle_by_discord_id(discord_guild_id)
        if bundle is not None:
            self._settings_cache.set(str(discord_guild_id), bundle)
        return bundle

    async def replace_staff_roles(
        self,
        repository: GuildRepository,
        guild_id: int,
        *,
        admin_role_ids: Iterable[int],
        moderator_role_ids: Iterable[int],
    ) -> None:
        await repository.replace_staff_roles(
            guild_id,
            admin_role_ids=set(admin_role_ids),
            moderator_role_ids=set(moderator_role_ids),
        )
        self._staff_cache.invalidate(str(guild_id))

    async def update_settings(
        self,
        repository: GuildRepository,
        *,
        discord_guild_id: int,
        guild_id: int,
        **fields,
    ) -> GuildBundle:
        settings = await repository.update_settings(guild_id, **fields)
        guild = await repository.get_by_id(guild_id)
        if guild is None:
            raise ValueError("Guild does not exist.")
        bundle = GuildBundle(guild=guild, settings=settings)
        self._settings_cache.set(str(discord_guild_id), bundle)
        return bundle

    async def get_staff_roles(self, repository: GuildRepository, guild_id: int) -> StaffRoleSet:
        cached = self._staff_cache.get(str(guild_id))
        if cached is not None:
            return cached
        roles = await repository.list_staff_roles(guild_id)
        role_set = StaffRoleSet(
            admin_role_ids={role.role_id for role in roles if role.role_kind == RoleKind.ADMIN},
            moderator_role_ids={role.role_id for role in roles if role.role_kind == RoleKind.MODERATOR},
        )
        self._staff_cache.set(str(guild_id), role_set)
        return role_set

    async def member_is_moderator(self, repository: GuildRepository, guild_id: int, role_ids: Iterable[int]) -> bool:
        staff_roles = await self.get_staff_roles(repository, guild_id)
        role_id_set = set(role_ids)
        return bool(role_id_set & (staff_roles.admin_role_ids | staff_roles.moderator_role_ids))

    async def member_is_admin(self, repository: GuildRepository, guild_id: int, role_ids: Iterable[int]) -> bool:
        staff_roles = await self.get_staff_roles(repository, guild_id)
        return bool(set(role_ids) & staff_roles.admin_role_ids)
