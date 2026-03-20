from __future__ import annotations

import asyncio
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands, tasks
from pymongo import AsyncMongoClient

from highlight_manager.commands.prefix import gameplay as prefix_gameplay
from highlight_manager.commands.slash.admin import register_admin_commands
from highlight_manager.config.logging import configure_logging, get_logger
from highlight_manager.config.settings import get_settings
from highlight_manager.models.audit_log import AuditLogRecord
from highlight_manager.models.guild_config import GuildConfig
from highlight_manager.models.match import MatchRecord
from highlight_manager.models.profile import PlayerProfile
from highlight_manager.models.season import SeasonRecord
from highlight_manager.models.vote import MatchVote
from highlight_manager.repositories.audit_repository import AuditRepository
from highlight_manager.repositories.config_repository import ConfigRepository
from highlight_manager.repositories.match_repository import MatchRepository
from highlight_manager.repositories.profile_repository import ProfileRepository
from highlight_manager.repositories.season_repository import SeasonRepository
from highlight_manager.repositories.vote_repository import VoteRepository
from highlight_manager.services.audit_service import AuditService
from highlight_manager.services.bootstrap_service import BootstrapService
from highlight_manager.services.config_service import ConfigService
from highlight_manager.services.match_service import MatchService
from highlight_manager.services.profile_service import ProfileService
from highlight_manager.services.rank_service import RankService
from highlight_manager.services.result_channel_service import ResultChannelService
from highlight_manager.services.season_service import SeasonService
from highlight_manager.services.setup_service import SetupService
from highlight_manager.services.voice_service import VoiceService
from highlight_manager.services.vote_service import VoteService
from highlight_manager.utils.exceptions import HighlightError


async def dynamic_prefix(bot: "HighlightBot", message: discord.Message) -> list[str]:
    if message.guild is None or bot.config_service is None:
        return [bot.settings.default_prefix]
    config = await bot.config_service.get_or_create(message.guild.id)
    return [config.prefix]


class HighlightBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = True
        intents.message_content = True
        intents.voice_states = True
        super().__init__(command_prefix=dynamic_prefix, intents=intents, help_command=None)
        self.settings = get_settings()
        self.logger = get_logger(__name__)
        self.mongo_client: AsyncMongoClient | None = None
        self.db: Any = None
        self.config_service: ConfigService | None = None
        self.profile_service: ProfileService | None = None
        self.season_service: SeasonService | None = None
        self.match_service: MatchService | None = None
        self.vote_service: VoteService | None = None
        self.audit_service: AuditService | None = None
        self.rank_service: RankService | None = None
        self.voice_service: VoiceService | None = None
        self.result_channel_service: ResultChannelService | None = None
        self.bootstrap_service: BootstrapService | None = None
        self.setup_service: SetupService | None = None

    async def setup_hook(self) -> None:
        self.logger.info("startup_initializing")
        self.mongo_client = AsyncMongoClient(self.settings.mongodb_uri)
        await self.mongo_client.admin.command("ping")
        self.db = self.mongo_client.get_database(self.settings.mongodb_database)
        config_repository = ConfigRepository(self.db.guild_configs, GuildConfig)
        profile_repository = ProfileRepository(self.db.player_profiles, PlayerProfile)
        match_repository = MatchRepository(self.db.matches, MatchRecord)
        vote_repository = VoteRepository(self.db.match_votes, MatchVote)
        season_repository = SeasonRepository(self.db.seasons, SeasonRecord)
        audit_repository = AuditRepository(self.db.audit_logs, AuditLogRecord)

        await asyncio.gather(
            config_repository.ensure_indexes(),
            profile_repository.ensure_indexes(),
            match_repository.ensure_indexes(),
            vote_repository.ensure_indexes(),
            season_repository.ensure_indexes(),
            audit_repository.ensure_indexes(),
        )

        self.rank_service = RankService()
        self.config_service = ConfigService(config_repository, self.settings)
        self.profile_service = ProfileService(profile_repository, self.rank_service)
        self.season_service = SeasonService(season_repository, self.profile_service, self.config_service)
        self.vote_service = VoteService(vote_repository)
        self.voice_service = VoiceService()
        self.result_channel_service = ResultChannelService()
        self.bootstrap_service = BootstrapService(self.profile_service)
        self.setup_service = SetupService(self.config_service, self.bootstrap_service)
        self.audit_service = AuditService(audit_repository, self.config_service)
        self.match_service = MatchService(
            self,
            match_repository,
            self.config_service,
            self.profile_service,
            self.season_service,
            self.vote_service,
            self.voice_service,
            self.result_channel_service,
            self.audit_service,
        )

        await prefix_gameplay.setup(self)
        register_admin_commands(self)
        if self.settings.discord_guild_id:
            target = discord.Object(id=self.settings.discord_guild_id)
            self.tree.copy_global_to(guild=target)
            await self.tree.sync(guild=target)
        else:
            await self.tree.sync()
        await self.match_service.reconcile_active_matches()
        await self.match_service.process_due_events()
        await self.match_service.cleanup_stale_resources()
        self.scheduler.change_interval(seconds=self.settings.poll_interval_seconds)
        self.scheduler.start()
        self.logger.info("bot_setup_complete", database=self.settings.mongodb_database)

    async def on_ready(self) -> None:
        self.logger.info("bot_ready", user=str(self.user), guilds=len(self.guilds))

    async def on_member_join(self, member: discord.Member) -> None:
        if member.bot or self.config_service is None or self.profile_service is None:
            return
        config = await self.config_service.get_or_create(member.guild.id)
        await self.profile_service.ensure_member_profile(member, config)

    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if member.bot or self.config_service is None or self.match_service is None:
            return
        config = await self.config_service.get(member.guild.id)
        if not config or not config.waiting_voice_channel_id:
            return
        before_id = before.channel.id if before.channel else None
        after_id = after.channel.id if after.channel else None
        if before_id == config.waiting_voice_channel_id and after_id != config.waiting_voice_channel_id:
            await self.match_service.handle_waiting_voice_departure(member)

    async def on_command_error(self, context: commands.Context, exception: commands.CommandError) -> None:
        original = getattr(exception, "original", exception)
        if isinstance(original, HighlightError):
            await context.reply(str(original))
            return
        self.logger.exception("prefix_command_error", command=context.command.qualified_name if context.command else None, error=str(original))
        await context.reply("Something went wrong while processing that command.")

    async def on_error(self, event_method: str, *args: Any, **kwargs: Any) -> None:
        self.logger.exception("discord_event_error", event=event_method)

    @tasks.loop(seconds=20)
    async def scheduler(self) -> None:
        if self.match_service is None:
            return
        await self.match_service.process_due_events()

    @scheduler.before_loop
    async def before_scheduler(self) -> None:
        await self.wait_until_ready()


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    bot = HighlightBot()

    @bot.tree.error
    async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        original = getattr(error, "original", error)
        if isinstance(original, HighlightError):
            if interaction.response.is_done():
                await interaction.followup.send(str(original), ephemeral=True)
            else:
                await interaction.response.send_message(str(original), ephemeral=True)
            return
        bot.logger.exception("app_command_error", error=str(original))
        if interaction.response.is_done():
            await interaction.followup.send("Something went wrong while processing that command.", ephemeral=True)
        else:
            await interaction.response.send_message("Something went wrong while processing that command.", ephemeral=True)

    bot.run(settings.discord_token, log_handler=None)


if __name__ == "__main__":
    main()
