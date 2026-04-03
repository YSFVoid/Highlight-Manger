from __future__ import annotations

from highlight_manager.models.guild_config import GuildConfig
from highlight_manager.models.profile import PlayerProfile
from highlight_manager.utils.embeds import build_config_embed, build_leaderboard_embed


class FakeMember:
    def __init__(self, user_id: int, *, nick: str | None = None, global_name: str | None = None, name: str) -> None:
        self.id = user_id
        self.nick = nick
        self.global_name = global_name
        self.name = name
        self.mention = f"<@{user_id}>"


class FakeGuild:
    def __init__(self, members: list[FakeMember]) -> None:
        self._members = {member.id: member for member in members}

    def get_member(self, user_id: int):
        return self._members.get(user_id)


def test_build_leaderboard_embed_uses_clean_member_names() -> None:
    guild = FakeGuild(
        [
            FakeMember(1, nick="RANK 621|HIGH Asta", name="asta_account"),
            FakeMember(2, nick="Rank 2 |HIGH rayen", name="rayen_account"),
        ]
    )
    profiles = [
        PlayerProfile(guild_id=1, user_id=1, current_points=120, current_rank=5),
        PlayerProfile(guild_id=1, user_id=2, current_points=90, current_rank=2),
    ]

    embed = build_leaderboard_embed(guild, profiles, title="Current Season Leaderboard")

    assert embed.description == (
        "**5.** Asta | 120 pts | RANK 5\n"
        "**2.** rayen | 90 pts | RANK 2"
    )


def test_build_config_embed_describes_live_rank_system() -> None:
    config = GuildConfig(guild_id=1, rank_role_map={"0": 123, "1": 456, "2": 789})

    embed = build_config_embed(config, guild=None)
    fields = {field.name: field.value for field in embed.fields}

    assert fields["Live Rank System"] == (
        "Rank is live leaderboard placement, not a Discord role.\n"
        "Tie-breaks: points, wins, winner MVP count, older join date, user ID."
    )
    assert fields["Rank 0 Override"] == "<@&123>"
    assert fields["Legacy Rank Roles"] == "2 configured but ignored"
