from __future__ import annotations

import discord


def member_has_any_role(member: discord.Member, role_ids: list[int]) -> bool:
    if not role_ids:
        return False
    member_role_ids = {role.id for role in member.roles}
    return any(role_id in member_role_ids for role_id in role_ids)


def bot_missing_permissions(
    me: discord.Member | None,
    channel: discord.abc.GuildChannel | None,
    permissions: list[str],
) -> list[str]:
    if me is None or channel is None:
        return permissions
    perms = channel.permissions_for(me)
    return [permission for permission in permissions if not getattr(perms, permission, False)]
