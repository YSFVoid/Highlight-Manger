from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260422_0002"
down_revision = "20260330_0001"
branch_labels = None
depends_on = None


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def upgrade() -> None:
    if not _has_column("queue_players", "ready_at"):
        op.add_column(
            "queue_players",
            sa.Column("ready_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    if _has_column("queue_players", "ready_at"):
        op.drop_column("queue_players", "ready_at")
