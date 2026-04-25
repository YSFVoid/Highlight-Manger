from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timedelta

from sqlalchemy import inspect as sqlalchemy_inspect
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from highlight_manager.db.models.competitive import MatchModel
from highlight_manager.modules.common.time import utcnow
from highlight_manager.modules.diagnostics.types import (
    AdminDiagnosticsSnapshot,
    BacklogDiagnostics,
    SchemaDiagnostics,
    UnresolvedMatchDiagnostics,
    VoiceDiagnostics,
)
from highlight_manager.modules.matches.repository import MatchRepository
from highlight_manager.modules.matches.service import MatchService
from highlight_manager.modules.profiles.repository import ProfileRepository


class AdminDiagnosticsService:
    REMINDER_LOOKAHEAD_SECONDS = 30

    async def collect(
        self,
        *,
        session: AsyncSession,
        matches: MatchRepository,
        profiles: ProfileRepository,
        match_service: MatchService,
        guild_id: int,
        now: datetime | None = None,
        channel_exists: Callable[[int], bool] | None = None,
        voice_status: object | None = None,
        voice_enabled: bool | None = None,
        voice_channel_id: int | None = None,
        scheduler_summary: Mapping[str, object] | None = None,
        cleanup_summary: Mapping[str, object] | None = None,
        startup_health: Mapping[str, object] | None = None,
        command_sync_status: Mapping[str, object] | None = None,
    ) -> AdminDiagnosticsSnapshot:
        now = now or utcnow()
        active_queue_ids = set(await matches.list_active_queue_ids_for_guild(guild_id))
        active_matches = await matches.list_active_matches_for_guild(guild_id)
        active_match_ids = {match.id for match in active_matches}
        unresolved_counts = await match_service.count_review_inbox_by_reason(
            matches,
            guild_id=guild_id,
            now=now,
        )
        reminder_threshold = now + timedelta(seconds=self.REMINDER_LOOKAHEAD_SECONDS)
        backlog = BacklogDiagnostics(
            room_info_reminders=await matches.count_due_room_info_reminders(
                guild_id,
                reminder_threshold,
            ),
            room_info_timeouts=await matches.count_due_room_info_timeouts(guild_id, now),
            captain_fallback_opens=await matches.count_due_captain_timeouts(guild_id, now),
            result_timeouts=await matches.count_due_fallback_timeouts(guild_id, now),
            stale_activity_rows=await profiles.count_stale_activity_rows_for_guild(
                guild_id,
                active_queue_ids=active_queue_ids,
                active_match_ids=active_match_ids,
            ),
            missing_match_resources=self._count_missing_match_resources(
                active_matches,
                channel_exists,
            ),
        )
        return AdminDiagnosticsSnapshot(
            guild_id=guild_id,
            collected_at=now,
            unresolved_matches=UnresolvedMatchDiagnostics(
                staff_review=unresolved_counts.get("staff_review", 0),
                overdue=unresolved_counts.get("overdue", 0),
                disputed=unresolved_counts.get("disputed", 0),
                total=unresolved_counts.get("total", 0),
            ),
            queue_counts=await matches.count_active_queues_by_state(guild_id),
            match_counts=await matches.count_active_matches_by_state(guild_id),
            backlog=backlog,
            scheduler_summary=dict(scheduler_summary or {}),
            cleanup_summary=dict(cleanup_summary or {}),
            startup_health=dict(startup_health or {}),
            command_sync_status=dict(command_sync_status or {}),
            voice=self._voice_diagnostics(
                voice_status,
                voice_enabled=voice_enabled,
                voice_channel_id=voice_channel_id,
            ),
            schema=await self._schema_health(session),
        )

    @staticmethod
    def _count_missing_match_resources(
        matches: list[MatchModel],
        channel_exists: Callable[[int], bool] | None,
    ) -> int:
        if channel_exists is None:
            return 0
        missing = 0
        for match in matches:
            for channel_id in [
                match.result_channel_id,
                match.team1_voice_channel_id,
                match.team2_voice_channel_id,
            ]:
                if channel_id is not None and not channel_exists(channel_id):
                    missing += 1
        return missing

    @staticmethod
    def _voice_diagnostics(
        voice_status: object | None,
        *,
        voice_enabled: bool | None,
        voice_channel_id: int | None,
    ) -> VoiceDiagnostics:
        if voice_status is None:
            return VoiceDiagnostics(
                enabled=voice_enabled,
                channel_id=voice_channel_id,
                state="unknown",
            )
        return VoiceDiagnostics(
            enabled=getattr(voice_status, "enabled", voice_enabled),
            channel_id=getattr(voice_status, "channel_id", voice_channel_id),
            state=str(getattr(voice_status, "state", "unknown")),
            reason=getattr(voice_status, "reason", None),
            retry_in_seconds=getattr(voice_status, "retry_in_seconds", None),
            connected_channel_id=getattr(voice_status, "connected_channel_id", None),
        )

    async def _schema_health(self, session: AsyncSession) -> SchemaDiagnostics:
        try:
            connection = await session.connection()
            return await connection.run_sync(self._inspect_schema)
        except Exception as exc:
            return SchemaDiagnostics(
                status="unknown",
                revision=None,
                details=f"Schema check unavailable: {type(exc).__name__}",
            )

    @staticmethod
    def _inspect_schema(sync_connection) -> SchemaDiagnostics:
        inspector = sqlalchemy_inspect(sync_connection)
        tables = set(inspector.get_table_names())
        required_columns = {
            "queue_players": {"ready_at"},
            "matches": {"result_phase", "captain_deadline_at", "fallback_deadline_at", "rehost_count"},
            "guild_settings": {
                "waiting_voice_channel_ids",
                "apostado_channel_ids",
                "highlight_channel_ids",
                "esport_channel_ids",
            },
        }
        missing: list[str] = []
        for table_name, column_names in required_columns.items():
            if table_name not in tables:
                missing.append(table_name)
                continue
            existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
            missing.extend(
                f"{table_name}.{column_name}"
                for column_name in sorted(column_names - existing_columns)
            )
        revision = None
        if "alembic_version" in tables:
            row = sync_connection.execute(text("SELECT version_num FROM alembic_version")).first()
            revision = str(row[0]) if row is not None else None
        if missing:
            return SchemaDiagnostics(
                status="warning",
                revision=revision,
                details="Missing required schema objects: " + ", ".join(missing),
            )
        if revision is None:
            return SchemaDiagnostics(
                status="unknown",
                revision=None,
                details="Alembic version is unavailable; required columns are present.",
            )
        return SchemaDiagnostics(
            status="ok",
            revision=revision,
            details="Required columns are present.",
        )
