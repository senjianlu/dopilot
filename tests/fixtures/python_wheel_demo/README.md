# Phase 2b demo wheel

A built-in Python-wheel fixture used to exercise the `python_wheel` runner
(phase 2b). It contains only `main.py` as the user payload; the `.dist-info`
metadata is required by the wheel format.

## Contents

- `main.py` — stdlib-only demo: requests `DOPILOT_DEMO_URL`
  (default `https://httpbin.org/headers`) and prints the response headers.
  Runs with `python -m main` once the wheel is installed on `PYTHONPATH`.
- `build_wheel.py` — deterministic, stdlib-only wheel builder. Import
  `build_demo_wheel()` for the wheel bytes, or run it to (re)generate
  `dopilot_demo-0.1.0-py3-none-any.whl`.

## Build

```bash
python tests/fixtures/python_wheel_demo/build_wheel.py
```

No build toolchain (`build`/`wheel`) is required — the wheel is assembled with
`zipfile`, so server upload tests (packet 2b-1) and agent install/run tests
(packet 2b-2) can obtain identical bytes from `build_demo_wheel()`.

## Phase 2b execution strategy

The agent installs the wheel with:

```text
pip install --no-deps --target <agent-cache>/python_wheel/<sha256>/site <wheel>
PYTHONPATH=<site-dir>:$PYTHONPATH /bin/sh -c "<command>"
```

No venv, no dependency management, no main-interpreter install. Because
`--target` installs no console-script wrappers, the demo command must be an
importable module form, e.g. `python -m main`. For a CI smoke without external
network, point `DOPILOT_DEMO_URL` at a local HTTP server.
