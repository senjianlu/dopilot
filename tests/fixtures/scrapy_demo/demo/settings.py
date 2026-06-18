"""Settings for the dopilot phase-1 ``demo`` Scrapy project.

Minimal and fully deterministic: no network, no autothrottle, no telnet.
The project exists only as a fixture for dopilot phase-1 automated tests and
the compose smoke. It must never import anything from ``reference/scrapydweb``.
"""

BOT_NAME = "demo"

SPIDER_MODULES = ["demo.spiders"]
NEWSPIDER_MODULE = "demo.spiders"

# Never fetch robots.txt; the spider makes no network calls at all.
ROBOTSTXT_OBEY = False

# Keep the run deterministic and fast: no throttling, no retries, no telnet.
AUTOTHROTTLE_ENABLED = False
RETRY_ENABLED = False
TELNETCONSOLE_ENABLED = False
COOKIES_ENABLED = False

# Default log level; runtime callers (scrapyd / scrapy crawl --loglevel) may override.
LOG_LEVEL = "INFO"

# Forward-compatibility knobs to silence Scrapy 2.11+ deprecation warnings and
# keep output stable across Scrapy patch versions.
REQUEST_FINGERPRINTER_IMPLEMENTATION = "2.7"
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
FEED_EXPORT_ENCODING = "utf-8"
