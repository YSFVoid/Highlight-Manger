from __future__ import annotations

from alembic import op

import highlight_manager.db.models  # noqa: F401
from highlight_manager.db.base import Base


revision = "20260330_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
