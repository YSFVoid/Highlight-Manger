from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Awaitable, Callable

import discord
from discord import app_commands

from highlight_manager.config.logging import get_logger
from highlight_manager.models.enums import AuditAction, ResultSource
from highlight_manager.utils.embeds import build_config_embed
from highlight_manager.utils.exceptions import HighlightError
if TYPE_CHECKING:
    from highlight_manager.bot import HighlightBot


@dataclass(slots=True)
class InteractionResponsePayload:
    content: str | None = None
    embed: discord.Embed | None = None


LOGGER = get_logger(__name__)


async def _send_interaction_response(
    interaction: discord.Interaction,
    *,
    content: str | None = None,
    embed: discord.Embed | None = None,
    ephemeral: bool = True,
) -> None:
    try:
        if interaction.response.is_done():
            await interaction.followup.send(content=content, embed=embed, ephemeral=ephemeral)
            return
        await interaction.response.send_message(content=content, embed=embed, ephemeral=ephemeral)
    except discord.NotFound:
        LOGGER.warning(
            "interaction_response_expired",
            guild_id=interaction.guild.id if interaction.guild else None,
            user_id=interaction.user.id if interaction.user else None,
            interaction_responded=interaction.response.is_done(),
        )


def _interaction_log_context(
    interaction: discord.Interaction,
    command_name: str,
    *,
    deferred: bool = False,
    **extra,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "command_name": command_name,
        "guild_id": interaction.guild.id if interaction.guild else None,
        "invoking_user_id": interaction.user.id if interaction.user else None,
        "interaction_responded": interaction.response.is_done(),
        "interaction_deferred": deferred,
    }
    payload.update(extra)
    return payload


async def _ensure_guild_member_context(interaction: discord.Interaction) -> bool:
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        await _send_interaction_response(
            interaction,
            content="This command can only be used inside the server.",
            ephemeral=True,
        )
        return False
    return True


async def _ensure_staff(bot: "HighlightBot", interaction: discord.Interaction) -> bool:
    if not await _ensure_guild_member_context(interaction):
        return False
    assert isinstance(interaction.user, discord.Member)
    if not await bot.config_service.is_staff(interaction.user):
        await _send_interaction_response(
            interaction,
            content="You do not have permission to use this command.",
            ephemeral=True,
        )
        return False
    return True


async def _ensure_setup_admin(bot: "HighlightBot", interaction: discord.Interaction) -> bool:
    if not await _ensure_guild_member_context(interaction):
        return False
    assert isinstance(interaction.user, discord.Member)
    if interaction.user.guild_permissions.administrator or interaction.user.guild_permissions.manage_guild:
        return True
    existing_config = await bot.config_service.get(interaction.guild.id)
    if existing_config and await bot.config_service.is_staff(interaction.user):
        return True
    await _send_interaction_response(
        interaction,
        content="You need Manage Guild, Administrator, or a configured staff role to use setup commands.",
        ephemeral=True,
    )
    return False


async def _defer_ephemeral_response(interaction: discord.Interaction) -> bool:
    if interaction.response.is_done():
        return False
    try:
        await interaction.response.defer(ephemeral=True, thinking=True)
    except discord.NotFound:
        LOGGER.warning(
            "interaction_defer_expired",
            guild_id=interaction.guild.id if interaction.guild else None,
            user_id=interaction.user.id if interaction.user else None,
        )
        return False
    return True


