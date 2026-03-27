from __future__ import annotations

import pytest

from highlight_manager.models.enums import TournamentMatchStatus, TournamentPhase, TournamentSize
from highlight_manager.models.tournament import TournamentMatchRecord, TournamentRecord, TournamentTeam
from highlight_manager.services.tournament_bracket_service import TournamentBracketService
from highlight_manager.services.tournament_service import TournamentService
from highlight_manager.services.tournament_standings_service import TournamentStandingsService
from highlight_manager.utils.dates import utcnow
from highlight_manager.utils.exceptions import UserFacingError


class FakeTournamentRepository:
    def __init__(self) -> None:
        self.storage: dict[tuple[int, int], TournamentRecord] = {}

    async def create(self, tournament: TournamentRecord) -> TournamentRecord:
        self.storage[(tournament.guild_id, tournament.tournament_number)] = tournament
        return tournament

    async def replace(self, tournament: TournamentRecord) -> TournamentRecord:
        self.storage[(tournament.guild_id, tournament.tournament_number)] = tournament
        return tournament

    async def get(self, guild_id: int, tournament_number: int) -> TournamentRecord | None:
        return self.storage.get((guild_id, tournament_number))

    async def get_active(self, guild_id: int) -> TournamentRecord | None:
        for (stored_guild_id, _), tournament in sorted(self.storage.items()):
            if stored_guild_id != guild_id:
                continue
            if tournament.phase in {TournamentPhase.REGISTRATION, TournamentPhase.GROUP_STAGE, TournamentPhase.KNOCKOUT}:
                return tournament
        return None

    async def get_latest(self, guild_id: int) -> TournamentRecord | None:
        tournaments = [item for (stored_guild_id, _), item in self.storage.items() if stored_guild_id == guild_id]
        return max(tournaments, key=lambda item: item.tournament_number, default=None)


class FakeTournamentTeamRepository:
    def __init__(self) -> None:
        self.storage: dict[tuple[int, int, int], TournamentTeam] = {}

    async def create(self, team: TournamentTeam) -> TournamentTeam:
        self.storage[(team.guild_id, team.tournament_number, team.team_number)] = team
        return team

    async def replace(self, team: TournamentTeam) -> TournamentTeam:
        self.storage[(team.guild_id, team.tournament_number, team.team_number)] = team
        return team

    async def get(self, guild_id: int, tournament_number: int, team_number: int) -> TournamentTeam | None:
        return self.storage.get((guild_id, tournament_number, team_number))

    async def list_for_tournament(self, guild_id: int, tournament_number: int) -> list[TournamentTeam]:
        teams = [
            team
            for (stored_guild_id, stored_tournament_number, _), team in self.storage.items()
            if stored_guild_id == guild_id and stored_tournament_number == tournament_number
        ]
        return sorted(teams, key=lambda item: (item.group_label or "", item.team_number))

    async def get_latest_team(self, guild_id: int, tournament_number: int) -> TournamentTeam | None:
        teams = await self.list_for_tournament(guild_id, tournament_number)
        return max(teams, key=lambda item: item.team_number, default=None)

    async def find_by_player(self, guild_id: int, tournament_number: int, user_id: int) -> TournamentTeam | None:
        for team in await self.list_for_tournament(guild_id, tournament_number):
            if user_id in team.player_ids:
                return team
        return None


class FakeTournamentMatchRepository:
    def __init__(self) -> None:
        self.storage: dict[tuple[int, int, int], TournamentMatchRecord] = {}

    async def create(self, match: TournamentMatchRecord) -> TournamentMatchRecord:
        self.storage[(match.guild_id, match.tournament_number, match.match_number)] = match
        return match

    async def replace(self, match: TournamentMatchRecord) -> TournamentMatchRecord:
        self.storage[(match.guild_id, match.tournament_number, match.match_number)] = match
        return match

    async def get(self, guild_id: int, tournament_number: int, match_number: int) -> TournamentMatchRecord | None:
        return self.storage.get((guild_id, tournament_number, match_number))

    async def list_for_tournament(self, guild_id: int, tournament_number: int) -> list[TournamentMatchRecord]:
        matches = [
            match
            for (stored_guild_id, stored_tournament_number, _), match in self.storage.items()
            if stored_guild_id == guild_id and stored_tournament_number == tournament_number
        ]
        return sorted(matches, key=lambda item: item.match_number)

    async def list_for_phase(self, guild_id: int, tournament_number: int, phase: TournamentPhase) -> list[TournamentMatchRecord]:
        matches = [
            match
            for match in await self.list_for_tournament(guild_id, tournament_number)
            if match.phase == phase
        ]
        return sorted(matches, key=lambda item: (item.group_label or "", item.match_number))

    async def list_due_reminders(self, now, reminder_cutoff) -> list[TournamentMatchRecord]:
        return []

    async def list_open_result_rooms(self, guild_id: int) -> list[TournamentMatchRecord]:
        return []


