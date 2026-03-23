import pytest
import discord

from highlight_manager.interactions.views import (
    CaptainMVPSelectionView,
    CaptainWinnerSelectionView,
    MatchQueueView,
    ResultEntryView,
    RoomInfoEntryView,
)


class DummyMatchService:
    class DummyBot:
        @staticmethod
        def get_guild(guild_id: int):
            return None

    def __init__(self) -> None:
        self.bot = self.DummyBot()


class FakeDiscordMember(discord.Member):
    __slots__ = ("id",)


class FakeResponse:
    def __init__(self) -> None:
        self.deferred = False
        self.messages: list[dict] = []

    async def send_message(self, content=None, embed=None, ephemeral: bool = False):
        self.messages.append({"content": content, "embed": embed, "ephemeral": ephemeral})

    async def defer(self, *, ephemeral: bool = False, thinking: bool = False):
        self.deferred = True


class FakeFollowup:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def send(self, content=None, embed=None, ephemeral: bool = False):
        self.messages.append({"content": content, "embed": embed, "ephemeral": ephemeral})


class FakeInteraction:
    def __init__(self, *, user, guild_id: int = 321) -> None:
        self.user = user
        self.guild_id = guild_id
        self.guild = object()
        self.response = FakeResponse()
        self.followup = FakeFollowup()


class CancelAwareMatchService(DummyMatchService):
    def __init__(self) -> None:
        super().__init__()
        self.cancel_calls = 0

    async def require_match(self, guild_id: int, match_number: int):
        return type("Match", (), {"creator_id": 10})()

    async def cancel_match(self, guild, match_number: int, *, actor_id: int | None, force: bool, reason: str):
        self.cancel_calls += 1
        return type("Result", (), {"message": "Canceled"})()


@pytest.mark.asyncio
async def test_match_queue_view_custom_ids_include_guild_and_match_number() -> None:
    view = MatchQueueView(DummyMatchService(), guild_id=321, match_number=7)

    assert view.join_team_1.custom_id == "match:321:7:join1"
    assert view.join_team_2.custom_id == "match:321:7:join2"
    assert view.leave_match.custom_id == "match:321:7:leave"
    assert view.cancel_match.custom_id == "match:321:7:cancel"


@pytest.mark.asyncio
async def test_match_queue_view_disables_only_the_full_team_button() -> None:
    view = MatchQueueView(
        DummyMatchService(),
        guild_id=321,
        match_number=7,
        team1_full=True,
        team2_full=False,
    )

    assert view.join_team_1.disabled is True
    assert view.join_team_1.label == "Team 1 Full"
    assert view.join_team_2.disabled is False
    assert view.join_team_2.label == "Join Team 2"
    assert view.leave_match.disabled is False
    assert view.cancel_match.disabled is False


@pytest.mark.asyncio
async def test_result_entry_view_custom_ids_include_guild_and_match_number() -> None:
    view = ResultEntryView(DummyMatchService(), guild_id=321, match_number=7)

    assert view.submit_vote.custom_id == "result:321:7:submit"
    assert view.refresh_status.custom_id == "result:321:7:status"
    assert view.cancel_match.custom_id == "result:321:7:cancel"


@pytest.mark.asyncio
async def test_room_info_entry_view_custom_id_includes_guild_and_match_number() -> None:
    view = RoomInfoEntryView(DummyMatchService(), guild_id=321, match_number=7)

    assert view.enter_room_info.custom_id == "roominfo:321:7:open"


@pytest.mark.asyncio
async def test_captain_winner_selection_view_custom_ids_include_guild_and_match_number() -> None:
    view = CaptainWinnerSelectionView(DummyMatchService(), guild_id=321, match_number=7)

    assert view.team_1_won.custom_id == "captainresult:321:7:winner:1"
    assert view.team_2_won.custom_id == "captainresult:321:7:winner:2"


@pytest.mark.asyncio
async def test_captain_mvp_selection_view_custom_id_includes_kind() -> None:
    view = CaptainMVPSelectionView(
        DummyMatchService(),
        guild_id=321,
        match_number=7,
        selection_kind="winner",
        player_ids=[11, 22],
    )

    select = view.children[0]
    assert select.custom_id == "captainresult:321:7:winner:mvp"


@pytest.mark.asyncio
async def test_match_queue_cancel_is_creator_only_in_ui() -> None:
    service = CancelAwareMatchService()
    view = MatchQueueView(service, guild_id=321, match_number=7)
    member = object.__new__(FakeDiscordMember)
    member.id = 99
    interaction = FakeInteraction(user=member)

    await view.cancel_match.callback(interaction)

    assert interaction.response.deferred is True
    assert interaction.followup.messages[0]["content"] == "Only the match creator can cancel this match here. Staff must use /match cancel."
    assert service.cancel_calls == 0
