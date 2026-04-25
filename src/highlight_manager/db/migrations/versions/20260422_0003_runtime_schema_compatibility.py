from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260422_0003"
down_revision = "20260422_0002"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def _has_column(table_name: str, column_name: str) -> bool:
    if not _has_table(table_name):
        return False
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def _has_columns(table_name: str, *column_names: str) -> bool:
    return all(_has_column(table_name, column_name) for column_name in column_names)


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if _has_table(table_name) and not _has_column(table_name, column.name):
        op.add_column(table_name, column)


def upgrade() -> None:
    for column_name in (
        "waiting_voice_channel_ids",
        "apostado_channel_ids",
        "highlight_channel_ids",
        "esport_channel_ids",
    ):
        _add_column_if_missing("guild_settings", sa.Column(column_name, sa.Text(), nullable=True))

    for column_name in ("team1_captain_player_id", "team2_captain_player_id"):
        _add_column_if_missing("matches", sa.Column(column_name, sa.Integer(), nullable=True))
    _add_column_if_missing("matches", sa.Column("result_phase", sa.Text(), nullable=True))
    for column_name in ("captain_deadline_at", "fallback_deadline_at"):
        _add_column_if_missing(
            "matches",
            sa.Column(column_name, sa.DateTime(timezone=True), nullable=True),
        )
    _add_column_if_missing(
        "matches",
        sa.Column("rehost_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )

    if _has_columns("guild_settings", "waiting_voice_channel_id", "waiting_voice_channel_ids"):
        op.execute(
            sa.text(
                """
                UPDATE guild_settings
                SET waiting_voice_channel_ids = CAST(waiting_voice_channel_id AS TEXT)
                WHERE waiting_voice_channel_id IS NOT NULL
                  AND (waiting_voice_channel_ids IS NULL OR waiting_voice_channel_ids = '')
                """
            )
        )

    if _has_columns("matches", "team1_captain_player_id", "creator_player_id"):
        op.execute(
            sa.text(
                """
                UPDATE matches
                SET team1_captain_player_id = creator_player_id
                WHERE team1_captain_player_id IS NULL
                """
            )
        )

    if _has_columns("matches", "team2_captain_player_id") and _has_columns(
        "match_players",
        "match_id",
        "player_id",
        "team_number",
    ):
        op.execute(
            sa.text(
                """
                UPDATE matches
                SET team2_captain_player_id = (
                    SELECT player_id
                    FROM match_players
                    WHERE match_players.match_id = matches.id
                      AND match_players.team_number = 2
                    ORDER BY match_players.id ASC
                    LIMIT 1
                )
                WHERE team2_captain_player_id IS NULL
                """
            )
        )

    if _has_columns("matches", "result_phase", "state"):
        op.execute(
            sa.text(
                """
                UPDATE matches
                SET result_phase = CASE
                    WHEN state = 'expired' THEN 'staff_review'
                    WHEN state IN ('live', 'result_pending') THEN 'fallback'
                    ELSE 'captain'
                END
                WHERE result_phase IS NULL OR result_phase = ''
                """
            )
        )

    if _has_columns("matches", "fallback_deadline_at", "result_deadline_at"):
        op.execute(
            sa.text(
                """
                UPDATE matches
                SET fallback_deadline_at = result_deadline_at
                WHERE fallback_deadline_at IS NULL
                  AND result_deadline_at IS NOT NULL
                """
            )
        )


def downgrade() -> None:
    for column_name in (
        "rehost_count",
        "fallback_deadline_at",
        "captain_deadline_at",
        "result_phase",
        "team2_captain_player_id",
        "team1_captain_player_id",
    ):
        if _has_column("matches", column_name):
            op.drop_column("matches", column_name)

    for column_name in (
        "esport_channel_ids",
        "highlight_channel_ids",
        "apostado_channel_ids",
        "waiting_voice_channel_ids",
    ):
        if _has_column("guild_settings", column_name):
            op.drop_column("guild_settings", column_name)
