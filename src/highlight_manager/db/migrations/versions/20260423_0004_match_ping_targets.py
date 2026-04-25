from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260423_0004"
down_revision = "20260422_0003"
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


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if _has_table(table_name) and not _has_column(table_name, column.name):
        op.add_column(table_name, column)


def upgrade() -> None:
    for column_name in (
        "apostado_match_ping_target",
        "highlight_match_ping_target",
        "esport_match_ping_target",
    ):
        _add_column_if_missing(
            "guild_settings",
            sa.Column(column_name, sa.String(length=64), nullable=False, server_default=sa.text("'here'")),
        )
        if _has_column("guild_settings", column_name):
            op.execute(
                sa.text(
                    f"""
                    UPDATE guild_settings
                    SET {column_name} = 'here'
                    WHERE {column_name} IS NULL OR TRIM({column_name}) = ''
                    """
                )
            )


def downgrade() -> None:
    for column_name in (
        "esport_match_ping_target",
        "highlight_match_ping_target",
        "apostado_match_ping_target",
    ):
        if _has_column("guild_settings", column_name):
            op.drop_column("guild_settings", column_name)
