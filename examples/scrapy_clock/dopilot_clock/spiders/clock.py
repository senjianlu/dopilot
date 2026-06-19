from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import scrapy


class ClockSpider(scrapy.Spider):
    name = "clock"

    async def start(self):
        for tick in range(60):
            now = datetime.now(UTC).isoformat()
            self.logger.info("clock tick %s %s", tick + 1, now)
            yield {"tick": tick + 1, "time": now}
            await asyncio.sleep(1)

    def start_requests(self):
        return iter(())
