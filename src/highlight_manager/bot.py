from __future__ import annotations

import asyncio
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands, tasks
from pymongo import AsyncMongoClient

from highlight_manager.commands.prefix import economy as prefix_economy
from highlight_manager.commands.prefix import gameplay as prefix_gameplay
from highlight_manager.commands.prefix import shop as prefix_shop
from highlight_manager.commands.prefix import tournament as prefix_tournament
from highlight_manager.commands.slash.admin import register_admin_commands
from highlight_manager.commands.slash.coins import register_coins_commands
from highlight_manager.commands.slash.shop import register_shop_commands
from highlight_manager.commands.slash.tournament import register_tournament_commands
from highlight_manager.config.logging import configure_logging, get_logger
from highlight_manager.config.settings import get_settings
from highlight_manager.models.audit_log import AuditLogRecord
from highlight_manager.models.economy import CoinSpendRequest, EconomyConfig
from highlight_manager.models.enums import MatchMode, MatchType, ShopSection
from highlight_manager.models.guild_config import GuildConfig
from highlight_manager.models.match import MatchRecord
from highlight_manager.models.profile import PlayerProfile
from highlight_manager.models.season import SeasonRecord
from highlight_manager.models.shop import ShopConfig, ShopItem
from highlight_manager.models.tournament import TournamentMatchRecord, TournamentRecord, TournamentTeam
from highlight_manager.models.vote import MatchVote
from highlight_manager.repositories.audit_repository import AuditRepository
from highlight_manager.repositories.config_repository import ConfigRepository
from highlight_manager.repositories.economy_repository import CoinSpendRequestRepository, EconomyConfigRepository
from highlight_manager.repositories.match_repository import MatchRepository
from highlight_manager.repositories.profile_repository import ProfileRepository
from highlight_manager.repositories.season_repository import SeasonRepository
from highlight_manager.repositories.shop_repository import ShopConfigRepository, ShopItemRepository
from highlight_manager.repositories.tournament_repository import TournamentMatchRepository, TournamentRepository, TournamentTeamRepository
from highlight_manager.repositories.vote_repository import VoteRepository
from highlight_manager.services.audit_service import AuditService
from highlight_manager.services.bootstrap_service import BootstrapService
from highlight_manager.services.coins_service import CoinsService
from highlight_manager.services.config_service import ConfigService
from highlight_manager.services.match_service import MatchService
from highlight_manager.services.profile_service import ProfileService
from highlight_manager.services.rank_service import RankService
from highlight_manager.services.result_channel_service import ResultChannelService
from highlight_manager.services.season_service import SeasonService
from highlight_manager.services.shop_service import ShopService
from highlight_manager.services.setup_service import SetupService
from highlight_manager.services.tournament_service import TournamentService
from highlight_manager.services.voice_service import VoiceService
from highlight_manager.services.vote_service import VoteService
from highlight_manager.utils.exceptions import HighlightError
from highlight_manager.utils.response_helpers import send_context_response, send_interaction_response


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
        self.shop_service: ShopService | None = None
        self.coins_service: CoinsService | None = None
        self.tournament_service: TournamentService | None = None
        self._play_channel_backfill_complete = False
        self._shop_reconcile_complete = False
        self._rank_reconcile_complete = False

    async def setup_hook(self) -> None:
        self.mongo_client = AsyncMongoClient(self.settings.mongodb_uri)
        self.db = self.mongo_client.get_database("highlight_manager")
        config_repository = ConfigRepository(self.db.guild_configs, GuildConfig)
        profile_repository = ProfileRepository(self.db.player_profiles, PlayerProfile)
        match_repository = MatchRepository(self.db.matches, MatchRecord)
        vote_repository = VoteRepository(self.db.match_votes, MatchVote)
        season_repository = SeasonRepository(self.db.seasons, SeasonRecord)
        audit_repository = AuditRepository(self.db.audit_logs, AuditLogRecord)
        shop_config_repository = ShopConfigRepository(self.db.shop_configs, ShopConfig)
        shop_item_repository = ShopItemRepository(self.db.shop_items, ShopItem)
        economy_config_repository = EconomyConfigRepository(self.db.economy_configs, EconomyConfig)
        coin_request_repository = CoinSpendRequestRepository(self.db.coin_spend_requests, CoinSpendRequest)
        tournament_repository = TournamentRepository(self.db.tournaments, TournamentRecord)
        tournament_team_repository = TournamentTeamRepository(self.db.tournament_teams, TournamentTeam)
        tournament_match_repository = TournamentMatchRepository(self.db.tournament_matches, TournamentMatchRecord)

        await asyncio.gather(
            config_repository.ensure_indexes(),
            profile_repository.ensure_indexes(),
            match_repository.ensure_indexes(),
            vote_repository.ensure_indexes(),
            season_repository.ensure_indexes(),
            audit_repository.ensure_indexes(),
            shop_config_repository.ensure_indexes(),
            shop_item_repository.ensure_indexes(),
            economy_config_repository.ensure_indexes(),
            coin_request_repository.ensure_indexes(),
            tournament_repository.ensure_indexes(),
            tournament_team_repository.ensure_indexes(),
            tournament_match_repository.ensure_indexes(),
        )

        self.rank_service = RankService()
        self.config_service = ConfigService(config_repository, self.settings)
        self.profile_service = ProfileService(profile_repository, self.rank_service)
        self.season_service = SeasonService(season_repository, self.profile_service)
        self.vote_service = VoteService(vote_repository)
        self.voice_service = VoiceService()
        self.result_channel_service = ResultChannelService()
        self.bootstrap_service = BootstrapService(self.profile_service)
        self.setup_service = SetupService(self.config_service, self.bootstrap_service)
        self.audit_service = AuditService(audit_repository, self.config_service)
        self.shop_service = ShopService(shop_config_repository, shop_item_repository, self.config_service)
        self.coins_service = CoinsService(
            self.profile_service,
            self.config_service,
            economy_config_repository,
            coin_request_repository,
        )
        self.tournament_service = TournamentService(
            self,
            tournament_repository,
            tournament_team_repository,
            tournament_match_repository,
            self.config_service,
            self.coins_service,
            self.audit_service,
            self.voice_service,
        )
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
            self.coins_service,
        )

        await prefix_gameplay.setup(self)
        await prefix_shop.setup(self)
        await prefix_economy.setup(self)
        await prefix_tournament.setup(self)
        register_admin_commands(self)
        register_shop_commands(self)
        register_coins_commands(self)
        register_tournament_commands(self)
        if self.settings.discord_guild_id:
            target = discord.Object(id=self.settings.discord_guild_id)
            self.tree.copy_global_to(guild=target)
            await self.tree.sync(guild=target)
        else:
            await self.tree.sync()
        await self.match_service.reconcile_active_matches()
        await self.tournament_service.reconcile_active_tournaments()
        self.scheduler.change_interval(seconds=self.settings.poll_interval_seconds)
        self.scheduler.start()
        from highlight_manager.interactions.shop_views import ShopOrderView

        for section in ShopSection:
            self.add_view(ShopOrderView(section=section))
        self.logger.info("bot_setup_complete")

    async def on_ready(self) -> None:
        if not self._play_channel_backfill_complete and self.config_service is not None:
            for guild in self.guilds:
                await self.config_service.backfill_play_channels(guild)
            self._play_channel_backfill_complete = True
        if not self._shop_reconcile_complete and self.shop_service is not None:
            for guild in self.guilds:
                await self.shop_service.reconcile_configured_sections(guild)
            self._shop_reconcile_complete = True
        if not self._rank_reconcile_complete and self.config_service is not None and self.profile_service is not None:
            for guild in self.guilds:
                config = await self.config_service.get_or_create(guild.id)
                await self.profile_service.sync_all_member_identities(guild, config)
            self._rank_reconcile_complete = True
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

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        if message.guild is not None and self.config_service is not None:
            config = await self.config_service.backfill_play_channels(
                message.guild,
                await self.config_service.get_or_create(message.guild.id),
            )
            if config and self._is_match_channel(message.channel.id, config):
                if not self._is_allowed_match_channel_message(message.content, config, message.channel.id):
                    try:
                        await message.delete()
                    except discord.HTTPException:
                        pass
                    return
        await self.process_commands(message)

    @staticmethod
    def _normalized_command_word(content: str, prefix: str) -> tuple[str | None, list[str]]:
        stripped = content.strip()
        if not stripped.lower().startswith(prefix.lower()):
            return None, []
        command_body = stripped[len(prefix):].strip()
        if not command_body:
            return None, []
        parts = command_body.split()
        return parts[0].lower(), parts[1:]

    @staticmethod
    def _match_type_allowed_in_channel(channel_id: int, config: GuildConfig) -> set[str] | None:
        if channel_id == config.apostado_channel_id:
            return {"apos", "apostado"}
        if channel_id == config.highlight_channel_id:
            return {"high", "highlight"}
        return None

    def _is_allowed_match_channel_message(self, content: str, config: GuildConfig, channel_id: int) -> bool:
        command_word, args = self._normalized_command_word(content, config.prefix)
        if command_word != "play":
            return False
        return True

    @staticmethod
    def _is_match_channel(channel_id: int, config: GuildConfig) -> bool:
        return channel_id in {config.apostado_channel_id, config.highlight_channel_id}

    async def on_command_error(self, context: commands.Context, exception: commands.CommandError) -> None:
        original = getattr(exception, "original", exception)
        if isinstance(original, commands.MissingRequiredArgument):
            if context.command and context.command.qualified_name == "play":
                await send_context_response(
                    context,
                    await self._play_usage_message(
                        context.guild.id if context.guild else None,
                        missing=original.param.name,
                    ),
                    error=True,
                )
                return
            await send_context_response(context, f"Missing required argument: `{original.param.name}`.", error=True)
            return
        if isinstance(original, commands.TooManyArguments):
            if context.command and context.command.qualified_name == "play":
                await send_context_response(
                    context,
                    await self._play_usage_message(context.guild.id if context.guild else None),
                    error=True,
                )
                return
            await send_context_response(context, "Too many arguments were provided.", error=True)
            return
        if isinstance(original, HighlightError):
            await send_context_response(context, str(original), error=True)
            return
        self.logger.exception("prefix_command_error", command=context.command.qualified_name if context.command else None, error=str(original))
        await send_context_response(context, "Something went wrong while processing that command.", error=True)

    async def _get_prefix_for_guild(self, guild_id: int | None) -> str:
        if guild_id is None or self.config_service is None:
            return self.settings.default_prefix
        config = await self.config_service.get_or_create(guild_id)
        return config.prefix

    async def _play_usage_message(self, guild_id: int | None, *, missing: str | None = None) -> str:
        prefix = await self._get_prefix_for_guild(guild_id)
        if missing == "match_type":
            return f"Write match type after the mode. Use `{prefix}play 4v4 apos` or `{prefix}play 4v4 high`."
        if missing == "mode":
            return f"Write match mode first. Use `{prefix}play 1v1 apos`, `{prefix}play 2v2 apos`, `{prefix}play 3v3 high`, or `{prefix}play 4v4 high`."
        return f"Use `{prefix}play <mode> <type>`. Match type must be `apos` or `high`."

    async def on_error(self, event_method: str, *args: Any, **kwargs: Any) -> None:
        self.logger.exception("discord_event_error", event=event_method)

    @tasks.loop(seconds=20)
    async def scheduler(self) -> None:
        if self.match_service is None:
            return
        await self.match_service.process_due_events()
        if self.tournament_service is not None:
            await self.tournament_service.process_due_events()

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
            try:
                await send_interaction_response(interaction, str(original), error=True, ephemeral=True)
            except discord.NotFound:
                pass
            return
        bot.logger.exception("app_command_error", error=str(original))
        try:
            await send_interaction_response(
                interaction,
                "Something went wrong while processing that command.",
                error=True,
                ephemeral=True,
            )
        except discord.NotFound:
            pass

    bot.run(settings.discord_token, log_handler=None)


if __name__ == "__main__":
    main()
