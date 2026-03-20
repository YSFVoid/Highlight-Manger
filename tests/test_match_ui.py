from highlight_manager.models.enums import MatchMode, MatchStatus, MatchType
from highlight_manager.models.guild_config import GuildConfig
from highlight_manager.models.match import MatchRecord
from highlight_manager.services.result_channel_service import ResultChannelService
from highlight_manager.utils.channel_names import format_match_channel_name
from highlight_manager.utils.dates import utcnow
from highlight_manager.utils.embeds import build_match_embed


class FakeTarget:
    def __init__(self, target_id: int, *, bot: bool | None = None, is_role: bool = False) -> None:
        self.id = target_id
        self.bot = bot
        self.is_role = is_role


class FakeGuild:
    def __init__(self) -> None:
        self.id = 1
        self.default_role = FakeTarget(0, is_role=True)
        self.me = FakeTarget(999, bot=True)
        self._members: dict[int, object] = {}
        self._roles: dict[int, object] = {}

    def add_member(self, member_id: int) -> None:
        self._members[member_id] = FakeTarget(member_id, bot=False)

    def add_role(self, role_id: int) -> None:
        self._roles[role_id] = FakeTarget(role_id, is_role=True)

    def get_member(self, user_id: int):
        return self._members.get(user_id)

    def get_role(self, role_id: int):
        return self._roles.get(role_id)


def build_match(*, status: MatchStatus, queue_opened: bool = True) -> MatchRecord:
    match = MatchRecord(
        guild_id=1,
        match_number=1,
        creator_id=10,
        mode=MatchMode.TWO_V_TWO,
        match_type=MatchType.APOSTADO,
        status=status,
        team1_player_ids=[10, 11],
        team2_player_ids=[12, 13],
        source_channel_id=100,
        created_at=utcnow(),
    )
    if queue_opened:
        match.queue_opened_at = utcnow()
    return match


def test_match_embed_switches_to_started_title_for_live_match() -> None:
    embed = build_match_embed(build_match(status=MatchStatus.IN_PROGRESS), None)
    assert embed.title == "Apostado 2v2 Match Started"
    assert "Teams are locked." in (embed.description or "")


def test_match_embed_switches_to_canceled_title_and_reason() -> None:
    match = build_match(status=MatchStatus.CANCELED)
    match.metadata["cancel_reason"] = "Host canceled."

    embed = build_match_embed(match, None)

    assert embed.title == "Apostado 2v2 Match Canceled"
    assert "Host canceled." in (embed.description or "")


def test_result_channel_permissions_only_include_players_and_staff_roles() -> None:
    guild = FakeGuild()
    for member_id in [10, 11, 12, 13, 77]:
        guild.add_member(member_id)
    guild.add_role(500)
    guild.add_role(600)
    config = GuildConfig(guild_id=1, admin_role_ids=[500], staff_role_ids=[600])
    match = MatchRecord(
        guild_id=1,
        match_number=1,
        creator_id=77,
        mode=MatchMode.TWO_V_TWO,
        match_type=MatchType.HIGHLIGHT,
        status=MatchStatus.OPEN,
        team1_player_ids=[10, 11],
        team2_player_ids=[12, 13],
        created_at=utcnow(),
    )

    overwrites = ResultChannelService()._build_overwrites(guild, match, config)
    member_ids = {target.id for target in overwrites if getattr(target, "bot", None) is False}

    assert member_ids == {10, 11, 12, 13}


def test_match_channel_name_formatter_uses_bold_unicode_templates() -> None:
    match = build_match(status=MatchStatus.OPEN)

    rendered = format_match_channel_name("{match_type_styled} {match_number_styled}", match)

    assert rendered == "𝐀𝐏𝐎𝐒𝐓𝐀𝐃𝐎 𝟏"
