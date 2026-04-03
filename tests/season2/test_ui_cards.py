from highlight_manager.ui.cards import (
    LeaderboardCardEntry,
    ProfileCardData,
    render_help_banner,
    render_leaderboard_card,
    render_profile_card,
)


def test_help_banner_renders_png() -> None:
    banner = render_help_banner("!")
    assert banner.getvalue().startswith(b"\x89PNG")


def test_profile_card_renders_png() -> None:
    card = render_profile_card(
        ProfileCardData(
            display_name="RANK 23 | ALLA",
            season_name="Season 2",
            points=3550,
            wins=56,
            losses=37,
            matches=128,
            winrate_text="60%",
            rank_text="Rank #23",
            coins=920,
            peak=3710,
        )
    )
    assert card.getvalue().startswith(b"\x89PNG")


def test_leaderboard_card_renders_png() -> None:
    card = render_leaderboard_card(
        "Season 2",
        50,
        [
            LeaderboardCardEntry(
                rank=1,
                display_name="MARSHI",
                wins=170,
                losses=78,
                winrate_text="68.6%",
                points=9560,
            ),
            LeaderboardCardEntry(
                rank=2,
                display_name="5AL ANAS",
                wins=230,
                losses=63,
                winrate_text="78.5%",
                points=9180,
            ),
        ],
    )
    assert card.getvalue().startswith(b"\x89PNG")
