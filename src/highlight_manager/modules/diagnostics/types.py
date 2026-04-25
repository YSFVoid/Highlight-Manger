from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from highlight_manager.modules.common.enums import MatchState, QueueState


@dataclass(slots=True)
class UnresolvedMatchDiagnostics:
    staff_review: int = 0
    overdue: int = 0
    disputed: int = 0
    total: int = 0


@dataclass(slots=True)
class BacklogDiagnostics:
    room_info_reminders: int = 0
    room_info_timeouts: int = 0
    captain_fallback_opens: int = 0
    result_timeouts: int = 0
    stale_activity_rows: int = 0
    missing_match_resources: int = 0


@dataclass(slots=True)
class VoiceDiagnostics:
    enabled: bool | None
    channel_id: int | None
    state: str
    reason: str | None = None
    retry_in_seconds: int | None = None
    connected_channel_id: int | None = None


@dataclass(slots=True)
class SchemaDiagnostics:
    status: str
    revision: str | None
    details: str


@dataclass(slots=True)
class AdminDiagnosticsSnapshot:
    guild_id: int
    collected_at: datetime
    unresolved_matches: UnresolvedMatchDiagnostics
    queue_counts: dict[QueueState, int]
    match_counts: dict[MatchState, int]
    backlog: BacklogDiagnostics
    scheduler_summary: Mapping[str, object] = field(default_factory=dict)
    cleanup_summary: Mapping[str, object] = field(default_factory=dict)
    startup_health: Mapping[str, object] = field(default_factory=dict)
    command_sync_status: Mapping[str, object] = field(default_factory=dict)
    voice: VoiceDiagnostics | None = None
    schema: SchemaDiagnostics | None = None