class FakeConfig:
    result_category_id = None
    admin_role_ids: list[int] = []
    staff_role_ids: list[int] = []


class FakeConfigService:
    async def get_or_create(self, guild_id: int) -> FakeConfig:
        return FakeConfig()

    async def is_staff(self, member) -> bool:
        return False


class FakeCoinsService:
    def __init__(self) -> None:
        self.participation_awards: list[int] = []
        self.final_rewards: list[tuple[int, int]] = []

    async def award_tournament_participation(self, guild, team: TournamentTeam) -> TournamentTeam:
        if not team.participation_rewarded:
            self.participation_awards.append(team.team_number)
            team.participation_rewarded = True
        return team

    async def award_tournament_final_rewards(self, guild, *, champion_team: TournamentTeam, runner_up_team: TournamentTeam) -> None:
        self.final_rewards.append((champion_team.team_number, runner_up_team.team_number))


class FakeAuditService:
    async def log(self, guild, action, message, **kwargs) -> None:
        return None


class FakeVoiceService:
    async def create_tournament_voice_channels(self, guild, tournament, match, config):
        class _Voice:
            def __init__(self, voice_id: int) -> None:
                self.id = voice_id

        return _Voice(1000 + match.match_number), _Voice(2000 + match.match_number)

    async def cleanup_tournament_voices(self, guild, match) -> None:
        return None


class FakeTextChannel:
    def __init__(self, channel_id: int) -> None:
        self.id = channel_id

    async def send(self, *args, **kwargs) -> None:
        return None


class FakeMember:
    def __init__(self, member_id: int, guild: "FakeGuild") -> None:
        self.id = member_id
        self.guild = guild
        self.bot = False


class FakeGuild:
    def __init__(self, guild_id: int, member_ids: list[int]) -> None:
        self.id = guild_id
        self.members = {member_id: FakeMember(member_id, self) for member_id in member_ids}

    def get_member(self, user_id: int) -> FakeMember | None:
        return self.members.get(user_id)

    def get_channel(self, channel_id: int | None):
        return None


@pytest.mark.asyncio
async def test_apply_team_rejects_duplicate_player_across_teams() -> None:
    tournament_repository = FakeTournamentRepository()
    team_repository = FakeTournamentTeamRepository()
    match_repository = FakeTournamentMatchRepository()
    coins_service = FakeCoinsService()
    service = TournamentService(
        bot=None,  # type: ignore[arg-type]
        tournament_repository=tournament_repository,
        team_repository=team_repository,
        match_repository=match_repository,
        config_service=FakeConfigService(),
        coins_service=coins_service,
        audit_service=FakeAuditService(),
        voice_service=FakeVoiceService(),
    )
    service.refresh_announcement = _noop_refresh.__get__(service, TournamentService)
    guild = FakeGuild(1, [10, 11, 12, 13, 20, 21, 22, 23])
    announcement_channel = FakeTextChannel(500)

    tournament = await service.create_tournament(
        guild,  # type: ignore[arg-type]
        name="Spring Cup",
        size=TournamentSize.SMALL,
        announcement_channel=announcement_channel,  # type: ignore[arg-type]
    )
    await service.apply_team(guild, tournament.tournament_number, guild.get_member(10), "Alpha", [10, 11, 12, 13])  # type: ignore[arg-type]

    with pytest.raises(UserFacingError):
        await service.apply_team(guild, tournament.tournament_number, guild.get_member(20), "Beta", [20, 11, 22, 23])  # type: ignore[arg-type]


def test_bracket_service_builds_expected_small_knockout_pairs() -> None:
    service = TournamentBracketService()
    group_a = [
        TournamentTeam(guild_id=1, tournament_number=1, team_number=1, team_name="A1", captain_id=1, player_ids=[1, 2, 3, 4]),
        TournamentTeam(guild_id=1, tournament_number=1, team_number=2, team_name="A2", captain_id=5, player_ids=[5, 6, 7, 8]),
    ]
    group_b = [
        TournamentTeam(guild_id=1, tournament_number=1, team_number=3, team_name="B1", captain_id=9, player_ids=[9, 10, 11, 12]),
        TournamentTeam(guild_id=1, tournament_number=1, team_number=4, team_name="B2", captain_id=13, player_ids=[13, 14, 15, 16]),
    ]

    round_label, pairs = service.seed_knockout(TournamentSize.SMALL, {"A": group_a, "B": group_b})

    assert round_label == "Semifinal"
    assert len(pairs) == 2
    assert {team_id for pair in pairs for team_id in pair} == {1, 2, 3, 4}


