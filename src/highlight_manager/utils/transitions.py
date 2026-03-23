from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import discord

from highlight_manager.utils.embeds import build_transition_embed

TransitionTone = Literal["progress", "success", "warning", "error", "info"]


@dataclass(slots=True)
class TransitionFrame:
    title: str
    detail: str
    tone: TransitionTone = "progress"
    step_index: int | None = None
    step_total: int | None = None
    footer: str | None = None


class StatusMessageTransition:
    def __init__(
        self,
        message: discord.Message,
        *,
        heading: str,
        default_footer: str | None = None,
    ) -> None:
        self.message = message
        self.heading = heading
        self.default_footer = default_footer or "Highlight Manager is updating this view."
        self._last_key: tuple[str, str, str, int | None, int | None] | None = None

    @classmethod
    async def create(
        cls,
        channel: discord.abc.Messageable,
        *,
        heading: str,
        initial: TransitionFrame,
        content: str | None = None,
        default_footer: str | None = None,
    ) -> "StatusMessageTransition":
        embed = build_transition_embed(
            heading,
            initial.title,
            initial.detail,
            tone=initial.tone,
            step_index=initial.step_index,
            step_total=initial.step_total,
            footer=initial.footer or default_footer,
        )
        message = await channel.send(content=content, embed=embed)
        transition = cls(message, heading=heading, default_footer=default_footer)
        transition._remember(initial)
        return transition

    @classmethod
    async def create_followup(
        cls,
        interaction: discord.Interaction,
        *,
        heading: str,
        initial: TransitionFrame,
        ephemeral: bool = True,
        content: str | None = None,
        default_footer: str | None = None,
    ) -> "StatusMessageTransition":
        embed = build_transition_embed(
            heading,
            initial.title,
            initial.detail,
            tone=initial.tone,
            step_index=initial.step_index,
            step_total=initial.step_total,
            footer=initial.footer or default_footer,
        )
        message = await interaction.followup.send(content=content, embed=embed, ephemeral=ephemeral, wait=True)
        transition = cls(message, heading=heading, default_footer=default_footer)
        transition._remember(initial)
        return transition

    @classmethod
    def attach(
        cls,
        message: discord.Message,
        *,
        heading: str,
        default_footer: str | None = None,
    ) -> "StatusMessageTransition":
        return cls(message, heading=heading, default_footer=default_footer)

    async def step(
        self,
        frame: TransitionFrame,
        *,
        content: str | None = None,
        view: discord.ui.View | None = None,
        force: bool = False,
    ) -> None:
        key = self._frame_key(frame)
        if not force and key == self._last_key:
            return
        embed = build_transition_embed(
            self.heading,
            frame.title,
            frame.detail,
            tone=frame.tone,
            step_index=frame.step_index,
            step_total=frame.step_total,
            footer=frame.footer or self.default_footer,
        )
        await self.message.edit(content=content, embed=embed, view=view)
        self._last_key = key

    async def replace(
        self,
        *,
        embed: discord.Embed | None = None,
        content: str | None = None,
        view: discord.ui.View | None = None,
    ) -> None:
        await self.message.edit(content=content, embed=embed, view=view)
        self._last_key = None

    async def fail(
        self,
        detail: str,
        *,
        title: str = "Request Failed",
        content: str | None = None,
    ) -> None:
        await self.step(
            TransitionFrame(
                title=title,
                detail=detail,
                tone="error",
                footer="Nothing was changed. You can retry once the issue is fixed.",
            ),
            content=content,
            view=None,
            force=True,
        )

    def _remember(self, frame: TransitionFrame) -> None:
        self._last_key = self._frame_key(frame)

    @staticmethod
    def _frame_key(frame: TransitionFrame) -> tuple[str, str, str, int | None, int | None]:
        return (frame.title, frame.detail, frame.tone, frame.step_index, frame.step_total)
