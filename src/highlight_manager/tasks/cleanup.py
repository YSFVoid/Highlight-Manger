from __future__ import annotations


class CleanupWorker:
    async def run(self, bot) -> None:
        del bot
        return None
