from __future__ import annotations

import discord

from highlight_manager.ui import theme


def build_tournament_embed(tournament, teams, matches) -> discord.Embed:
    state_str = tournament.state.value.replace('_', ' ').title()
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
    
    team_dict = {t.id: t.name for t in teams}
    
    if teams:
        team_lines = []
        for i, team in enumerate(teams[:10], 1):
            team_lines.append(f"`{i}.` **{team.name}**")
        if len(teams) > 10:
            team_lines.append(f"...and {len(teams) - 10} more")
        embed.add_field(name="🛡️ Registered Teams", value="\n".join(team_lines), inline=False)
    
    if matches:
        match_lines = []
        for match in matches[:5]:
            t1 = team_dict.get(match.team1_id, "TBD") if match.team1_id else "TBD"
            t2 = team_dict.get(match.team2_id, "TBD") if match.team2_id else "TBD"
            match_state = match.state.value.replace('_', ' ').title()
            match_lines.append(f"{theme.EMOJI_SWORD} **Round {match.round_num}:** {t1} vs {t2} — `{match_state}`")
        if len(matches) > 5:
            match_lines.append(f"...and {len(matches) - 5} more")
        embed.add_field(name="⚔️ Latest Matches", value="\n".join(match_lines), inline=False)
    
    embed.set_footer(text="Highlight Manger  •  Esports")
    return embed
