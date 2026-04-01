from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    discord_token: str = Field(alias="DISCORD_TOKEN")
    discord_client_id: int | None = Field(default=None, alias="DISCORD_CLIENT_ID")
    discord_guild_id: int | None = Field(default=None, alias="DISCORD_GUILD_ID")
    database_url: str | None = Field(default=None, alias="DATABASE_URL")
    mongodb_uri: str | None = Field(default=None, alias="MONGODB_URI")
    default_prefix: str = Field(default="!", alias="DEFAULT_PREFIX")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO",
        alias="LOG_LEVEL",
    )
    poll_interval_seconds: int = Field(default=5, alias="POLL_INTERVAL_SECONDS")
    queue_timeout_seconds: int = Field(default=300, alias="QUEUE_TIMEOUT_SECONDS")
    room_info_timeout_seconds: int = Field(default=60, alias="ROOM_INFO_TIMEOUT_SECONDS")
    result_timeout_seconds: int = Field(default=1800, alias="RESULT_TIMEOUT_SECONDS")
    recovery_interval_seconds: int = Field(default=5, alias="RECOVERY_INTERVAL_SECONDS")
    cleanup_interval_seconds: int = Field(default=30, alias="CLEANUP_INTERVAL_SECONDS")
    result_channel_delete_delay_seconds: int = Field(
        default=600,
        alias="RESULT_CHANNEL_DELETE_DELAY_SECONDS",
    )

    @field_validator("discord_guild_id", mode="before")
    @classmethod
    def empty_guild_id_to_none(cls, value: int | str | None) -> int | None:
        if value in ("", None):
            return None
        return int(value)

    @model_validator(mode="after")
    def validate_positive_intervals(self) -> "Settings":
        interval_fields = (
            "poll_interval_seconds",
            "queue_timeout_seconds",
            "room_info_timeout_seconds",
            "result_timeout_seconds",
            "recovery_interval_seconds",
            "cleanup_interval_seconds",
            "result_channel_delete_delay_seconds",
        )
        for field_name in interval_fields:
            if getattr(self, field_name) <= 0:
                raise ValueError(f"{field_name} must be greater than 0.")
        return self

    @property
    def has_legacy_mongo(self) -> bool:
        return bool(self.mongodb_uri)

    def normalized_database_url(self) -> str | None:
        if not self.database_url:
            return None
        database_url = self.database_url.strip()
        if database_url.startswith("postgres://"):
            database_url = f"postgresql://{database_url.removeprefix('postgres://')}"
        if database_url.startswith("postgresql://"):
            database_url = f"postgresql+asyncpg://{database_url.removeprefix('postgresql://')}"
        if "://" in database_url:
            prefix, remainder = database_url.split("://", 1)
            if "@" in remainder:
                userinfo, host_part = remainder.rsplit("@", 1)
                if "%5B" not in userinfo and "%5D" not in userinfo and ("[" in userinfo or "]" in userinfo):
                    userinfo = userinfo.replace("[", "%5B").replace("]", "%5D")
                    database_url = f"{prefix}://{userinfo}@{host_part}"
        return database_url

    def require_database_url(self) -> str:
        database_url = self.normalized_database_url()
        if not database_url:
            raise ValueError("DATABASE_URL must be set for the Season 2 PostgreSQL runtime.")
        return database_url


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
