from __future__ import annotations

from dataclasses import dataclass

import discord

from highlight_manager.models.common import MatchResultSummary
from highlight_manager.models.economy import CoinSpendRequest, EconomyConfig
from highlight_manager.models.enums import CoinSpendStatus
from highlight_manager.models.match import MatchRecord
from highlight_manager.models.profile import PlayerProfile
from highlight_manager.models.shop import ShopItem
from highlight_manager.models.tournament import TournamentTeam
from highlight_manager.repositories.economy_repository import CoinSpendRequestRepository, EconomyConfigRepository
from highlight_manager.services.config_service import ConfigService
from highlight_manager.services.profile_service import ProfileService
from highlight_manager.utils.dates import utcnow
from highlight_manager.utils.exceptions import UserFacingError


@dataclass(slots=True)
class CoinBalanceResult:
    profile: PlayerProfile
    previous_balance: int
    new_balance: int
    delta: int


class CoinsService:
    def __init__(
        self,
        profile_service: ProfileService,
        config_service: ConfigService,
        economy_config_repository: EconomyConfigRepository,
        request_repository: CoinSpendRequestRepository,
    ) -> None:
        self.profile_service = profile_service
        self.config_service = config_service
        self.economy_config_repository = economy_config_repository
        self.request_repository = request_repository

    async def get_or_create_config(self, guild_id: int) -> EconomyConfig:
        existing = await self.economy_config_repository.get(guild_id)
        if existing:
            return existing
        return await self.economy_config_repository.upsert(EconomyConfig(guild_id=guild_id))

    async def get_profile(self, guild: discord.Guild, user_id: int) -> PlayerProfile:
        config = await self.config_service.get_or_create(guild.id)
        return await self.profile_service.ensure_profile(guild, user_id, config)

    async def adjust_balance(
        self,
        guild: discord.Guild,
        user_id: int,
        delta: int,
    ) -> CoinBalanceResult:
        profile = await self.get_profile(guild, user_id)
        previous_balance = profile.coins_balance
        new_balance = previous_balance + delta
        if new_balance < 0:
            raise UserFacingError("That member does not have enough coins.")
        profile.coins_balance = new_balance
        if delta > 0:
            profile.lifetime_coins_earned += delta
        elif delta < 0:
            profile.lifetime_coins_spent += abs(delta)
        profile.updated_at = utcnow()
        saved = await self.profile_service.repository.upsert(profile)
        return CoinBalanceResult(
            profile=saved,
            previous_balance=previous_balance,
            new_balance=saved.coins_balance,
            delta=delta,
        )

    async def set_balance(self, guild: discord.Guild, user_id: int, amount: int) -> CoinBalanceResult:
        profile = await self.get_profile(guild, user_id)
        return await self.adjust_balance(guild, user_id, amount - profile.coins_balance)

    async def create_spend_request(
        self,
        guild: discord.Guild,
        user_id: int,
        *,
        coin_amount: int,
        requested_item_text: str,
        shop_item_id: int | None = None,
    ) -> CoinSpendRequest:
        if coin_amount <= 0:
            raise UserFacingError("Redeem amount must be greater than 0.")
        profile = await self.get_profile(guild, user_id)
        if profile.coins_balance < coin_amount:
            raise UserFacingError("You do not have enough coins for that request.")
        latest = await self.request_repository.get_latest_request(guild.id)
        request_number = (latest.request_number + 1) if latest else 1
        request = CoinSpendRequest(
            guild_id=guild.id,
            request_number=request_number,
            user_id=user_id,
            requested_item_text=requested_item_text,
            coin_amount=coin_amount,
            shop_item_id=shop_item_id,
        )
        return await self.request_repository.create(request)

    async def approve_request(self, guild: discord.Guild, request_number: int, staff_actor_id: int) -> CoinSpendRequest:
        request = await self.require_request(guild.id, request_number)
        if request.status != CoinSpendStatus.PENDING:
            raise UserFacingError("That request has already been resolved.")
        profile = await self.get_profile(guild, request.user_id)
        if profile.coins_balance < request.coin_amount:
            raise UserFacingError("The requester no longer has enough coins.")
        await self.adjust_balance(guild, request.user_id, -request.coin_amount)
        request.status = CoinSpendStatus.APPROVED
        request.staff_actor_id = staff_actor_id
        request.decided_at = utcnow()
        return await self.request_repository.replace(request)

    async def reject_request(
        self,
        guild_id: int,
        request_number: int,
        staff_actor_id: int,
        *,
        reason: str | None = None,
    ) -> CoinSpendRequest:
        request = await self.require_request(guild_id, request_number)
        if request.status != CoinSpendStatus.PENDING:
            raise UserFacingError("That request has already been resolved.")
        request.status = CoinSpendStatus.REJECTED
        request.staff_actor_id = staff_actor_id
        request.decided_at = utcnow()
        request.rejection_reason = reason
        return await self.request_repository.replace(request)

    async def require_request(self, guild_id: int, request_number: int) -> CoinSpendRequest:
        request = await self.request_repository.get(guild_id, request_number)
        if request is None:
            raise UserFacingError(f"Coin request #{request_number} was not found.")
        return request

    async def list_pending_requests(self, guild_id: int) -> list[CoinSpendRequest]:
        return await self.request_repository.list_pending(guild_id)

    async def award_regular_match_rewards(
        self,
        guild: discord.Guild,
        match: MatchRecord,
        summary: MatchResultSummary,
    ) -> None:
        config = await self.get_or_create_config(guild.id)
        if summary.winner_team is None:
            return
        winner_ids = set(summary.winner_player_ids)
        deltas: dict[int, int] = {user_id: config.match_participation for user_id in match.all_player_ids}
        for user_id in winner_ids:
            deltas[user_id] = deltas.get(user_id, 0) + config.match_win_bonus
        if summary.winner_mvp_id is not None:
            deltas[summary.winner_mvp_id] = deltas.get(summary.winner_mvp_id, 0) + config.winner_mvp_bonus
        if summary.loser_mvp_id is not None:
            deltas[summary.loser_mvp_id] = deltas.get(summary.loser_mvp_id, 0) + config.loser_mvp_bonus
        for user_id, delta in deltas.items():
            await self.adjust_balance(guild, user_id, delta)

    async def award_tournament_participation(self, guild: discord.Guild, team: TournamentTeam) -> TournamentTeam:
        if team.participation_rewarded:
            return team
        config = await self.get_or_create_config(guild.id)
        for user_id in team.player_ids:
            await self.adjust_balance(guild, user_id, config.tournament_participation)
        team.participation_rewarded = True
        return team

    async def award_tournament_final_rewards(
        self,
        guild: discord.Guild,
        *,
        champion_team: TournamentTeam,
        runner_up_team: TournamentTeam,
    ) -> None:
        config = await self.get_or_create_config(guild.id)
        for user_id in champion_team.player_ids:
            await self.adjust_balance(guild, user_id, config.tournament_champion)
        for user_id in runner_up_team.player_ids:
            await self.adjust_balance(guild, user_id, config.tournament_runner_up)

    async def purchase_shop_item(
        self,
        guild: discord.Guild,
        user_id: int,
        item: ShopItem,
    ) -> CoinBalanceResult:
        if not item.active:
            raise UserFacingError("That shop item is no longer available.")
        if item.coin_price is None or item.coin_price <= 0:
            raise UserFacingError("That item cannot be bought with coins.")
        return await self.adjust_balance(guild, user_id, -item.coin_price)