async def _run_deferred_admin_command(
    bot: "HighlightBot",
    interaction: discord.Interaction,
    *,
    command_name: str,
    permission_check: Callable[[discord.Interaction], Awaitable[bool]],
    operation: Callable[[], Awaitable[InteractionResponsePayload]],
) -> None:
    if not await _ensure_guild_member_context(interaction):
        return
    deferred = False
    try:
        deferred = await _defer_ephemeral_response(interaction)
        if not await permission_check(interaction):
            bot.logger.info(
                "slash_command_permission_denied",
                **_interaction_log_context(interaction, command_name, deferred=deferred),
            )
            return
        bot.logger.info(
            "slash_command_started",
            **_interaction_log_context(interaction, command_name, deferred=deferred),
        )
        payload = await operation()
        bot.logger.info(
            "slash_command_completed",
            **_interaction_log_context(interaction, command_name, deferred=deferred),
        )
        await _send_interaction_response(
            interaction,
            content=payload.content,
            embed=payload.embed,
            ephemeral=True,
        )
    except HighlightError as exc:
        bot.logger.warning(
            "slash_command_validation_failed",
            error=str(exc),
            **_interaction_log_context(interaction, command_name, deferred=deferred),
        )
        await _send_interaction_response(interaction, content=str(exc), ephemeral=True)
    except Exception:
        bot.logger.exception(
            "slash_command_unexpected_failure",
            **_interaction_log_context(interaction, command_name, deferred=deferred),
        )
        await _send_interaction_response(
            interaction,
            content="I hit an internal error while processing that request.",
            ephemeral=True,
        )


