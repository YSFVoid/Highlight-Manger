from __future__ import annotations

from collections import defaultdict

import discord

from highlight_manager.models.enums import TournamentPhase
from highlight_manager.models.tournament import TournamentMatchRecord, TournamentRecord, TournamentTeam
from highlight_manager.utils.dates import format_dt


def build_tournament_embed(tournament: TournamentRecord, team_count: int) -> discord.Embed:
    embed = discord.Embed(
        title=f"{tournament.name} | Tournament #{tournament.tournament_number:03d}",
        description="Competitive tournament registration and progression powered by Highlight Manager.",
        colour=discord.Colour.from_rgb(27, 30, 36),
    )
    embed.add_field(name="Size", value=tournament.size.value, inline=True)
    embed.add_field(name="Phase", value=tournament.phase.value, inline=True)
    embed.add_field(name="Teams", value=f"{team_count}/{tournament.max_teams}", inline=True)
    embed.add_field(name="Format", value="4-player teams | BO3 series", inline=False)
    embed.add_field(
        name="Progression",
        value=f"{tournament.group_count} groups -> top {tournament.advancing_per_group} advance per group",
        inline=False,
    )
    embed.set_footer(text="Use !tournament apply to register.")
    return embed


def build_tournament_roster_embed(tournament: TournamentRecord, teams: list[TournamentTeam]) -> discord.Embed:
    embed = discord.Embed(
        title=f"{tournament.name} Rosters",
        colour=discord.Colour.blurple(),
    )
    lines = []
    for team in teams[:20]:
        lines.append(
            f"**#{team.team_number} {team.team_name}** | Captain: <@{team.captain_id}> | Players: "
            + ", ".join(f"<@{user_id}>" for user_id in team.player_ids)
        )
    embed.description = "\n".join(lines) if lines else "No teams registered yet."
    return embed


def build_tournament_bracket_embed(tournament: TournamentRecord, matches: list[TournamentMatchRecord], teams_by_id: dict[int, TournamentTeam]) -> discord.Embed:
    embed = discord.Embed(
        title=f"{tournament.name} Bracket / Matches",
        colour=discord.Colour.dark_magenta(),
    )
    if not matches:
        embed.description = "No tournament matches generated yet."
        return embed
    grouped: dict[str, list[str]] = defaultdict(list)
    for match in matches:
        team1 = teams_by_id.get(match.team1_id)
        team2 = teams_by_id.get(match.team2_id)
        winner = teams_by_id.get(match.winner_team_id) if match.winner_team_id else None
        grouped[match.round_label].append(
            f"Match #{match.match_number:03d} | {team1.team_name if team1 else match.team1_id} vs "
            f"{team2.team_name if team2 else match.team2_id} | "
            f"{match.team1_room_wins}-{match.team2_room_wins} | "
            f"{winner.team_name if winner else match.status.value} | {format_dt(match.scheduled_at)}"
        )
    for round_label, lines in grouped.items():
        embed.add_field(name=round_label, value="\n".join(lines)[:1024], inline=False)
    return embed


def build_group_standings_embed(
    tournament: TournamentRecord,
    standings: dict[str, list[dict]],
    teams_by_id: dict[int, TournamentTeam],
) -> discord.Embed:
    embed = discord.Embed(
        title=f"{tournament.name} Group Standings",
        colour=discord.Colour.teal(),
    )
    if not standings:
        embed.description = "Standings are not available yet."
        return embed
    for group_label, rows in standings.items():
        lines = []
        for index, row in enumerate(rows, start=1):
            team = teams_by_id.get(row["team_id"])
            lines.append(
                f"{index}. {team.team_name if team else row['team_id']} | "
                f"{row['points']} pts | {row['series_wins']}-{row['series_losses']} | "
                f"Series diff {row['series_diff']} | Room diff {row['room_diff']}"
            )
        embed.add_field(name=f"Group {group_label}", value="\n".join(lines)[:1024], inline=False)
    return embed


def build_tournament_match_embed(
    tournament: TournamentRecord,
    match: TournamentMatchRecord,
    team1: TournamentTeam | None,
    team2: TournamentTeam | None,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"{tournament.name} | Match #{match.match_number:03d}",
        colour=discord.Colour.orange() if match.phase == TournamentPhase.GROUP_STAGE else discord.Colour.red(),
    )
    embed.add_field(name="Round", value=match.round_label, inline=True)
    embed.add_field(name="Status", value=match.status.value, inline=True)
    embed.add_field(name="Scheduled", value=format_dt(match.scheduled_at), inline=True)
    embed.add_field(name="Team 1", value=team1.team_name if team1 else str(match.team1_id), inline=True)
    embed.add_field(name="Team 2", value=team2.team_name if team2 else str(match.team2_id), inline=True)
    embed.add_field(name="Series Score", value=f"{match.team1_room_wins} - {match.team2_room_wins}", inline=True)
    if match.group_label:
        embed.add_field(name="Group", value=match.group_label, inline=True)
    embed.set_footer(text="Captains/staff can report room wins here.")
    return embed


def build_champion_embed(tournament: TournamentRecord, champion: TournamentTeam | None) -> discord.Embed:
    embed = discord.Embed(
        title=f"{tournament.name} Champion",
        description=champion.team_name if champion else "Champion decided.",
        colour=discord.Colour.gold(),
    )
    if champion:
        embed.add_field(name="Captain", value=f"<@{champion.captain_id}>", inline=True)
        embed.add_field(name="Players", value=", ".join(f"<@{user_id}>" for user_id in champion.player_ids), inline=False)
    return embed
