from highlight_manager.models.enums import MatchMode, MatchStatus, MatchType
from highlight_manager.models.match import MatchRecord
from highlight_manager.models.vote import MatchVote
from highlight_manager.services.vote_service import VoteService


class DummyVoteRepository:
    async def upsert(self, vote: MatchVote) -> MatchVote:
        return vote

    async def list_for_match(self, guild_id: int, match_number: int) -> list[MatchVote]:
        return []

    async def delete_for_match(self, guild_id: int, match_number: int) -> None:
        return None


def build_match() -> MatchRecord:
    from highlight_manager.utils.dates import utcnow, minutes_from_now

    return MatchRecord(
        guild_id=1,
        match_number=1,
        creator_id=10,
        mode=MatchMode.TWO_V_TWO,
        match_type=MatchType.APOSTADO,
        status=MatchStatus.VOTING,
        team1_player_ids=[10, 11],
        team2_player_ids=[20, 21],
        created_at=utcnow(),
        queue_expires_at=minutes_from_now(5),
        vote_expires_at=minutes_from_now(30),
    )


def test_compute_consensus_returns_majority_result() -> None:
    service = VoteService(DummyVoteRepository())
    match = build_match()
    votes = [
        MatchVote(guild_id=1, match_number=1, user_id=10, winner_team=1, winner_mvp_id=10, loser_mvp_id=20),
        MatchVote(guild_id=1, match_number=1, user_id=11, winner_team=1, winner_mvp_id=10, loser_mvp_id=20),
        MatchVote(guild_id=1, match_number=1, user_id=20, winner_team=1, winner_mvp_id=10, loser_mvp_id=20),
        MatchVote(guild_id=1, match_number=1, user_id=21, winner_team=2, winner_mvp_id=21, loser_mvp_id=11),
    ]
    consensus = service.compute_consensus(match, votes)
    assert consensus is not None
    assert consensus.winner_team == 1
    assert consensus.winner_mvp_id == 10
    assert consensus.loser_mvp_id == 20


def test_compute_consensus_returns_none_for_conflict() -> None:
    service = VoteService(DummyVoteRepository())
    match = build_match()
    votes = [
        MatchVote(guild_id=1, match_number=1, user_id=10, winner_team=1, winner_mvp_id=10, loser_mvp_id=20),
        MatchVote(guild_id=1, match_number=1, user_id=11, winner_team=2, winner_mvp_id=21, loser_mvp_id=10),
        MatchVote(guild_id=1, match_number=1, user_id=20, winner_team=1, winner_mvp_id=11, loser_mvp_id=20),
        MatchVote(guild_id=1, match_number=1, user_id=21, winner_team=2, winner_mvp_id=21, loser_mvp_id=11),
    ]
    assert service.compute_consensus(match, votes) is None
