from __future__ import annotations

import asyncio
from io import BytesIO
from functools import wraps
import re
import time
from typing import Optional
from uuid import UUID

import discord
from discord import app_commands
from discord.ext import commands, tasks
from sqlalchemy import inspect, text

import highlight_manager.db.models  # noqa: F401
from highlight_manager.app.config import get_settings
from highlight_manager.app.logging import configure_logging, get_logger
from highlight_manager.app.runtime import Runtime
from highlight_manager.db.base import Base
from highlight_manager.modules.common.cache import SimpleTTLCache
from highlight_manager.legacy_runtime import get_legacy_runtime_summary
from highlight_manager.modules.common.enums import (
    AuditAction,
    AuditEntityType,
    MatchMode,
    MatchResultPhase,
    MatchState,
    ModerationActionType,
    QueueState,
    RulesetKey,
    ShopSection,
    WalletTransactionType,
)
from highlight_manager.modules.common.exceptions import HighlightManagerError, NotFoundError, ValidationError
from highlight_manager.modules.matches.ui import build_public_match_embed, build_queue_embed, build_result_match_embed
from highlight_manager.modules.matches.states import MATCH_RESULT_OPEN_STATES, QUEUE_JOINABLE_STATES, QUEUE_MUTABLE_STATES
from highlight_manager.modules.ranks.calculator import resolve_tier, tier_emoji
from highlight_manager.modules.shop.ui import (
    STOREFRONT_FOOTER_PREFIX,
    build_shop_embed,
    build_storefront_section_embed,
    build_storefront_ticket_embed,
)
from highlight_manager.modules.tournaments.ui import build_tournament_embed
from highlight_manager.tasks.cleanup import CleanupWorker
from highlight_manager.tasks.decay import DecayWorker
from highlight_manager.tasks.recovery import RecoveryCoordinator
from highlight_manager.tasks.scheduler import SchedulerWorker
from highlight_manager.ui.cards import (
    LeaderboardCardEntry,
    ProfileCardData,
    render_help_banner,
    render_leaderboard_card,
    render_profile_card,
    warm_card_assets,
)
from highlight_manager.ui.embeds import build_notice_embed, build_promotion_embed, build_reward_embed
from highlight_manager.ui.renderers import build_leaderboard_embed, build_profile_embed
from highlight_manager.ui import theme


MENTION_ID_PATTERN = re.compile(r"\d+")
RANK_NICKNAME_PATTERN = re.compile(r"^\s*RANK\s+\d+\s*(?:\|\s*|[-:]\s*|\s+)?", re.IGNORECASE)
PLAY_HIDDEN_SPACE_PATTERN = re.compile(r"[\u00A0\u2000-\u200D\u2060\uFEFF]")
PLAY_ARGUMENT_GAP_PATTERN = re.compile(r"\s+")
DEFAULT_STOREFRONT_CHANNELS: dict[ShopSection, int] = {
    ShopSection.DEVELOPE: 1486113305033707592,
    ShopSection.OPTIMIZE_TOOL: 1486112868356067402,
    ShopSection.VIDEO_EDIT: 1486112519889358980,
    ShopSection.SENSI_PC: 1486112441975832617,
    ShopSection.SENSI_IPHONE: 1486112372178423910,
    ShopSection.SENSI_ANDROID: 1486112240854892624,
}
SHOP_SECTION_DETAIL_PROMPTS: dict[ShopSection, tuple[str, str]] = {
    ShopSection.DEVELOPE: (
        "Project Requirements",
        "Tell us what bot, source code, or website you want.",
    ),
    ShopSection.OPTIMIZE_TOOL: (
        "PC / Tool Notes",
        "Tell us the optimization or tool setup you need.",
    ),
    ShopSection.VIDEO_EDIT: (
        "Video / Edit Notes",
        "Tell us the video type, style, and edit details you want.",
    ),
    ShopSection.SENSI_PC: (
        "PC Sensitivity Notes",
        "Tell us your DPI, emulator version, and current setup.",
    ),
    ShopSection.SENSI_IPHONE: (
        "iPhone Sensitivity Notes",
        "Tell us your iPhone model and the sensitivity style you want.",
    ),
    ShopSection.SENSI_ANDROID: (
        "Android Sensitivity Notes",
        "Tell us your Android device and the sensitivity style you want.",
    ),
}


def normalize_play_arguments(raw: str | None) -> str:
    if raw is None:
        return ""
    normalized = PLAY_HIDDEN_SPACE_PATTERN.sub(" ", raw)
    return PLAY_ARGUMENT_GAP_PATTERN.sub(" ", normalized).strip()


def parse_ranked_queue_request(raw: str) -> tuple[MatchMode, RulesetKey]:
    normalized = normalize_play_arguments(raw)
    if not normalized:
        raise ValidationError("Use `!play <mode> <ruleset>` or `!play <ruleset> <mode>`.")
    tokens = normalized.split(" ")
    if len(tokens) != 2:
        raise ValidationError("Use `!play <mode> <ruleset>` or `!play <ruleset> <mode>`.")

    parsed_modes: list[MatchMode] = []
    parsed_rulesets: list[RulesetKey] = []
    mode_errors = 0
    ruleset_errors = 0
    for token in tokens:
        try:
            parsed_modes.append(MatchMode.from_input(token))
        except ValidationError:
            mode_errors += 1
        try:
            parsed_rulesets.append(RulesetKey.from_input(token))
        except ValidationError:
            ruleset_errors += 1

    if len(parsed_modes) == 1 and len(parsed_rulesets) == 1:
        return parsed_modes[0], parsed_rulesets[0]
    if len(parsed_modes) == 0:
        raise ValidationError("Mode must be one of: 1v1, 2v2, 3v3, 4v4, 6v6.")
    if len(parsed_rulesets) == 0:
        raise ValidationError("Ruleset must be one of: apos, apostado, high, highlight, es, esport.")
    raise ValidationError("Use exactly one mode and one ruleset, for example `!play 2v2 apos`.")


def parse_optional_player_reference(raw: str | None) -> int | None:
    if not raw:
        return None
    match = MENTION_ID_PATTERN.search(raw)
    if match is None:
        raise ValidationError("Enter a valid player mention or numeric ID.")
    return int(match.group(0))


def parse_discord_id_list(raw: str | None) -> list[int]:
    if not raw:
        return []
    seen: set[int] = set()
    ordered_ids: list[int] = []
    for match in MENTION_ID_PATTERN.findall(raw):
        value = int(match)
        if value in seen:
            continue
        seen.add(value)
        ordered_ids.append(value)
    return ordered_ids


def parse_channel_config_input(raw: str) -> list[int]:
    normalized = raw.strip().lower()
    if normalized in {"clear", "none", "disable"}:
        return []
    channel_ids = parse_discord_id_list(raw)
    if not channel_ids:
        raise ValidationError("Enter one or more channel mentions or numeric IDs, or use `clear`.")
    return channel_ids


def serialize_discord_id_list(ids: list[int]) -> str | None:
    if not ids:
        return None
    return ",".join(str(value) for value in ids)


def format_channel_mentions(channel_ids: list[int]) -> str:
    if not channel_ids:
        return "Not configured"
    return ", ".join(f"<#{channel_id}>" for channel_id in channel_ids)


def timed_prefix_command(command_name: str):
    def decorator(func):
        @wraps(func)
        async def wrapper(self, ctx: commands.Context, *args, **kwargs):
            started_at = time.monotonic()
            success = False
            error_name: str | None = None
            try:
                result = await func(self, ctx, *args, **kwargs)
                success = True
                return result
            except Exception as exc:
                error_name = type(exc).__name__
                raise
            finally:
                self.bot.log_prefix_command_timing(
                    command_name,
                    ctx,
                    started_at=started_at,
                    success=success,
                    error=error_name,
                )

        return wrapper

    return decorator


async def dynamic_prefix(bot: "HighlightBot", message: discord.Message) -> list[str]:
    if message.guild is None:
        return [bot.settings.default_prefix]
    cached_prefix = bot.prefix_cache.get(str(message.guild.id))
    if isinstance(cached_prefix, str):
        return [cached_prefix]
    try:
        async with bot.runtime.session() as repos:
            bundle = await bot.runtime.services.guilds.get_bundle(repos.guilds, message.guild.id)
            if bundle is None:
                return [bot.settings.default_prefix]
            bot.prefix_cache.set(str(message.guild.id), bundle.settings.prefix)
            return [bundle.settings.prefix]
    except Exception as exc:
        bot.logger.warning("prefix_lookup_failed", guild_id=message.guild.id, error=str(exc))
        return [bot.settings.default_prefix]


class RoomInfoModal(discord.ui.Modal, title="Submit Match Room"):
    room_code = discord.ui.TextInput(label="Room ID", placeholder="Required", max_length=128)
    room_password = discord.ui.TextInput(label="Password", placeholder="Required", max_length=128)
    room_notes = discord.ui.TextInput(label="Key (Optional)", required=False, max_length=128)

    def __init__(self, bot: "HighlightBot", queue_id: UUID) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.queue_id = queue_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.bot.handle_room_info_submission(
            interaction,
            self.queue_id,
            room_code=self.room_code.value,
            room_password=self.room_password.value or None,
            room_notes=self.room_notes.value or None,
        )


class ResultVoteModal(discord.ui.Modal):
    winner_team = discord.ui.TextInput(label="Winner Team (1 or 2)", max_length=1)
    winner_mvp = discord.ui.TextInput(label="Winner MVP Mention/ID", required=False, max_length=64)
    loser_mvp = discord.ui.TextInput(label="Loser MVP Mention/ID", required=False, max_length=64)

    def __init__(self, bot: "HighlightBot", match_id: UUID, *, force: bool, title: str) -> None:
        super().__init__(title=title, timeout=None)
        self.bot = bot
        self.match_id = match_id
        self.force = force

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            winner_team = int(self.winner_team.value)
        except ValueError:
            await interaction.response.send_message(
                embed=self.bot.build_notice_embed("Vote failed", "Winner Team must be 1 or 2.", error=True),
                ephemeral=True,
            )
            return
        try:
            winner_mvp = parse_optional_player_reference(self.winner_mvp.value or None)
            loser_mvp = parse_optional_player_reference(self.loser_mvp.value or None)
        except HighlightManagerError as exc:
            await interaction.response.send_message(
                embed=self.bot.build_notice_embed("Vote failed", str(exc), error=True),
                ephemeral=True,
            )
            return
        if self.force:
            await self.bot.handle_force_result(interaction, self.match_id, winner_team, winner_mvp, loser_mvp)
        else:
            await self.bot.handle_vote_submission(interaction, self.match_id, winner_team, winner_mvp, loser_mvp)


class MatchRoomUpdateModal(discord.ui.Modal, title="Update Match Room"):
    room_code = discord.ui.TextInput(label="Room ID", placeholder="Required", max_length=128)
    room_password = discord.ui.TextInput(label="Password", placeholder="Required", max_length=128)
    room_notes = discord.ui.TextInput(label="Key (Optional)", required=False, max_length=128)

    def __init__(self, bot: "HighlightBot", match_id: UUID) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.match_id = match_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.bot.handle_match_room_update(
            interaction,
            self.match_id,
            room_code=self.room_code.value,
            room_password=self.room_password.value or None,
            room_notes=self.room_notes.value or None,
        )


class ForceCloseModal(discord.ui.Modal, title="Admin Cancel Match"):
    reason = discord.ui.TextInput(label="Reason", style=discord.TextStyle.paragraph, max_length=500)

    def __init__(self, bot: "HighlightBot", match_id: UUID) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.match_id = match_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.bot.handle_force_close(interaction, self.match_id, self.reason.value)


