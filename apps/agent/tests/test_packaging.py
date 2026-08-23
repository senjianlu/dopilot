"""TC-01f(b): packaging wires the logcap ``.pth`` into the agent wheel."""

from __future__ import annotations

import tomllib
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]


def test_pth_file_imports_logcap() -> None:
    pth = AGENT_DIR / "dopilot_logcap.pth"
    assert pth.read_text(encoding="utf-8").strip() == "import dopilot_agent.logcap"


def test_pyproject_force_includes_pth_at_wheel_root() -> None:
    data = tomllib.loads((AGENT_DIR / "pyproject.toml").read_text(encoding="utf-8"))
    force = data["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    assert force["dopilot_logcap.pth"] == "dopilot_logcap.pth"
    assert "hatchling" in data["project"]["optional-dependencies"]["dev"]
