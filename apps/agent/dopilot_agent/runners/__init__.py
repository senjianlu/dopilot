"""Execution runners package (phase-1+).

Empty in phase 0. Phase 1+ adds runners in strict order behind a common
``BaseExecutor`` seam: (1) the scrapyd runner, then (2) the plain Python3
script runner, then (3) the docker long-lived crawler runner. No execution is
implemented now.
"""
