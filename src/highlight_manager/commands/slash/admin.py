from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands

from highlight_manager.models.enums import AuditAction, ResultSource
from highlight_manager.utils.embeds import build_config_embed
if TYPE_CHECKING:
    from highlight_manager.bot import HighlightBot


def register_admin_commands(bot: "HighlightBot") -> None:
    async def ensure_staff(interaction: discord.Interaction) -> bool:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            if not interaction.response.is_done():
                await interaction.response.send_message("This command can only be used inside the server.", ephemeral=True)
            return False
        if not await bot.config_service.is_staff(interaction.user):
            if not interaction.response.is_done():
                await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
            return False
        return True

    async def ensure_setup_admin(interaction: discord.Interaction) -> bool:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            if not interaction.response.is_done():
                await interaction.response.send_message("This command can only be used inside the server.", ephemeral=True)
            return False
        if interaction.user.guild_permissions.administrator or interaction.user.guild_permissions.manage_guild:
            return True
        existing_config = await bot.config_service.get(interaction.guild.id)
        if existing_config and await bot.config_service.is_staff(interaction.user):
            return True
        if not interaction.response.is_done():
            await interaction.response.send_message("You need Manage Guild, Administrator, or a configured staff role to use setup commands.", ephemeral=True)
        return False

    def build_setup_embed(result, guild: discord.Guild) -> discord.Embed:
        embed = build_config_embed(result.config, guild)
        embed.title = "Setup Summary"
        embed.add_field(
            name="Resources",
            value=(
                f"Created:\n{chr(10).join(result.created_resources) if result.created_resources else 'None'}\n\n"
                f"Reused:\n{chr(10).join(result.reused_resources) if result.reused_resources else 'None'}"
            )[:1024],
            inline=False,
        )
        if result.bootstrap_summary:
            rank_lines = [
                f"Rank {rank}: {count}"
                for rank, count in sorted(result.bootstrap_summary.rank_counts.items(), key=lambda item: int(item[0]))
            ]
            embed.add_field(
                name="Bootstrap",
                value=(
                    f"Processed: {result.bootstrap_summary.processed_members}\n"
                    f"Ranks: {', '.join(rank_lines) if rank_lines else 'N/A'}\n"
                    f"Renamed: {result.bootstrap_summary.renamed_members}\n"
                    f"Rename Failures: {result.bootstrap_summary.rename_failures}\n"
                    f"Rename Already Correct: {result.bootstrap_summary.rename_already_correct}\n"
                    f"Rename Skipped Due To Hierarchy: {result.bootstrap_summary.rename_skipped_due_to_hierarchy}\n"
                    f"Rename Skipped Due To Missing Permission: {result.bootstrap_summary.rename_skipped_due_to_missing_permission}\n"
                    f"Rename Skipped Other: {result.bootstrap_summary.rename_skipped_other}\n"
                    f"Skipped: {len(result.bootstrap_summary.skipped_members)}"
                ),
                inline=False,
            )
        return embed

    @bot.tree.command(name="setup", description="Initial guild setup for Highlight Manager")
    @app_commands.choices(
        action=[
            app_commands.Choice(name="Run setup", value="run"),
            app_commands.Choice(name="Show setup status", value="status"),
            app_commands.Choice(name="Repair missing resources", value="repair"),
        ],
    )
    async def setup(
        interaction: discord.Interaction,
        action: app_commands.Choice[str] | None = None,
        prefix: str | None = None,
    ) -> None:
        if not await ensure_setup_admin(interaction):
            return
        selected_action = action.value if action else "run"
        if selected_action == "status":
            config = await bot.config_service.get_or_create(interaction.guild.id)
            return await interaction.response.send_message(embed=build_config_embed(config, interaction.guild), ephemeral=True)

        if selected_action == "repair":
            result = await bot.setup_service.repair(interaction.guild)
            await bot.audit_service.log(
                interaction.guild,
                AuditAction.SETUP,
                "Setup repair completed.",
                actor_id=interaction.user.id,
                metadata={"created": result.created_resources, "reused": result.reused_resources},
            )
            return await interaction.response.send_message(embed=build_setup_embed(result, interaction.guild), ephemeral=True)

        result = await bot.setup_service.run(interaction.guild, prefix=prefix)
        await bot.audit_service.log(
            interaction.guild,
            AuditAction.SETUP,
            "Automatic setup completed.",
            actor_id=interaction.user.id,
            metadata={
                "created": result.created_resources,
                "reused": result.reused_resources,
                "bootstrap_ran": result.first_bootstrap_ran,
            },
        )
        await interaction.response.send_message(embed=build_setup_embed(result, interaction.guild), ephemeral=True)

    @bot.tree.command(name="config", description="View or update guild configuration")
    @app_commands.choices(
        result_behavior=[
            app_commands.Choice(name="Delete after delay", value="DELETE"),
            app_commands.Choice(name="Archive and lock", value="ARCHIVE_LOCK"),
        ],
    )
    async def config(
        interaction: discord.Interaction,
        prefix: str | None = None,
        apostado_play_channel: discord.TextChannel | None = None,
        highlight_play_channel: discord.TextChannel | None = None,
        waiting_voice: discord.VoiceChannel | None = None,
        temp_voice_category: discord.CategoryChannel | None = None,
        result_category: discord.CategoryChannel | None = None,
        log_channel: discord.TextChannel | None = None,
        admin_role: discord.Role | None = None,
        staff_role: discord.Role | None = None,
        season_reward_role: discord.Role | None = None,
        season_reward_role_name: str | None = None,
        result_behavior: app_commands.Choice[str] | None = None,
    ) -> None:
        if not await ensure_staff(interaction):
            return
        config = await bot.config_service.get_or_create(interaction.guild.id)
        if not any([prefix, apostado_play_channel, highlight_play_channel, waiting_voice, temp_voice_category, result_category, log_channel, admin_role, staff_role, season_reward_role, season_reward_role_name, result_behavior]):
            return await interaction.response.send_message(embed=build_config_embed(config, interaction.guild), ephemeral=True)
        config, _ = await bot.config_service.run_setup(
            interaction.guild,
            prefix=prefix,
            apostado_play_channel=apostado_play_channel,
            highlight_play_channel=highlight_play_channel,
            waiting_voice=waiting_voice,
            temp_voice_category=temp_voice_category,
            result_category=result_category,
            log_channel=log_channel,
            admin_role=admin_role,
            staff_role=staff_role,
            season_reward_role=season_reward_role,
            season_reward_role_name=season_reward_role_name,
            create_missing=False,
            result_behavior=result_behavior.value if result_behavior else None,
        )
        await bot.audit_service.log(interaction.guild, AuditAction.CONFIG_UPDATED, "Guild config updated.", actor_id=interaction.user.id)
        await interaction.response.send_message(embed=build_config_embed(config, interaction.guild), ephemeral=True)

    season = app_commands.Group(name="season", description="Season management")
    bootstrap = app_commands.Group(name="bootstrap", description="Bootstrap preview and rerun")
    rank = app_commands.Group(name="rank", description="Rank management")
    rank0 = app_commands.Group(name="rank0", description="Manual Rank 0 management")
    points = app_commands.Group(name="points", description="Point adjustments")
    match = app_commands.Group(name="match", description="Match moderation")
    blacklist = app_commands.Group(name="blacklist", description="Blacklist management")

    @season.command(name="start", description="Start a new season")
    async def season_start(interaction: discord.Interaction, name: str | None = None) -> None:
        if not await ensure_staff(interaction):
            return
        config = await bot.config_service.get_or_create(interaction.guild.id)
        season_record = await bot.season_service.start_new_season(interaction.guild, config, name=name)
        await bot.audit_service.log(interaction.guild, AuditAction.SEASON_STARTED, f"Started {season_record.name}.", actor_id=interaction.user.id)
        await interaction.response.send_message(f"Started **{season_record.name}**.", ephemeral=True)

    @season.command(name="end", description="End the current season")
    async def season_end(interaction: discord.Interaction) -> None:
        if not await ensure_staff(interaction):
            return
        config = await bot.config_service.get_or_create(interaction.guild.id)
        ended = await bot.season_service.end_active(interaction.guild, config)
        if ended is None:
            return await interaction.response.send_message("There is no active season to end.", ephemeral=True)
        await bot.audit_service.log(
            interaction.guild,
            AuditAction.SEASON_ENDED,
            f"Ended {ended.name}.",
            actor_id=interaction.user.id,
            metadata={"top_player_ids": ended.top_player_ids},
        )
        reward_count = len(ended.top_player_ids)
        await interaction.response.send_message(
            f"Ended **{ended.name}** and synced the Professional Highlight Player reward for **{reward_count}** player(s).",
            ephemeral=True,
        )

    @bootstrap.command(name="preview", description="Preview server-age bootstrap assignments")
    async def bootstrap_preview(interaction: discord.Interaction) -> None:
        if not await ensure_setup_admin(interaction):
            return
        config = await bot.config_service.get_or_create(interaction.guild.id)
        summary, preview_entries = await bot.bootstrap_service.preview(interaction.guild, config)
        lines = [
            f"{entry.display_name} -> Rank {entry.rank} ({entry.starting_points} pts, {entry.age_days}d)"
            for entry in preview_entries[:20]
        ]
        embed = discord.Embed(title="Bootstrap Preview", colour=discord.Colour.orange())
        embed.description = "\n".join(lines) if lines else "No members found."
        embed.add_field(name="Members Processed", value=str(summary.processed_members), inline=True)
        embed.add_field(
            name="Rank Counts",
            value=", ".join(
                f"Rank {rank}: {count}" for rank, count in sorted(summary.rank_counts.items(), key=lambda item: int(item[0]))
            ) or "N/A",
            inline=False,
        )
        if len(preview_entries) > 20:
            embed.set_footer(text=f"Showing 20 of {len(preview_entries)} members.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @bootstrap.command(name="rerun", description="Explicitly rerun server-age bootstrap")
    async def bootstrap_rerun(interaction: discord.Interaction) -> None:
        if not await ensure_setup_admin(interaction):
            return
        config = await bot.config_service.get_or_create(interaction.guild.id)
        summary = await bot.bootstrap_service.run(interaction.guild, config)
        await bot.config_service.update(
            interaction.guild.id,
            {
                "bootstrap_completed": True,
                "bootstrap_completed_at": summary.completed_at,
                "bootstrap_last_summary": summary.model_dump(mode="python"),
            },
        )
        await bot.audit_service.log(interaction.guild, AuditAction.SETUP, "Bootstrap rerun completed.", actor_id=interaction.user.id)
        embed = discord.Embed(title="Bootstrap Rerun Complete", colour=discord.Colour.green())
        embed.add_field(name="Processed Members", value=str(summary.processed_members), inline=True)
        embed.add_field(name="Renamed Members", value=str(summary.renamed_members), inline=True)
        embed.add_field(name="Rename Failures", value=str(summary.rename_failures), inline=True)
        embed.add_field(name="Rename Already Correct", value=str(summary.rename_already_correct), inline=True)
        embed.add_field(name="Rename Skipped Due To Hierarchy", value=str(summary.rename_skipped_due_to_hierarchy), inline=True)
        embed.add_field(name="Rename Skipped Due To Missing Permission", value=str(summary.rename_skipped_due_to_missing_permission), inline=True)
        embed.add_field(name="Rename Skipped Other", value=str(summary.rename_skipped_other), inline=True)
        embed.add_field(
            name="Rank Counts",
            value=", ".join(
                f"Rank {rank}: {count}" for rank, count in sorted(summary.rank_counts.items(), key=lambda item: int(item[0]))
            ) or "N/A",
            inline=False,
        )
        if summary.skipped_members:
            embed.add_field(name="Skipped Members", value="\n".join(summary.skipped_members[:10])[:1024], inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @rank.command(name="set", description="Manually set a player's rank")
    async def rank_set(interaction: discord.Interaction, member: discord.Member, rank_number: app_commands.Range[int, 1, 999]) -> None:
        if not await ensure_staff(interaction):
            return
        config = await bot.config_service.get_or_create(interaction.guild.id)
        profile = await bot.profile_service.set_rank(interaction.guild, member.id, config, rank_number)
        await bot.audit_service.log(interaction.guild, AuditAction.RANK_UPDATED, f"Set {member.mention} to Rank {rank_number}.", actor_id=interaction.user.id, target_id=member.id)
        await interaction.response.send_message(f"{member.mention} is now **Rank {profile.current_rank}**.", ephemeral=True)

    @rank0.command(name="grant", description="Grant manual Rank 0")
    async def rank0_grant(interaction: discord.Interaction, member: discord.Member) -> None:
        if not await ensure_staff(interaction):
            return
        config = await bot.config_service.get_or_create(interaction.guild.id)
        await bot.profile_service.set_rank0(interaction.guild, member.id, config, True)
        await bot.audit_service.log(interaction.guild, AuditAction.RANK_UPDATED, f"Granted Rank 0 to {member.mention}.", actor_id=interaction.user.id, target_id=member.id)
        await interaction.response.send_message(f"Granted Rank 0 to {member.mention}.", ephemeral=True)

    @rank0.command(name="revoke", description="Revoke manual Rank 0")
    async def rank0_revoke(interaction: discord.Interaction, member: discord.Member) -> None:
        if not await ensure_staff(interaction):
            return
        config = await bot.config_service.get_or_create(interaction.guild.id)
        profile = await bot.profile_service.set_rank0(interaction.guild, member.id, config, False)
        await bot.audit_service.log(interaction.guild, AuditAction.RANK_UPDATED, f"Revoked Rank 0 from {member.mention}.", actor_id=interaction.user.id, target_id=member.id)
        await interaction.response.send_message(f"Revoked Rank 0 from {member.mention}. They are now Rank {profile.current_rank}.", ephemeral=True)

    @points.command(name="add", description="Add points to a player")
    async def points_add(interaction: discord.Interaction, member: discord.Member, amount: int) -> None:
        if not await ensure_staff(interaction):
            return
        config = await bot.config_service.get_or_create(interaction.guild.id)
        result = await bot.profile_service.adjust_points(interaction.guild, member.id, config, abs(amount))
        await bot.audit_service.log(interaction.guild, AuditAction.POINTS_UPDATED, f"Added {abs(amount)} points to {member.mention}.", actor_id=interaction.user.id, target_id=member.id)
        await interaction.response.send_message(f"{member.mention}: {result.previous_points} -> {result.new_points} points.", ephemeral=True)

    @points.command(name="remove", description="Remove points from a player")
    async def points_remove(interaction: discord.Interaction, member: discord.Member, amount: int) -> None:
        if not await ensure_staff(interaction):
            return
        config = await bot.config_service.get_or_create(interaction.guild.id)
        result = await bot.profile_service.adjust_points(interaction.guild, member.id, config, -abs(amount))
        await bot.audit_service.log(interaction.guild, AuditAction.POINTS_UPDATED, f"Removed {abs(amount)} points from {member.mention}.", actor_id=interaction.user.id, target_id=member.id)
        await interaction.response.send_message(f"{member.mention}: {result.previous_points} -> {result.new_points} points.", ephemeral=True)

    @points.command(name="set", description="Set a player's points exactly")
    async def points_set(interaction: discord.Interaction, member: discord.Member, amount: int) -> None:
        if not await ensure_staff(interaction):
            return
        config = await bot.config_service.get_or_create(interaction.guild.id)
        result = await bot.profile_service.set_points(interaction.guild, member.id, config, amount)
        await bot.audit_service.log(interaction.guild, AuditAction.POINTS_UPDATED, f"Set {member.mention} to {amount} points.", actor_id=interaction.user.id, target_id=member.id)
        await interaction.response.send_message(f"{member.mention}: {result.previous_points} -> {result.new_points} points.", ephemeral=True)

    @match.command(name="cancel", description="Cancel a match")
    async def match_cancel(interaction: discord.Interaction, match_number: int, reason: str | None = None) -> None:
        if not await ensure_staff(interaction):
            return
        result = await bot.match_service.cancel_match(interaction.guild, match_number, actor_id=interaction.user.id, force=True, reason=reason or "Canceled by staff.")
        await interaction.response.send_message(result.message, ephemeral=True)

    @match.command(name="force-result", description="Force a result for a match")
    async def match_force_result(
        interaction: discord.Interaction,
        match_number: int,
        winner_team: app_commands.Range[int, 1, 2],
        winner_mvp: discord.Member | None = None,
        loser_mvp: discord.Member | None = None,
        notes: str | None = None,
    ) -> None:
        if not await ensure_staff(interaction):
            return
        current_match = await bot.match_service.require_match(interaction.guild.id, match_number)
        if current_match.mode.team_size > 1 and (winner_mvp is None or loser_mvp is None):
            return await interaction.response.send_message("Team matches require both winner MVP and loser MVP.", ephemeral=True)
        finalized = await bot.match_service.finalize_match(
            interaction.guild,
            match_number,
            winner_team=winner_team,
            winner_mvp_id=winner_mvp.id if winner_mvp else None,
            loser_mvp_id=loser_mvp.id if loser_mvp else None,
            source=ResultSource.FORCE_RESULT,
            actor_id=interaction.user.id,
            notes=notes or "Forced by staff command.",
        )
        await interaction.response.send_message(f"Forced result for Match #{finalized.display_id}.", ephemeral=True)

    @match.command(name="force-close", description="Force close a match")
    async def match_force_close(interaction: discord.Interaction, match_number: int, reason: str | None = None) -> None:
        if not await ensure_staff(interaction):
            return
        result = await bot.match_service.force_close(interaction.guild, match_number, interaction.user.id, reason or "Force closed by staff.")
        await interaction.response.send_message(result.message, ephemeral=True)

    @blacklist.command(name="add", description="Blacklist a player from matches")
    async def blacklist_add(interaction: discord.Interaction, member: discord.Member) -> None:
        if not await ensure_staff(interaction):
            return
        profile = await bot.profile_service.set_blacklist(interaction.guild, member.id, True)
        await bot.audit_service.log(interaction.guild, AuditAction.BLACKLIST_UPDATED, f"Blacklisted {member.mention}.", actor_id=interaction.user.id, target_id=member.id)
        await interaction.response.send_message(f"{member.mention} is now blacklisted. Current points: {profile.current_points}.", ephemeral=True)

    @blacklist.command(name="remove", description="Remove a player from the blacklist")
    async def blacklist_remove(interaction: discord.Interaction, member: discord.Member) -> None:
        if not await ensure_staff(interaction):
            return
        profile = await bot.profile_service.set_blacklist(interaction.guild, member.id, False)
        await bot.audit_service.log(interaction.guild, AuditAction.BLACKLIST_UPDATED, f"Removed blacklist for {member.mention}.", actor_id=interaction.user.id, target_id=member.id)
        await interaction.response.send_message(f"{member.mention} is no longer blacklisted. Current points: {profile.current_points}.", ephemeral=True)

    for group in [season, bootstrap, rank, rank0, points, match, blacklist]:
        bot.tree.add_command(group)
