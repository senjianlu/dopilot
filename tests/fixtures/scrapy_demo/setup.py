# Build script for the dopilot phase-1 demo Scrapy egg.
#
# scrapyd locates a project's settings via the ``scrapy`` entry point group
# (key ``settings``), exactly as ``scrapyd-deploy --build-egg`` expects. Build
# the egg with build_egg.sh (which runs ``python setup.py clean bdist_egg``).
#
# This project is a test fixture only; it must never import reference/scrapydweb.

from setuptools import setup, find_packages

setup(
    name="demo",
    version="1.0",
    packages=find_packages(),
    entry_points={"scrapy": ["settings = demo.settings"]},
)
