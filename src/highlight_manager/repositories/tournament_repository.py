from __future__ import annotations

from pymongo import ReturnDocument

from highlight_manager.models.enums import TournamentMatchStatus, TournamentPhase
from highlight_manager.models.tournament import TournamentMatchRecord, TournamentRecord, TournamentTeam
from highlight_manager.repositories.base import BaseRepository


class TournamentRepository(BaseRepository[TournamentRecord]):
    async def ensure_indexes(self) -> None:
        await self.collection.create_index([("guild_id", 1), ("tournament_number", 1)], unique=True)
        await self.collection.create_index([("guild_id", 1), ("phase", 1)])

    async def create(self, tournament: TournamentRecord) -> TournamentRecord:
        await self.collection.insert_one(tournament.model_dump(mode="python"))
        return tournament

    async def replace(self, tournament: TournamentRecord) -> TournamentRecord:
        updated = await self.collection.find_one_and_replace(
            {"guild_id": tournament.guild_id, "tournament_number": tournament.tournament_number},
            tournament.model_dump(mode="python"),
            return_document=ReturnDocument.AFTER,
        )
        return self._to_model(updated) or tournament

    async def get(self, guild_id: int, tournament_number: int) -> TournamentRecord | None:
        return self._to_model(
            await self.collection.find_one({"guild_id": guild_id, "tournament_number": tournament_number}),
        )

    async def get_latest(self, guild_id: int) -> TournamentRecord | None:
        cursor = self.collection.find({"guild_id": guild_id}).sort("tournament_number", -1).limit(1)
        documents = await cursor.to_list(length=1)
        return self._to_model(documents[0]) if documents else None

    async def get_active(self, guild_id: int) -> TournamentRecord | None:
        return self._to_model(
            await self.collection.find_one(
                {
                    "guild_id": guild_id,
                    "phase": {"$in": [phase.value for phase in [TournamentPhase.REGISTRATION, TournamentPhase.GROUP_STAGE, TournamentPhase.KNOCKOUT]]},
                },
                sort=[("tournament_number", -1)],
            ),
        )


class TournamentTeamRepository(BaseRepository[TournamentTeam]):
    async def ensure_indexes(self) -> None:
        await self.collection.create_index([("guild_id", 1), ("tournament_number", 1), ("team_number", 1)], unique=True)
        await self.collection.create_index([("guild_id", 1), ("tournament_number", 1), ("player_ids", 1)])

    async def create(self, team: TournamentTeam) -> TournamentTeam:
        await self.collection.insert_one(team.model_dump(mode="python"))
        return team

    async def replace(self, team: TournamentTeam) -> TournamentTeam:
        updated = await self.collection.find_one_and_replace(
            {
                "guild_id": team.guild_id,
                "tournament_number": team.tournament_number,
                "team_number": team.team_number,
            },
            team.model_dump(mode="python"),
            return_document=ReturnDocument.AFTER,
        )
        return self._to_model(updated) or team

    async def get(self, guild_id: int, tournament_number: int, team_number: int) -> TournamentTeam | None:
        return self._to_model(
            await self.collection.find_one(
                {
                    "guild_id": guild_id,
                    "tournament_number": tournament_number,
                    "team_number": team_number,
                },
            ),
        )

    async def list_for_tournament(self, guild_id: int, tournament_number: int) -> list[TournamentTeam]:
        cursor = self.collection.find(
            {"guild_id": guild_id, "tournament_number": tournament_number},
        ).sort([("group_label", 1), ("team_number", 1)])
        return self._to_models(await cursor.to_list(length=None))

    async def get_latest_team(self, guild_id: int, tournament_number: int) -> TournamentTeam | None:
        cursor = self.collection.find(
            {"guild_id": guild_id, "tournament_number": tournament_number},
        ).sort("team_number", -1).limit(1)
        documents = await cursor.to_list(length=1)
        return self._to_model(documents[0]) if documents else None

    async def find_by_player(self, guild_id: int, tournament_number: int, user_id: int) -> TournamentTeam | None:
        return self._to_model(
            await self.collection.find_one(
                {"guild_id": guild_id, "tournament_number": tournament_number, "player_ids": user_id},
            ),
        )


class TournamentMatchRepository(BaseRepository[TournamentMatchRecord]):
    async def ensure_indexes(self) -> None:
        await self.collection.create_index([("guild_id", 1), ("tournament_number", 1), ("match_number", 1)], unique=True)
        await self.collection.create_index([("guild_id", 1), ("tournament_number", 1), ("status", 1)])
        await self.collection.create_index([("scheduled_at", 1)])

    async def create(self, match: TournamentMatchRecord) -> TournamentMatchRecord:
        await self.collection.insert_one(match.model_dump(mode="python"))
        return match

    async def replace(self, match: TournamentMatchRecord) -> TournamentMatchRecord:
        updated = await self.collection.find_one_and_replace(
            {
                "guild_id": match.guild_id,
                "tournament_number": match.tournament_number,
                "match_number": match.match_number,
            },
            match.model_dump(mode="python"),
            return_document=ReturnDocument.AFTER,
        )
        return self._to_model(updated) or match

    async def get(self, guild_id: int, tournament_number: int, match_number: int) -> TournamentMatchRecord | None:
        return self._to_model(
            await self.collection.find_one(
                {
                    "guild_id": guild_id,
                    "tournament_number": tournament_number,
                    "match_number": match_number,
                },
            ),
        )

    async def list_for_tournament(self, guild_id: int, tournament_number: int) -> list[TournamentMatchRecord]:
        cursor = self.collection.find(
            {"guild_id": guild_id, "tournament_number": tournament_number},
        ).sort([("match_number", 1)])
        return self._to_models(await cursor.to_list(length=None))

    async def list_for_phase(
        self,
        guild_id: int,
        tournament_number: int,
        phase: TournamentPhase,
    ) -> list[TournamentMatchRecord]:
        cursor = self.collection.find(
            {"guild_id": guild_id, "tournament_number": tournament_number, "phase": phase.value},
        ).sort([("group_label", 1), ("match_number", 1)])
        return self._to_models(await cursor.to_list(length=None))

    async def list_due_reminders(self, now, reminder_cutoff) -> list[TournamentMatchRecord]:
        cursor = self.collection.find(
            {
                "status": {"$in": [TournamentMatchStatus.SCHEDULED.value, TournamentMatchStatus.READY.value]},
                "scheduled_at": {"$gte": now, "$lte": reminder_cutoff},
                "reminder_sent_at": None,
            },
        )
        return self._to_models(await cursor.to_list(length=None))

    async def list_open_result_rooms(self, guild_id: int) -> list[TournamentMatchRecord]:
        cursor = self.collection.find(
            {
                "guild_id": guild_id,
                "result_channel_id": {"$ne": None},
                "status": {"$in": [TournamentMatchStatus.SCHEDULED.value, TournamentMatchStatus.READY.value, TournamentMatchStatus.IN_PROGRESS.value]},
            },
        )
        return self._to_models(await cursor.to_list(length=None))
