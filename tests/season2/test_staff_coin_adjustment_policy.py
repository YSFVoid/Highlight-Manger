from __future__ import annotations

import inspect

from highlight_manager.app.bot import HighlightBot
from highlight_manager.app.config import Settings


def test_emergency_coin_adjustments_are_disabled_by_default() -> None:
    settings = Settings(DISCORD_TOKEN="token", DATABASE_URL="sqlite+aiosqlite:///test.db")

    assert settings.emergency_coin_adjustments_enabled is False


def test_emergency_coin_adjustments_can_only_be_enabled_explicitly() -> None:
    settings = Settings(
        DISCORD_TOKEN="token",
        DATABASE_URL="sqlite+aiosqlite:///test.db",
        EMERGENCY_COIN_ADJUSTMENTS_ENABLED=True,
    )

    assert settings.emergency_coin_adjustments_enabled is True


def test_adjust_coins_command_is_launch_quarantined_and_audited() -> None:
    source = inspect.getsource(HighlightBot._register_app_commands)
    guard_index = source.index("emergency_coin_adjustments_enabled")
    adjustment_index = source.index("services.economy.adjust_balance")

    assert '@admin_group.command(name="adjust-coins"' in source
    assert "Emergency wallet correction, disabled by default" in source
    assert guard_index < adjustment_index
    assert "Manual coin changes are disabled for Season 2 launch" in source
    assert "EMERGENCY_COIN_ADJUSTMENTS_ENABLED=true" in source
    assert 'idempotency_key=f"emergency-coin-adjustment:{interaction.id}"' in source
    assert '"emergency": True' in source
    assert "Emergency coins adjusted" in source
