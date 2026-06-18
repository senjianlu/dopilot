"""Executor seam and registry.

Phase order is locked: ① Scrapy (scrapyd) is the only executor wired in phase
0/1; ③ plain Python3 scripts (phase 2) and ② Docker long-lived crawlers
(phase 3) register here later. One type stable before the next.
"""