def test_standings_service_applies_deterministic_tie_break_order() -> None:
    standings_service = TournamentStandingsService()
    teams = [
        TournamentTeam(guild_id=1, tournament_number=1, team_number=1, team_name="Alpha", captain_id=1, player_ids=[1, 2, 3, 4], group_label="A"),
        TournamentTeam(guild_id=1, tournament_number=1, team_number=2, team_name="Bravo", captain_id=5, player_ids=[5, 6, 7, 8], group_label="A"),
        TournamentTeam(guild_id=1, tournament_number=1, team_number=3, team_name="Charlie", captain_id=9, player_ids=[9, 10, 11, 12], group_label="A"),
    ]
    matches = [
        TournamentMatchRecord(guild_id=1, tournament_number=1, match_number=1, phase=TournamentPhase.GROUP_STAGE, round_label="A-R1", group_label="A", team1_id=1, team2_id=2, status=TournamentMatchStatus.COMPLETED, team1_room_wins=2, team2_room_wins=1, winner_team_id=1),
        TournamentMatchRecord(guild_id=1, tournament_number=1, match_number=2, phase=TournamentPhase.GROUP_STAGE, round_label="A-R2", group_label="A", team1_id=2, team2_id=3, status=TournamentMatchStatus.COMPLETED, team1_room_wins=2, team2_room_wins=1, winner_team_id=2),
        TournamentMatchRecord(guild_id=1, tournament_number=1, match_number=3, phase=TournamentPhase.GROUP_STAGE, round_label="A-R3", group_label="A", team1_id=3, team2_id=1, status=TournamentMatchStatus.COMPLETED, team1_room_wins=2, team2_room_wins=0, winner_team_id=3),
    ]

    standings = standings_service.compute_group_standings(teams, matches)

    assert [row["team_id"] for row in standings["A"]] == [3, 1, 2]


@pytest.mark.asyncio
async def test_report_room_win_completes_final_and_awards_rewards() -> None:
    tournament_repository = FakeTournamentRepository()
    team_repository = FakeTournamentTeamRepository()
    match_repository = FakeTournamentMatchRepository()
    coins_service = FakeCoinsService()
    service = TournamentService(
        bot=None,  # type: ignore[arg-type]
        tournament_repository=tournament_repository,
        team_repository=team_repository,
        match_repository=match_repository,
        config_service=FakeConfigService(),
        coins_service=coins_service,
        audit_service=FakeAuditService(),
        voice_service=FakeVoiceService(),
    )
    service.refresh_announcement = _noop_refresh.__get__(service, TournamentService)
    service.refresh_result_room = _noop_result_room.__get__(service, TournamentService)
    guild = FakeGuild(1, [10, 11, 12, 13, 20, 21, 22, 23])

    tournament = TournamentRecord(
        guild_id=1,
        tournament_number=1,
        name="Final Cup",
        size=TournamentSize.SMALL,
        phase=TournamentPhase.KNOCKOUT,
        max_teams=8,
        group_count=2,
        advancing_per_group=2,
    )
    await tournament_repository.create(tournament)
    await team_repository.create(
        TournamentTeam(guild_id=1, tournament_number=1, team_number=1, team_name="Alpha", captain_id=10, player_ids=[10, 11, 12, 13]),
    )
    await team_repository.create(
        TournamentTeam(guild_id=1, tournament_number=1, team_number=2, team_name="Bravo", captain_id=20, player_ids=[20, 21, 22, 23]),
    )
    await match_repository.create(
        TournamentMatchRecord(
            guild_id=1,
            tournament_number=1,
            match_number=1,
            phase=TournamentPhase.KNOCKOUT,
            round_label="Final",
            team1_id=1,
            team2_id=2,
            status=TournamentMatchStatus.READY,
            scheduled_at=utcnow(),
        ),
    )

    first_update = await service.report_room_win(guild, 1, 1, guild.get_member(10), 1)  # type: ignore[arg-type]
    second_update = await service.report_room_win(guild, 1, 1, guild.get_member(10), 1)  # type: ignore[arg-type]
    stored_tournament = await tournament_repository.get(1, 1)

    assert first_update.status == TournamentMatchStatus.IN_PROGRESS
    assert second_update.status == TournamentMatchStatus.COMPLETED
    assert second_update.winner_team_id == 1
    assert stored_tournament is not None
    assert stored_tournament.phase == TournamentPhase.COMPLETED
    assert stored_tournament.champion_team_id == 1
    assert stored_tournament.runner_up_team_id == 2
    assert sorted(coins_service.participation_awards) == [1, 2]
    assert coins_service.final_rewards == [(1, 2)]


async def _noop_refresh(self, guild, tournament):
    return tournament


async def _noop_result_room(self, guild, tournament, match):
    return None
