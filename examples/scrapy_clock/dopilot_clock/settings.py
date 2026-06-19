BOT_NAME = "dopilot_clock"

SPIDER_MODULES = ["dopilot_clock.spiders"]
NEWSPIDER_MODULE = "dopilot_clock.spiders"

ROBOTSTXT_OBEY = False
AUTOTHROTTLE_ENABLED = False
RETRY_ENABLED = False
TELNETCONSOLE_ENABLED = False
COOKIES_ENABLED = False
LOG_LEVEL = "INFO"
REQUEST_FINGERPRINTER_IMPLEMENTATION = "2.7"
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
FEED_EXPORT_ENCODING = "utf-8"
