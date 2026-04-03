from __future__ import annotations

from dataclasses import dataclass
import re

import discord

from highlight_manager.models.enums import ShopSection
from highlight_manager.models.shop import ShopConfig, ShopItem
from highlight_manager.repositories.shop_repository import ShopConfigRepository, ShopItemRepository
from highlight_manager.services.config_service import ConfigService
from highlight_manager.utils.dates import utcnow
from highlight_manager.utils.exceptions import UserFacingError
from highlight_manager.utils.shop_embeds import build_shop_navigation_embed, build_shop_section_embed
from highlight_manager.interactions.shop_views import build_order_view


@dataclass(slots=True)
class ShopSetupResult:
    config: ShopConfig
    created_resources: list[str]
    reused_resources: list[str]
    published_sections: list[str]


@dataclass(slots=True)
class ShopPublishResult:
    config: ShopConfig
    announcement_warning: str | None = None


class ShopService:
    SHOP_CATEGORY_NAME = "Highlight Shop"
    ORDER_CHANNEL_NAME = "shop-orders"
    TICKET_CATEGORY_NAME = "Shop Tickets"

    def __init__(
        self,
        config_repository: ShopConfigRepository,
        item_repository: ShopItemRepository,
        config_service: ConfigService | None = None,
    ) -> None:
        self.config_repository = config_repository
        self.item_repository = item_repository
        self.config_service = config_service

    async def get_or_create_config(self, guild_id: int) -> ShopConfig:
        existing = await self.config_repository.get(guild_id)
        if existing:
            changed = False
            for section in ShopSection:
                if not existing.section_descriptions.get(section.value):
                    existing.section_descriptions[section.value] = self.default_section_description(section)
                    changed = True
            if changed:
                existing = await self.config_repository.upsert(existing)
            return existing
        config = ShopConfig(
            guild_id=guild_id,
            section_descriptions={section.value: self.default_section_description(section) for section in ShopSection},
        )
        return await self.config_repository.upsert(config)

    async def setup(self, guild: discord.Guild) -> ShopSetupResult:
        config = await self.get_or_create_config(guild.id)
        created_resources: list[str] = []
        reused_resources: list[str] = []
        published_sections: list[str] = []
        discovered_channels = {
            section.value: self._find_section_channel(guild, section)
            for section in ShopSection
        }
        prefer_existing = bool(config.section_channel_ids) or any(channel is not None for channel in discovered_channels.values())

        category = guild.get_channel(config.category_channel_id) if config.category_channel_id else None
        if not isinstance(category, discord.CategoryChannel):
            category = self._find_shop_category(guild, discovered_channels)
        if isinstance(category, discord.CategoryChannel):
            reused_resources.append(f"Shop Category: **{category.name}**")
        elif not prefer_existing:
            category = await guild.create_category(self.SHOP_CATEGORY_NAME, reason="Highlight Manager shop setup")
            created_resources.append(f"Shop Category: **{category.name}**")

        order_channel = guild.get_channel(config.order_channel_id) if config.order_channel_id else None
        if not isinstance(order_channel, discord.TextChannel):
            order_channel = discord.utils.find(
                lambda item: isinstance(item, discord.TextChannel) and item.name.lower() == self.ORDER_CHANNEL_NAME.lower(),
                guild.channels,
            )
        if isinstance(order_channel, discord.TextChannel):
            reused_resources.append(f"Legacy Order Channel: {order_channel.mention}")

        ticket_category = guild.get_channel(config.ticket_category_id) if config.ticket_category_id else None
        if not isinstance(ticket_category, discord.CategoryChannel):
            ticket_category = discord.utils.find(
                lambda item: isinstance(item, discord.CategoryChannel) and item.name.lower() == self.TICKET_CATEGORY_NAME.lower(),
                guild.channels,
            )
        if isinstance(ticket_category, discord.CategoryChannel):
            reused_resources.append(f"Ticket Category: **{ticket_category.name}**")
        else:
            ticket_category = await guild.create_category(self.TICKET_CATEGORY_NAME, reason="Highlight Manager shop setup")
            created_resources.append(f"Ticket Category: **{ticket_category.name}**")

        section_channel_ids: dict[str, int] = {}
        for section in ShopSection:
            configured_channel = guild.get_channel(config.section_channel_ids.get(section.value))
            channel = configured_channel if isinstance(configured_channel, discord.TextChannel) else discovered_channels.get(section.value)
            if isinstance(channel, discord.TextChannel):
                reused_resources.append(f"{section.label}: {channel.mention}")
            elif not prefer_existing and isinstance(category, discord.CategoryChannel):
                channel = await guild.create_text_channel(
                    section.value,
                    category=category,
                    reason=f"Highlight Manager shop setup for {section.label}",
                )
                created_resources.append(f"{section.label}: {channel.mention}")
            else:
                continue
            section_channel_ids[section.value] = channel.id

        if isinstance(category, discord.CategoryChannel):
            config.category_channel_id = category.id
        if isinstance(order_channel, discord.TextChannel):
            config.order_channel_id = order_channel.id
        if isinstance(ticket_category, discord.CategoryChannel):
            config.ticket_category_id = ticket_category.id
        config.section_channel_ids = section_channel_ids
        config = await self.config_repository.upsert(config)
        await self.ensure_default_items(guild.id)
        for section in ShopSection:
            if config.section_channel_ids.get(section.value):
                await self.post_section(guild, section, ping_everyone=True)
                published_sections.append(section.label)
        return ShopSetupResult(
            config=config,
            created_resources=created_resources,
            reused_resources=reused_resources,
            published_sections=published_sections,
        )

    async def set_section_image(self, guild_id: int, section: ShopSection, image_url: str) -> ShopConfig:
        config = await self.get_or_create_config(guild_id)
        config.section_image_urls[section.value] = image_url
        return await self.config_repository.upsert(config)

    async def set_section_description(self, guild_id: int, section: ShopSection, description: str) -> ShopConfig:
        config = await self.get_or_create_config(guild_id)
        config.section_descriptions[section.value] = description
        return await self.config_repository.upsert(config)

    async def set_section_channel(self, guild_id: int, section: ShopSection, channel_id: int) -> ShopConfig:
        config = await self.get_or_create_config(guild_id)
        config.section_channel_ids[section.value] = channel_id
        return await self.config_repository.upsert(config)

    async def set_order_channel(self, guild_id: int, channel_id: int) -> ShopConfig:
        config = await self.get_or_create_config(guild_id)
        config.order_channel_id = channel_id
        return await self.config_repository.upsert(config)

    async def set_ticket_category(self, guild_id: int, category_id: int) -> ShopConfig:
        config = await self.get_or_create_config(guild_id)
        config.ticket_category_id = category_id
        return await self.config_repository.upsert(config)

    async def create_item(
        self,
        guild_id: int,
        *,
        section: ShopSection,
        title: str,
        description: str,
        image_url: str | None,
        metadata_text: str | None,
        category_label: str | None,
        cash_price_text: str | None,
        coin_price: int | None,
        display_order: int | None = None,
    ) -> ShopItem:
        latest = await self.item_repository.get_latest_item(guild_id)
        item_id = (latest.item_id + 1) if latest else 1
        if display_order is None:
            display_order = len(await self.item_repository.list_for_section(guild_id, section.value, active_only=False)) + 1
        item = ShopItem(
            guild_id=guild_id,
            item_id=item_id,
            section=section,
            title=title,
            description=description,
            image_url=image_url,
            metadata_text=metadata_text,
            category_label=category_label,
            cash_price_text=cash_price_text,
            coin_price=coin_price,
            display_order=display_order,
        )
        return await self.item_repository.create(item)

    async def edit_item(
        self,
        guild_id: int,
        item_id: int,
        *,
        title: str | None = None,
        description: str | None = None,
        image_url: str | None = None,
        metadata_text: str | None = None,
        category_label: str | None = None,
        cash_price_text: str | None = None,
        coin_price: int | None = None,
        active: bool | None = None,
        display_order: int | None = None,
    ) -> ShopItem:
        item = await self.require_item(guild_id, item_id)
        if title is not None:
            item.title = title
        if description is not None:
            item.description = description
        if image_url is not None:
            item.image_url = image_url
        if metadata_text is not None:
            item.metadata_text = metadata_text
        if category_label is not None:
            item.category_label = category_label
        if cash_price_text is not None:
            item.cash_price_text = cash_price_text
        if coin_price is not None:
            item.coin_price = coin_price
        if active is not None:
            item.active = active
        if display_order is not None:
            item.display_order = display_order
        item.updated_at = utcnow()
        return await self.item_repository.replace(item)

    async def archive_item(self, guild_id: int, item_id: int) -> ShopItem:
        item = await self.require_item(guild_id, item_id)
        item.active = False
        item.updated_at = utcnow()
        return await self.item_repository.replace(item)

    async def require_item(self, guild_id: int, item_id: int) -> ShopItem:
        item = await self.item_repository.get(guild_id, item_id)
        if item is None:
            raise UserFacingError(f"Shop item #{item_id} was not found.")
        return item

    async def post_section(
        self,
        guild: discord.Guild,
        section: ShopSection,
        *,
        ping_everyone: bool = False,
    ) -> ShopPublishResult:
        await self.ensure_default_items(guild.id)
        config = await self.get_or_create_config(guild.id)
        channel = self._resolve_section_channel(guild, config, section)
        items = await self.item_repository.list_for_section(guild.id, section.value)
        showcase_embed = build_shop_section_embed(
            section,
            config.section_descriptions.get(section.value, self.default_section_description(section)),
            image_url=config.section_image_urls.get(section.value),
            items=items,
        )
        showcase_view = build_order_view(guild.id, config.order_channel_id, section=section, label="Buy here")
        warning: str | None = None
        if ping_everyone:
            warning = self._everyone_warning(guild, channel)
        showcase_message_id = await self._publish_section_message(
            channel,
            config.section_showcase_message_ids.get(section.value),
            showcase_embed,
            showcase_view,
            section=section,
            ping_everyone=ping_everyone and warning is None,
        )
        await self._cleanup_stale_section_posts(channel, section, keep_message_id=showcase_message_id)
        config.section_showcase_message_ids[section.value] = showcase_message_id

        existing_featured_ids = list(config.section_featured_message_ids.get(section.value, []))
        for old_message_id in existing_featured_ids:
            await self._delete_message_if_exists(channel, old_message_id)
        config.section_featured_message_ids[section.value] = []
        config = await self.config_repository.upsert(config)
        return ShopPublishResult(config=config, announcement_warning=warning)

    async def publish_section_update(self, guild: discord.Guild, section: ShopSection) -> ShopPublishResult:
        return await self.post_section(guild, section, ping_everyone=True)

    async def reconcile_configured_sections(self, guild: discord.Guild) -> None:
        config = await self.get_or_create_config(guild.id)
        if not config.section_channel_ids:
            return
        await self.ensure_default_items(guild.id)
        for section in ShopSection:
            if not config.section_channel_ids.get(section.value):
                continue
            try:
                await self.post_section(guild, section)
            except UserFacingError:
                continue

    async def build_navigation_embed(self, guild: discord.Guild) -> discord.Embed:
        config = await self.get_or_create_config(guild.id)
        lines: list[str] = []
        for section in ShopSection:
            channel_id = config.section_channel_ids.get(section.value)
            channel = guild.get_channel(channel_id) if channel_id else None
            if isinstance(channel, discord.TextChannel):
                lines.append(f"**{section.label}** -> {channel.mention}")
            else:
                lines.append(f"**{section.label}** -> Not configured")
        return build_shop_navigation_embed(lines)

    async def list_coin_items(self, guild_id: int) -> list[ShopItem]:
        await self.ensure_default_items(guild_id)
        return await self.item_repository.list_coin_items(guild_id)

    async def list_section_items(self, guild_id: int, section: ShopSection) -> list[ShopItem]:
        await self.ensure_default_items(guild_id)
        return await self.item_repository.list_for_section(guild_id, section.value)

    async def ensure_default_items(self, guild_id: int) -> None:
        for section in ShopSection:
            existing = await self.item_repository.list_for_section(guild_id, section.value, active_only=False)
            if existing:
                continue
            for template in self._default_item_templates(section):
                await self.create_item(
                    guild_id,
                    section=section,
                    title=template["title"],
                    description=template["description"],
                    image_url=None,
                    metadata_text=template.get("metadata_text"),
                    category_label=template.get("category_label"),
                    cash_price_text=template.get("cash_price_text"),
                    coin_price=template.get("coin_price"),
                    display_order=template["display_order"],
                )

    async def resolve_requested_item(
        self,
        guild_id: int,
        section: ShopSection,
        requested_text: str,
    ) -> ShopItem | None:
        items = await self.list_section_items(guild_id, section)
        normalized = requested_text.strip().casefold()
        if not normalized:
            return items[0] if len(items) == 1 else None

        item_id_match = re.search(r"#(\d+)", requested_text)
        if item_id_match:
            item_id = int(item_id_match.group(1))
            for item in items:
                if item.item_id == item_id:
                    return item

        exact = [item for item in items if item.title.strip().casefold() == normalized]
        if exact:
            return exact[0]

        partial = [item for item in items if item.title.strip().casefold() in normalized or normalized in item.title.strip().casefold()]
        if len(partial) == 1:
            return partial[0]
        return items[0] if len(items) == 1 else None

    async def get_section_channel(self, guild: discord.Guild, section: ShopSection) -> discord.TextChannel | None:
        config = await self.get_or_create_config(guild.id)
        channel_id = config.section_channel_ids.get(section.value)
        channel = guild.get_channel(channel_id) if channel_id else None
        return channel if isinstance(channel, discord.TextChannel) else None

    async def create_purchase_ticket(
        self,
        guild: discord.Guild,
        buyer: discord.Member,
        *,
        section: ShopSection,
        item: ShopItem | None,
        requested_text: str,
        details: str,
        remaining_balance: str | None = None,
    ) -> discord.TextChannel:
        if self.config_service is None:
            raise UserFacingError("Shop ticket creation is not available right now.")
        shop_config, ticket_category = await self._ensure_ticket_category(guild)
        guild_config = await self.config_service.get_or_create(guild.id)

        ticket_number = shop_config.next_ticket_number
        shop_config.next_ticket_number += 1
        shop_config = await self.config_repository.upsert(shop_config)

        overwrites: dict[discord.Role | discord.Member, discord.PermissionOverwrite] = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
        }
        if guild.me:
            overwrites[guild.me] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                embed_links=True,
                manage_channels=True,
            )
        staff_roles: list[discord.Role] = []
        for role_id in {*(guild_config.admin_role_ids or []), *(guild_config.staff_role_ids or [])}:
            role = guild.get_role(role_id)
            if role is None:
                continue
            staff_roles.append(role)
            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
            )
        overwrites[buyer] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
        )

        channel = await guild.create_text_channel(
            name=f"shop-ticket-{ticket_number:03d}",
            category=ticket_category,
            overwrites=overwrites,
            topic=(
                f"Shop ticket #{ticket_number:03d} | Buyer: {buyer.id} | Item: {item.item_id}"
                if item is not None
                else f"Shop ticket #{ticket_number:03d} | Buyer: {buyer.id} | Requested: {requested_text[:60]}"
            ),
            reason=f"Shop ticket #{ticket_number:03d} for {buyer.id}",
        )
        mentions = [buyer.mention, *[role.mention for role in staff_roles]]
        from highlight_manager.utils.shop_embeds import build_shop_ticket_embed

        try:
            await channel.send(
                content=" ".join(mention for mention in mentions if mention).strip() or None,
                embed=build_shop_ticket_embed(
                    buyer=buyer,
                    section=section,
                    item=item,
                    requested_text=requested_text,
                    details=details,
                    remaining_balance=remaining_balance,
                    ticket_number=ticket_number,
                ),
            )
        except discord.HTTPException:
            try:
                await channel.delete(reason=f"Rolling back failed shop ticket #{ticket_number:03d}")
            except discord.HTTPException:
                pass
            raise
        return channel

    def default_section_description(self, section: ShopSection) -> str:
        descriptions = {
            ShopSection.DEVELOPE: (
                "Premium development services for serious clients.\n"
                "Discord bot source code, custom bot systems, and polished portfolio websites."
            ),
            ShopSection.OPTIMIZE_TOOL: (
                "Aggressive Windows optimization tools focused on performance.\n"
                "Built for players who want stronger tuning, cleanup, and system boost."
            ),
            ShopSection.VIDEO_EDIT: (
                "Professional video editing with 3 main tiers.\n"
                "Short-form edits, 5 to 9 minute edits, and 10 to 30 minute premium edits."
            ),
            ShopSection.SENSI_PC: (
                "Free Fire PC sensitivity setup.\n"
                "Includes mouse DPI, emulator version, and X/Y sensitivity details."
            ),
            ShopSection.SENSI_IPHONE: (
                "Free Fire iPhone sensitivity setup.\n"
                "Mobile-only sensitivity values without emulator or DPI settings."
            ),
            ShopSection.SENSI_ANDROID: (
                "Free Fire Android sensitivity setup.\n"
                "Mobile-only sensitivity values without emulator or DPI settings."
            ),
        }
        return descriptions[section]

    async def _publish_section_message(
        self,
        channel: discord.TextChannel,
        message_id: int | None,
        embed: discord.Embed,
        view: discord.ui.View | None,
        *,
        section: ShopSection,
        ping_everyone: bool,
    ) -> int:
        content = f"@everyone {section.label} shop updated." if ping_everyone else None
        allowed_mentions = discord.AllowedMentions(everyone=ping_everyone)
        if message_id and not ping_everyone:
            try:
                message = await channel.fetch_message(message_id)
                await message.edit(content=content, embed=embed, view=view)
                return message.id
            except discord.NotFound:
                pass
        if message_id and ping_everyone:
            await self._delete_message_if_exists(channel, message_id)
        message = await channel.send(content=content, embed=embed, view=view, allowed_mentions=allowed_mentions)
        return message.id

    async def _delete_message_if_exists(self, channel: discord.TextChannel, message_id: int) -> None:
        try:
            message = await channel.fetch_message(message_id)
            await message.delete()
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return

    async def _cleanup_stale_section_posts(
        self,
        channel: discord.TextChannel,
        section: ShopSection,
        *,
        keep_message_id: int,
    ) -> None:
        if not hasattr(channel, "history"):
            return
        me = getattr(channel.guild, "me", None)
        my_id = getattr(me, "id", None)
        try:
            async for message in channel.history(limit=50):
                if message.id == keep_message_id:
                    continue
                if my_id is not None and getattr(message.author, "id", None) != my_id:
                    continue
                if not self._looks_like_section_shop_post(message, section):
                    continue
                try:
                    await message.delete()
                except (discord.Forbidden, discord.HTTPException):
                    continue
        except (AttributeError, discord.Forbidden, discord.HTTPException):
            return

    def _looks_like_section_shop_post(self, message: discord.Message, section: ShopSection) -> bool:
        if any(
            getattr(component, "label", None) == "Buy here"
            for row in getattr(message, "components", [])
            for component in getattr(row, "children", [])
        ):
            return True
        for embed in getattr(message, "embeds", []):
            title = (embed.title or "").casefold()
            footer = (embed.footer.text if embed.footer else "").casefold()
            if section.label.casefold() in title and "premium showcase" in title:
                return True
            if footer.startswith("highlight manager shop"):
                return True
        return False

    async def _ensure_ticket_category(self, guild: discord.Guild) -> tuple[ShopConfig, discord.CategoryChannel]:
        config = await self.get_or_create_config(guild.id)
        category = guild.get_channel(config.ticket_category_id) if config.ticket_category_id else None
        if not isinstance(category, discord.CategoryChannel):
            category = discord.utils.find(
                lambda item: isinstance(item, discord.CategoryChannel) and item.name.lower() == self.TICKET_CATEGORY_NAME.lower(),
                guild.channels,
            )
        if not isinstance(category, discord.CategoryChannel):
            category = await guild.create_category(self.TICKET_CATEGORY_NAME, reason="Highlight Manager shop tickets")
        if category.id != config.ticket_category_id:
            config.ticket_category_id = category.id
            config = await self.config_repository.upsert(config)
        return config, category

    def _resolve_section_channel(
        self,
        guild: discord.Guild,
        config: ShopConfig,
        section: ShopSection,
    ) -> discord.TextChannel:
        channel_id = config.section_channel_ids.get(section.value)
        channel = guild.get_channel(channel_id) if channel_id else None
        if not isinstance(channel, discord.TextChannel):
            raise UserFacingError(f"{section.label} channel is not configured. Run /shop setup first.")
        return channel

    def _find_shop_category(
        self,
        guild: discord.Guild,
        discovered_channels: dict[str, discord.TextChannel | None],
    ) -> discord.CategoryChannel | None:
        category = discord.utils.find(
            lambda item: isinstance(item, discord.CategoryChannel)
            and self._normalize_name(item.name) in {"shop", "highlightshop"},
            guild.channels,
        )
        if isinstance(category, discord.CategoryChannel):
            return category
        channel_categories = [channel.category for channel in discovered_channels.values() if isinstance(channel, discord.TextChannel) and isinstance(channel.category, discord.CategoryChannel)]
        return channel_categories[0] if channel_categories else None

    def _find_section_channel(self, guild: discord.Guild, section: ShopSection) -> discord.TextChannel | None:
        aliases = {self._normalize_name(section.value), *self._section_aliases(section)}
        candidates = [
            channel
            for channel in guild.channels
            if isinstance(channel, discord.TextChannel) and any(alias in self._normalize_name(channel.name) for alias in aliases)
        ]
        if not candidates:
            return None
        shop_category_matches = [channel for channel in candidates if isinstance(channel.category, discord.CategoryChannel) and "shop" in self._normalize_name(channel.category.name)]
        return shop_category_matches[0] if shop_category_matches else candidates[0]

    @staticmethod
    def _normalize_name(value: str) -> str:
        return "".join(character for character in value.casefold() if character.isalnum())

    def _section_aliases(self, section: ShopSection) -> set[str]:
        return {
            ShopSection.DEVELOPE: {"develope", "develop", "development"},
            ShopSection.OPTIMIZE_TOOL: {"optimizetool", "optimize", "optimizationtool", "optimization"},
            ShopSection.VIDEO_EDIT: {"videoedit", "video", "edit", "videoeditor"},
            ShopSection.SENSI_PC: {"sensipc", "pcsensi", "pcsensitivity"},
            ShopSection.SENSI_IPHONE: {"sensiiphone", "iphonesensi", "iphonesensitivity"},
            ShopSection.SENSI_ANDROID: {"sensiandroid", "androidsensi", "androidsensitivity"},
        }[section]

    def _everyone_warning(
        self,
        guild: discord.Guild,
        channel: discord.TextChannel,
    ) -> str | None:
        me = guild.me
        permissions = channel.permissions_for(me) if me is not None else None
        if permissions is not None and not permissions.mention_everyone:
            return "Shop was updated, but I do not have permission to ping @everyone in that channel."
        return None

    def _default_item_templates(self, section: ShopSection) -> list[dict[str, object]]:
        defaults = {
            ShopSection.DEVELOPE: [
                {
                    "display_order": 1,
                    "title": "Discord Bot Source Code",
                    "description": "Ready bot source packages and custom competitive bot systems.",
                    "category_label": "Development",
                },
                {
                    "display_order": 2,
                    "title": "Portfolio Website",
                    "description": "Premium portfolio websites and clean personal brand pages.",
                    "category_label": "Development",
                },
                {
                    "display_order": 3,
                    "title": "Custom Development Service",
                    "description": "Custom bot features, systems, and premium web work on request.",
                    "category_label": "Development",
                },
            ],
            ShopSection.OPTIMIZE_TOOL: [
                {
                    "display_order": 1,
                    "title": "Windows Optimization Tool",
                    "description": "Aggressive Windows optimization focused on performance, cleanup, and tuning.",
                    "category_label": "Optimize Tool",
                }
            ],
            ShopSection.VIDEO_EDIT: [
                {
                    "display_order": 1,
                    "title": "TikTok / Short-Form Edit",
                    "description": "Short-form edits for TikTok, reels, and fast highlight content.",
                    "category_label": "Video Edit",
                },
                {
                    "display_order": 2,
                    "title": "5 to 9 Minute Video Edit",
                    "description": "Mid-length edited videos with stronger pacing and presentation.",
                    "category_label": "Video Edit",
                },
                {
                    "display_order": 3,
                    "title": "10 to 30 Minute Video Edit",
                    "description": "Long-form edited videos for showcase, gameplay, and premium content delivery.",
                    "category_label": "Video Edit",
                },
            ],
            ShopSection.SENSI_PC: [
                {
                    "display_order": 1,
                    "title": "PC Sensitivity Setup",
                    "description": "Free Fire PC setup with mouse DPI, emulator version, and X/Y sensitivity guidance.",
                    "category_label": "Sensi PC",
                }
            ],
            ShopSection.SENSI_IPHONE: [
                {
                    "display_order": 1,
                    "title": "iPhone Sensitivity Setup",
                    "description": "Free Fire iPhone mobile sensitivity setup without emulator or DPI settings.",
                    "category_label": "Sensi iPhone",
                }
            ],
            ShopSection.SENSI_ANDROID: [
                {
                    "display_order": 1,
                    "title": "Android Sensitivity Setup",
                    "description": "Free Fire Android mobile sensitivity setup without emulator or DPI settings.",
                    "category_label": "Sensi Android",
                }
            ],
        }
        return defaults[section]
