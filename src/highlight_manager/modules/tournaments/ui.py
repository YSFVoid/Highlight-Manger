from __future__ import annotations

import discord

from highlight_manager.ui import theme
from highlight_manager.ui.brand import apply_embed_chrome


def build_tournament_embed(tournament, teams, matches) -> discord.Embed:
    state_str = tournament.state.value.replace("_", " ").title()
    format_str = tournament.format.value.replace("_", " ").title()

    embed = discord.Embed(
        title=f"{theme.EMOJI_TROPHY} Tournament: {tournament.name}",
        description=(
            f"**Status:** `{state_str}`\n"
            f"**Format:** `{format_str}`\n"
            f"**Total Teams:** `{len(teams)}`\n"
            f"**Total Matches:** `{len(matches)}`\n"
        ),
        colour=theme.ACCENT,
    )

    team_dict = {team.id: team.team_name for team in teams}

    if teams:
        team_lines = []
        for index, team in enumerate(teams[:10], 1):
            team_lines.append(f"`{index}.` **{team.team_name}**")
        if len(teams) > 10:
            team_lines.append(f"...and {len(teams) - 10} more")
        embed.add_field(name=f"{theme.EMOJI_SHIELD} Registered Teams", value="\n".join(team_lines), inline=False)

    if matches:
        match_lines = []
        for match in matches[:5]:
            team1_name = team_dict.get(match.team1_id, "TBD") if match.team1_id else "TBD"
            team2_name = team_dict.get(match.team2_id, "TBD") if match.team2_id else "TBD"
            match_state = match.state.value.replace("_", " ").title()
            match_lines.append(
                f"{theme.EMOJI_SWORD} **Round {match.round_number}:** "
                f"{team1_name} vs {team2_name} - `{match_state}`"
            )
        if len(matches) > 5:
            match_lines.append(f"...and {len(matches) - 5} more")
        embed.add_field(name=f"{theme.EMOJI_SWORD} Latest Matches", value="\n".join(match_lines), inline=False)

    return apply_embed_chrome(embed, section="Esports")
