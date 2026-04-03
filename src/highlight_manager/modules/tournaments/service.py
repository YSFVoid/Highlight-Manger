from __future__ import annotations

from highlight_manager.modules.common.enums import (
    AuditAction,
    AuditEntityType,
    TournamentFormat,
    TournamentMatchState,
    TournamentState,
    TournamentTeamStatus,
    WalletTransactionType,
)
from highlight_manager.modules.common.exceptions import NotFoundError, StateTransitionError, ValidationError
from highlight_manager.modules.common.time import utcnow
from highlight_manager.modules.economy.repository import EconomyRepository
from highlight_manager.modules.economy.service import EconomyService
from highlight_manager.modules.moderation.repository import ModerationRepository
from highlight_manager.modules.moderation.service import ModerationService
from highlight_manager.modules.tournaments.bracket import seed_pairs
from highlight_manager.modules.tournaments.repository import TournamentRepository


class TournamentService:
    def __init__(
        self,
        *,
        economy_service: EconomyService,
        moderation_service: ModerationService,
    ) -> None:
        self.economy_service = economy_service
        self.moderation_service = moderation_service

    async def _ensure_bracket_match(
        self,
        repository: TournamentRepository,
        *,
        tournament_id,
        round_number: int,
        bracket_position: int,
        team1,
        team2,
    ):
        match = await repository.get_match_by_slot(
            tournament_id,
            round_number=round_number,
            bracket_position=bracket_position,
            for_update=True,
        )
        if match is None:
            match = await repository.create_match(
                tournament_id=tournament_id,
                round_number=round_number,
                bracket_position=bracket_position,
                team1_id=team1,
                team2_id=team2,
            )
        else:
            if match.team1_id is None:
                match.team1_id = team1
            if match.team2_id is None and team2 is not None:
                match.team2_id = team2
        if team1 is not None and team2 is None and match.state != TournamentMatchState.CONFIRMED:
            match.state = TournamentMatchState.CONFIRMED
            match.winner_team_id = team1
        return match

    async def create_tournament(
        self,
        repository: TournamentRepository,
        moderation_repository: ModerationRepository,
        *,
        guild_id: int,
        season_id: int,
        name: str,
        team_size: int,
        max_teams: int,
        prize_coins_first: int = 0,
        prize_coins_second: int = 0,
        actor_player_id: int | None = None,
    ):
        cleaned_name = name.strip()
        if not cleaned_name:
            raise ValidationError("Tournament name is required.")
        if team_size <= 0:
            raise ValidationError("Team size must be greater than zero.")
        if max_teams < 2:
            raise ValidationError("A tournament needs at least two teams.")
        if prize_coins_first < 0 or prize_coins_second < 0:
            raise ValidationError("Prize coins cannot be negative.")
        tournament = await repository.create_tournament(
            guild_id=guild_id,
            season_id=season_id,
            tournament_number=await repository.next_tournament_number(guild_id),
            name=cleaned_name,
            format=TournamentFormat.SINGLE_ELIMINATION,
            state=TournamentState.REGISTRATION,
            team_size=team_size,
            max_teams=max_teams,
            prize_coins_first=prize_coins_first,
            prize_coins_second=prize_coins_second,
        )
        await self.moderation_service.audit(
            moderation_repository,
            guild_id=guild_id,
            action=AuditAction.TOURNAMENT_CREATED,
            entity_type=AuditEntityType.TOURNAMENT,
            entity_id=str(tournament.id),
            actor_player_id=actor_player_id,
        )
        return tournament

    async def register_team(
        self,
        repository: TournamentRepository,
        *,
        tournament_id,
        captain_player_id: int,
        team_name: str,
        player_ids: list[int],
    ):
        tournament = await repository.get_tournament(tournament_id, for_update=True)
        if tournament is None:
            raise NotFoundError("Tournament not found.")
        if tournament.state != TournamentState.REGISTRATION:
            raise StateTransitionError("Tournament registration is closed.")
        cleaned_team_name = team_name.strip()
        if not cleaned_team_name:
            raise ValidationError("Team name is required.")
        if len(player_ids) != tournament.team_size:
            raise ValidationError(f"Teams must have exactly {tournament.team_size} players.")
        if len(set(player_ids)) != len(player_ids):
            raise ValidationError("Duplicate players are not allowed.")
        if player_ids[0] != captain_player_id:
            raise ValidationError("The captain must be the first player in the roster.")
        teams = await repository.list_teams(tournament_id)
        if len(teams) >= tournament.max_teams:
            raise ValidationError("The tournament is already full.")
        for player_id in player_ids:
            existing = await repository.find_registration_for_player(tournament_id, player_id)
            if existing is not None:
                raise ValidationError(f"Player {player_id} is already registered for this tournament.")

        team = await repository.create_team(
            tournament_id=tournament_id,
            team_name=cleaned_team_name,
            captain_player_id=captain_player_id,
            status=TournamentTeamStatus.REGISTERED,
        )
        for player_id in player_ids:
            await repository.create_registration(
                tournament_id=tournament_id,
                tournament_team_id=team.id,
                player_id=player_id,
            )
        return team

    async def start_tournament(self, repository: TournamentRepository, *, tournament_id):
        tournament = await repository.get_tournament(tournament_id, for_update=True)
        if tournament is None:
            raise NotFoundError("Tournament not found.")
        if tournament.state == TournamentState.LIVE:
            return tournament
        if tournament.state not in {TournamentState.REGISTRATION, TournamentState.SEEDING}:
            raise StateTransitionError("Tournament has already started.")
        teams = await repository.list_teams(tournament_id)
        if len(teams) < 2:
            raise ValidationError("At least two teams are required.")
        tournament.state = TournamentState.SEEDING
        for index, team in enumerate(teams, start=1):
            team.seed = index
        for round_number, bracket_position, team1, team2 in seed_pairs([team.id for team in teams]):
            await self._ensure_bracket_match(
                repository,
                tournament_id=tournament_id,
                round_number=round_number,
                bracket_position=bracket_position,
                team1=team1,
                team2=team2,
            )
        tournament.state = TournamentState.LIVE
        if tournament.starts_at is None:
            tournament.starts_at = utcnow()
        return tournament

    async def report_match_winner(
        self,
        repository: TournamentRepository,
        economy_repository: EconomyRepository,
        moderation_repository: ModerationRepository,
        *,
        match_id,
        winner_team_id,
        actor_player_id: int | None,
    ):
        match = await repository.get_match(match_id, for_update=True)
        if match is None:
            raise NotFoundError("Tournament match not found.")
        if match.state == TournamentMatchState.CONFIRMED:
            return match
        if winner_team_id not in {match.team1_id, match.team2_id}:
            raise ValidationError("Winner must be one of the participating teams.")
        match.winner_team_id = winner_team_id
        match.state = TournamentMatchState.CONFIRMED
        match.confirmed_at = utcnow()

        tournament = await repository.get_tournament(match.tournament_id, for_update=True)
        assert tournament is not None
        matches = await repository.list_matches(match.tournament_id)
        current_round = [item for item in matches if item.round_number == match.round_number]
        if all(item.state == TournamentMatchState.CONFIRMED for item in current_round):
            winners = [item.winner_team_id for item in current_round if item.winner_team_id is not None]
            if len(winners) == 1:
                tournament.state = TournamentState.COMPLETED
                tournament.completed_at = utcnow()
                tournament.winner_team_id = winners[0]
                if match.team1_id and match.team2_id:
                    tournament.runner_up_team_id = match.team1_id if winners[0] == match.team2_id else match.team2_id
                if tournament.prize_coins_first or tournament.prize_coins_second:
                    winner_team = next(team for team in await repository.list_teams(match.tournament_id) if team.id == tournament.winner_team_id)
                    runner_up_team = next((team for team in await repository.list_teams(match.tournament_id) if team.id == tournament.runner_up_team_id), None)
                    if tournament.prize_coins_first:
                        for registration in await repository.list_registrations_for_team(winner_team.id):
                            await self.economy_service.grant_tournament_reward(
                                economy_repository,
                                tournament_id=tournament.id,
                                player_id=registration.player_id,
                                amount=tournament.prize_coins_first,
                                transaction_type=WalletTransactionType.TOURNAMENT_CHAMPION,
                                reward_kind="champion",
                                reason=f"Tournament champion prize: {tournament.name}",
                            )
                    if tournament.prize_coins_second and runner_up_team is not None:
                        for registration in await repository.list_registrations_for_team(runner_up_team.id):
                            await self.economy_service.grant_tournament_reward(
                                economy_repository,
                                tournament_id=tournament.id,
                                player_id=registration.player_id,
                                amount=tournament.prize_coins_second,
                                transaction_type=WalletTransactionType.TOURNAMENT_RUNNER_UP,
                                reward_kind="runner_up",
                                reason=f"Tournament runner-up prize: {tournament.name}",
                            )
            else:
                next_round = match.round_number + 1
                for position in range(0, len(winners), 2):
                    team1 = winners[position]
                    team2 = winners[position + 1] if position + 1 < len(winners) else None
                    next_match = await self._ensure_bracket_match(
                        repository,
                        tournament_id=match.tournament_id,
                        round_number=next_round,
                        bracket_position=(position // 2) + 1,
                        team1=team1,
                        team2=team2,
                    )

        await self.moderation_service.audit(
            moderation_repository,
            guild_id=tournament.guild_id,
            action=AuditAction.TOURNAMENT_MATCH_CONFIRMED,
            entity_type=AuditEntityType.TOURNAMENT,
            entity_id=str(tournament.id),
            actor_player_id=actor_player_id,
            metadata_json={"match_id": str(match.id), "winner_team_id": str(winner_team_id)},
        )
        return match
