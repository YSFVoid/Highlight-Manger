from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from highlight_manager.app.config import Settings
from highlight_manager.db.session import create_engine, create_session_factory, session_scope
from highlight_manager.modules.economy.repository import EconomyRepository
from highlight_manager.modules.economy.service import EconomyService
from highlight_manager.modules.guilds.repository import GuildRepository
from highlight_manager.modules.guilds.service import GuildService
from highlight_manager.modules.matches.repository import MatchRepository
from highlight_manager.modules.matches.service import MatchService
from highlight_manager.modules.moderation.repository import ModerationRepository
from highlight_manager.modules.moderation.service import ModerationService
from highlight_manager.modules.profiles.repository import ProfileRepository
from highlight_manager.modules.profiles.service import ProfileService
from highlight_manager.modules.ranks.repository import RankRepository
from highlight_manager.modules.ranks.service import RankService
from highlight_manager.modules.seasons.repository import SeasonRepository
from highlight_manager.modules.seasons.service import SeasonService
from highlight_manager.modules.shop.repository import ShopRepository
from highlight_manager.modules.shop.service import ShopService
from highlight_manager.modules.tournaments.repository import TournamentRepository
from highlight_manager.modules.tournaments.service import TournamentService


@dataclass(slots=True)
class Repositories:
    session: AsyncSession
    guilds: GuildRepository
    profiles: ProfileRepository
    seasons: SeasonRepository
    ranks: RankRepository
    matches: MatchRepository
    economy: EconomyRepository
    shop: ShopRepository
    tournaments: TournamentRepository
    moderation: ModerationRepository


@dataclass(slots=True)
class Services:
    guilds: GuildService
    profiles: ProfileService
    seasons: SeasonService
    ranks: RankService
    moderation: ModerationService
    economy: EconomyService
    shop: ShopService
    matches: MatchService
    tournaments: TournamentService


class Runtime:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.engine = create_engine(settings.require_database_url())
        self.session_factory: async_sessionmaker[AsyncSession] = create_session_factory(self.engine)
        guild_service = GuildService(settings)
        profile_service = ProfileService()
        season_service = SeasonService()
        rank_service = RankService()
        moderation_service = ModerationService()
        economy_service = EconomyService()
        shop_service = ShopService(economy_service)
        match_service = MatchService(
            settings,
            profile_service=profile_service,
            season_service=season_service,
            rank_service=rank_service,
            economy_service=economy_service,
            moderation_service=moderation_service,
        )
        tournament_service = TournamentService(
            economy_service=economy_service,
            moderation_service=moderation_service,
        )
        self.services = Services(
            guilds=guild_service,
            profiles=profile_service,
            seasons=season_service,
            ranks=rank_service,
            moderation=moderation_service,
            economy=economy_service,
            shop=shop_service,
            matches=match_service,
            tournaments=tournament_service,
        )

    @asynccontextmanager
    async def session(self) -> AsyncIterator[Repositories]:
        async with session_scope(self.session_factory) as session:
            yield Repositories(
                session=session,
                guilds=GuildRepository(session),
                profiles=ProfileRepository(session),
                seasons=SeasonRepository(session),
                ranks=RankRepository(session),
                matches=MatchRepository(session),
                economy=EconomyRepository(session),
                shop=ShopRepository(session),
                tournaments=TournamentRepository(session),
                moderation=ModerationRepository(session),
            )
