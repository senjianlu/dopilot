"""TC-01i: the ``.pth`` hook is shipped by the wheel and auto-activates.

Builds the agent wheel offline (``pip wheel --no-build-isolation`` needs
``hatchling`` from the ``dev`` extra), installs it into a fresh venv with
``--no-deps`` (``logcap`` only needs the standard library), then runs a fake
crawler whose ONLY link to dopilot is the interpreter-startup ``.pth`` import:
the script neither touches ``sys.argv`` nor imports ``dopilot_agent``.
"""

from __future__ import annotations

import signal
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
AGENT_DIR = REPO / "apps" / "agent"

SCRIPT = textwrap.dedent(
    """
    import logging, sys
    path = next(a.split("=", 1)[1] for a in sys.argv if a.startswith("LOG_FILE="))
    h = logging.FileHandler(path, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(message)s"))
    log = logging.getLogger("crawler"); log.addHandler(h); log.setLevel(logging.INFO)
    chunk = "y" * 1023
    for _ in range(50 * 1024):
        log.info(chunk)
    h.close()
    print("FINISHED")
    """
)


@pytest.fixture(scope="module")
def isolated_venv(tmp_path_factory: pytest.TempPathFactory) -> Path:
    tmp = tmp_path_factory.mktemp("logcap-install")
    try:
        import hatchling  # noqa: F401
    except ImportError:  # pragma: no cover - the plan mandates fail, not skip
        pytest.fail("hatchling missing: install apps/agent[dev] before running TC-01i")
    subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
         "-q", str(AGENT_DIR), "-w", str(tmp)],
        check=True,
    )
    wheel = next(tmp.glob("dopilot_agent-*.whl"))
    venv = tmp / "venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    py = venv / "bin" / "python"
    subprocess.run(
        [str(py), "-m", "pip", "install", "-q", "--no-deps", str(wheel)], check=True
    )
    return venv


def _site_packages(venv: Path) -> Path:
    return next((venv / "lib").glob("python*")) / "site-packages"


def test_wheel_installs_pth_hook_at_site_root(isolated_venv: Path) -> None:
    pth = _site_packages(isolated_venv) / "dopilot_logcap.pth"
    assert pth.is_file()
    assert pth.read_text(encoding="utf-8").strip() == "import dopilot_agent.logcap"


def test_crawler_shaped_command_line_is_capped_without_explicit_import(
    isolated_venv: Path, tmp_path: Path
) -> None:
    py = isolated_venv / "bin" / "python"
    script = tmp_path / "fake_crawler.py"
    script.write_text(SCRIPT, encoding="utf-8")
    log_file = tmp_path / "job.log"
    cap = 65536
    proc = subprocess.run(
        [str(py), str(script), "crawl", "x", "-a", "_job=abc",
         "-s", f"LOG_FILE={log_file}", "-s", f"DOPILOT_JOB_LOG_CAP_BYTES={cap}"],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == -signal.SIGTERM, proc.stdout + proc.stderr
    assert "FINISHED" not in proc.stdout
    size = log_file.stat().st_size
    marker_len = len(f"\n[dopilot:job-log-truncated max_bytes={cap} reason=size-cap]\n")
    assert cap <= size <= cap + 1024 + marker_len

    # Control group: daemon-shaped argv writes the full 50MB and exits normally.
    free = tmp_path / "free.log"
    proc = subprocess.run(
        [str(py), str(script), f"LOG_FILE={free}"],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0 and "FINISHED" in proc.stdout
    assert free.stat().st_size == 50 * 1024 * 1024
