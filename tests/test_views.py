import pytest

from highlight_manager.interactions.views import MatchQueueView, ResultEntryView


class DummyMatchService:
    pass


@pytest.mark.asyncio
async def test_match_queue_view_custom_ids_include_guild_and_match_number() -> None:
    view = MatchQueueView(DummyMatchService(), guild_id=321, match_number=7)

    assert view.join_team_1.custom_id == "match:321:7:join1"
    assert view.join_team_2.custom_id == "match:321:7:join2"
    assert view.leave_match.custom_id == "match:321:7:leave"
    assert view.cancel_match.custom_id == "match:321:7:cancel"


@pytest.mark.asyncio
async def test_result_entry_view_custom_ids_include_guild_and_match_number() -> None:
    view = ResultEntryView(DummyMatchService(), guild_id=321, match_number=7)

    assert view.submit_vote.custom_id == "result:321:7:submit"
    assert view.refresh_status.custom_id == "result:321:7:status"
