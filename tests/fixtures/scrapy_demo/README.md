# dopilot phase-1 demo Scrapy fixture

A minimal, deterministic Scrapy project used by dopilot phase-1 automated tests
and the compose smoke. It exercises the full Scrapy execution chain
(server -> agent -> in-agent scrapyd -> scrapy job -> tail log) without any
network access.

> **scrapydweb reference boundary.** This fixture is greenfield dopilot code. It
> must never import anything from `reference/scrapydweb/`, and it is not derived
> from scrapydweb's demo project.

## Project / spider names

| Thing | Value |
|---|---|
| Scrapy project | `demo` |
| Spider | `phase1` |
| Egg version (setup.py) | `1.0` |
| Committed egg | `eggs/demo_phase1.egg` |

These names are fixed constants that the rest of phase 1 agrees on. The spider
makes **no network calls**: it emits markers + items from the spider entry point
and the engine closes immediately.

## Deterministic contract

The spider logs exactly these two marker lines (via `self.logger.info`), which
tests assert on:

```text
phase1 demo spider started
phase1 demo spider done
```

It also scrapes exactly **2** trivial items, so Scrapy stats are deterministic:

```text
item_scraped_count == 2
finish_reason == "finished"
```

Note on Scrapy versions: Scrapy >= 2.13 drives the spider through the async
`start()` method and no longer calls the legacy `start_requests()`. The spider
implements `start()` (preferred) and keeps `start_requests()` as a fallback for
older Scrapy (2.11..2.12), so the markers and item count are emitted on any
Scrapy 2.11..2.16.

## Layout

```text
tests/fixtures/scrapy_demo/
├── scrapy.cfg                # [settings] default = demo.settings
├── setup.py                  # entry_points: scrapy -> settings = demo.settings
├── build_egg.sh              # deterministic egg build -> eggs/demo_phase1.egg
├── README.md
├── eggs/
│   └── demo_phase1.egg       # committed pre-built egg (NOT under dist/)
└── demo/
    ├── __init__.py
    ├── settings.py           # BOT_NAME='demo', offline, ROBOTSTXT_OBEY=False
    └── spiders/
        ├── __init__.py
        └── phase1.py         # the phase1 spider
```

The egg is committed under `eggs/` (not `dist/`) on purpose: the repo
`.gitignore` ignores `dist/`, `build/`, and `*.egg-info/`, so an egg placed
there would be uncommittable. `eggs/demo_phase1.egg` is tracked in git.

## How the egg is built

The egg is built with setuptools `bdist_egg`. The `scrapy` entry-point group
(key `settings = demo.settings`) is what scrapyd uses to locate the project's
settings after `addversion.json`.

Exact command (from the repo root):

```bash
tests/fixtures/scrapy_demo/build_egg.sh /home/rabbir/dopilot/.venv/bin/python
```

which runs, inside `tests/fixtures/scrapy_demo/`:

```bash
python setup.py clean --all
python setup.py bdist_egg          # -> dist/demo-1.0-pyX.Y.egg
cp dist/*.egg eggs/demo_phase1.egg
rm -rf build dist demo.egg-info    # leave the working tree clean
```

Build dependencies (dev/build tools, installed into the repo venv):

```bash
.venv/bin/pip install 'scrapy>=2.11,<3' 'scrapyd>=1.4,<2'
```

Equivalent: `scrapyd-deploy --build-egg eggs/demo_phase1.egg` also works because
`setup.py` declares the same `scrapy` entry point.

## Committed egg provenance

- File: `eggs/demo_phase1.egg`
- Build source: this directory's `setup.py` + `demo/` package, via
  `build_egg.sh` (`python setup.py bdist_egg`).
- Built with: Scrapy 2.16.0, scrapyd 1.6.0, setuptools 80.10.2, CPython 3.12.3.
- **sha256:** `be59e2c12a5771cb9950a0c170392be98750b29db5d3a2b4fe0c1bc145229bc7`

Note: the egg bundles compiled `.pyc` files whose embedded timestamps make the
sha256 vary across rebuilds. The committed `eggs/demo_phase1.egg` above is the
canonical artifact; the recorded sha256 identifies that exact committed file. If
you rebuild, expect a different sha256 — update this README and any test that
pins the hash, or treat the committed egg as authoritative and rebuild only when
the project source changes.

## Verify locally

```bash
# Spider discovery (prints: phase1)
cd tests/fixtures/scrapy_demo && /home/rabbir/dopilot/.venv/bin/scrapy list

# Full run (markers + 2 items)
cd tests/fixtures/scrapy_demo && \
  /home/rabbir/dopilot/.venv/bin/scrapy crawl phase1 --loglevel=INFO 2>&1 | \
  grep -E "phase1 demo spider (started|done)|item_scraped_count"
```

Expected output includes:

```text
[phase1] INFO: phase1 demo spider started
[phase1] INFO: phase1 demo spider done
 'item_scraped_count': 2,
```
