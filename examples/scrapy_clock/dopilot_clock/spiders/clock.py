from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import scrapy

DEFAULT_DURATION_SECONDS = 60.0


class ClockSpider(scrapy.Spider):
    name = "clock"

    def __init__(self, duration_seconds=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.duration_seconds = self._parse_duration(duration_seconds)

    @staticmethod
    def _parse_duration(value) -> float:
        if value is None:
            return DEFAULT_DURATION_SECONDS
        try:
            parsed = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"duration_seconds must be a number, got {value!r}"
            ) from exc
        if parsed < 0:
            raise ValueError(
                f"duration_seconds must be >= 0, got {parsed}"
            )
        return parsed

    async def start(self):
        for tick in range(int(self.duration_seconds)):
            now = datetime.now(UTC).isoformat()
            self.logger.info("clock tick %s %s", tick + 1, now)
            yield {"tick": tick + 1, "time": now}
            await asyncio.sleep(1)

    def start_requests(self):
        return iter(())