class QueueActionView(discord.ui.View):
    def __init__(self, bot: "HighlightBot", queue_id: UUID, *, snapshot=None) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.queue_id = queue_id
        custom_ids = [
            f"queue:{queue_id}:join:1",
            f"queue:{queue_id}:join:2",
            f"queue:{queue_id}:ready",
            f"queue:{queue_id}:leave",
            f"queue:{queue_id}:room-info",
            f"queue:{queue_id}:admin-cancel",
        ]
        for item, custom_id in zip(self.children, custom_ids, strict=False):
            item.custom_id = custom_id
        if snapshot is not None:
            self.apply_snapshot(snapshot)

    def apply_snapshot(self, snapshot) -> None:
        queue = snapshot.queue
        queue_joinable = queue.state in QUEUE_JOINABLE_STATES
        queue_mutable = queue.state in QUEUE_MUTABLE_STATES
        t1_full = len(snapshot.team1_ids) >= queue.team_size
        t2_full = len(snapshot.team2_ids) >= queue.team_size
        self.join_team_1.disabled = not queue_joinable or t1_full
        self.join_team_1.label = "🔒 Team 1 FULL" if t1_full else "⚔️ Join Team 1"
        self.join_team_2.disabled = not queue_joinable or t2_full
        self.join_team_2.label = "🔒 Team 2 FULL" if t2_full else "🛡️ Join Team 2"
        self.mark_ready.disabled = queue.state != QueueState.READY_CHECK
        self.leave_queue.disabled = not queue_mutable
        self.enter_room_info.disabled = queue.state != QueueState.FULL_PENDING_ROOM_INFO
        self.admin_cancel.disabled = not queue_mutable

    @discord.ui.button(label="⚔️ Join Team 1", style=discord.ButtonStyle.danger)
    async def join_team_1(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.bot.handle_queue_join(interaction, self.queue_id, 1)

    @discord.ui.button(label="🛡️ Join Team 2", style=discord.ButtonStyle.success)
    async def join_team_2(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.bot.handle_queue_join(interaction, self.queue_id, 2)

    @discord.ui.button(label="✅ Ready", style=discord.ButtonStyle.success)
    async def mark_ready(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.bot.handle_queue_ready(interaction, self.queue_id)

    @discord.ui.button(label="🚪 Leave Queue", style=discord.ButtonStyle.secondary)
    async def leave_queue(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.bot.handle_queue_leave(interaction, self.queue_id)

    @discord.ui.button(label="🔑 Enter Room Info", style=discord.ButtonStyle.primary)
    async def enter_room_info(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(RoomInfoModal(self.bot, self.queue_id))

    @discord.ui.button(label="❌ Admin Cancel", style=discord.ButtonStyle.danger)
    async def admin_cancel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.bot.handle_queue_admin_cancel(interaction, self.queue_id)


class MatchActionView(discord.ui.View):
    def __init__(self, bot: "HighlightBot", match_id: UUID, *, snapshot=None) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.match_id = match_id
        custom_ids = [
            f"match:{match_id}:vote-result",
            f"match:{match_id}:update-room-info",
            f"match:{match_id}:creator-cancel",
            f"match:{match_id}:admin-cancel",
            f"match:{match_id}:admin-force-result",
        ]
        for item, custom_id in zip(self.children, custom_ids, strict=False):
            item.custom_id = custom_id
        if snapshot is not None:
            self.apply_snapshot(snapshot)

    def apply_snapshot(self, snapshot) -> None:
        state = snapshot.match.state
        result_phase = getattr(snapshot.match, "result_phase", MatchResultPhase.CAPTAIN)
        rehost_allowed = getattr(snapshot, "rehost_allowed", not bool(getattr(snapshot, "votes", [])))
        creator_cancel_allowed = getattr(snapshot, "creator_cancel_allowed", not bool(getattr(snapshot, "votes", [])))
        voting_open = state in {MatchState.LIVE, MatchState.RESULT_PENDING} and result_phase != MatchResultPhase.STAFF_REVIEW
        self.vote_result.disabled = not voting_open
        self.update_room_info.disabled = (not voting_open) or (not rehost_allowed)
        self.creator_cancel.disabled = (not voting_open) or (not creator_cancel_allowed)
        self.admin_cancel.disabled = state in {MatchState.CONFIRMED, MatchState.CANCELLED, MatchState.FORCE_CLOSED}
        self.admin_force_result.disabled = state not in MATCH_RESULT_OPEN_STATES

    @discord.ui.button(label="🗳️ Vote Result", style=discord.ButtonStyle.primary)
    async def vote_result(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(
            ResultVoteModal(self.bot, self.match_id, force=False, title="Vote Match Result")
        )

    @discord.ui.button(label="🔑 Update Room Info", style=discord.ButtonStyle.secondary)
    async def update_room_info(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(MatchRoomUpdateModal(self.bot, self.match_id))

    @discord.ui.button(label="🚪 Creator Cancel", style=discord.ButtonStyle.secondary)
    async def creator_cancel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.bot.handle_creator_cancel(interaction, self.match_id)

    @discord.ui.button(label="❌ Admin Cancel", style=discord.ButtonStyle.danger)
    async def admin_cancel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(ForceCloseModal(self.bot, self.match_id))

    @discord.ui.button(label="⚡ Admin Force Result", style=discord.ButtonStyle.success)
    async def admin_force_result(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(
            ResultVoteModal(self.bot, self.match_id, force=True, title="Admin Force Result")
        )


class StorefrontOrderModal(discord.ui.Modal):
    def __init__(self, bot: "HighlightBot", section: ShopSection) -> None:
        super().__init__(title=f"{section.label} Purchase", timeout=None)
        self.bot = bot
        self.section = section
        self.requested_item = discord.ui.TextInput(
            label="What do you want to buy?",
            placeholder=f"{section.label} product or custom request",
            max_length=150,
        )
        detail_label, detail_placeholder = SHOP_SECTION_DETAIL_PROMPTS[section]
        self.details = discord.ui.TextInput(
            label=detail_label,
            placeholder=detail_placeholder,
            style=discord.TextStyle.paragraph,
            max_length=500,
        )
        self.add_item(self.requested_item)
        self.add_item(self.details)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.bot.handle_storefront_purchase(
            interaction,
            self.section,
            requested_item=str(self.requested_item),
            details=str(self.details),
        )


class StorefrontOrderView(discord.ui.View):
    def __init__(self, bot: "HighlightBot", section: ShopSection) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.section = section
        self.buy_now.custom_id = f"storefront:{section.value}:buy"

    @discord.ui.button(label="Buy Now", style=discord.ButtonStyle.success, emoji="🛒")
    async def buy_now(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(StorefrontOrderModal(self.bot, self.section))


class PlayerCommands(commands.Cog):
    def __init__(self, bot: "HighlightBot") -> None:
        self.bot = bot

    @commands.command(name="help")
    @timed_prefix_command("help")
    async def help(self, ctx: commands.Context) -> None:
        if ctx.guild is None:
            return
        embed, file = await self.bot.build_help_response(ctx.clean_prefix)
        if file is None:
            await ctx.reply(embed=embed)
        else:
            await ctx.reply(embed=embed, file=file)

    @commands.command(name="latestupdate", aliases=["latest", "patchnotes", "updates"])
    @timed_prefix_command("latestupdate")
    async def latest_update(self, ctx: commands.Context) -> None:
        if ctx.guild is None:
            return
        await ctx.reply(embed=self.bot.build_latest_update_embed(ctx.clean_prefix))

    @commands.command(name="play")
    @timed_prefix_command("play")
    async def play(self, ctx: commands.Context, *, queue_request: str = "") -> None:
        if ctx.guild is None or ctx.author.bot:
            return
        assert isinstance(ctx.author, discord.Member)
        # If no arguments, show a visual picker instead of an error
        if not queue_request.strip():
            await ctx.reply(
                embed=self.bot.build_play_picker_embed(ctx.clean_prefix),
                view=self.bot.build_play_picker_view(),
            )
            return
        try:
            mode, ruleset = parse_ranked_queue_request(queue_request)
            snapshot = await self.bot.create_ranked_queue(
                ctx.guild,
                ctx.author,
                mode,
                ruleset,
                ctx.channel.id if ctx.channel else None,
            )
        except HighlightManagerError as exc:
            await ctx.reply(embed=self.bot.build_notice_embed("Queue creation failed", str(exc), error=True))
            return
        message = await ctx.reply(
            embed=build_queue_embed(snapshot),
            view=self.bot.build_queue_view(snapshot.queue.id, snapshot=snapshot),
        )
        async with self.bot.runtime.session() as repos:
            await repos.matches.set_queue_public_message_id(snapshot.queue.id, message.id)

    @commands.command(name="profile")
    @timed_prefix_command("profile")
    async def profile(self, ctx: commands.Context) -> None:
        if ctx.guild is None or ctx.author.bot:
            return
        assert isinstance(ctx.author, discord.Member)
        embed, file = await self.bot.build_profile_command_response(ctx.guild, ctx.author)
        if file is None:
            await ctx.reply(embed=embed)
        else:
            await ctx.reply(embed=embed, file=file)

    @commands.command(name="rank")
    @timed_prefix_command("rank")
    async def rank(self, ctx: commands.Context) -> None:
        if ctx.guild is None or ctx.author.bot:
            return
        assert isinstance(ctx.author, discord.Member)
        embed, file = await self.bot.build_profile_command_response(ctx.guild, ctx.author)
        if file is None:
            await ctx.reply(embed=embed)
        else:
            await ctx.reply(embed=embed, file=file)

    @commands.command(name="leaderboard")
    @timed_prefix_command("leaderboard")
    async def leaderboard(self, ctx: commands.Context) -> None:
        if ctx.guild is None:
            return
        embed, file = await self.bot.build_leaderboard_command_response(ctx.guild)
        if file is None:
            await ctx.reply(embed=embed)
        else:
            await ctx.reply(embed=embed, file=file)

    @commands.command(name="coins")
    @timed_prefix_command("coins")
    async def coins(self, ctx: commands.Context) -> None:
        if ctx.guild is None or ctx.author.bot:
            return
        assert isinstance(ctx.author, discord.Member)
        embed = await self.bot.build_coins_embed(ctx.guild, ctx.author)
        await ctx.reply(embed=embed)

    @commands.command(name="shop")
    @timed_prefix_command("shop")
    async def shop(self, ctx: commands.Context) -> None:
        if ctx.guild is None:
            return
        embed = await self.bot.build_shop_command_embed(ctx.guild)
        await ctx.reply(embed=embed)

    @commands.command(name="tournament")
    @timed_prefix_command("tournament")
    async def tournament(self, ctx: commands.Context) -> None:
        if ctx.guild is None:
            return
        async with self.bot.runtime.session() as repos:
            bundle = await self.bot.runtime.services.guilds.ensure_guild(repos.guilds, ctx.guild.id, ctx.guild.name)
            tournament = await repos.tournaments.get_latest_active(bundle.guild.id)
            if tournament is None:
                await ctx.reply(embed=self.bot.build_notice_embed("Tournament", "No active tournament right now."))
                return
            teams = await repos.tournaments.list_teams(tournament.id)
            matches = await repos.tournaments.list_matches(tournament.id)
        await ctx.reply(embed=build_tournament_embed(tournament, teams, matches))


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
        self.runtime = Runtime(self.settings)
        self.recovery = RecoveryCoordinator()
        self.cleanup_worker = CleanupWorker()
        self.scheduler_worker = SchedulerWorker()
        self.prefix_cache = SimpleTTLCache(maxsize=256, ttl=300)
        self.avatar_cache = SimpleTTLCache(maxsize=1024, ttl=1800)
        self.help_banner_cache = SimpleTTLCache(maxsize=32, ttl=3600)
        self.profile_card_cache = SimpleTTLCache(maxsize=256, ttl=300)
        self.leaderboard_card_cache = SimpleTTLCache(maxsize=64, ttl=180)
        self._guild_commands_synced = False
        self.command_sync_status: dict[str, object] = {
            "scope": "pending",
            "success": False,
            "count": 0,
            "last_error": None,
        }
        legacy_summary = get_legacy_runtime_summary()
        self.startup_health: dict[str, object] = {
            "db_ready": False,
            "views_restored": 0,
            "assets_warmed": False,
            "guild_cache_warmed": False,
            "canonical_runtime": legacy_summary["canonical_entrypoint"],
            "legacy_import_count": legacy_summary["legacy_import_count"],
        }

    def app_command_target_guild(self) -> discord.Object | None:
        if not self.settings.discord_guild_id:
            return None
        return discord.Object(id=self.settings.discord_guild_id)

    def build_notice_embed(self, title: str, description: str, *, error: bool = False) -> discord.Embed:
        return build_notice_embed(title, description, error=error)

    def refresh_runtime_health(self) -> dict[str, object]:
        legacy_summary = get_legacy_runtime_summary()
        self.startup_health["canonical_runtime"] = legacy_summary["canonical_entrypoint"]
        self.startup_health["legacy_import_count"] = legacy_summary["legacy_import_count"]
        self.startup_health["legacy_packages"] = legacy_summary["legacy_packages"]
        return legacy_summary

    def log_duration(self, event: str, started_at: float, **fields) -> None:
        self.logger.info(
            event,
            duration_ms=round((time.monotonic() - started_at) * 1000, 2),
            **fields,
        )

    def log_prefix_command_timing(
        self,
        command_name: str,
        ctx: commands.Context,
        *,
        started_at: float,
        success: bool,
        error: str | None = None,
    ) -> None:
        payload = {
            "command": command_name,
            "command_duration_ms": round((time.monotonic() - started_at) * 1000, 2),
            "guild_id": ctx.guild.id if ctx.guild else None,
            "channel_id": ctx.channel.id if ctx.channel else None,
            "user_id": ctx.author.id if ctx.author else None,
            "success": success,
        }
        if error is not None:
            payload["error"] = error
        self.logger.info("prefix_command_completed", **payload)

    async def acknowledge_interaction(
        self,
        interaction: discord.Interaction,
        *,
        operation: str,
        started_at: float,
        update_message: bool = False,
        ephemeral: bool = True,
    ) -> None:
        if interaction.response.is_done():
            return
        if update_message:
            await interaction.response.defer()
        else:
            await interaction.response.defer(ephemeral=ephemeral, thinking=True)
        self.logger.info(
            "interaction_acknowledged",
            operation=operation,
            ack_duration_ms=round((time.monotonic() - started_at) * 1000, 2),
            guild_id=interaction.guild.id if interaction.guild else None,
            channel_id=interaction.channel_id,
            user_id=interaction.user.id if interaction.user else None,
        )

    async def send_interaction_notice(
        self,
        interaction: discord.Interaction,
        title: str,
        description: str,
        *,
        error: bool = False,
        ephemeral: bool = True,
    ) -> None:
        embed = self.build_notice_embed(title, description, error=error)
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=ephemeral)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=ephemeral)

    async def edit_interaction_message(
        self,
        interaction: discord.Interaction,
        *,
        embed: discord.Embed,
        view: discord.ui.View | None = None,
    ) -> None:
        if interaction.response.is_done():
            await interaction.edit_original_response(embed=embed, view=view)
        else:
            await interaction.response.edit_message(embed=embed, view=view)

    async def edit_or_followup_notice(
        self,
        interaction: discord.Interaction,
        title: str,
        description: str,
        *,
        error: bool = False,
        ephemeral: bool = True,
    ) -> None:
        embed = self.build_notice_embed(title, description, error=error)
        if interaction.response.is_done():
            await interaction.edit_original_response(embed=embed)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=ephemeral)

    async def render_help_banner_bytes(self, prefix: str) -> bytes:
        cached = self.help_banner_cache.get(prefix)
        if isinstance(cached, bytes):
            return cached
        banner_bytes = await asyncio.to_thread(lambda: render_help_banner(prefix).getvalue())
        self.help_banner_cache.set(prefix, banner_bytes)
        return banner_bytes

    async def warm_runtime_assets(self) -> None:
        started_at = time.monotonic()
        await asyncio.to_thread(warm_card_assets, self.settings.default_prefix)
        default_banner = await self.render_help_banner_bytes(self.settings.default_prefix)
        self.help_banner_cache.set(self.settings.default_prefix, default_banner)
        self.startup_health["assets_warmed"] = True
        self.log_duration("ui_assets_warmed", started_at, prefix=self.settings.default_prefix)

    async def warm_connected_guild_caches(self) -> None:
        if self.startup_health["guild_cache_warmed"]:
            return
        started_at = time.monotonic()
        warmed_guilds = 0
        async with self.runtime.session() as repos:
            for guild in self.guilds:
                bundle = await self.ensure_guild_bundle(repos, guild)
                await self.runtime.services.seasons.ensure_active(repos.seasons, bundle.guild.id, bundle.settings)
                await self.render_help_banner_bytes(bundle.settings.prefix)
                warmed_guilds += 1
        self.startup_health["guild_cache_warmed"] = True
        self.log_duration("guild_runtime_caches_warmed", started_at, guilds=warmed_guilds)

    def build_help_embed(self, prefix: str) -> discord.Embed:
        embed = discord.Embed(
            title="Highlight Manger Help",
            description="Member prefix commands for ranked play, profiles, coins, shop, and tournaments.",
            colour=discord.Colour.from_rgb(95, 112, 255),
        )
        embed.add_field(
            name="Competitive Commands",
            value=(
                f"`{prefix}help` Show this menu\n"
                f"`{prefix}latestupdate` Show the current V2 update notes\n"
                f"`{prefix}play <mode> <ruleset>` Open a ranked queue\n"
                f"`{prefix}profile` View your profile\n"
                f"`{prefix}rank` View your rank card\n"
                f"`{prefix}leaderboard` Show the leaderboard"
            ),
            inline=False,
        )
        embed.add_field(
            name="Queue Modes",
            value=(
                "`apostado`: 1v1, 2v2, 3v3, 4v4\n"
                "`highlight`: 1v1, 2v2, 3v3, 4v4\n"
                "`esport`: 4v4, 6v6"
            ),
            inline=False,
        )
        embed.add_field(
            name="Economy And Events",
            value=(
                f"`{prefix}coins` View your coin balance\n"
                f"`{prefix}shop` View the cosmetic shop\n"
                f"`{prefix}tournament` View the latest tournament"
            ),
            inline=False,
        )
        embed.add_field(
            name="Quick Example",
            value=f"`{prefix}play 4v4 esport`",
            inline=False,
        )
        embed.set_footer(text=f"Prefix in this server: {prefix}")
        return embed

    async def build_help_response(self, prefix: str) -> tuple[discord.Embed, discord.File | None]:
        embed = self.build_help_embed(prefix)
        started_at = time.monotonic()
        try:
            banner_bytes = await asyncio.wait_for(self.render_help_banner_bytes(prefix), timeout=1.5)
            file = discord.File(BytesIO(banner_bytes), filename="help-banner.png")
            embed.set_image(url="attachment://help-banner.png")
            self.log_duration("render_completed", started_at, surface="help_banner", success=True, prefix=prefix)
            return embed, file
        except Exception as exc:
            self.logger.warning("help_banner_render_failed", error=str(exc))
            self.log_duration("render_completed", started_at, surface="help_banner", success=False, prefix=prefix, error=type(exc).__name__)
            return embed, None

    def build_play_picker_embed(self, prefix: str) -> discord.Embed:
        embed = discord.Embed(
            title=f"{theme.EMOJI_SWORD} Play Ranked",
            description=(
                f"Use the buttons below to quickly start a queue, or type it manually:\n"
                f"`{prefix}play <mode> <ruleset>`\n\n"
                f"**Modes:** `1v1`, `2v2`, `3v3`, `4v4`, `6v6`\n"
                f"**Rulesets:** `apostado`, `highlight`, `esport`"
            ),
            colour=theme.PRIMARY,
        )
        embed.set_footer(text="Highlight Manger  •  Quick Play")
        return embed

    def build_play_picker_view(self) -> discord.ui.View:
        class PlayPickerView(discord.ui.View):
            def __init__(self, bot: "HighlightBot"):
                super().__init__(timeout=180)
                self.bot = bot

            @discord.ui.button(label="💰 4v4 Apostado", style=discord.ButtonStyle.primary)
            async def ap_4v4(self, interaction: discord.Interaction, button: discord.ui.Button):
                await self._create(interaction, MatchMode.FOUR_V_FOUR, RulesetKey.APOSTADO)

            @discord.ui.button(label="🔦 4v4 Highlight", style=discord.ButtonStyle.secondary)
            async def hl_4v4(self, interaction: discord.Interaction, button: discord.ui.Button):
                await self._create(interaction, MatchMode.FOUR_V_FOUR, RulesetKey.HIGHLIGHT)

            @discord.ui.button(label="🏆 4v4 Esport", style=discord.ButtonStyle.success)
            async def es_4v4(self, interaction: discord.Interaction, button: discord.ui.Button):
                await self._create(interaction, MatchMode.FOUR_V_FOUR, RulesetKey.ESPORT)

            async def _create(self, interaction: discord.Interaction, mode: MatchMode, ruleset: RulesetKey):
                try:
                    await interaction.response.defer()
                    snapshot = await self.bot.create_ranked_queue(
                        interaction.guild,
                        interaction.user,
                        mode,
                        ruleset,
                        interaction.channel_id,
                    )
                    message = await interaction.followup.send(
                        embed=build_queue_embed(snapshot),
                        view=self.bot.build_queue_view(snapshot.queue.id, snapshot=snapshot),
                    )
                    async with self.bot.runtime.session() as repos:
                        await repos.matches.set_queue_public_message_id(snapshot.queue.id, message.id)
                except HighlightManagerError as exc:
                    await interaction.followup.send(embed=self.bot.build_notice_embed("Queue creation failed", str(exc), error=True), ephemeral=True)

        return PlayPickerView(self)

    def build_latest_update_embed(self, prefix: str) -> discord.Embed:
        embed = discord.Embed(
            title="Highlight Manger V2 Latest Update",
            description=(
                "Season 2 now runs on the reworked V2 system. "
                "This update rebuilt the competitive flow, cleaned the UI, and separated the major systems properly."
            ),
            colour=discord.Colour.from_rgb(95, 112, 255),
        )
        embed.add_field(
            name="What Changed",
            value=(
                "The bot now runs on the new PostgreSQL Season 2 runtime.\n"
                "Ranked flow uses a strict queue -> room info -> official match pipeline.\n"
                "Ruleset text channels and waiting voice pools are configurable.\n"
                "Prefix and interaction hot paths were cleaned up to reduce visible delay."
            ),
            inline=False,
        )
        embed.add_field(
            name="What Was Added",
            value=(
                "Season-based rank progression and trusted leaderboards.\n"
                "Separate coins, wallet ledger, cosmetic shop, and inventory.\n"
                "Single-elimination tournaments.\n"
                "Persistent bot voice anchor and restart recovery.\n"
                "Premium help, profile, rank, leaderboard, queue, and match UI."
            ),
            inline=False,
        )
        embed.add_field(
            name="What Was Removed Or Reworked",
            value=(
                "Official matches no longer start the instant a queue fills; room info is required first.\n"
                "Coins are no longer mixed into competitive rank progression.\n"
                "The old prefix mass-rename flow was removed; use `/admin rename-members`.\n"
                "Older cluttered match panels were replaced with cleaner live queue and match cards."
            ),
            inline=False,
        )
        embed.add_field(
            name="Current V2 Match Flow",
            value=(
                f"`{prefix}play <mode> <ruleset>` opens the queue.\n"
                "Players fill both teams.\n"
                "The host submits `Room ID`, `Password`, and optional `Key`.\n"
                "Then the bot creates the official match, pings `@here`, opens the live rooms, and starts result tracking."
            ),
            inline=False,
        )
        embed.set_footer(text=f"Use {prefix}help for member commands and /admin for staff controls.")
        return embed

    def build_profile_card_cache_key(
        self,
        *,
        guild_id: int,
        member: discord.Member,
        season_id: int,
        rating: int,
        wins: int,
        losses: int,
        matches: int,
        leaderboard_rank: int | None,
        coins: int,
        peak_rating: int,
        avatar_bytes: bytes | None,
    ) -> str:
        avatar_marker = member.display_avatar.url if avatar_bytes else "no-avatar"
        return ":".join(
            [
                str(guild_id),
                str(member.id),
                str(season_id),
                str(rating),
                str(wins),
                str(losses),
                str(matches),
                str(leaderboard_rank or 0),
                str(coins),
                str(peak_rating),
                avatar_marker,
            ]
        )

    def build_leaderboard_card_cache_key(
        self,
        *,
        guild_id: int,
        season_id: int,
        entries: list[LeaderboardCardEntry],
        avatar_markers: list[str],
        total_players: int,
    ) -> str:
        entry_bits = [
            f"{entry.rank}:{entry.display_name}:{entry.wins}:{entry.losses}:{entry.winrate_text}:{entry.points}:{avatar_markers[index]}"
            for index, entry in enumerate(entries)
        ]
        return "|".join([str(guild_id), str(season_id), str(total_players), *entry_bits])

    def build_queue_view(self, queue_id: UUID, *, snapshot=None) -> QueueActionView:
        return QueueActionView(self, queue_id, snapshot=snapshot)

    def build_match_view(self, match_id: UUID, *, snapshot=None) -> MatchActionView:
        return MatchActionView(self, match_id, snapshot=snapshot)

    def build_storefront_order_view(self, section: ShopSection) -> StorefrontOrderView:
        return StorefrontOrderView(self, section)

    async def ensure_guild_bundle(self, repos, guild: discord.Guild):
        bundle = await self.runtime.services.guilds.get_bundle(repos.guilds, guild.id)
        if bundle is None:
            bundle = await self.runtime.services.guilds.ensure_guild(repos.guilds, guild.id, guild.name)
        self.prefix_cache.set(str(guild.id), bundle.settings.prefix)
        return bundle

    async def ensure_runtime_schema(self) -> None:
        async with self.runtime.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            guild_setting_columns = await connection.run_sync(
                lambda sync_connection: {
                    column["name"] for column in inspect(sync_connection).get_columns("guild_settings")
                }
            )
            guild_setting_compatibility_columns = {
                "waiting_voice_channel_ids": "ALTER TABLE guild_settings ADD COLUMN waiting_voice_channel_ids TEXT",
                "apostado_channel_ids": "ALTER TABLE guild_settings ADD COLUMN apostado_channel_ids TEXT",
                "highlight_channel_ids": "ALTER TABLE guild_settings ADD COLUMN highlight_channel_ids TEXT",
                "esport_channel_ids": "ALTER TABLE guild_settings ADD COLUMN esport_channel_ids TEXT",
            }
            for column_name, statement in guild_setting_compatibility_columns.items():
                if column_name in guild_setting_columns:
                    continue
                await connection.execute(text(statement))
            match_columns = await connection.run_sync(
                lambda sync_connection: {
                    column["name"] for column in inspect(sync_connection).get_columns("matches")
                }
            )
            match_compatibility_columns = {
                "team1_captain_player_id": "ALTER TABLE matches ADD COLUMN team1_captain_player_id INTEGER",
                "team2_captain_player_id": "ALTER TABLE matches ADD COLUMN team2_captain_player_id INTEGER",
                "result_phase": "ALTER TABLE matches ADD COLUMN result_phase TEXT",
                "captain_deadline_at": "ALTER TABLE matches ADD COLUMN captain_deadline_at TIMESTAMP",
                "fallback_deadline_at": "ALTER TABLE matches ADD COLUMN fallback_deadline_at TIMESTAMP",
                "rehost_count": "ALTER TABLE matches ADD COLUMN rehost_count INTEGER DEFAULT 0 NOT NULL",
            }
            for column_name, statement in match_compatibility_columns.items():
                if column_name in match_columns:
                    continue
                await connection.execute(text(statement))
            await connection.execute(
                text(
                    """
                    UPDATE guild_settings
                    SET waiting_voice_channel_ids = CAST(waiting_voice_channel_id AS TEXT)
                    WHERE waiting_voice_channel_id IS NOT NULL
                      AND (waiting_voice_channel_ids IS NULL OR waiting_voice_channel_ids = '')
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    UPDATE matches
                    SET team1_captain_player_id = creator_player_id
                    WHERE team1_captain_player_id IS NULL
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    UPDATE matches
                    SET team2_captain_player_id = (
                        SELECT player_id
                        FROM match_players
                        WHERE match_players.match_id = matches.id
                          AND match_players.team_number = 2
                        ORDER BY match_players.id ASC
                        LIMIT 1
                    )
                    WHERE team2_captain_player_id IS NULL
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    UPDATE matches
                    SET result_phase = CASE
                        WHEN state = 'expired' THEN 'staff_review'
                        WHEN state IN ('live', 'result_pending') THEN 'fallback'
                        ELSE 'captain'
                    END
                    WHERE result_phase IS NULL OR result_phase = ''
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    UPDATE matches
                    SET fallback_deadline_at = result_deadline_at
                    WHERE fallback_deadline_at IS NULL
                      AND result_deadline_at IS NOT NULL
                    """
                )
            )

    async def setup_hook(self) -> None:
        await self.ensure_runtime_schema()
        self.startup_health["db_ready"] = True
        self.refresh_runtime_health()
        await self.warm_runtime_assets()
        await self.add_cog(PlayerCommands(self))
        target_guild = self.app_command_target_guild()
        self._register_app_commands(guild=target_guild)
        for section in ShopSection:
            self.add_view(self.build_storefront_order_view(section))
        if target_guild is not None:
            try:
                self.tree.clear_commands(guild=None)
                await self.tree.sync()
                synced = await self.tree.sync(guild=target_guild)
                self._guild_commands_synced = True
                self.command_sync_status = {
                    "scope": "guild",
                    "success": True,
                    "count": len(synced),
                    "last_error": None,
                    "guild_id": self.settings.discord_guild_id,
                }
                self.logger.info(
                    "app_commands_synced",
                    scope="guild",
                    guild_id=self.settings.discord_guild_id,
                    count=len(synced),
                )
            except Exception as exc:
                self.command_sync_status = {
                    "scope": "guild",
                    "success": False,
                    "count": 0,
                    "last_error": str(exc),
                    "guild_id": self.settings.discord_guild_id,
                }
                self.logger.exception(
                    "app_commands_sync_failed",
                    scope="guild",
                    guild_id=self.settings.discord_guild_id,
                    error=str(exc),
                )
        else:
            self.command_sync_status = {
                "scope": "connected_guilds_pending",
                "success": False,
                "count": 0,
                "last_error": None,
            }
            self.logger.info("app_commands_sync_deferred", scope="connected_guilds")
        restored_count = await self.recovery.restore_views(self)
        self.startup_health["views_restored"] = restored_count
        self.deadline_loop.change_interval(seconds=self.settings.recovery_interval_seconds)
        self.cleanup_loop.change_interval(seconds=self.settings.cleanup_interval_seconds)
        self.voice_anchor_loop.change_interval(seconds=self.settings.recovery_interval_seconds)
        self.deadline_loop.start()
        self.cleanup_loop.start()
        self.voice_anchor_loop.start()

    async def on_ready(self) -> None:
        if not self.settings.discord_guild_id and not self._guild_commands_synced and self.guilds:
            synced_guilds = 0
            synced_commands = 0
            sync_errors: list[str] = []
            for guild in self.guilds:
                try:
                    guild_object = discord.Object(id=guild.id)
                    self.tree.copy_global_to(guild=guild_object)
                    synced = await self.tree.sync(guild=guild_object)
                    self.logger.info("app_commands_synced", scope="guild", guild_id=guild.id, count=len(synced))
                    synced_guilds += 1
                    synced_commands += len(synced)
                except Exception as exc:
                    sync_errors.append(f"{guild.id}:{exc}")
                    self.logger.exception("app_commands_sync_failed", scope="guild", guild_id=guild.id, error=str(exc))
            self._guild_commands_synced = True
            self.command_sync_status = {
                "scope": "connected_guilds",
                "success": not sync_errors,
                "count": synced_commands,
                "last_error": "; ".join(sync_errors) if sync_errors else None,
                "guilds": synced_guilds,
            }
            self.logger.info("connected_guild_commands_synced", guilds=synced_guilds, count=synced_commands)
        await self.warm_connected_guild_caches()
        async with self.runtime.session() as repos:
            for guild in self.guilds:
                bundle = await self.ensure_guild_bundle(repos, guild)
                await self.ensure_storefront_sections(guild, repos, bundle.guild.id)
                await self.republish_storefront_sections(guild, bundle.guild.id, repos, *list(ShopSection))
        await self.recovery.restore_persistent_voice(self)
        legacy_summary = self.refresh_runtime_health()
        if legacy_summary["legacy_import_count"]:
            self.logger.warning(
                "legacy_runtime_imports_detected",
                packages=legacy_summary["legacy_packages"],
                count=legacy_summary["legacy_import_count"],
            )
        self.logger.info(
            "startup_health",
            db_ready=self.startup_health["db_ready"],
            views_restored=self.startup_health["views_restored"],
            assets_warmed=self.startup_health["assets_warmed"],
            guild_cache_warmed=self.startup_health["guild_cache_warmed"],
            canonical_runtime=self.startup_health.get("canonical_runtime"),
            legacy_import_count=self.startup_health.get("legacy_import_count"),
            command_sync_scope=self.command_sync_status.get("scope"),
            command_sync_success=self.command_sync_status.get("success"),
            voice_ready_guilds=self.recovery.connected_guild_count,
        )
        self.logger.info("bot_ready", user=str(self.user), guilds=len(self.guilds))

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            await super().on_message(message)
            return

        async with self.runtime.session() as repos:
            bundle = await self.ensure_guild_bundle(repos, message.guild)
            is_staff = await self.runtime.services.guilds.member_is_admin(
                repos.guilds,
                bundle.guild.id,
                [role.id for role in getattr(message.author, "roles", [])],
            )
            
            if not is_staff:
                all_ruleset_channels = set()
                for key in RulesetKey:
                    all_ruleset_channels.update(self.get_ruleset_channel_ids(bundle.settings, key))
                
                if message.channel.id in all_ruleset_channels:
                    prefixes = await self.command_prefix(self, message)
                    if isinstance(prefixes, str):
                        prefixes = [prefixes]
                    
                    is_command = any(message.content.startswith(p) for p in prefixes)
                    if not is_command:
                        try:
                            await message.delete()
                        except Exception:
                            pass
                        return

        await super().on_message(message)

    async def on_command_error(self, context: commands.Context, exception: commands.CommandError) -> None:
        original = getattr(exception, "original", exception)
        if isinstance(exception, commands.CommandNotFound):
            attempted_command = context.message.content.strip().split(maxsplit=1)[0].lower()
            if attempted_command in {f"{context.clean_prefix}renameall", f"{context.clean_prefix}r"}:
                await context.reply(
                    embed=self.build_notice_embed(
                        "Rename command moved",
                        "Use `/admin rename-members` for the rank nickname sync.",
                        error=True,
                    )
                )
                return
            await context.reply(
                embed=self.build_notice_embed(
                    "Unknown command",
                    f"Use `{context.clean_prefix}help` to see the available commands.",
                    error=True,
                )
            )
            return
        if isinstance(original, HighlightManagerError):
            self.logger.warning(
                "prefix_command_failed",
                command=context.command.qualified_name if context.command else None,
                guild_id=context.guild.id if context.guild else None,
                channel_id=context.channel.id if context.channel else None,
                user_id=context.author.id if context.author else None,
                error=str(original),
            )
            await context.reply(embed=self.build_notice_embed("Command failed", str(original), error=True))
            return
        self.logger.exception(
            "command_error",
            command=context.command.qualified_name if context.command else None,
            guild_id=context.guild.id if context.guild else None,
            channel_id=context.channel.id if context.channel else None,
            user_id=context.author.id if context.author else None,
            error=str(original),
        )
        await context.reply(embed=self.build_notice_embed("Command failed", "Something went wrong.", error=True))

    async def on_error(self, event_method: str, *args, **kwargs) -> None:
        del args, kwargs
        self.logger.exception("discord_event_error", event=event_method)

    @tasks.loop(seconds=5)
    async def deadline_loop(self) -> None:
        await self.scheduler_worker.process_deadlines(self)

    @tasks.loop(seconds=30)
    async def cleanup_loop(self) -> None:
        await self.cleanup_worker.run(self)

    @tasks.loop(seconds=5)
    async def voice_anchor_loop(self) -> None:
        await self.recovery.restore_persistent_voice(self)

    @deadline_loop.before_loop
    @cleanup_loop.before_loop
    @voice_anchor_loop.before_loop
    async def before_loops(self) -> None:
        await self.wait_until_ready()

    async def ensure_context(self, guild: discord.Guild, member: discord.Member | None = None):
        async with self.runtime.session() as repos:
            bundle = await self.runtime.services.guilds.ensure_guild(repos.guilds, guild.id, guild.name)
            season = await self.runtime.services.seasons.ensure_active(repos.seasons, bundle.guild.id, bundle.settings)
            player = None
            if member is not None:
                player = await self.runtime.services.profiles.ensure_player(
                    repos.profiles,
                    bundle.guild.id,
                    member.id,
                    display_name=member.display_name,
                    global_name=member.global_name,
                    joined_guild_at=member.joined_at,
                )
            return bundle, season, player

    @staticmethod
    def get_ruleset_channel_ids(settings, ruleset: RulesetKey) -> list[int]:
        field_by_ruleset = {
            RulesetKey.APOSTADO: "apostado_channel_ids",
            RulesetKey.HIGHLIGHT: "highlight_channel_ids",
            RulesetKey.ESPORT: "esport_channel_ids",
        }
        return parse_discord_id_list(getattr(settings, field_by_ruleset[ruleset], None))

    @staticmethod
    def get_waiting_voice_channel_ids(settings) -> list[int]:
        configured_ids = parse_discord_id_list(getattr(settings, "waiting_voice_channel_ids", None))
        if configured_ids:
            return configured_ids
        legacy_id = getattr(settings, "waiting_voice_channel_id", None)
        return [legacy_id] if legacy_id else []

    def validate_ranked_queue_request(
        self,
        settings,
        *,
        mode: MatchMode,
        ruleset: RulesetKey,
        source_channel_id: int | None,
    ) -> None:
        if ruleset == RulesetKey.ESPORT and mode not in {MatchMode.FOUR_V_FOUR, MatchMode.SIX_V_SIX}:
            raise ValidationError("Esport queues only support 4v4 or 6v6.")
        if mode == MatchMode.SIX_V_SIX and ruleset != RulesetKey.ESPORT:
            raise ValidationError("6v6 is only available for the esport ruleset.")
        allowed_channel_ids = self.get_ruleset_channel_ids(settings, ruleset)
        if allowed_channel_ids and source_channel_id not in allowed_channel_ids:
            raise ValidationError(
                f"{ruleset.value.title()} queues can only be opened in: {format_channel_mentions(allowed_channel_ids)}"
            )

    async def create_ranked_queue(
        self,
        guild: discord.Guild,
        member: discord.Member,
        mode_raw: MatchMode | str,
        ruleset_raw: RulesetKey | str,
        source_channel_id: int | None,
    ):
        mode = mode_raw if isinstance(mode_raw, MatchMode) else MatchMode.from_input(mode_raw)
        ruleset = ruleset_raw if isinstance(ruleset_raw, RulesetKey) else RulesetKey.from_input(ruleset_raw)
        async with self.runtime.session() as repos:
            bundle = await self.ensure_guild_bundle(repos, guild)
            self.validate_ranked_queue_request(
                bundle.settings,
                mode=mode,
                ruleset=ruleset,
                source_channel_id=source_channel_id,
            )
            season = await self.runtime.services.seasons.ensure_active(repos.seasons, bundle.guild.id, bundle.settings)
            if season.ranked_queue_locked:
                raise ValidationError("Ranked queue creation is currently locked for this season.")
            player = await self.runtime.services.profiles.require_not_blacklisted(repos.profiles, bundle.guild.id, member.id)
            await self.runtime.services.seasons.ensure_player(repos.seasons, season.id, player.id)
            await self.runtime.services.profiles.require_idle(repos.profiles, player)
            return await self.runtime.services.matches.create_queue(
                repos.matches,
                repos.profiles,
                repos.moderation,
                guild_id=bundle.guild.id,
                season_id=season.id,
                creator_player_id=player.id,
                ruleset_key=ruleset,
                mode=mode,
                source_channel_id=source_channel_id,
            )

    async def fetch_avatar_bytes(self, member: discord.Member | None, *, size: int = 128) -> bytes | None:
        if member is None:
            return None
        avatar_asset = member.display_avatar.replace(size=size)
        cache_key = f"{member.id}:{size}:{avatar_asset.url}"
        cached_avatar = self.avatar_cache.get(cache_key)
        if isinstance(cached_avatar, bytes):
            return cached_avatar or None
        try:
            avatar_bytes = await asyncio.wait_for(avatar_asset.read(), timeout=0.75)
            self.avatar_cache.set(cache_key, avatar_bytes)
            return avatar_bytes
        except (asyncio.TimeoutError, discord.HTTPException):
            self.avatar_cache.set(cache_key, b"")
            return None

    async def build_profile_command_response(self, guild: discord.Guild, member: discord.Member) -> tuple[discord.Embed, discord.File | None]:
        started_at = time.monotonic()
        async with self.runtime.session() as repos:
            bundle = await self.runtime.services.guilds.ensure_guild(repos.guilds, guild.id, guild.name)
            season = await self.runtime.services.seasons.ensure_active(repos.seasons, bundle.guild.id, bundle.settings)
            player = await self.runtime.services.profiles.ensure_player(
                repos.profiles,
                bundle.guild.id,
                member.id,
                display_name=member.display_name,
                global_name=member.global_name,
                joined_guild_at=member.joined_at,
            )
            season_player = await self.runtime.services.seasons.ensure_player(repos.seasons, season.id, player.id)
            wallet = await repos.economy.ensure_wallet(player.id)
            leaderboard_rows = await repos.ranks.list_leaderboard(season.id, limit=None)
        leaderboard_rank = next(
            (index for index, row in enumerate(leaderboard_rows, start=1) if row.player_id == player.id),
            None,
        )
        matches_played = season_player.matches_played
        winrate = (season_player.wins / matches_played * 100.0) if matches_played else 0.0
        embed = build_profile_embed(
            display_name=member.display_name,
            rating=season_player.rating,
            wins=season_player.wins,
            losses=season_player.losses,
            coins=wallet.balance,
            matches_played=matches_played,
            winrate=winrate,
            leaderboard_rank=leaderboard_rank,
            peak_rating=season_player.peak_rating,
            season_name=season.name,
            avatar_url=None,
        )
        avatar_bytes = await self.fetch_avatar_bytes(member, size=256)
        card_data = ProfileCardData(
            display_name=member.display_name,
            season_name=season.name,
            points=season_player.rating,
            wins=season_player.wins,
            losses=season_player.losses,
            matches=matches_played,
            winrate_text=f"{winrate:.1f}%" if not winrate.is_integer() else f"{int(winrate)}%",
            rank_text=f"Rank #{leaderboard_rank}" if leaderboard_rank is not None else "Unranked",
            coins=wallet.balance,
            peak=season_player.peak_rating,
            avatar_bytes=avatar_bytes,
        )
        cache_key = self.build_profile_card_cache_key(
            guild_id=guild.id,
            member=member,
            season_id=season.id,
            rating=season_player.rating,
            wins=season_player.wins,
            losses=season_player.losses,
            matches=matches_played,
            leaderboard_rank=leaderboard_rank,
            coins=wallet.balance,
            peak_rating=season_player.peak_rating,
            avatar_bytes=avatar_bytes,
        )
        try:
            cached_card = self.profile_card_cache.get(cache_key)
            card_bytes = (
                cached_card
                if isinstance(cached_card, bytes)
                else await asyncio.wait_for(
                    asyncio.to_thread(lambda: render_profile_card(card_data).getvalue()),
                    timeout=2.0,
                )
            )
            if cached_card is None:
                self.profile_card_cache.set(cache_key, card_bytes)
            file = discord.File(BytesIO(card_bytes), filename="profile-card.png")
            embed.set_image(url="attachment://profile-card.png")
            self.log_duration(
                "render_completed",
                started_at,
                surface="profile_card",
                guild_id=guild.id,
                member_id=member.id,
                success=True,
            )
            return embed, file
        except Exception as exc:
            self.logger.warning("profile_card_render_failed", guild_id=guild.id, member_id=member.id, error=str(exc))
            self.log_duration(
                "render_completed",
                started_at,
                surface="profile_card",
                guild_id=guild.id,
                member_id=member.id,
                success=False,
                error=type(exc).__name__,
            )
            return embed, None

    async def build_leaderboard_command_response(self, guild: discord.Guild) -> tuple[discord.Embed, discord.File | None]:
        started_at = time.monotonic()
        async with self.runtime.session() as repos:
            bundle = await self.runtime.services.guilds.ensure_guild(repos.guilds, guild.id, guild.name)
            season = await self.runtime.services.seasons.ensure_active(repos.seasons, bundle.guild.id, bundle.settings)
            rows = await repos.ranks.list_leaderboard(season.id, limit=None)
            players = await repos.profiles.list_players_by_ids([row.player_id for row in rows[:10]])
            players_by_id = {player.id: player for player in players}
        embed = build_leaderboard_embed(rows[:10], players_by_id, season_name=season.name, total_players=len(rows))
        members = [
            guild.get_member(players_by_id[row.player_id].discord_user_id) if row.player_id in players_by_id else None
            for row in rows[:10]
        ]
        avatar_bytes = await asyncio.gather(
            *(self.fetch_avatar_bytes(member, size=128) for member in members)
        )
        entries: list[LeaderboardCardEntry] = []
        for index, row in enumerate(rows[:10], start=1):
            player = players_by_id.get(row.player_id)
            member = guild.get_member(player.discord_user_id) if player is not None else None
            display_name = member.display_name if member is not None else (player.display_name if player and player.display_name else f"Player {row.player_id}")
            matches_played = row.matches_played
            winrate = (row.wins / matches_played * 100.0) if matches_played else 0.0
            entries.append(
                LeaderboardCardEntry(
                    rank=index,
                    display_name=display_name,
                    wins=row.wins,
                    losses=row.losses,
                    winrate_text=f"{winrate:.1f}%" if not winrate.is_integer() else f"{int(winrate)}%",
                    points=row.rating,
                    avatar_bytes=avatar_bytes[index - 1],
                )
            )
        avatar_markers = [member.display_avatar.url if member is not None else "no-avatar" for member in members]
        cache_key = self.build_leaderboard_card_cache_key(
            guild_id=guild.id,
            season_id=season.id,
            entries=entries,
            avatar_markers=avatar_markers,
            total_players=len(rows),
        )
        try:
            cached_card = self.leaderboard_card_cache.get(cache_key)
            card_bytes = (
                cached_card
                if isinstance(cached_card, bytes)
                else await asyncio.wait_for(
                    asyncio.to_thread(lambda: render_leaderboard_card(season.name, len(rows), entries).getvalue()),
                    timeout=2.5,
                )
            )
            if cached_card is None:
                self.leaderboard_card_cache.set(cache_key, card_bytes)
            file = discord.File(
                BytesIO(card_bytes),
                filename="leaderboard-card.png",
            )
            embed.set_image(url="attachment://leaderboard-card.png")
            self.log_duration(
                "render_completed",
                started_at,
                surface="leaderboard_card",
                guild_id=guild.id,
                success=True,
            )
            return embed, file
        except Exception as exc:
            self.logger.warning("leaderboard_card_render_failed", guild_id=guild.id, error=str(exc))
            self.log_duration(
                "render_completed",
                started_at,
                surface="leaderboard_card",
                guild_id=guild.id,
                success=False,
                error=type(exc).__name__,
            )
            return embed, None

    async def build_coins_embed(self, guild: discord.Guild, member: discord.Member) -> discord.Embed:
        async with self.runtime.session() as repos:
            bundle = await self.runtime.services.guilds.ensure_guild(repos.guilds, guild.id, guild.name)
            player = await self.runtime.services.profiles.ensure_player(
                repos.profiles,
                bundle.guild.id,
                member.id,
                display_name=member.display_name,
                global_name=member.global_name,
                joined_guild_at=member.joined_at,
            )
            wallet = await repos.economy.ensure_wallet(player.id)
            season = await self.runtime.services.seasons.ensure_active(repos.seasons, bundle.guild.id, bundle.settings)
            sp = await repos.seasons.get_season_player(season.id, player.id)
            cheapest_item = await self.runtime.services.shop.get_cheapest_coin_item(repos.shop, bundle.guild.id)
        matches_played = sp.matches_played if sp else 0
        next_milestone = None
        from highlight_manager.modules.economy.ledger import MILESTONE_THRESHOLDS
        for threshold in MILESTONE_THRESHOLDS:
            if matches_played < threshold:
                next_milestone = threshold
                break
        milestone_text = f"Next milestone: **{next_milestone}** matches" if next_milestone else "All milestones complete! 🎉"
        cheapest_text = f"Cheapest shop item: **{cheapest_item.price_coins}** coins (`{cheapest_item.name}`)" if cheapest_item else "No coin items available"
        embed = discord.Embed(
            title=f"{theme.EMOJI_COIN} Wallet — {member.display_name}",
            description=(
                f"**Balance:** `{wallet.balance}` coins\n"
                f"**Lifetime Earned:** `{wallet.lifetime_earned}` coins\n"
                f"**Lifetime Spent:** `{wallet.lifetime_spent}` coins\n\n"
                f"{theme.EMOJI_STAR} {milestone_text}\n"
                f"{theme.EMOJI_SPARKLE} {cheapest_text}\n\n"
                f"**How to earn:**\n"
                f"  {theme.EMOJI_SWORD} Play a match → +5 coins\n"
                f"  {theme.EMOJI_TROPHY} Win → +5 bonus\n"
                f"  {theme.EMOJI_FIRE} Win streak (3+) → +2 to +5 bonus\n"
                f"  {theme.EMOJI_STAR} First match of the day → +10 bonus"
            ),
            colour=theme.ACCENT,
        )
        embed.set_footer(text="Highlight Manger  •  Economy")
        return embed

    async def ensure_storefront_sections(self, guild: discord.Guild, repos, guild_id: int) -> dict[ShopSection, object]:
        configs = await self.runtime.services.shop.ensure_section_configs(repos.shop, guild_id)
        updated = False
        for section, channel_id in DEFAULT_STOREFRONT_CHANNELS.items():
            config = configs[section]
            if config.channel_id is not None:
                continue
            if guild.get_channel(channel_id) is None:
                continue
            configs[section] = await self.runtime.services.shop.update_section_config(
                repos.shop,
                guild_id=guild_id,
                section=section,
                channel_id=channel_id,
            )
            updated = True
        if updated:
            return await self.runtime.services.shop.ensure_section_configs(repos.shop, guild_id)
        return configs

    async def build_shop_command_embed(self, guild: discord.Guild) -> discord.Embed:
        async with self.runtime.session() as repos:
            bundle = await self.runtime.services.guilds.ensure_guild(repos.guilds, guild.id, guild.name)
            await self.ensure_storefront_sections(guild, repos, bundle.guild.id)
            catalog = await self.runtime.services.shop.list_mixed_catalog(repos.shop, bundle.guild.id)
        return build_shop_embed(
            coin_items=catalog.coin_items,
            section_configs=catalog.section_configs,
        )

    @staticmethod
    def normalize_rank_source_name(source_name: str | None) -> str:
        cleaned = (source_name or "").strip()
        while cleaned:
            updated = RANK_NICKNAME_PATTERN.sub("", cleaned, count=1).strip()
            if updated == cleaned:
                break
            cleaned = updated
        return cleaned.strip(" |-:")

    @classmethod
    def pick_rank_source_name(cls, member: discord.Member) -> str:
        candidates = [
            member.nick,
            member.global_name,
            member.name,
            member.display_name,
        ]
        for candidate in candidates:
            cleaned = cls.normalize_rank_source_name(candidate)
            if cleaned:
                return cleaned
        return "PLAYER"

    @classmethod
    def build_rank_nickname(cls, rank: int, source_name: str) -> str:
        base_name = cls.normalize_rank_source_name(source_name)
        if not base_name:
            base_name = "PLAYER"
        prefix = f"RANK {rank} | "
        available = max(0, 32 - len(prefix))
        trimmed_name = base_name[:available].rstrip() or base_name[:available]
        return f"{prefix}{trimmed_name}"

    async def rename_members_to_rank_format(self, guild: discord.Guild, *, progress_callback=None) -> tuple[int, int, list[str]]:
        me = guild.me
        if me is None or not me.guild_permissions.manage_nicknames:
            raise ValidationError("The bot needs the Manage Nicknames permission.")

        eligible_members = [member for member in guild.members if not member.bot]
        async with self.runtime.session() as repos:
            bundle = await self.runtime.services.guilds.ensure_guild(repos.guilds, guild.id, guild.name)
            season = await self.runtime.services.seasons.ensure_active(repos.seasons, bundle.guild.id, bundle.settings)
            existing_players = await repos.profiles.list_players_by_discord_ids(
                bundle.guild.id,
                [member.id for member in eligible_members],
            )
            leaderboard_rows = await repos.ranks.list_leaderboard(season.id, limit=None)

        players_by_discord_id = {
            player.discord_user_id: player.id
            for player in existing_players
        }
        rank_by_player_id = {
            row.player_id: index
            for index, row in enumerate(leaderboard_rows, start=1)
        }
        actionable_members = [
            member
            for member in eligible_members
            if member != guild.owner
            and me.top_role > member.top_role
            and (player_id := players_by_discord_id.get(member.id)) is not None
            and rank_by_player_id.get(player_id) is not None
        ]
        renamed = 0
        skipped = 0
        failed: list[str] = []
        processed = 0
        total = len(actionable_members)
        if progress_callback is not None:
            await progress_callback(processed, total, renamed, skipped, len(failed))
        actionable_member_ids = {member.id for member in actionable_members}
        for member in eligible_members:
            if member == guild.owner:
                skipped += 1
                continue
            if me.top_role <= member.top_role:
                skipped += 1
                continue
            player_id = players_by_discord_id.get(member.id)
            if player_id is None:
                skipped += 1
                continue
            rank = rank_by_player_id.get(player_id)
            if rank is None:
                skipped += 1
                continue
            nickname = self.build_rank_nickname(rank, self.pick_rank_source_name(member))
            if member.nick == nickname:
                skipped += 1
                processed += 1
                if progress_callback is not None and member.id in actionable_member_ids:
                    await progress_callback(processed, total, renamed, skipped, len(failed))
                continue
            try:
                await member.edit(nick=nickname, reason="Highlight Manger rank sync")
                renamed += 1
            except discord.Forbidden:
                failed.append(member.display_name)
            except discord.HTTPException:
                failed.append(member.display_name)
            processed += 1
            if progress_callback is not None and member.id in actionable_member_ids:
                await progress_callback(processed, total, renamed, skipped, len(failed))
        return renamed, skipped, failed

    async def is_staff_member(self, guild: discord.Guild, member: discord.Member) -> bool:
        if member.guild_permissions.administrator:
            return True
        async with self.runtime.session() as repos:
            bundle = await self.runtime.services.guilds.ensure_guild(repos.guilds, guild.id, guild.name)
            return await self.runtime.services.guilds.member_is_moderator(
                repos.guilds,
                bundle.guild.id,
                [role.id for role in member.roles],
            )

    async def is_admin_member(self, guild: discord.Guild, member: discord.Member) -> bool:
        if member.guild_permissions.administrator:
            return True
        async with self.runtime.session() as repos:
            bundle = await self.runtime.services.guilds.ensure_guild(repos.guilds, guild.id, guild.name)
            return await self.runtime.services.guilds.member_is_admin(
                repos.guilds,
                bundle.guild.id,
                [role.id for role in member.roles],
            )

    async def handle_queue_join(self, interaction: discord.Interaction, queue_id: UUID, team_number: int) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return
        started_at = time.monotonic()
        try:
            await self.acknowledge_interaction(
                interaction,
                operation="queue_join",
                started_at=started_at,
                update_message=True,
            )
            async with self.runtime.session() as repos:
                bundle = await self.ensure_guild_bundle(repos, interaction.guild)
                season = await self.runtime.services.seasons.ensure_active(repos.seasons, bundle.guild.id, bundle.settings)
                player = await self.runtime.services.profiles.require_not_blacklisted(repos.profiles, bundle.guild.id, interaction.user.id)
                await self.runtime.services.seasons.ensure_player(repos.seasons, season.id, player.id)
                await self.runtime.services.profiles.require_idle(repos.profiles, player)
                snapshot = await self.runtime.services.matches.join_queue(
                    repos.matches,
                    repos.profiles,
                    repos.moderation,
                    queue_id=queue_id,
                    player_id=player.id,
                    team_number=team_number,
                )
            await self.edit_interaction_message(
                interaction,
                embed=build_queue_embed(snapshot),
                view=self.build_queue_view(queue_id, snapshot=snapshot),
            )
            self.log_duration(
                "interaction_completed",
                started_at,
                operation="queue_join",
                queue_id=str(queue_id),
                success=True,
            )
        except HighlightManagerError as exc:
            await self.send_interaction_notice(interaction, "Queue update failed", str(exc), error=True, ephemeral=True)
            self.log_duration(
                "interaction_completed",
                started_at,
                operation="queue_join",
                queue_id=str(queue_id),
                success=False,
                error=type(exc).__name__,
            )

    async def handle_queue_ready(self, interaction: discord.Interaction, queue_id: UUID) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return
        started_at = time.monotonic()
        try:
            await self.acknowledge_interaction(
                interaction,
                operation="queue_ready",
                started_at=started_at,
                update_message=True,
            )
            async with self.runtime.session() as repos:
                player = await self.runtime.services.profiles.require_not_blacklisted(repos.profiles, interaction.guild.id, interaction.user.id)
                snapshot = await self.runtime.services.matches.mark_ready(
                    repos.matches,
                    repos.profiles,
                    queue_id=queue_id,
                    player_id=player.id,
                )
            await self.edit_interaction_message(
                interaction,
                embed=build_queue_embed(snapshot),
                view=self.build_queue_view(queue_id, snapshot=snapshot),
            )
            self.log_duration(
                "interaction_completed",
                started_at,
                operation="queue_ready",
                queue_id=str(queue_id),
                success=True,
            )
        except HighlightManagerError as exc:
            await self.send_interaction_notice(interaction, "Ready check failed", str(exc), error=True, ephemeral=True)
            self.log_duration(
                "interaction_completed",
                started_at,
                operation="queue_ready",
                queue_id=str(queue_id),
                success=False,
                error=type(exc).__name__,
            )

    async def handle_queue_leave(self, interaction: discord.Interaction, queue_id: UUID) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return
        started_at = time.monotonic()
        try:
            await self.acknowledge_interaction(
                interaction,
                operation="queue_leave",
                started_at=started_at,
                update_message=True,
            )
            async with self.runtime.session() as repos:
                bundle = await self.ensure_guild_bundle(repos, interaction.guild)
                player = await self.runtime.services.profiles.ensure_player(
                    repos.profiles,
                    bundle.guild.id,
                    interaction.user.id,
                    display_name=interaction.user.display_name,
                    global_name=interaction.user.global_name,
                    joined_guild_at=interaction.user.joined_at,
                )
                snapshot = await self.runtime.services.matches.leave_queue(
                    repos.matches,
                    repos.profiles,
                    repos.moderation,
                    queue_id=queue_id,
                    player_id=player.id,
                )
            await self.edit_interaction_message(
                interaction,
                embed=build_queue_embed(snapshot),
                view=self.build_queue_view(queue_id, snapshot=snapshot),
            )
            self.log_duration(
                "interaction_completed",
                started_at,
                operation="queue_leave",
                queue_id=str(queue_id),
                success=True,
            )
        except HighlightManagerError as exc:
            await self.send_interaction_notice(interaction, "Queue update failed", str(exc), error=True, ephemeral=True)
            self.log_duration(
                "interaction_completed",
                started_at,
                operation="queue_leave",
                queue_id=str(queue_id),
                success=False,
                error=type(exc).__name__,
            )

    async def handle_queue_admin_cancel(self, interaction: discord.Interaction, queue_id: UUID) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return
        if not await self.is_staff_member(interaction.guild, interaction.user):
            await self.send_interaction_notice(interaction, "Not allowed", "Staff only.", error=True, ephemeral=True)
            return
        started_at = time.monotonic()
        try:
            await self.acknowledge_interaction(
                interaction,
                operation="queue_admin_cancel",
                started_at=started_at,
                update_message=True,
            )
            async with self.runtime.session() as repos:
                bundle = await self.ensure_guild_bundle(repos, interaction.guild)
                actor = await self.runtime.services.profiles.ensure_player(
                    repos.profiles,
                    bundle.guild.id,
                    interaction.user.id,
                    display_name=interaction.user.display_name,
                    global_name=interaction.user.global_name,
                    joined_guild_at=interaction.user.joined_at,
                )
                snapshot = await self.runtime.services.matches.cancel_queue(
                    repos.matches,
                    repos.profiles,
                    repos.moderation,
                    queue_id=queue_id,
                    actor_player_id=actor.id,
                    reason="admin_cancel",
                )
            await self.edit_interaction_message(
                interaction,
                embed=build_queue_embed(snapshot),
                view=self.build_queue_view(queue_id, snapshot=snapshot),
            )
            self.log_duration(
                "interaction_completed",
                started_at,
                operation="queue_admin_cancel",
                queue_id=str(queue_id),
                success=True,
            )
        except HighlightManagerError as exc:
            await self.send_interaction_notice(interaction, "Queue update failed", str(exc), error=True, ephemeral=True)
            self.log_duration(
                "interaction_completed",
                started_at,
                operation="queue_admin_cancel",
                queue_id=str(queue_id),
                success=False,
                error=type(exc).__name__,
            )

    async def handle_room_info_submission(self, interaction: discord.Interaction, queue_id: UUID, *, room_code: str, room_password: str | None, room_notes: str | None) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return
        started_at = time.monotonic()
        player_id: int | None = None
        try:
            is_moderator = await self.is_staff_member(interaction.guild, interaction.user)
            await self.acknowledge_interaction(
                interaction,
                operation="submit_room_info",
                started_at=started_at,
                ephemeral=True,
            )
            async with self.runtime.session() as repos:
                bundle = await self.ensure_guild_bundle(repos, interaction.guild)
                player = await self.runtime.services.profiles.ensure_player(
                    repos.profiles,
                    bundle.guild.id,
                    interaction.user.id,
                    display_name=interaction.user.display_name,
                    global_name=interaction.user.global_name,
                    joined_guild_at=interaction.user.joined_at,
                )
                player_id = player.id
                match_snapshot = await self.runtime.services.matches.submit_room_info(
                    repos.matches,
                    repos.profiles,
                    repos.moderation,
                    queue_id=queue_id,
                    submitter_player_id=player.id,
                    is_moderator=is_moderator,
                    room_code=room_code,
                    room_password=room_password,
                    room_notes=room_notes,
                )
            match_snapshot.match.state = MatchState.MOVING
            await self.refresh_match_messages(interaction.guild, match_snapshot)
            await interaction.edit_original_response(
                embed=self.build_notice_embed(
                    "Creating match",
                    "Room info locked. Building the match room, voice rooms, and live panel now.",
                )
            )
            live_snapshot = await self.provision_match_resources(interaction.guild, match_snapshot)
            await self.announce_match_created(interaction.guild, live_snapshot)
            await self.refresh_match_messages(interaction.guild, live_snapshot)
            result_channel_text = (
                f" in <#{live_snapshot.match.result_channel_id}>"
                if live_snapshot.match.result_channel_id
                else ""
            )
            await interaction.edit_original_response(
                embed=self.build_notice_embed(
                    "Match created",
                    f"Official Match #{live_snapshot.match.match_number:03d} is now live{result_channel_text}.",
                )
            )
            self.log_duration(
                "interaction_completed",
                started_at,
                operation="submit_room_info",
                queue_id=str(queue_id),
                success=True,
            )
        except Exception as exc:  # pragma: no cover - safety path exercised via higher-level tests
            if isinstance(exc, HighlightManagerError):
                await self.edit_or_followup_notice(interaction, "Room info failed", str(exc), error=True, ephemeral=True)
                self.log_duration(
                    "interaction_completed",
                    started_at,
                    operation="submit_room_info",
                    queue_id=str(queue_id),
                    success=False,
                    error=type(exc).__name__,
                )
                return
            self.logger.exception(
                "match_provision_failed",
                guild_id=interaction.guild.id,
                queue_id=str(queue_id),
                error=str(exc),
            )
            failure_snapshot = None
            if player_id is not None:
                async with self.runtime.session() as repos:
                    queue_snapshot = await repos.matches.get_queue_snapshot(queue_id)
                    match_id = queue_snapshot.queue.converted_match_id if queue_snapshot is not None else None
                    if match_id is not None:
                        failure_snapshot = await self.runtime.services.matches.force_close_match(
                            repos.matches,
                            repos.profiles,
                            repos.moderation,
                            match_id=match_id,
                            actor_player_id=player_id,
                            reason="Automatic match setup failed after multiple retry attempts.",
                        )
            if failure_snapshot is not None:
                await self.finalize_terminal_match(interaction.guild, failure_snapshot)
                await self.edit_or_followup_notice(
                    interaction,
                    "Match setup failed",
                    "The official match could not finish building and was closed safely. Staff can review the source channel summary.",
                    error=True,
                    ephemeral=True,
                )
            else:
                await self.edit_or_followup_notice(
                    interaction,
                    "Match setup failed",
                    "The bot hit a startup error while building the official match.",
                    error=True,
                    ephemeral=True,
                )
            self.log_duration(
                "interaction_completed",
                started_at,
                operation="submit_room_info",
                queue_id=str(queue_id),
                success=False,
                error=type(exc).__name__,
            )

    async def handle_vote_submission(self, interaction: discord.Interaction, match_id: UUID, winner_team: int, winner_mvp: int | None, loser_mvp: int | None) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return
        started_at = time.monotonic()
        try:
            await self.acknowledge_interaction(
                interaction,
                operation="submit_vote",
                started_at=started_at,
                ephemeral=True,
            )
            async with self.runtime.session() as repos:
                bundle = await self.runtime.services.guilds.ensure_guild(repos.guilds, interaction.guild.id, interaction.guild.name)
                player = await self.runtime.services.profiles.ensure_player(
                    repos.profiles,
                    bundle.guild.id,
                    interaction.user.id,
                    display_name=interaction.user.display_name,
                    global_name=interaction.user.global_name,
                    joined_guild_at=interaction.user.joined_at,
                )
                snapshot = await self.runtime.services.matches.submit_vote(
                    repos.matches,
                    match_id=match_id,
                    player_id=player.id,
                    winner_team_number=winner_team,
                    winner_mvp_player_id=winner_mvp,
                    loser_mvp_player_id=loser_mvp,
                )
                if snapshot.all_votes_match():
                    final_vote = snapshot.votes[0]
                    snapshot = await self.runtime.services.matches.confirm_match(
                        repos.matches,
                        repos.profiles,
                        repos.seasons,
                        repos.ranks,
                        repos.economy,
                        repos.moderation,
                        match_id=match_id,
                        winner_team_number=final_vote.winner_team_number,
                        winner_mvp_player_id=final_vote.winner_mvp_player_id,
                        loser_mvp_player_id=final_vote.loser_mvp_player_id,
                        actor_player_id=player.id,
                        source=f"{snapshot.match.result_phase.value}_consensus",
                    )
            if snapshot.match.state == MatchState.CONFIRMED:
                await interaction.edit_original_response(
                    embed=self.build_notice_embed("Match confirmed", "All votes matched and the result was confirmed."),
                )
                await self.finalize_terminal_match(interaction.guild, snapshot)
            else:
                if snapshot.match.result_phase == MatchResultPhase.CAPTAIN and len(snapshot.phase_votes) == len(snapshot.captain_ids):
                    message = "Captain vote saved. The captains do not agree yet, so backup voting will open when the captain window ends."
                elif snapshot.match.result_phase == MatchResultPhase.CAPTAIN:
                    message = "Captain vote saved. Waiting for the other team captain."
                else:
                    message = "Fallback vote saved."
                await interaction.edit_original_response(
                    embed=self.build_notice_embed("Vote recorded", message),
                )
                await self.refresh_match_messages(interaction.guild, snapshot)
            self.log_duration(
                "interaction_completed",
                started_at,
                operation="submit_vote",
                match_id=str(match_id),
                success=True,
            )
        except HighlightManagerError as exc:
            await self.edit_or_followup_notice(interaction, "Vote failed", str(exc), error=True, ephemeral=True)
            self.log_duration(
                "interaction_completed",
                started_at,
                operation="submit_vote",
                match_id=str(match_id),
                success=False,
                error=type(exc).__name__,
            )

    async def handle_match_room_update(
        self,
        interaction: discord.Interaction,
        match_id: UUID,
        *,
        room_code: str,
        room_password: str | None,
        room_notes: str | None,
    ) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return
        started_at = time.monotonic()
        try:
            await self.acknowledge_interaction(
                interaction,
                operation="update_match_room",
                started_at=started_at,
                ephemeral=True,
            )
            async with self.runtime.session() as repos:
                bundle = await self.runtime.services.guilds.ensure_guild(repos.guilds, interaction.guild.id, interaction.guild.name)
                actor = await self.runtime.services.profiles.ensure_player(
                    repos.profiles,
                    bundle.guild.id,
                    interaction.user.id,
                    display_name=interaction.user.display_name,
                    global_name=interaction.user.global_name,
                    joined_guild_at=interaction.user.joined_at,
                )
                snapshot = await self.runtime.services.matches.update_room_info(
                    repos.matches,
                    repos.moderation,
                    match_id=match_id,
                    creator_player_id=actor.id,
                    room_code=room_code,
                    room_password=room_password,
                    room_notes=room_notes,
                )
            await self.refresh_match_messages(interaction.guild, snapshot)
            await interaction.edit_original_response(
                embed=self.build_notice_embed("Room info updated", "The live room details were updated for this match."),
            )
            self.log_duration(
                "interaction_completed",
                started_at,
                operation="update_match_room",
                match_id=str(match_id),
                success=True,
            )
        except HighlightManagerError as exc:
            await self.edit_or_followup_notice(interaction, "Room update failed", str(exc), error=True, ephemeral=True)
            self.log_duration(
                "interaction_completed",
                started_at,
                operation="update_match_room",
                match_id=str(match_id),
                success=False,
                error=type(exc).__name__,
            )

    async def handle_force_result(self, interaction: discord.Interaction, match_id: UUID, winner_team: int, winner_mvp: int | None, loser_mvp: int | None) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return
        if not await self.is_staff_member(interaction.guild, interaction.user):
            await self.send_interaction_notice(interaction, "Not allowed", "Staff only.", error=True, ephemeral=True)
            return
        started_at = time.monotonic()
        try:
            await self.acknowledge_interaction(
                interaction,
                operation="force_result",
                started_at=started_at,
                ephemeral=True,
            )
            async with self.runtime.session() as repos:
                bundle = await self.runtime.services.guilds.ensure_guild(repos.guilds, interaction.guild.id, interaction.guild.name)
                actor = await self.runtime.services.profiles.ensure_player(
                    repos.profiles,
                    bundle.guild.id,
                    interaction.user.id,
                    display_name=interaction.user.display_name,
                    global_name=interaction.user.global_name,
                    joined_guild_at=interaction.user.joined_at,
                )
                snapshot = await self.runtime.services.matches.confirm_match(
                    repos.matches,
                    repos.profiles,
                    repos.seasons,
                    repos.ranks,
                    repos.economy,
                    repos.moderation,
                    match_id=match_id,
                    winner_team_number=winner_team,
                    winner_mvp_player_id=winner_mvp,
                    loser_mvp_player_id=loser_mvp,
                    actor_player_id=actor.id,
                    source="force_result",
                )
            await interaction.edit_original_response(
                embed=self.build_notice_embed("Force result applied", "The match was confirmed by staff."),
            )
            await self.finalize_terminal_match(interaction.guild, snapshot)
            self.log_duration(
                "interaction_completed",
                started_at,
                operation="force_result",
                match_id=str(match_id),
                success=True,
            )
        except HighlightManagerError as exc:
            await self.edit_or_followup_notice(interaction, "Force result failed", str(exc), error=True, ephemeral=True)
            self.log_duration(
                "interaction_completed",
                started_at,
                operation="force_result",
                match_id=str(match_id),
                success=False,
                error=type(exc).__name__,
            )

    async def handle_force_close(self, interaction: discord.Interaction, match_id: UUID, reason: str) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return
        if not await self.is_staff_member(interaction.guild, interaction.user):
            await self.send_interaction_notice(interaction, "Not allowed", "Staff only.", error=True, ephemeral=True)
            return
        started_at = time.monotonic()
        try:
            await self.acknowledge_interaction(
                interaction,
                operation="force_close",
                started_at=started_at,
                ephemeral=True,
            )
            async with self.runtime.session() as repos:
                bundle = await self.runtime.services.guilds.ensure_guild(repos.guilds, interaction.guild.id, interaction.guild.name)
                actor = await self.runtime.services.profiles.ensure_player(
                    repos.profiles,
                    bundle.guild.id,
                    interaction.user.id,
                    display_name=interaction.user.display_name,
                    global_name=interaction.user.global_name,
                    joined_guild_at=interaction.user.joined_at,
                )
                snapshot = await self.runtime.services.matches.force_close_match(
                    repos.matches,
                    repos.profiles,
                    repos.moderation,
                    match_id=match_id,
                    actor_player_id=actor.id,
                    reason=reason,
                )
            await interaction.edit_original_response(
                embed=self.build_notice_embed("Match closed", "The match was force closed."),
            )
            await self.finalize_terminal_match(interaction.guild, snapshot)
            self.log_duration(
                "interaction_completed",
                started_at,
                operation="force_close",
                match_id=str(match_id),
                success=True,
            )
        except HighlightManagerError as exc:
            await self.edit_or_followup_notice(interaction, "Force close failed", str(exc), error=True, ephemeral=True)
            self.log_duration(
                "interaction_completed",
                started_at,
                operation="force_close",
                match_id=str(match_id),
                success=False,
                error=type(exc).__name__,
            )

    async def handle_creator_cancel(self, interaction: discord.Interaction, match_id: UUID) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return
        started_at = time.monotonic()
        try:
            await self.acknowledge_interaction(
                interaction,
                operation="creator_cancel",
                started_at=started_at,
                ephemeral=True,
            )
            async with self.runtime.session() as repos:
                bundle = await self.runtime.services.guilds.ensure_guild(repos.guilds, interaction.guild.id, interaction.guild.name)
                actor = await self.runtime.services.profiles.ensure_player(
                    repos.profiles,
                    bundle.guild.id,
                    interaction.user.id,
                    display_name=interaction.user.display_name,
                    global_name=interaction.user.global_name,
                    joined_guild_at=interaction.user.joined_at,
                )
                snapshot = await self.runtime.services.matches.cancel_match_by_creator(
                    repos.matches,
                    repos.profiles,
                    repos.moderation,
                    match_id=match_id,
                    creator_player_id=actor.id,
                )
            await interaction.edit_original_response(
                embed=self.build_notice_embed("Match cancelled", "You cancelled the match before voting was finalized."),
            )
            await self.finalize_terminal_match(interaction.guild, snapshot)
            self.log_duration(
                "interaction_completed",
                started_at,
                operation="creator_cancel",
                match_id=str(match_id),
                success=True,
            )
        except HighlightManagerError as exc:
            await self.edit_or_followup_notice(interaction, "Creator cancel failed", str(exc), error=True, ephemeral=True)
            self.log_duration(
                "interaction_completed",
                started_at,
                operation="creator_cancel",
                match_id=str(match_id),
                success=False,
                error=type(exc).__name__,
            )

    async def edit_message_view(
        self,
        channel: discord.abc.GuildChannel | discord.Thread | None,
        message_id: int | None,
        *,
        embed: discord.Embed,
        view: discord.ui.View | None,
    ) -> None:
        if message_id is None:
            return
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return
        try:
            message = await channel.fetch_message(message_id)
            await message.edit(embed=embed, view=view)
        except discord.HTTPException:
            return

    async def refresh_queue_public_message(self, guild: discord.Guild, snapshot) -> None:
        channel = guild.get_channel(snapshot.queue.source_channel_id) if snapshot.queue.source_channel_id else None
        await self.edit_message_view(
            channel,
            snapshot.queue.public_message_id,
            embed=build_queue_embed(snapshot),
            view=self.build_queue_view(snapshot.queue.id, snapshot=snapshot),
        )

    async def refresh_match_messages(self, guild: discord.Guild, snapshot) -> None:
        public_embed = build_public_match_embed(snapshot)
        result_embed = build_result_match_embed(snapshot)
        result_view = self.build_match_view(snapshot.match.id, snapshot=snapshot)
        public_channel = guild.get_channel(snapshot.match.source_channel_id) if snapshot.match.source_channel_id else None
        result_channel = guild.get_channel(snapshot.match.result_channel_id) if snapshot.match.result_channel_id else None
        await self.edit_message_view(
            public_channel,
            snapshot.match.public_message_id,
            embed=public_embed,
            view=None,
        )
        await self.edit_message_view(
            result_channel,
            snapshot.match.result_message_id,
            embed=result_embed,
            view=result_view,
        )

    async def provision_match_resources(self, guild: discord.Guild, snapshot):
        started_at = time.monotonic()
        max_attempts = 3
        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            created_channels: list[discord.abc.GuildChannel] = []
            try:
                async with self.runtime.session() as repos:
                    bundle = await self.ensure_guild_bundle(repos, guild)
                    category = guild.get_channel(bundle.settings.match_category_id) if bundle.settings.match_category_id else None
                    result_category = guild.get_channel(bundle.settings.result_category_id) if bundle.settings.result_category_id else None
                    waiting_voice_channel_ids = set(self.get_waiting_voice_channel_ids(bundle.settings))
                    snapshot.match.state = MatchState.MOVING
                    overwrites = {
                        guild.default_role: discord.PermissionOverwrite(view_channel=False),
                    }
                    if guild.me:
                        overwrites[guild.me] = discord.PermissionOverwrite(
                            view_channel=True,
                            send_messages=True,
                            read_message_history=True,
                            embed_links=True,
                        )
                    staff_roles = await self.runtime.services.guilds.get_staff_roles(repos.guilds, bundle.guild.id)
                    for role_id in staff_roles.admin_role_ids | staff_roles.moderator_role_ids:
                        role = guild.get_role(role_id)
                        if role is not None:
                            overwrites[role] = discord.PermissionOverwrite(
                                view_channel=True,
                                send_messages=True,
                                read_message_history=True,
                            )
                    for discord_user_id in snapshot.player_discord_ids.values():
                        member = guild.get_member(discord_user_id)
                        if member is not None:
                            overwrites[member] = discord.PermissionOverwrite(
                                view_channel=True,
                                send_messages=True,
                                read_message_history=True,
                            )

                    voice_category = category if isinstance(category, discord.CategoryChannel) else None
                    result_parent = result_category if isinstance(result_category, discord.CategoryChannel) else None

                    team1_channel = await guild.create_voice_channel(
                        name=f"TEAM 1 - Match #{snapshot.match.match_number:03d}",
                        category=voice_category,
                    )
                    created_channels.append(team1_channel)
                    team2_channel = await guild.create_voice_channel(
                        name=f"TEAM 2 - Match #{snapshot.match.match_number:03d}",
                        category=voice_category,
                    )
                    created_channels.append(team2_channel)
                    result_channel = await guild.create_text_channel(
                        name=f"match-{snapshot.match.match_number:03d}",
                        category=result_parent,
                        overwrites=overwrites,
                    )
                    created_channels.append(result_channel)

                    result_message = await result_channel.send(
                        embed=build_result_match_embed(snapshot),
                        view=self.build_match_view(snapshot.match.id, snapshot=snapshot),
                    )

                    move_tasks: list[asyncio.Future] = []
                    for player_id in snapshot.team1_ids:
                        member = guild.get_member(snapshot.player_discord_ids.get(player_id, 0))
                        if (
                            member
                            and member.voice
                            and member.voice.channel
                            and (not waiting_voice_channel_ids or member.voice.channel.id in waiting_voice_channel_ids)
                        ):
                            move_tasks.append(member.move_to(team1_channel))
                    for player_id in snapshot.team2_ids:
                        member = guild.get_member(snapshot.player_discord_ids.get(player_id, 0))
                        if (
                            member
                            and member.voice
                            and member.voice.channel
                            and (not waiting_voice_channel_ids or member.voice.channel.id in waiting_voice_channel_ids)
                        ):
                            move_tasks.append(member.move_to(team2_channel))
                    if move_tasks:
                        await asyncio.gather(*move_tasks, return_exceptions=True)

                    live_snapshot = await self.runtime.services.matches.mark_match_live(
                        repos.matches,
                        match_id=snapshot.match.id,
                        result_channel_id=result_channel.id,
                        result_message_id=result_message.id,
                        team1_voice_channel_id=team1_channel.id,
                        team2_voice_channel_id=team2_channel.id,
                    )
                    self.log_duration(
                        "match_resource_provisioned",
                        started_at,
                        guild_id=guild.id,
                        match_id=str(snapshot.match.id),
                        result_channel_id=result_channel.id,
                        attempt=attempt,
                    )
                    return live_snapshot
            except Exception as exc:
                last_error = exc
                for channel in reversed(created_channels):
                    await self.delete_channel_if_exists(channel)
                self.logger.warning(
                    "match_resource_provision_retry",
                    guild_id=guild.id,
                    match_id=str(snapshot.match.id),
                    attempt=attempt,
                    error=str(exc),
                )
                if attempt < max_attempts:
                    await asyncio.sleep(1)
        assert last_error is not None
        raise last_error

    def build_match_terminal_notice(self, snapshot) -> discord.Embed:
        match = snapshot.match
        ruleset_label = match.ruleset_key.value.title()
        if match.state == MatchState.CONFIRMED:
            winner_team = next((row.team_number for row in snapshot.players if row.result.value == "win"), None)
            winner_mvp = next((row for row in snapshot.players if row.is_winner_mvp), None)
            loser_mvp = next((row for row in snapshot.players if row.is_loser_mvp), None)
            details = [
                f"{ruleset_label} {match.mode.value.upper()} finished successfully.",
                f"Winner Team: **Team {winner_team}**" if winner_team is not None else "Winner Team: **Unknown**",
            ]
            if winner_mvp is not None:
                winner_id = snapshot.player_discord_ids.get(winner_mvp.player_id)
                details.append(f"Winner MVP: <@{winner_id}>" if winner_id else f"Winner MVP: Player {winner_mvp.player_id}")
            if loser_mvp is not None:
                loser_id = snapshot.player_discord_ids.get(loser_mvp.player_id)
                details.append(f"Loser MVP: <@{loser_id}>" if loser_id else f"Loser MVP: Player {loser_mvp.player_id}")
            return self.build_notice_embed(
                f"Match #{match.match_number:03d} Confirmed",
                "\n".join(details),
            )
        if match.state == MatchState.CANCELLED:
            return self.build_notice_embed(
                f"Match #{match.match_number:03d} Cancelled",
                "The match creator cancelled the match before results were finalized.",
                error=True,
            )
        if match.state == MatchState.FORCE_CLOSED:
            reason = match.force_close_reason or "No staff reason was provided."
            return self.build_notice_embed(
                f"Match #{match.match_number:03d} Force Closed",
                reason,
                error=True,
            )
        if match.state == MatchState.EXPIRED:
            return self.build_notice_embed(
                f"Match #{match.match_number:03d} Expired",
                "Voting expired and staff review is now required.",
                error=True,
            )
        return self.build_notice_embed(
            f"Match #{match.match_number:03d}",
            f"{ruleset_label} {match.mode.value.upper()} updated.",
        )

    async def post_match_terminal_notice(self, guild: discord.Guild, snapshot) -> None:
        if snapshot.match.state not in {MatchState.CONFIRMED, MatchState.CANCELLED, MatchState.FORCE_CLOSED}:
            return
        channel = guild.get_channel(snapshot.match.source_channel_id) if snapshot.match.source_channel_id else None
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return
        try:
            await channel.send(embed=self.build_match_terminal_notice(snapshot))
        except discord.HTTPException:
            self.logger.warning(
                "match_terminal_notice_failed",
                guild_id=guild.id,
                match_id=str(snapshot.match.id),
                source_channel_id=snapshot.match.source_channel_id,
            )

    async def delete_channel_if_exists(self, channel: discord.abc.GuildChannel | None) -> None:
        if channel is None:
            return
        try:
            await channel.delete(reason="Highlight Manger match cleanup")
        except discord.HTTPException:
            return

    async def cleanup_terminal_match_resources(self, guild: discord.Guild, snapshot) -> None:
        if snapshot.match.state not in {MatchState.CONFIRMED, MatchState.CANCELLED, MatchState.FORCE_CLOSED}:
            return
        result_channel = guild.get_channel(snapshot.match.result_channel_id) if snapshot.match.result_channel_id else None
        team1_channel = guild.get_channel(snapshot.match.team1_voice_channel_id) if snapshot.match.team1_voice_channel_id else None
        team2_channel = guild.get_channel(snapshot.match.team2_voice_channel_id) if snapshot.match.team2_voice_channel_id else None
        await self.delete_channel_if_exists(result_channel)
        await self.delete_channel_if_exists(team1_channel)
        await self.delete_channel_if_exists(team2_channel)

    async def finalize_terminal_match(self, guild: discord.Guild, snapshot) -> None:
        await self.refresh_match_messages(guild, snapshot)
        await self.post_match_terminal_notice(guild, snapshot)
        await self.cleanup_terminal_match_resources(guild, snapshot)

    async def announce_match_created(self, guild: discord.Guild, snapshot) -> None:
        channel = guild.get_channel(snapshot.match.source_channel_id) if snapshot.match.source_channel_id else None
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return
        result_room = f"<#{snapshot.match.result_channel_id}>" if snapshot.match.result_channel_id else "the match room"
        try:
            await channel.send(
                content="@here",
                embed=self.build_notice_embed(
                    f"Official Match #{snapshot.match.match_number:03d}",
                    (
                        f"{snapshot.match.ruleset_key.value.title()} {snapshot.match.mode.value.upper()} is now live.\n"
                        f"Use {result_room} for room access, result voting, and live match updates."
                    ),
                ),
                allowed_mentions=discord.AllowedMentions(everyone=True),
            )
        except discord.HTTPException:
            self.logger.warning(
                "match_announcement_failed",
                guild_id=guild.id,
                match_id=str(snapshot.match.id),
                source_channel_id=snapshot.match.source_channel_id,
            )

    async def publish_storefront_section(self, guild: discord.Guild, guild_id: int, repos, section: ShopSection) -> int | None:
        configs = await self.ensure_storefront_sections(guild, repos, guild_id)
        config = configs[section]
        if config.channel_id is None:
            return None
        channel = guild.get_channel(config.channel_id)
        if not isinstance(channel, discord.TextChannel):
            return None
        items = await self.runtime.services.shop.list_section_items(repos.shop, guild_id, section)
        embed = build_storefront_section_embed(
            section=section,
            config=config,
            items=items,
            shop_service=self.runtime.services.shop,
        )
        view = self.build_storefront_order_view(section)
        message_id = await self.upsert_storefront_message(channel, config.showcase_message_id, embed, view)
        await self.cleanup_stale_storefront_messages(channel, section, keep_message_id=message_id)
        if config.showcase_message_id != message_id:
            await self.runtime.services.shop.update_section_config(
                repos.shop,
                guild_id=guild_id,
                section=section,
                showcase_message_id=message_id,
            )
        return message_id

    async def upsert_storefront_message(
        self,
        channel: discord.TextChannel,
        message_id: int | None,
        embed: discord.Embed,
        view: discord.ui.View,
    ) -> int:
        if message_id:
            try:
                message = await channel.fetch_message(message_id)
                await message.edit(embed=embed, view=view)
                return message.id
            except discord.HTTPException:
                pass
        message = await channel.send(embed=embed, view=view)
        return message.id

    async def cleanup_stale_storefront_messages(self, channel: discord.TextChannel, section: ShopSection, *, keep_message_id: int) -> None:
        me = channel.guild.me
        my_id = me.id if me is not None else None
        signature = f"{STOREFRONT_FOOTER_PREFIX} | {section.value}".casefold()
        try:
            async for message in channel.history(limit=50):
                if message.id == keep_message_id:
                    continue
                if my_id is not None and getattr(message.author, "id", None) != my_id:
                    continue
                if not any(
                    embed.footer and (embed.footer.text or "").casefold() == signature
                    for embed in message.embeds
                ):
                    continue
                try:
                    await message.delete()
                except discord.HTTPException:
                    continue
        except discord.HTTPException:
            return

    async def republish_storefront_sections(
        self,
        guild: discord.Guild,
        guild_id: int,
        repos,
        *sections: ShopSection,
    ) -> None:
        ordered_sections: list[ShopSection] = []
        seen: set[ShopSection] = set()
        for section in sections:
            if section in seen:
                continue
            seen.add(section)
            ordered_sections.append(section)
        for section in ordered_sections:
            try:
                await self.publish_storefront_section(guild, guild_id, repos, section)
            except discord.HTTPException:
                self.logger.warning(
                    "storefront_section_publish_failed",
                    guild_id=guild.id,
                    section=section.value,
                )

    async def ensure_shop_ticket_category(self, guild: discord.Guild) -> discord.CategoryChannel:
        category = discord.utils.find(
            lambda item: isinstance(item, discord.CategoryChannel) and item.name.lower() == "shop tickets",
            guild.channels,
        )
        if isinstance(category, discord.CategoryChannel):
            return category
        return await guild.create_category("Shop Tickets", reason="Highlight Manger storefront ticket setup")

    async def resolve_storefront_item(self, repos, guild_id: int, section: ShopSection, requested_text: str):
        items = await self.runtime.services.shop.list_section_items(repos.shop, guild_id, section)
        normalized = requested_text.strip().casefold()
        if not normalized:
            return items[0] if len(items) == 1 else None
        item_id_match = re.search(r"#(\d+)", requested_text)
        if item_id_match:
            item_id = int(item_id_match.group(1))
            return next((item for item in items if item.id == item_id), None)
        exact = [item for item in items if item.name.strip().casefold() == normalized or item.sku.casefold() == normalized]
        if exact:
            return exact[0]
        partial = [
            item
            for item in items
            if normalized in item.name.strip().casefold()
            or item.name.strip().casefold() in normalized
            or normalized in item.sku.casefold()
        ]
        if len(partial) == 1:
            return partial[0]
        return items[0] if len(items) == 1 else None

    @staticmethod
    def build_storefront_ticket_channel_name(section: ShopSection, member: discord.Member) -> str:
        base_name = re.sub(r"[^a-z0-9-]+", "-", member.display_name.casefold()).strip("-")
        trimmed = (base_name or "buyer")[:16]
        section_name = section.value.replace("sensi-", "sn-")
        return f"shop-{section_name[:10]}-{trimmed}"

    async def handle_storefront_purchase(
        self,
        interaction: discord.Interaction,
        section: ShopSection,
        *,
        requested_item: str,
        details: str,
    ) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return
        started_at = time.monotonic()
        try:
            await self.acknowledge_interaction(
                interaction,
                operation="storefront_purchase",
                started_at=started_at,
                ephemeral=True,
            )
            async with self.runtime.session() as repos:
                bundle = await self.runtime.services.guilds.ensure_guild(repos.guilds, interaction.guild.id, interaction.guild.name)
                await self.ensure_storefront_sections(interaction.guild, repos, bundle.guild.id)
                matched_item = await self.resolve_storefront_item(repos, bundle.guild.id, section, requested_item)
                ticket_category = await self.ensure_shop_ticket_category(interaction.guild)
                staff_roles = await self.runtime.services.guilds.get_staff_roles(repos.guilds, bundle.guild.id)
                overwrites: dict[discord.Role | discord.Member, discord.PermissionOverwrite] = {
                    interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                    interaction.user: discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        read_message_history=True,
                    ),
                }
                if interaction.guild.me is not None:
                    overwrites[interaction.guild.me] = discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        read_message_history=True,
                        embed_links=True,
                        manage_channels=True,
                    )
                for role_id in staff_roles.admin_role_ids | staff_roles.moderator_role_ids:
                    role = interaction.guild.get_role(role_id)
                    if role is None:
                        continue
                    overwrites[role] = discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        read_message_history=True,
                    )
                ticket_channel = await interaction.guild.create_text_channel(
                    self.build_storefront_ticket_channel_name(section, interaction.user),
                    category=ticket_category,
                    overwrites=overwrites,
                    reason="Highlight Manger storefront order",
                )
                await ticket_channel.send(
                    embed=build_storefront_ticket_embed(
                        buyer_mention=interaction.user.mention,
                        section=section,
                        requested_text=requested_item,
                        details_text=details,
                        matched_item=matched_item,
                        shop_service=self.runtime.services.shop,
                    )
                )
            await interaction.edit_original_response(
                embed=self.build_notice_embed(
                    "Shop ticket opened",
                    f"Your private order ticket is {ticket_channel.mention}. Staff will continue there.",
                ),
            )
            self.log_duration(
                "interaction_completed",
                started_at,
                operation="storefront_purchase",
                guild_id=interaction.guild.id,
                section=section.value,
                success=True,
            )
        except HighlightManagerError as exc:
            await self.edit_or_followup_notice(interaction, "Storefront request failed", str(exc), error=True, ephemeral=True)
            self.log_duration(
                "interaction_completed",
                started_at,
                operation="storefront_purchase",
                guild_id=interaction.guild.id,
                section=section.value,
                success=False,
                error=type(exc).__name__,
            )
        except discord.HTTPException as exc:
            await self.edit_or_followup_notice(
                interaction,
                "Storefront request failed",
                "I could not open the private ticket channel right now.",
                error=True,
                ephemeral=True,
            )
            self.log_duration(
                "interaction_completed",
                started_at,
                operation="storefront_purchase",
                guild_id=interaction.guild.id,
                section=section.value,
                success=False,
                error=type(exc).__name__,
            )

    def _register_app_commands(self, *, guild: discord.Object | None = None) -> None:
        admin_group = app_commands.Group(name="admin", description="Highlight Manger admin commands")
        season_group = app_commands.Group(name="season", description="Season controls")
        match_group = app_commands.Group(name="match", description="Match moderation")
        tournament_group = app_commands.Group(name="tournament-admin", description="Tournament administration")

        @admin_group.command(name="set-bot-voice", description="Set the persistent bot voice channel")
        async def set_bot_voice(interaction: discord.Interaction, channel: discord.VoiceChannel) -> None:
            if interaction.guild is None or not isinstance(interaction.user, discord.Member):
                return
            if not await self.is_admin_member(interaction.guild, interaction.user):
                await self.send_interaction_notice(interaction, "Not allowed", "Admins only.", error=True, ephemeral=True)
                return
            started_at = time.monotonic()
            await self.acknowledge_interaction(
                interaction,
                operation="set_bot_voice",
                started_at=started_at,
                ephemeral=True,
            )
            async with self.runtime.session() as repos:
                bundle = await self.runtime.services.guilds.ensure_guild(repos.guilds, interaction.guild.id, interaction.guild.name)
                await self.runtime.services.guilds.update_settings(
                    repos.guilds,
                    discord_guild_id=interaction.guild.id,
                    guild_id=bundle.guild.id,
                    persistent_voice_enabled=True,
                    persistent_voice_channel_id=channel.id,
                    persistent_voice_auto_rejoin=True,
                )
            await self.recovery.restore_persistent_voice(self)
            connected = (
                interaction.guild.voice_client is not None
                and interaction.guild.voice_client.channel is not None
                and interaction.guild.voice_client.channel.id == channel.id
            )
            message = (
                f"The bot joined {channel.mention}."
                if connected
                else f"The bot is configured for {channel.mention}. If it is still not inside, check voice permissions and dependencies."
            )
            await interaction.edit_original_response(embed=self.build_notice_embed("Persistent voice updated", message))
            self.log_duration(
                "interaction_completed",
                started_at,
                operation="set_bot_voice",
                guild_id=interaction.guild.id,
                success=True,
            )

        @admin_group.command(name="disable-bot-voice", description="Disable the persistent bot voice anchor")
        async def disable_bot_voice(interaction: discord.Interaction) -> None:
            if interaction.guild is None or not isinstance(interaction.user, discord.Member):
                return
            if not await self.is_admin_member(interaction.guild, interaction.user):
                await interaction.response.send_message(embed=self.build_notice_embed("Not allowed", "Admins only.", error=True), ephemeral=True)
                return
            async with self.runtime.session() as repos:
                bundle = await self.runtime.services.guilds.ensure_guild(repos.guilds, interaction.guild.id, interaction.guild.name)
                await self.runtime.services.guilds.update_settings(
                    repos.guilds,
                    discord_guild_id=interaction.guild.id,
                    guild_id=bundle.guild.id,
                    persistent_voice_enabled=False,
                    persistent_voice_channel_id=None,
                )
            if interaction.guild.voice_client:
                await interaction.guild.voice_client.disconnect(force=False)
            await self.recovery.restore_persistent_voice(self)
            await interaction.response.send_message(embed=self.build_notice_embed("Persistent voice disabled", "The bot voice anchor is disabled."), ephemeral=True)

        @admin_group.command(name="bot-voice-status", description="Show persistent bot voice status")
        async def bot_voice_status(interaction: discord.Interaction) -> None:
            if interaction.guild is None:
                return
            async with self.runtime.session() as repos:
                bundle = await self.runtime.services.guilds.ensure_guild(repos.guilds, interaction.guild.id, interaction.guild.name)
                settings = bundle.settings
            voice_status = self.recovery.get_voice_status(interaction.guild.id)
            channel_text = f"<#{settings.persistent_voice_channel_id}>" if settings.persistent_voice_channel_id else "Not configured"
            apostado_channels = format_channel_mentions(self.get_ruleset_channel_ids(settings, RulesetKey.APOSTADO))
            highlight_channels = format_channel_mentions(self.get_ruleset_channel_ids(settings, RulesetKey.HIGHLIGHT))
            esport_channels = format_channel_mentions(self.get_ruleset_channel_ids(settings, RulesetKey.ESPORT))
            waiting_channels = format_channel_mentions(self.get_waiting_voice_channel_ids(settings))
            if voice_status is None:
                runtime_lines = "Runtime voice state: `unknown`"
            else:
                runtime_lines = (
                    f"Runtime voice state: `{voice_status.state}`\n"
                    f"Reason: {voice_status.reason or 'None'}"
                )
                if voice_status.retry_in_seconds is not None:
                    runtime_lines += f"\nRetry in: `{voice_status.retry_in_seconds}s`"
                if voice_status.next_retry_at is not None:
                    runtime_lines += f"\nNext retry: <t:{int(voice_status.next_retry_at.timestamp())}:R>"
            await interaction.response.send_message(
                embed=self.build_notice_embed(
                    "Persistent voice status",
                    (
                        f"Enabled: **{settings.persistent_voice_enabled}**\n"
                        f"Bot voice: {channel_text}\n"
                        f"{runtime_lines}\n"
                        f"Apostado text channels: {apostado_channels}\n"
                        f"Highlight text channels: {highlight_channels}\n"
                        f"Esport text channels: {esport_channels}\n"
                        f"Waiting voice channels: {waiting_channels}"
                    ),
                ),
                ephemeral=True,
            )

        @admin_group.command(name="set-apostado-channels", description="Set the text channels allowed for apostado queues")
        @app_commands.describe(channels="Channel mentions or IDs separated by spaces. Use 'clear' to remove the rule.")
        async def set_apostado_channels(interaction: discord.Interaction, channels: str) -> None:
            if interaction.guild is None or not isinstance(interaction.user, discord.Member):
                return
            if not await self.is_admin_member(interaction.guild, interaction.user):
                await interaction.response.send_message(embed=self.build_notice_embed("Not allowed", "Admins only.", error=True), ephemeral=True)
                return
            channel_ids = parse_channel_config_input(channels)
            async with self.runtime.session() as repos:
                bundle = await self.runtime.services.guilds.ensure_guild(repos.guilds, interaction.guild.id, interaction.guild.name)
                await self.runtime.services.guilds.update_settings(
                    repos.guilds,
                    discord_guild_id=interaction.guild.id,
                    guild_id=bundle.guild.id,
                    apostado_channel_ids=serialize_discord_id_list(channel_ids),
                )
            await interaction.response.send_message(
                embed=self.build_notice_embed(
                    "Apostado channels updated",
                    f"Allowed channels: {format_channel_mentions(channel_ids)}",
                ),
                ephemeral=True,
            )

        @admin_group.command(name="set-highlight-channels", description="Set the text channels allowed for highlight queues")
        @app_commands.describe(channels="Channel mentions or IDs separated by spaces. Use 'clear' to remove the rule.")
        async def set_highlight_channels(interaction: discord.Interaction, channels: str) -> None:
            if interaction.guild is None or not isinstance(interaction.user, discord.Member):
                return
            if not await self.is_admin_member(interaction.guild, interaction.user):
                await interaction.response.send_message(embed=self.build_notice_embed("Not allowed", "Admins only.", error=True), ephemeral=True)
                return
            channel_ids = parse_channel_config_input(channels)
            async with self.runtime.session() as repos:
                bundle = await self.runtime.services.guilds.ensure_guild(repos.guilds, interaction.guild.id, interaction.guild.name)
                await self.runtime.services.guilds.update_settings(
                    repos.guilds,
                    discord_guild_id=interaction.guild.id,
                    guild_id=bundle.guild.id,
                    highlight_channel_ids=serialize_discord_id_list(channel_ids),
                )
            await interaction.response.send_message(
                embed=self.build_notice_embed(
                    "Highlight channels updated",
                    f"Allowed channels: {format_channel_mentions(channel_ids)}",
                ),
                ephemeral=True,
            )

        @admin_group.command(name="set-esport-channels", description="Set the text channels allowed for esport queues")
        @app_commands.describe(channels="Channel mentions or IDs separated by spaces. Use 'clear' to remove the rule.")
        async def set_esport_channels(interaction: discord.Interaction, channels: str) -> None:
            if interaction.guild is None or not isinstance(interaction.user, discord.Member):
                return
            if not await self.is_admin_member(interaction.guild, interaction.user):
                await interaction.response.send_message(embed=self.build_notice_embed("Not allowed", "Admins only.", error=True), ephemeral=True)
                return
            channel_ids = parse_channel_config_input(channels)
            async with self.runtime.session() as repos:
                bundle = await self.runtime.services.guilds.ensure_guild(repos.guilds, interaction.guild.id, interaction.guild.name)
                await self.runtime.services.guilds.update_settings(
                    repos.guilds,
                    discord_guild_id=interaction.guild.id,
                    guild_id=bundle.guild.id,
                    esport_channel_ids=serialize_discord_id_list(channel_ids),
                )
            await interaction.response.send_message(
                embed=self.build_notice_embed(
                    "Esport channels updated",
                    f"Allowed channels: {format_channel_mentions(channel_ids)}",
                ),
                ephemeral=True,
            )

        @admin_group.command(name="set-waiting-voice-channels", description="Set one or more waiting voice channels used for player moves")
        @app_commands.describe(channels="Voice channel mentions or IDs separated by spaces. Use 'clear' to remove the rule.")
        async def set_waiting_voice_channels(interaction: discord.Interaction, channels: str) -> None:
            if interaction.guild is None or not isinstance(interaction.user, discord.Member):
                return
            if not await self.is_admin_member(interaction.guild, interaction.user):
                await interaction.response.send_message(embed=self.build_notice_embed("Not allowed", "Admins only.", error=True), ephemeral=True)
                return
            channel_ids = parse_channel_config_input(channels)
            async with self.runtime.session() as repos:
                bundle = await self.runtime.services.guilds.ensure_guild(repos.guilds, interaction.guild.id, interaction.guild.name)
                await self.runtime.services.guilds.update_settings(
                    repos.guilds,
                    discord_guild_id=interaction.guild.id,
                    guild_id=bundle.guild.id,
                    waiting_voice_channel_ids=serialize_discord_id_list(channel_ids),
                    waiting_voice_channel_id=channel_ids[0] if channel_ids else None,
                )
            await interaction.response.send_message(
                embed=self.build_notice_embed(
                    "Waiting voice channels updated",
                    f"Configured waiting voice channels: {format_channel_mentions(channel_ids)}",
                ),
                ephemeral=True,
            )

        @admin_group.command(name="system-status", description="Show active queue and match counts")
        async def system_status(interaction: discord.Interaction) -> None:
            if interaction.guild is None:
                return
            async with self.runtime.session() as repos:
                bundle = await self.runtime.services.guilds.ensure_guild(repos.guilds, interaction.guild.id, interaction.guild.name)
                active_queues = [
                    queue for queue in await repos.matches.list_active_queues() if queue.guild_id == bundle.guild.id
                ]
                active_matches = [
                    match for match in await repos.matches.list_active_matches() if match.guild_id == bundle.guild.id
                ]
                stale_activities = [
                    activity
                    for activity in await repos.profiles.list_non_idle_activities()
                    if (activity.queue_id is not None and activity.queue_id not in {queue.id for queue in active_queues})
                    or (activity.match_id is not None and activity.match_id not in {match.id for match in active_matches})
                ]
            legacy_summary = self.refresh_runtime_health()
            voice_status = self.recovery.get_voice_status(interaction.guild.id)
            scheduler_summary = self.scheduler_worker.last_summary
            cleanup_summary = self.cleanup_worker.last_summary
            legacy_packages = ", ".join(legacy_summary["legacy_packages"][:4]) if legacy_summary["legacy_packages"] else "none"
            await interaction.response.send_message(
                embed=self.build_notice_embed(
                    "System status",
                    (
                        f"Active queues: **{len(active_queues)}**\n"
                        f"Active matches: **{len(active_matches)}**\n"
                        f"Startup: db=`{self.startup_health.get('db_ready')}` / views=`{self.startup_health.get('views_restored')}` / assets=`{self.startup_health.get('assets_warmed')}`\n"
                        f"Runtime: `{self.startup_health.get('canonical_runtime')}` / legacy imports=`{legacy_summary['legacy_import_count']}` ({legacy_packages})\n"
                        f"Command sync: `{self.command_sync_status.get('scope')}` / success=`{self.command_sync_status.get('success')}` / count=`{self.command_sync_status.get('count')}`\n"
                        f"Voice state: `{voice_status.state if voice_status else 'unknown'}`\n"
                        f"Recovery backlog: reminders=`{scheduler_summary.get('room_info_reminders', 0)}` / queue timeouts=`{scheduler_summary.get('room_info_timeouts', 0)}` / captain fallback opens=`{scheduler_summary.get('captain_fallback_opens', 0)}` / result timeouts=`{scheduler_summary.get('result_timeouts', 0)}`\n"
                        f"Cleanup: cleared stale activity rows=`{cleanup_summary.get('cleared_orphaned_activities', 0)}` / missing match resources=`{cleanup_summary.get('missing_match_resources', 0)}` / repaired matches=`{cleanup_summary.get('repaired_matches', 0)}` / reconciled wallets=`{cleanup_summary.get('reconciled_wallets', 0)}`\n"
                        f"Current stale activity rows: **{len(stale_activities)}**"
                    ),
                ),
                ephemeral=True,
            )

        @admin_group.command(name="adjust-coins", description="Add or remove coins from a player's wallet")
        async def adjust_coins(interaction: discord.Interaction, member: discord.Member, amount: int, reason: str) -> None:
            if interaction.guild is None or not isinstance(interaction.user, discord.Member):
                return
            if not await self.is_admin_member(interaction.guild, interaction.user):
                await interaction.response.send_message(embed=self.build_notice_embed("Not allowed", "Admins only.", error=True), ephemeral=True)
                return
            if amount == 0:
                raise ValidationError("Amount must be greater than zero or less than zero.")
            async with self.runtime.session() as repos:
                bundle = await self.runtime.services.guilds.ensure_guild(repos.guilds, interaction.guild.id, interaction.guild.name)
                actor = await self.runtime.services.profiles.ensure_player(
                    repos.profiles,
                    bundle.guild.id,
                    interaction.user.id,
                    display_name=interaction.user.display_name,
                    global_name=interaction.user.global_name,
                    joined_guild_at=interaction.user.joined_at,
                )
                target = await self.runtime.services.profiles.ensure_player(
                    repos.profiles,
                    bundle.guild.id,
                    member.id,
                    display_name=member.display_name,
                    global_name=member.global_name,
                    joined_guild_at=member.joined_at,
                )
                transaction = await self.runtime.services.economy.adjust_balance(
                    repos.economy,
                    player_id=target.id,
                    amount=amount,
                    transaction_type=WalletTransactionType.ADMIN_ADJUSTMENT,
                    idempotency_key=f"admin-adjustment:{interaction.id}",
                    reason=reason,
                    actor_player_id=actor.id,
                )
                await self.runtime.services.moderation.apply_action(
                    repos.moderation,
                    guild_id=bundle.guild.id,
                    player_id=target.id,
                    action_type=ModerationActionType.COIN_ADJUSTMENT,
                    actor_player_id=actor.id,
                    reason=reason,
                )
                await self.runtime.services.moderation.audit(
                    repos.moderation,
                    guild_id=bundle.guild.id,
                    action=AuditAction.COINS_ADJUSTED,
                    entity_type=AuditEntityType.WALLET,
                    entity_id=str(transaction.wallet_id),
                    actor_player_id=actor.id,
                    target_player_id=target.id,
                    reason=reason,
                    metadata_json={"amount": amount, "balance_after": transaction.balance_after},
                )
            delta_text = f"+{amount}" if amount > 0 else str(amount)
            await interaction.response.send_message(
                embed=self.build_notice_embed(
                    "Coins updated",
                    f"{member.mention} was adjusted by **{delta_text}** coins.\nNew balance: **{transaction.balance_after}**",
                ),
                ephemeral=True,
            )

        @admin_group.command(name="set-blacklist", description="Blacklist or unblacklist a player from competitive play")
        async def set_blacklist(interaction: discord.Interaction, member: discord.Member, enabled: bool, reason: str) -> None:
            if interaction.guild is None or not isinstance(interaction.user, discord.Member):
                return
            if not await self.is_admin_member(interaction.guild, interaction.user):
                await interaction.response.send_message(embed=self.build_notice_embed("Not allowed", "Admins only.", error=True), ephemeral=True)
                return
            async with self.runtime.session() as repos:
                bundle = await self.runtime.services.guilds.ensure_guild(repos.guilds, interaction.guild.id, interaction.guild.name)
                actor = await self.runtime.services.profiles.ensure_player(
                    repos.profiles,
                    bundle.guild.id,
                    interaction.user.id,
                    display_name=interaction.user.display_name,
                    global_name=interaction.user.global_name,
                    joined_guild_at=interaction.user.joined_at,
                )
                target = await self.runtime.services.profiles.ensure_player(
                    repos.profiles,
                    bundle.guild.id,
                    member.id,
                    display_name=member.display_name,
                    global_name=member.global_name,
                    joined_guild_at=member.joined_at,
                )
                await self.runtime.services.profiles.set_blacklisted(repos.profiles, target.id, enabled)
                if enabled:
                    await self.runtime.services.moderation.apply_action(
                        repos.moderation,
                        guild_id=bundle.guild.id,
                        player_id=target.id,
                        action_type=ModerationActionType.BLACKLIST,
                        actor_player_id=actor.id,
                        reason=reason,
                    )
                await self.runtime.services.moderation.audit(
                    repos.moderation,
                    guild_id=bundle.guild.id,
                    action=AuditAction.MODERATION_APPLIED,
                    entity_type=AuditEntityType.PLAYER,
                    entity_id=str(target.id),
                    actor_player_id=actor.id,
                    target_player_id=target.id,
                    reason=reason,
                    metadata_json={"blacklisted": enabled},
                )
            status_text = "is now blacklisted from competitive play." if enabled else "is no longer blacklisted."
            await interaction.response.send_message(
                embed=self.build_notice_embed("Blacklist updated", f"{member.mention} {status_text}"),
                ephemeral=True,
            )

        @admin_group.command(name="add-shop-item", description="Create a mixed shop item")
        async def add_shop_item(
            interaction: discord.Interaction,
            sku: str,
            name: str,
            category: str,
            coin_price: Optional[int] = None,
            section: Optional[str] = None,
            description: Optional[str] = None,
            cash_price_text: Optional[str] = None,
            image_url: Optional[str] = None,
            details_text: Optional[str] = None,
            cosmetic_slot: Optional[str] = None,
            repeatable: bool = False,
            sort_order: int = 0,
        ) -> None:
            if interaction.guild is None or not isinstance(interaction.user, discord.Member):
                return
            if not await self.is_admin_member(interaction.guild, interaction.user):
                await interaction.response.send_message(embed=self.build_notice_embed("Not allowed", "Admins only.", error=True), ephemeral=True)
                return
            started_at = time.monotonic()
            await self.acknowledge_interaction(
                interaction,
                operation="add_shop_item",
                started_at=started_at,
                ephemeral=True,
            )
            shop_section = ShopSection.from_input(section) if section else None
            async with self.runtime.session() as repos:
                bundle = await self.runtime.services.guilds.ensure_guild(repos.guilds, interaction.guild.id, interaction.guild.name)
                await self.ensure_storefront_sections(interaction.guild, repos, bundle.guild.id)
                actor = await self.runtime.services.profiles.ensure_player(
                    repos.profiles,
                    bundle.guild.id,
                    interaction.user.id,
                    display_name=interaction.user.display_name,
                    global_name=interaction.user.global_name,
                    joined_guild_at=interaction.user.joined_at,
                )
                item = await self.runtime.services.shop.create_item(
                    repos.shop,
                    guild_id=bundle.guild.id,
                    sku=sku,
                    name=name,
                    category=category,
                    price_coins=coin_price,
                    description=description,
                    cosmetic_slot=cosmetic_slot,
                    repeatable=repeatable,
                    sort_order=sort_order,
                    section=shop_section,
                    cash_price_text=cash_price_text,
                    image_url=image_url,
                    details_text=details_text,
                )
                if shop_section is not None and item.active:
                    await self.republish_storefront_sections(interaction.guild, bundle.guild.id, repos, shop_section)
                await self.runtime.services.moderation.audit(
                    repos.moderation,
                    guild_id=bundle.guild.id,
                    action=AuditAction.SHOP_ITEM_CREATED,
                    entity_type=AuditEntityType.SHOP,
                    entity_id=str(item.id),
                    actor_player_id=actor.id,
                    metadata_json={
                        "sku": item.sku,
                        "active": item.active,
                        "section": shop_section.value if shop_section else None,
                        "price_coins": item.price_coins,
                    },
                )
            section_text = f" in **{shop_section.label}**" if shop_section else ""
            await interaction.edit_original_response(
                embed=self.build_notice_embed(
                    "Shop item created",
                    f"Created **{item.name}** as `#{item.id}` with SKU `{item.sku}`{section_text}.",
                ),
            )

        @admin_group.command(name="set-shop-item-active", description="Enable or disable a shop item")
        async def set_shop_item_active(interaction: discord.Interaction, item_id: int, active: bool, reason: str) -> None:
            if interaction.guild is None or not isinstance(interaction.user, discord.Member):
                return
            if not await self.is_admin_member(interaction.guild, interaction.user):
                await interaction.response.send_message(embed=self.build_notice_embed("Not allowed", "Admins only.", error=True), ephemeral=True)
                return
            started_at = time.monotonic()
            await self.acknowledge_interaction(
                interaction,
                operation="set_shop_item_active",
                started_at=started_at,
                ephemeral=True,
            )
            async with self.runtime.session() as repos:
                bundle = await self.runtime.services.guilds.ensure_guild(repos.guilds, interaction.guild.id, interaction.guild.name)
                await self.ensure_storefront_sections(interaction.guild, repos, bundle.guild.id)
                actor = await self.runtime.services.profiles.ensure_player(
                    repos.profiles,
                    bundle.guild.id,
                    interaction.user.id,
                    display_name=interaction.user.display_name,
                    global_name=interaction.user.global_name,
                    joined_guild_at=interaction.user.joined_at,
                )
                item = await self.runtime.services.shop.set_item_active(
                    repos.shop,
                    guild_id=bundle.guild.id,
                    item_id=item_id,
                    active=active,
                )
                section_key = self.runtime.services.shop.get_item_section(item)
                if section_key is not None:
                    await self.republish_storefront_sections(interaction.guild, bundle.guild.id, repos, section_key)
                await self.runtime.services.moderation.audit(
                    repos.moderation,
                    guild_id=bundle.guild.id,
                    action=AuditAction.SHOP_ITEM_UPDATED,
                    entity_type=AuditEntityType.SHOP,
                    entity_id=str(item.id),
                    actor_player_id=actor.id,
                    reason=reason,
                    metadata_json={"active": item.active, "sku": item.sku},
                )
            state_text = "enabled" if active else "disabled"
            await interaction.edit_original_response(
                embed=self.build_notice_embed("Shop item updated", f"`#{item.id}` is now {state_text}."),
            )

        @admin_group.command(name="update-shop-item", description="Update an existing mixed shop item")
        async def update_shop_item(
            interaction: discord.Interaction,
            item_id: int,
            name: Optional[str] = None,
            category: Optional[str] = None,
            coin_price: Optional[int] = None,
            section: Optional[str] = None,
            description: Optional[str] = None,
            cash_price_text: Optional[str] = None,
            image_url: Optional[str] = None,
            details_text: Optional[str] = None,
            cosmetic_slot: Optional[str] = None,
            repeatable: Optional[bool] = None,
            sort_order: Optional[int] = None,
        ) -> None:
            if interaction.guild is None or not isinstance(interaction.user, discord.Member):
                return
            if not await self.is_admin_member(interaction.guild, interaction.user):
                await interaction.response.send_message(embed=self.build_notice_embed("Not allowed", "Admins only.", error=True), ephemeral=True)
                return
            started_at = time.monotonic()
            await self.acknowledge_interaction(
                interaction,
                operation="update_shop_item",
                started_at=started_at,
                ephemeral=True,
            )
            section_value = ShopSection.from_input(section) if section else None
            async with self.runtime.session() as repos:
                bundle = await self.runtime.services.guilds.ensure_guild(repos.guilds, interaction.guild.id, interaction.guild.name)
                await self.ensure_storefront_sections(interaction.guild, repos, bundle.guild.id)
                actor = await self.runtime.services.profiles.ensure_player(
                    repos.profiles,
                    bundle.guild.id,
                    interaction.user.id,
                    display_name=interaction.user.display_name,
                    global_name=interaction.user.global_name,
                    joined_guild_at=interaction.user.joined_at,
                )
                existing_item = await repos.shop.get_item(item_id)
                if existing_item is None or existing_item.guild_id != bundle.guild.id:
                    raise NotFoundError("Shop item not found.")
                existing_section = self.runtime.services.shop.get_item_section(existing_item)
                update_fields = {}
                if name is not None:
                    update_fields["name"] = name
                if category is not None:
                    update_fields["category"] = category
                if coin_price is not None:
                    update_fields["price_coins"] = coin_price
                if description is not None:
                    update_fields["description"] = description
                if cosmetic_slot is not None:
                    update_fields["cosmetic_slot"] = cosmetic_slot
                if repeatable is not None:
                    update_fields["repeatable"] = repeatable
                if sort_order is not None:
                    update_fields["sort_order"] = sort_order
                if section is not None:
                    update_fields["section"] = section_value
                if image_url is not None:
                    update_fields["image_url"] = image_url
                if cash_price_text is not None:
                    update_fields["cash_price_text"] = cash_price_text
                if details_text is not None:
                    update_fields["details_text"] = details_text
                item = await self.runtime.services.shop.update_item(
                    repos.shop,
                    guild_id=bundle.guild.id,
                    item_id=item_id,
                    **update_fields,
                )
                new_section = self.runtime.services.shop.get_item_section(item)
                sections_to_publish = [section_key for section_key in {existing_section, new_section} if section_key is not None]
                if sections_to_publish:
                    await self.republish_storefront_sections(interaction.guild, bundle.guild.id, repos, *sections_to_publish)
                await self.runtime.services.moderation.audit(
                    repos.moderation,
                    guild_id=bundle.guild.id,
                    action=AuditAction.SHOP_ITEM_UPDATED,
                    entity_type=AuditEntityType.SHOP,
                    entity_id=str(item.id),
                    actor_player_id=actor.id,
                    metadata_json={"sku": item.sku, "section": new_section.value if new_section else None},
                )
            await interaction.edit_original_response(
                embed=self.build_notice_embed("Shop item updated", f"`#{item.id}` was updated successfully."),
            )

        @admin_group.command(name="set-shop-section-channel", description="Configure the storefront channel for a shop section")
        async def set_shop_section_channel(interaction: discord.Interaction, section: str, channel: discord.TextChannel) -> None:
            if interaction.guild is None or not isinstance(interaction.user, discord.Member):
                return
            if not await self.is_admin_member(interaction.guild, interaction.user):
                await interaction.response.send_message(embed=self.build_notice_embed("Not allowed", "Admins only.", error=True), ephemeral=True)
                return
            started_at = time.monotonic()
            await self.acknowledge_interaction(
                interaction,
                operation="set_shop_section_channel",
                started_at=started_at,
                ephemeral=True,
            )
            shop_section = ShopSection.from_input(section)
            async with self.runtime.session() as repos:
                bundle = await self.runtime.services.guilds.ensure_guild(repos.guilds, interaction.guild.id, interaction.guild.name)
                await self.runtime.services.shop.update_section_config(
                    repos.shop,
                    guild_id=bundle.guild.id,
                    section=shop_section,
                    channel_id=channel.id,
                )
                await self.republish_storefront_sections(interaction.guild, bundle.guild.id, repos, shop_section)
            await interaction.edit_original_response(
                embed=self.build_notice_embed(
                    "Section channel updated",
                    f"{shop_section.label} storefront now publishes in {channel.mention}.",
                ),
            )

        @admin_group.command(name="set-shop-section-image", description="Set the showcase image for a shop section")
        async def set_shop_section_image(interaction: discord.Interaction, section: str, image_url: str) -> None:
            if interaction.guild is None or not isinstance(interaction.user, discord.Member):
                return
            if not await self.is_admin_member(interaction.guild, interaction.user):
                await interaction.response.send_message(embed=self.build_notice_embed("Not allowed", "Admins only.", error=True), ephemeral=True)
                return
            started_at = time.monotonic()
            await self.acknowledge_interaction(
                interaction,
                operation="set_shop_section_image",
                started_at=started_at,
                ephemeral=True,
            )
            shop_section = ShopSection.from_input(section)
            async with self.runtime.session() as repos:
                bundle = await self.runtime.services.guilds.ensure_guild(repos.guilds, interaction.guild.id, interaction.guild.name)
                await self.runtime.services.shop.update_section_config(
                    repos.shop,
                    guild_id=bundle.guild.id,
                    section=shop_section,
                    image_url=image_url,
                )
                await self.republish_storefront_sections(interaction.guild, bundle.guild.id, repos, shop_section)
            await interaction.edit_original_response(
                embed=self.build_notice_embed("Section image updated", f"{shop_section.label} showcase image was updated."),
            )

        @admin_group.command(name="set-shop-section-description", description="Set the storefront description for a shop section")
        async def set_shop_section_description(interaction: discord.Interaction, section: str, description: str) -> None:
            if interaction.guild is None or not isinstance(interaction.user, discord.Member):
                return
            if not await self.is_admin_member(interaction.guild, interaction.user):
                await interaction.response.send_message(embed=self.build_notice_embed("Not allowed", "Admins only.", error=True), ephemeral=True)
                return
            started_at = time.monotonic()
            await self.acknowledge_interaction(
                interaction,
                operation="set_shop_section_description",
                started_at=started_at,
                ephemeral=True,
            )
            shop_section = ShopSection.from_input(section)
            async with self.runtime.session() as repos:
                bundle = await self.runtime.services.guilds.ensure_guild(repos.guilds, interaction.guild.id, interaction.guild.name)
                await self.runtime.services.shop.update_section_config(
                    repos.shop,
                    guild_id=bundle.guild.id,
                    section=shop_section,
                    description=description,
                )
                await self.republish_storefront_sections(interaction.guild, bundle.guild.id, repos, shop_section)
            await interaction.edit_original_response(
                embed=self.build_notice_embed("Section description updated", f"{shop_section.label} description was updated."),
            )

        @admin_group.command(name="rename-members", description="Rename members to RANK X | USERNAME")
        async def rename_members(interaction: discord.Interaction) -> None:
            if interaction.guild is None or not isinstance(interaction.user, discord.Member):
                return
            if not await self.is_admin_member(interaction.guild, interaction.user):
                await interaction.response.send_message(embed=self.build_notice_embed("Not allowed", "Admins only.", error=True), ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True, thinking=True)
            progress_state = {
                "last_update": 0.0,
                "last_processed": -1,
            }

            async def update_progress(processed: int, total: int, renamed: int, skipped: int, failed_count: int) -> None:
                now = time.monotonic()
                should_update = (
                    processed == 0
                    or processed == total
                    or processed - progress_state["last_processed"] >= 25
                    or now - progress_state["last_update"] >= 5
                )
                if not should_update:
                    return
                progress_state["last_update"] = now
                progress_state["last_processed"] = processed
                description = (
                    f"Processed **{processed}/{total}** ranked members.\n"
                    f"Renamed: **{renamed}** | Skipped: **{skipped}** | Failed: **{failed_count}**\n"
                    "Discord nickname changes can take a while when many members need updates."
                )
                title = "Rename sync started" if processed == 0 else "Rename sync running"
                await interaction.edit_original_response(
                    embed=self.build_notice_embed(title, description),
                )

            try:
                renamed, skipped, failed = await self.rename_members_to_rank_format(
                    interaction.guild,
                    progress_callback=update_progress,
                )
            except HighlightManagerError as exc:
                await interaction.edit_original_response(
                    embed=self.build_notice_embed("Rename failed", str(exc), error=True),
                )
                return
            summary = f"Renamed **{renamed}** members.\nSkipped **{skipped}** members."
            if failed:
                summary += "\nCould not rename: " + ", ".join(failed[:10])
            await interaction.edit_original_response(
                embed=self.build_notice_embed("Rename complete", summary),
            )

        @season_group.command(name="next", description="Archive the active season and start the next one")
        async def next_season(interaction: discord.Interaction, name: Optional[str] = None) -> None:
            if interaction.guild is None or not isinstance(interaction.user, discord.Member):
                return
            if not await self.is_admin_member(interaction.guild, interaction.user):
                await interaction.response.send_message(embed=self.build_notice_embed("Not allowed", "Admins only.", error=True), ephemeral=True)
                return
            async with self.runtime.session() as repos:
                bundle = await self.runtime.services.guilds.ensure_guild(repos.guilds, interaction.guild.id, interaction.guild.name)
                season = await self.runtime.services.seasons.start_next_season(repos.seasons, bundle.guild.id, bundle.settings, name=name)
            await interaction.response.send_message(embed=self.build_notice_embed("Season created", f"{season.name} is now active."), ephemeral=True)

        @match_group.command(name="force-close", description="Force close a match")
        async def force_close(interaction: discord.Interaction, match_number: int, reason: str) -> None:
            if interaction.guild is None or not isinstance(interaction.user, discord.Member):
                return
            if not await self.is_staff_member(interaction.guild, interaction.user):
                await interaction.response.send_message(embed=self.build_notice_embed("Not allowed", "Staff only.", error=True), ephemeral=True)
                return
            async with self.runtime.session() as repos:
                bundle = await self.runtime.services.guilds.ensure_guild(repos.guilds, interaction.guild.id, interaction.guild.name)
                actor = await self.runtime.services.profiles.ensure_player(repos.profiles, bundle.guild.id, interaction.user.id)
                match = await repos.matches.get_match_by_number(bundle.guild.id, match_number)
                if match is None:
                    raise NotFoundError("Match not found.")
                await self.runtime.services.matches.force_close_match(
                    repos.matches,
                    repos.profiles,
                    repos.moderation,
                    match_id=match.id,
                    actor_player_id=actor.id,
                    reason=reason,
                )
            await interaction.response.send_message(embed=self.build_notice_embed("Force close applied", f"Match #{match_number:03d} was force closed."), ephemeral=True)

        @match_group.command(name="force-result", description="Force confirm a match result")
        async def force_result(interaction: discord.Interaction, match_number: int, winner_team: int, winner_mvp: Optional[str] = None, loser_mvp: Optional[str] = None) -> None:
            if interaction.guild is None or not isinstance(interaction.user, discord.Member):
                return
            if not await self.is_staff_member(interaction.guild, interaction.user):
                await interaction.response.send_message(embed=self.build_notice_embed("Not allowed", "Staff only.", error=True), ephemeral=True)
                return
            async with self.runtime.session() as repos:
                bundle = await self.runtime.services.guilds.ensure_guild(repos.guilds, interaction.guild.id, interaction.guild.name)
                actor = await self.runtime.services.profiles.ensure_player(repos.profiles, bundle.guild.id, interaction.user.id)
                match = await repos.matches.get_match_by_number(bundle.guild.id, match_number)
                if match is None:
                    raise NotFoundError("Match not found.")
                await self.runtime.services.matches.confirm_match(
                    repos.matches,
                    repos.profiles,
                    repos.seasons,
                    repos.ranks,
                    repos.economy,
                    repos.moderation,
                    match_id=match.id,
                    winner_team_number=winner_team,
                    winner_mvp_player_id=parse_optional_player_reference(winner_mvp),
                    loser_mvp_player_id=parse_optional_player_reference(loser_mvp),
                    actor_player_id=actor.id,
                    source="force_result",
                )
            await interaction.response.send_message(embed=self.build_notice_embed("Force result applied", f"Match #{match_number:03d} was confirmed."), ephemeral=True)

        @tournament_group.command(name="create", description="Create a single-elimination tournament")
        async def tournament_create(interaction: discord.Interaction, name: str, team_size: int, max_teams: int) -> None:
            if interaction.guild is None or not isinstance(interaction.user, discord.Member):
                return
            if not await self.is_staff_member(interaction.guild, interaction.user):
                await interaction.response.send_message(embed=self.build_notice_embed("Not allowed", "Staff only.", error=True), ephemeral=True)
                return
            async with self.runtime.session() as repos:
                bundle = await self.runtime.services.guilds.ensure_guild(repos.guilds, interaction.guild.id, interaction.guild.name)
                season = await self.runtime.services.seasons.ensure_active(repos.seasons, bundle.guild.id, bundle.settings)
                actor = await self.runtime.services.profiles.ensure_player(repos.profiles, bundle.guild.id, interaction.user.id)
                tournament = await self.runtime.services.tournaments.create_tournament(
                    repos.tournaments,
                    repos.moderation,
                    guild_id=bundle.guild.id,
                    season_id=season.id,
                    name=name,
                    team_size=team_size,
                    max_teams=max_teams,
                    actor_player_id=actor.id,
                )
            await interaction.response.send_message(embed=self.build_notice_embed("Tournament created", f"{tournament.name} is open for registration."), ephemeral=True)

        @tournament_group.command(name="start", description="Start the latest active tournament")
        async def tournament_start(interaction: discord.Interaction) -> None:
            if interaction.guild is None or not isinstance(interaction.user, discord.Member):
                return
            if not await self.is_staff_member(interaction.guild, interaction.user):
                await interaction.response.send_message(embed=self.build_notice_embed("Not allowed", "Staff only.", error=True), ephemeral=True)
                return
            async with self.runtime.session() as repos:
                bundle = await self.runtime.services.guilds.ensure_guild(repos.guilds, interaction.guild.id, interaction.guild.name)
                tournament = await repos.tournaments.get_latest_active(bundle.guild.id)
                if tournament is None:
                    raise NotFoundError("No active tournament found.")
                await self.runtime.services.tournaments.start_tournament(repos.tournaments, tournament_id=tournament.id)
            await interaction.response.send_message(embed=self.build_notice_embed("Tournament started", f"{tournament.name} is now live."), ephemeral=True)

        self.tree.add_command(admin_group, guild=guild)
        self.tree.add_command(season_group, guild=guild)
        self.tree.add_command(match_group, guild=guild)
        self.tree.add_command(tournament_group, guild=guild)


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    bot = HighlightBot()

    @bot.tree.error
    async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        original = getattr(error, "original", error)
        if isinstance(original, HighlightManagerError):
            bot.logger.warning(
                "app_command_failed",
                command=interaction.command.qualified_name if interaction.command else None,
                guild_id=interaction.guild.id if interaction.guild else None,
                channel_id=interaction.channel_id,
                user_id=interaction.user.id if interaction.user else None,
                error=str(original),
            )
            try:
                await interaction.response.send_message(
                    embed=bot.build_notice_embed("Command failed", str(original), error=True),
                    ephemeral=True,
                )
            except discord.InteractionResponded:
                await interaction.followup.send(
                    embed=bot.build_notice_embed("Command failed", str(original), error=True),
                    ephemeral=True,
                )
            return
        bot.logger.exception(
            "app_command_error",
            command=interaction.command.qualified_name if interaction.command else None,
            guild_id=interaction.guild.id if interaction.guild else None,
            channel_id=interaction.channel_id,
            user_id=interaction.user.id if interaction.user else None,
            error=str(original),
        )
        try:
            await interaction.response.send_message(
                embed=bot.build_notice_embed("Command failed", "Something went wrong.", error=True),
                ephemeral=True,
            )
        except discord.InteractionResponded:
            await interaction.followup.send(
                embed=bot.build_notice_embed("Command failed", "Something went wrong.", error=True),
                ephemeral=True,
            )

    bot.run(settings.discord_token, log_handler=None)
