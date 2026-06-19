from setuptools import find_packages, setup

setup(
    name="dopilot_clock",
    version="1.0.0",
    packages=find_packages(),
    entry_points={"scrapy": ["settings = dopilot_clock.settings"]},
)
