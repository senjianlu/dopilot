"""The dopilot phase-1 ``phase1`` demo spider.

Deterministic and offline. It makes no network requests: it emits two fixed
marker log lines and a fixed set of trivial items, then closes. This gives
stable ``item_scraped_count`` / log markers for automated assertions and the
compose smoke.

Phase 1.8.2 adds a ``duration_seconds`` spider argument so the same fixture can
back BOTH near-instant automated tests and long-running operational checks::

    scrapy crawl phase1 -a duration_seconds=10

Behavior:
  * omitted          -> default 60 seconds;
  * ``=0``           -> near-instant (preserves the original behavior);
  * negative / non-numeric -> a clear ``ValueError`` is raised early.

The delay is REACTOR-SAFE: the async ``start()`` path (Scrapy >= 2.13, which is
what this fixture runs under) uses ``asyncio.sleep`` on the same event loop as
the configured ``AsyncioSelectorReactor``, so it never blocks the Twisted
reactor (no ``time.sleep``). The legacy synchronous ``start_requests()`` fallback
(Scrapy 2.11..2.12, which has no async ``start()``) keeps the markers + item
count but does NOT delay, because it cannot await without blocking the reactor.

Deterministic contract (do not change without updating tests + README):
  * marker line: ``phase1 demo spider started``
  * marker line: ``phase1 demo spider done``
  * emits exactly 2 items (item_scraped_count == 2)
"""

import asyncio

import scrapy

# Default runtime when ``-a duration_seconds=...`` is omitted.
DEFAULT_DURATION_SECONDS = 60.0


class Phase1Spider(scrapy.Spider):
    name = "phase1"

    # No allowed_domains / start_urls: the spider is fully offline.
    custom_settings = {
        "ROBOTSTXT_OBEY": False,
    }

    # Fixed, deterministic payload. Kept tiny on purpose.
    ITEMS = (
        {"id": 1, "value": "phase1-item-1"},
        {"id": 2, "value": "phase1-item-2"},
    )

    def __init__(self, duration_seconds=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Scrapy passes ``-a duration_seconds=...`` as a string kwarg.
        self.duration_seconds = self._parse_duration(duration_seconds)

    @staticmethod
    def _parse_duration(value) -> float:
        """Validate the ``duration_seconds`` arg; fail fast on bad input."""
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
        # Scrapy >= 2.13 entry point. ``start`` is an async generator; yielding
        # items (not Requests) makes the engine idle and close once the
        # generator is exhausted. Awaiting ``asyncio.sleep`` between the markers
        # keeps the spider alive for ``duration_seconds`` without blocking the
        # reactor (the asyncio reactor shares this event loop).
        self.logger.info("phase1 demo spider started")
        for item in self.ITEMS:
            # dict() copies so the item pipeline can't mutate the constant.
            yield dict(item)
        if self.duration_seconds > 0:
            await asyncio.sleep(self.duration_seconds)
        self.logger.info("phase1 demo spider done")

    def start_requests(self):
        # Fallback for Scrapy < 2.13, which calls start_requests() instead. This
        # path is synchronous and cannot await, so it keeps the markers + item
        # count but does not apply the delay (it must never block the reactor).
        self.logger.info("phase1 demo spider started")
        for item in self.ITEMS:
            yield dict(item)
        self.logger.info("phase1 demo spider done")