def register_admin_commands(bot: "HighlightBot") -> None:

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
            assigned_range = (
                f"Rank {result.bootstrap_summary.first_assigned_rank} to Rank {result.bootstrap_summary.last_assigned_rank}"
                if result.bootstrap_summary.first_assigned_rank and result.bootstrap_summary.last_assigned_rank
                else "N/A"
            )
            embed.add_field(
                name="Bootstrap",
                value=(
                    f"Processed: {result.bootstrap_summary.processed_members}\n"
                    f"Assigned Ranks: {assigned_range}\n"
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
        selected_action = action.value if action else "run"
        if selected_action == "status":
            if not await _ensure_setup_admin(bot, interaction):
                return
            config = await bot.config_service.get_or_create(interaction.guild.id)
            await _send_interaction_response(
                interaction,
                embed=build_config_embed(config, interaction.guild),
                ephemeral=True,
            )
            return

        if selected_action == "repair":
            async def repair_operation() -> InteractionResponsePayload:
                result = await bot.setup_service.repair(interaction.guild)
                await bot.audit_service.log(
                    interaction.guild,
                    AuditAction.SETUP,
                    "Setup repair completed.",
                    actor_id=interaction.user.id,
                    metadata={"created": result.created_resources, "reused": result.reused_resources},
                )
                return InteractionResponsePayload(embed=build_setup_embed(result, interaction.guild))

            await _run_deferred_admin_command(
                bot,
                interaction,
                command_name="/setup repair",
                permission_check=lambda current: _ensure_setup_admin(bot, current),
                operation=repair_operation,
            )
            return

        async def setup_operation() -> InteractionResponsePayload:
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
            return InteractionResponsePayload(embed=build_setup_embed(result, interaction.guild))

        await _run_deferred_admin_command(
            bot,
            interaction,
            command_name="/setup",
            permission_check=lambda current: _ensure_setup_admin(bot, current),
            operation=setup_operation,
        )

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
        mvp_reward_role: discord.Role | None = None,
        mvp_reward_role_name: str | None = None,
        season_reward_role: discord.Role | None = None,
        season_reward_role_name: str | None = None,
        ping_here_on_match_create: bool | None = None,
        ping_here_on_match_ready: bool | None = None,
        private_match_key_required: bool | None = None,
        result_behavior: app_commands.Choice[str] | None = None,
    ) -> None:
        if not any(
            [
                prefix,
                apostado_play_channel,
                highlight_play_channel,
                waiting_voice,
                temp_voice_category,
                result_category,
                log_channel,
                admin_role,
                staff_role,
                mvp_reward_role,
                mvp_reward_role_name,
                season_reward_role,
                season_reward_role_name,
                ping_here_on_match_create is not None,
                ping_here_on_match_ready is not None,
                private_match_key_required is not None,
                result_behavior,
            ]
        ):
            if not await _ensure_staff(bot, interaction):
                return
            current_config = await bot.config_service.get_or_create(interaction.guild.id)
            await _send_interaction_response(
                interaction,
                embed=build_config_embed(current_config, interaction.guild),
                ephemeral=True,
            )
            return

        async def config_operation() -> InteractionResponsePayload:
            updated_config, _ = await bot.config_service.run_setup(
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
                mvp_reward_role=mvp_reward_role,
                mvp_reward_role_name=mvp_reward_role_name,
                season_reward_role=season_reward_role,
                season_reward_role_name=season_reward_role_name,
                ping_here_on_match_create=ping_here_on_match_create,
                ping_here_on_match_ready=ping_here_on_match_ready,
                private_match_key_required=private_match_key_required,
                create_missing=False,
                result_behavior=result_behavior.value if result_behavior else None,
            )
            await bot.audit_service.log(
                interaction.guild,
                AuditAction.CONFIG_UPDATED,
                "Guild config updated.",
                actor_id=interaction.user.id,
            )
            return InteractionResponsePayload(embed=build_config_embed(updated_config, interaction.guild))

        await _run_deferred_admin_command(
            bot,
            interaction,
            command_name="/config",
            permission_check=lambda current: _ensure_staff(bot, current),
            operation=config_operation,
        )

    season = app_commands.Group(name="season", description="Season management")
    bootstrap = app_commands.Group(name="bootstrap", description="Bootstrap preview and rerun")
    points = app_commands.Group(name="points", description="Point adjustments")
    rank0 = app_commands.Group(name="rank0", description="Manual Rank 0 override")
    match = app_commands.Group(name="match", description="Match moderation")
    blacklist = app_commands.Group(name="blacklist", description="Blacklist management")

    @season.command(name="start", description="Start a new season")
    async def season_start(interaction: discord.Interaction, name: str | None = None) -> None:
        command_name = "/season start"
        if not await _ensure_guild_member_context(interaction):
            return
        deferred = False
        active_before = None
        try:
            deferred = await _defer_ephemeral_response(interaction)
            if not await _ensure_staff(bot, interaction):
                bot.logger.info(
                    "season_command_permission_denied",
                    **_interaction_log_context(interaction, command_name, deferred=deferred),
                )
                return
            active_before = await bot.season_service.get_active(interaction.guild.id)
            bot.logger.info(
                "season_command_requested",
                **_interaction_log_context(
                    interaction,
                    command_name,
                    deferred=deferred,
                    active_season_before=active_before.name if active_before else None,
                    active_season_number_before=active_before.season_number if active_before else None,
                ),
            )
            config = await bot.config_service.get_or_create(interaction.guild.id)
            season_record = await bot.season_service.start_new_season(interaction.guild, config, name=name)
            await bot.audit_service.log(
                interaction.guild,
                AuditAction.SEASON_STARTED,
                f"Started {season_record.name}.",
                actor_id=interaction.user.id,
            )
            bot.logger.info(
                "season_command_completed",
                **_interaction_log_context(
                    interaction,
                    command_name,
                    deferred=deferred,
                    active_season_before=active_before.name if active_before else None,
                    active_season_number_before=active_before.season_number if active_before else None,
                    db_result="season_started",
                    started_season_name=season_record.name,
                    started_season_number=season_record.season_number,
                ),
            )
            await _send_interaction_response(
                interaction,
                content=f"Started **{season_record.name}**.",
                ephemeral=True,
            )
        except HighlightError as exc:
            bot.logger.warning(
                "season_command_validation_failed",
                error=str(exc),
                **_interaction_log_context(
                    interaction,
                    command_name,
                    deferred=deferred,
                    active_season_before=active_before.name if active_before else None,
                    active_season_number_before=active_before.season_number if active_before else None,
                ),
            )
            await _send_interaction_response(interaction, content=str(exc), ephemeral=True)
        except Exception:
            bot.logger.exception(
                "season_command_failed",
                **_interaction_log_context(
                    interaction,
                    command_name,
                    deferred=deferred,
                    active_season_before=active_before.name if active_before else None,
                    active_season_number_before=active_before.season_number if active_before else None,
                ),
            )
            await _send_interaction_response(
                interaction,
                content="I hit an internal error while processing that request.",
                ephemeral=True,
            )

    @season.command(name="end", description="End the current season")
    async def season_end(interaction: discord.Interaction) -> None:
        command_name = "/season end"
        if not await _ensure_guild_member_context(interaction):
            return
        deferred = False
        active_before = None
        try:
            deferred = await _defer_ephemeral_response(interaction)
            if not await _ensure_staff(bot, interaction):
                bot.logger.info(
                    "season_command_permission_denied",
                    **_interaction_log_context(interaction, command_name, deferred=deferred),
                )
                return
            active_before = await bot.season_service.get_active(interaction.guild.id)
            bot.logger.info(
                "season_command_requested",
                **_interaction_log_context(
                    interaction,
                    command_name,
                    deferred=deferred,
                    active_season_before=active_before.name if active_before else None,
                    active_season_number_before=active_before.season_number if active_before else None,
                ),
            )
            config = await bot.config_service.get_or_create(interaction.guild.id)
            ended = await bot.season_service.end_active(interaction.guild, config)
            if ended is None:
                bot.logger.info(
                    "season_command_completed",
                    **_interaction_log_context(
                        interaction,
                        command_name,
                        deferred=deferred,
                        active_season_before=None,
                        active_season_number_before=None,
                        db_result="no_active_season",
                    ),
                )
                await _send_interaction_response(
                    interaction,
                    content="There is no active season to end.",
                    ephemeral=True,
                )
                return
            await bot.audit_service.log(
                interaction.guild,
                AuditAction.SEASON_ENDED,
                f"Ended {ended.name}.",
                actor_id=interaction.user.id,
                metadata={"top_player_ids": ended.top_player_ids},
            )
            reward_count = len(ended.top_player_ids)
            bot.logger.info(
                "season_command_completed",
                **_interaction_log_context(
                    interaction,
                    command_name,
                    deferred=deferred,
                    active_season_before=active_before.name if active_before else None,
                    active_season_number_before=active_before.season_number if active_before else None,
                    db_result="season_ended",
                    ended_season_name=ended.name,
                    ended_season_number=ended.season_number,
                    reward_top_player_ids=ended.top_player_ids,
                    reward_count=reward_count,
                ),
            )
            await _send_interaction_response(
                interaction,
                content=(
                    f"Ended **{ended.name}** and synced the Professional Highlight Player "
                    f"reward for **{reward_count}** player(s)."
                ),
                ephemeral=True,
            )
        except HighlightError as exc:
            bot.logger.warning(
                "season_command_validation_failed",
                error=str(exc),
                **_interaction_log_context(
                    interaction,
                    command_name,
                    deferred=deferred,
                    active_season_before=active_before.name if active_before else None,
                    active_season_number_before=active_before.season_number if active_before else None,
                ),
            )
            await _send_interaction_response(interaction, content=str(exc), ephemeral=True)
        except Exception:
            bot.logger.exception(
                "season_command_failed",
                **_interaction_log_context(
                    interaction,
                    command_name,
                    deferred=deferred,
                    active_season_before=active_before.name if active_before else None,
                    active_season_number_before=active_before.season_number if active_before else None,
                ),
            )
            await _send_interaction_response(
                interaction,
                content="I hit an internal error while processing that request.",
                ephemeral=True,
            )

    @bootstrap.command(name="preview", description="Preview server-age bootstrap assignments")
    async def bootstrap_preview(interaction: discord.Interaction) -> None:
        if not await _ensure_setup_admin(bot, interaction):
            return
        config = await bot.config_service.get_or_create(interaction.guild.id)
        summary, preview_entries = await bot.bootstrap_service.preview(interaction.guild, config)
        lines = [
            f"{entry.display_name} -> Rank {entry.rank} (0 pts, {entry.age_days}d)"
            for entry in preview_entries[:20]
        ]
        embed = discord.Embed(title="Bootstrap Preview", colour=discord.Colour.orange())
        embed.description = "\n".join(lines) if lines else "No members found."
        embed.add_field(name="Members Processed", value=str(summary.processed_members), inline=True)
        embed.add_field(
            name="Assigned Rank Range",
            value=(
                f"Rank {summary.first_assigned_rank} to Rank {summary.last_assigned_rank}"
                if summary.first_assigned_rank and summary.last_assigned_rank
                else "N/A"
            ),
            inline=True,
        )
        if len(preview_entries) > 20:
            embed.set_footer(text=f"Showing 20 of {len(preview_entries)} members.")
        await _send_interaction_response(interaction, embed=embed, ephemeral=True)

    @bootstrap.command(name="rerun", description="Explicitly rerun server-age bootstrap")
    async def bootstrap_rerun(interaction: discord.Interaction) -> None:
        async def rerun_operation() -> InteractionResponsePayload:
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
            await bot.audit_service.log(
                interaction.guild,
                AuditAction.SETUP,
                "Bootstrap rerun completed.",
                actor_id=interaction.user.id,
            )
            embed = discord.Embed(title="Bootstrap Rerun Complete", colour=discord.Colour.green())
            embed.add_field(name="Processed Members", value=str(summary.processed_members), inline=True)
            embed.add_field(name="Renamed Members", value=str(summary.renamed_members), inline=True)
            embed.add_field(name="Rename Failures", value=str(summary.rename_failures), inline=True)
            embed.add_field(name="Rename Already Correct", value=str(summary.rename_already_correct), inline=True)
            embed.add_field(name="Rename Skipped Due To Hierarchy", value=str(summary.rename_skipped_due_to_hierarchy), inline=True)
            embed.add_field(name="Rename Skipped Due To Missing Permission", value=str(summary.rename_skipped_due_to_missing_permission), inline=True)
            embed.add_field(name="Rename Skipped Other", value=str(summary.rename_skipped_other), inline=True)
            embed.add_field(
                name="Assigned Rank Range",
                value=(
                    f"Rank {summary.first_assigned_rank} to Rank {summary.last_assigned_rank}"
                    if summary.first_assigned_rank and summary.last_assigned_rank
                    else "N/A"
                ),
                inline=False,
            )
            if summary.skipped_members:
                embed.add_field(
                    name="Skipped Members",
                    value="\n".join(summary.skipped_members[:10])[:1024],
                    inline=False,
                )
            return InteractionResponsePayload(embed=embed)

        await _run_deferred_admin_command(
            bot,
            interaction,
            command_name="/bootstrap rerun",
            permission_check=lambda current: _ensure_setup_admin(bot, current),
            operation=rerun_operation,
        )

    @points.command(name="add", description="Add points to a player")
    async def points_add(interaction: discord.Interaction, member: discord.Member, amount: int) -> None:
        async def points_add_operation() -> InteractionResponsePayload:
            config = await bot.config_service.get_or_create(interaction.guild.id)
            result = await bot.profile_service.adjust_points(interaction.guild, member.id, config, abs(amount))
            await bot.audit_service.log(
                interaction.guild,
                AuditAction.POINTS_UPDATED,
                f"Added {abs(amount)} points to {member.mention}.",
                actor_id=interaction.user.id,
                target_id=member.id,
            )
            return InteractionResponsePayload(
                content=f"{member.mention}: {result.previous_points} -> {result.new_points} points.",
            )

        await _run_deferred_admin_command(
            bot,
            interaction,
            command_name="/points add",
            permission_check=lambda current: _ensure_staff(bot, current),
            operation=points_add_operation,
        )

    @points.command(name="remove", description="Remove points from a player")
    async def points_remove(interaction: discord.Interaction, member: discord.Member, amount: int) -> None:
        async def points_remove_operation() -> InteractionResponsePayload:
            config = await bot.config_service.get_or_create(interaction.guild.id)
            result = await bot.profile_service.adjust_points(interaction.guild, member.id, config, -abs(amount))
            await bot.audit_service.log(
                interaction.guild,
                AuditAction.POINTS_UPDATED,
                f"Removed {abs(amount)} points from {member.mention}.",
                actor_id=interaction.user.id,
                target_id=member.id,
            )
            return InteractionResponsePayload(
                content=f"{member.mention}: {result.previous_points} -> {result.new_points} points.",
            )

        await _run_deferred_admin_command(
            bot,
            interaction,
            command_name="/points remove",
            permission_check=lambda current: _ensure_staff(bot, current),
            operation=points_remove_operation,
        )

    @points.command(name="set", description="Set a player's points exactly")
    async def points_set(interaction: discord.Interaction, member: discord.Member, amount: int) -> None:
        async def points_set_operation() -> InteractionResponsePayload:
            config = await bot.config_service.get_or_create(interaction.guild.id)
            result = await bot.profile_service.set_points(interaction.guild, member.id, config, amount)
            await bot.audit_service.log(
                interaction.guild,
                AuditAction.POINTS_UPDATED,
                f"Set {member.mention} to {amount} points.",
                actor_id=interaction.user.id,
                target_id=member.id,
            )
            return InteractionResponsePayload(
                content=f"{member.mention}: {result.previous_points} -> {result.new_points} points.",
            )

        await _run_deferred_admin_command(
            bot,
            interaction,
            command_name="/points set",
            permission_check=lambda current: _ensure_staff(bot, current),
            operation=points_set_operation,
        )

    @rank0.command(name="grant", description="Grant the manual Rank 0 override to a member")
    async def rank0_grant(interaction: discord.Interaction, member: discord.Member) -> None:
        async def rank0_grant_operation() -> InteractionResponsePayload:
            config = await bot.config_service.get_or_create(interaction.guild.id)
            profile = await bot.profile_service.set_manual_rank_override(
                interaction.guild,
                member.id,
                config,
                manual_rank_override=0,
            )
            await bot.audit_service.log(
                interaction.guild,
                AuditAction.RANK_OVERRIDE_UPDATED,
                f"Granted Rank 0 to {member.mention}.",
                actor_id=interaction.user.id,
                target_id=member.id,
                metadata={"manual_rank_override": profile.manual_rank_override},
            )
            bot.logger.info(
                "rank0_granted",
                guild_id=interaction.guild.id,
                actor_id=interaction.user.id,
                target_id=member.id,
            )
            embed = discord.Embed(
                title="Rank 0 Granted",
                description=f"{member.mention} is now on the manual Rank 0 override.",
                colour=discord.Colour.orange(),
            )
            embed.add_field(name="Rank", value="Rank 0", inline=True)
            embed.add_field(name="Points", value=str(profile.current_points), inline=True)
            embed.add_field(name="Nickname Sync", value="Rank 0 nickname sync was attempted.", inline=False)
            return InteractionResponsePayload(embed=embed)

        await _run_deferred_admin_command(
            bot,
            interaction,
            command_name="/rank0 grant",
            permission_check=lambda current: _ensure_staff(bot, current),
            operation=rank0_grant_operation,
        )

    @rank0.command(name="revoke", description="Remove the manual Rank 0 override from a member")
    async def rank0_revoke(interaction: discord.Interaction, member: discord.Member) -> None:
        async def rank0_revoke_operation() -> InteractionResponsePayload:
            config = await bot.config_service.get_or_create(interaction.guild.id)
            profile = await bot.profile_service.set_manual_rank_override(
                interaction.guild,
                member.id,
                config,
                manual_rank_override=None,
            )
            await bot.audit_service.log(
                interaction.guild,
                AuditAction.RANK_OVERRIDE_UPDATED,
                f"Revoked Rank 0 from {member.mention}.",
                actor_id=interaction.user.id,
                target_id=member.id,
                metadata={"manual_rank_override": profile.manual_rank_override},
            )
            bot.logger.info(
                "rank0_revoked",
                guild_id=interaction.guild.id,
                actor_id=interaction.user.id,
                target_id=member.id,
                new_rank=profile.current_rank,
            )
            embed = discord.Embed(
                title="Rank 0 Removed",
                description=f"Removed the manual Rank 0 override from {member.mention}.",
                colour=discord.Colour.blurple(),
            )
            embed.add_field(name="Current Rank", value=f"Rank {profile.current_rank}", inline=True)
            embed.add_field(name="Points", value=str(profile.current_points), inline=True)
            embed.add_field(name="Nickname Sync", value="Leaderboard nickname sync was attempted.", inline=False)
            return InteractionResponsePayload(embed=embed)

        await _run_deferred_admin_command(
            bot,
            interaction,
            command_name="/rank0 revoke",
            permission_check=lambda current: _ensure_staff(bot, current),
            operation=rank0_revoke_operation,
        )

    @match.command(name="cancel", description="Cancel a match")
    async def match_cancel(interaction: discord.Interaction, match_number: int, reason: str | None = None) -> None:
        async def cancel_operation() -> InteractionResponsePayload:
            result = await bot.match_service.cancel_match(
                interaction.guild,
                match_number,
                actor_id=interaction.user.id,
                force=True,
                reason=reason or "Canceled by staff.",
            )
            return InteractionResponsePayload(content=result.message)

        await _run_deferred_admin_command(
            bot,
            interaction,
            command_name="/match cancel",
            permission_check=lambda current: _ensure_staff(bot, current),
            operation=cancel_operation,
        )

    @match.command(name="force-result", description="Force a result for a match")
    async def match_force_result(
        interaction: discord.Interaction,
        match_number: int,
        winner_team: app_commands.Range[int, 1, 2],
        winner_mvp: discord.Member | None = None,
        loser_mvp: discord.Member | None = None,
        notes: str | None = None,
    ) -> None:
        async def force_result_operation() -> InteractionResponsePayload:
            current_match = await bot.match_service.require_match(interaction.guild.id, match_number)
            if current_match.mode.team_size > 1 and (winner_mvp is None or loser_mvp is None):
                raise HighlightError("Team matches require both winner MVP and loser MVP.")
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
            return InteractionResponsePayload(content=f"Forced result for Match #{finalized.display_id}.")

        await _run_deferred_admin_command(
            bot,
            interaction,
            command_name="/match force-result",
            permission_check=lambda current: _ensure_staff(bot, current),
            operation=force_result_operation,
        )

    @match.command(name="force-close", description="Force close a match")
    async def match_force_close(interaction: discord.Interaction, match_number: int, reason: str | None = None) -> None:
        async def force_close_operation() -> InteractionResponsePayload:
            result = await bot.match_service.force_close(
                interaction.guild,
                match_number,
                interaction.user.id,
                reason or "Force closed by staff.",
            )
            return InteractionResponsePayload(content=result.message)

        await _run_deferred_admin_command(
            bot,
            interaction,
            command_name="/match force-close",
            permission_check=lambda current: _ensure_staff(bot, current),
            operation=force_close_operation,
        )

    @blacklist.command(name="add", description="Blacklist a player from matches")
    async def blacklist_add(interaction: discord.Interaction, member: discord.Member) -> None:
        async def blacklist_add_operation() -> InteractionResponsePayload:
            profile = await bot.profile_service.set_blacklist(interaction.guild, member.id, True)
            await bot.audit_service.log(
                interaction.guild,
                AuditAction.BLACKLIST_UPDATED,
                f"Blacklisted {member.mention}.",
                actor_id=interaction.user.id,
                target_id=member.id,
            )
            return InteractionResponsePayload(
                content=f"{member.mention} is now blacklisted. Current points: {profile.current_points}.",
            )

        await _run_deferred_admin_command(
            bot,
            interaction,
            command_name="/blacklist add",
            permission_check=lambda current: _ensure_staff(bot, current),
            operation=blacklist_add_operation,
        )

    @blacklist.command(name="remove", description="Remove a player from the blacklist")
    async def blacklist_remove(interaction: discord.Interaction, member: discord.Member) -> None:
        async def blacklist_remove_operation() -> InteractionResponsePayload:
            profile = await bot.profile_service.set_blacklist(interaction.guild, member.id, False)
            await bot.audit_service.log(
                interaction.guild,
                AuditAction.BLACKLIST_UPDATED,
                f"Removed blacklist for {member.mention}.",
                actor_id=interaction.user.id,
                target_id=member.id,
            )
            return InteractionResponsePayload(
                content=f"{member.mention} is no longer blacklisted. Current points: {profile.current_points}.",
            )

        await _run_deferred_admin_command(
            bot,
            interaction,
            command_name="/blacklist remove",
            permission_check=lambda current: _ensure_staff(bot, current),
            operation=blacklist_remove_operation,
        )

    for group in [season, bootstrap, points, rank0, match, blacklist]:
        bot.tree.add_command(group)
