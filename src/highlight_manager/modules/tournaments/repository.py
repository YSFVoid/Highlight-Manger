from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from highlight_manager.db.models.tournaments import (
    TournamentMatchModel,
    TournamentModel,
    TournamentRegistrationModel,
    TournamentTeamModel,
)
from highlight_manager.modules.common.enums import TournamentState


class TournamentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def next_tournament_number(self, guild_id: int) -> int:
        value = await self.session.scalar(
            select(func.max(TournamentModel.tournament_number)).where(TournamentModel.guild_id == guild_id)
        )
        return int(value or 0) + 1

    async def create_tournament(self, **kwargs) -> TournamentModel:
        tournament = TournamentModel(**kwargs)
        self.session.add(tournament)
        await self.session.flush()
        return tournament

    async def get_tournament(self, tournament_id, *, for_update: bool = False):
        stmt = select(TournamentModel).where(TournamentModel.id == tournament_id)
        if for_update:
            stmt = stmt.with_for_update()
        return await self.session.scalar(stmt)

    async def get_latest_active(self, guild_id: int) -> TournamentModel | None:
        return await self.session.scalar(
            select(TournamentModel)
            .where(
                TournamentModel.guild_id == guild_id,
                TournamentModel.state.in_(
                    [
                        TournamentState.REGISTRATION,
                        TournamentState.CHECK_IN,
                        TournamentState.SEEDING,
                        TournamentState.LIVE,
                    ]
                ),
            )
            .order_by(TournamentModel.tournament_number.desc())
        )

    async def list_teams(self, tournament_id) -> list[TournamentTeamModel]:
        result = await self.session.scalars(
            select(TournamentTeamModel)
            .where(TournamentTeamModel.tournament_id == tournament_id)
            .order_by(TournamentTeamModel.seed.asc().nulls_last(), TournamentTeamModel.created_at.asc())
        )
        return list(result.all())

    async def find_registration_for_player(self, tournament_id, player_id):
        return await self.session.scalar(
            select(TournamentRegistrationModel).where(
                TournamentRegistrationModel.tournament_id == tournament_id,
                TournamentRegistrationModel.player_id == player_id,
            )
        )

    async def create_team(self, **kwargs) -> TournamentTeamModel:
        team = TournamentTeamModel(**kwargs)
        self.session.add(team)
        await self.session.flush()
        return team

    async def create_registration(self, **kwargs) -> TournamentRegistrationModel:
        registration = TournamentRegistrationModel(**kwargs)
        self.session.add(registration)
        await self.session.flush()
        return registration

    async def list_registrations_for_team(self, tournament_team_id) -> list[TournamentRegistrationModel]:
        result = await self.session.scalars(
            select(TournamentRegistrationModel)
            .where(TournamentRegistrationModel.tournament_team_id == tournament_team_id)
            .order_by(TournamentRegistrationModel.created_at.asc(), TournamentRegistrationModel.id.asc())
        )
        return list(result.all())

    async def create_match(self, **kwargs) -> TournamentMatchModel:
        match = TournamentMatchModel(**kwargs)
        self.session.add(match)
        await self.session.flush()
        return match

    async def list_matches(self, tournament_id) -> list[TournamentMatchModel]:
        result = await self.session.scalars(
            select(TournamentMatchModel)
            .where(TournamentMatchModel.tournament_id == tournament_id)
            .order_by(TournamentMatchModel.round_number.asc(), TournamentMatchModel.bracket_position.asc())
        )
        return list(result.all())

    async def get_match(self, match_id, *, for_update: bool = False):
        stmt = select(TournamentMatchModel).where(TournamentMatchModel.id == match_id)
        if for_update:
            stmt = stmt.with_for_update()
        return await self.session.scalar(stmt)

    async def get_match_by_slot(
        self,
        tournament_id,
        *,
        round_number: int,
        bracket_position: int,
        for_update: bool = False,
    ) -> TournamentMatchModel | None:
        stmt = select(TournamentMatchModel).where(
            TournamentMatchModel.tournament_id == tournament_id,
            TournamentMatchModel.round_number == round_number,
            TournamentMatchModel.bracket_position == bracket_position,
        )
        if for_update:
            stmt = stmt.with_for_update()
        return await self.session.scalar(stmt)
