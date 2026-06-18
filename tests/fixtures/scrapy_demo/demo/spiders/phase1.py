"""The dopilot phase-1 ``phase1`` demo spider.

Deterministic, offline, and fast. It makes no network requests: it emits two
fixed marker log lines and a fixed set of trivial items, then closes. This
gives stable ``item_scraped_count`` / log markers for automated assertions and
the compose smoke.

Deterministic contract (do not change without updating tests + README):
  * marker line: ``phase1 demo spider started``
  * marker line: ``phase1 demo spider done``
  * emits exactly 2 items (item_scraped_count == 2)

Scrapy 2.13+ drives spider entry through the async ``start()`` method and no
longer calls the legacy synchronous ``start_requests()``. To stay deterministic
across Scrapy 2.11..2.16 we implement ``start()`` (preferred) and keep
``start_requests()`` as a fallback for older releases that lack ``start()``.
"""

import scrapy


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

    def _emit(self):
        """Yield markers + items without making any network request."""
        self.logger.info("phase1 demo spider started")
        for item in self.ITEMS:
            # dict() copies so the item pipeline can't mutate the constant.
            yield dict(item)
        self.logger.info("phase1 demo spider done")

    async def start(self):
        # Scrapy >= 2.13 entry point. ``start`` is an async generator; yielding
        # items (not Requests) and no Request makes the engine idle and close
        # immediately.
        for obj in self._emit():
            yield obj

    def start_requests(self):
        # Fallback for Scrapy < 2.13, which calls start_requests() instead.
        yield from self._emit()
