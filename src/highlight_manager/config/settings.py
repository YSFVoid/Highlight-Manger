from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    discord_token: str = Field(alias="DISCORD_TOKEN")
    discord_client_id: int | None = Field(default=None, alias="DISCORD_CLIENT_ID")
    mongodb_uri: str = Field(alias="MONGODB_URI")
    discord_guild_id: int | None = Field(default=None, alias="DISCORD_GUILD_ID")
    default_prefix: str = Field(default="!", alias="DEFAULT_PREFIX")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO",
        alias="LOG_LEVEL",
    )
    poll_interval_seconds: int = Field(default=20, alias="POLL_INTERVAL_SECONDS")
    result_channel_delete_delay_seconds: int = Field(
        default=600,
        alias="RESULT_CHANNEL_DELETE_DELAY_SECONDS",
    )

    @field_validator("discord_guild_id", mode="before")
    @classmethod
    def empty_guild_id_to_none(cls, value):
        if value in ("", None):
            return None
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
