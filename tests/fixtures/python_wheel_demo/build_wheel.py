"""Deterministic stdlib-only builder for the phase-2b demo wheel.

A ``.whl`` is just a zip with a ``{dist}-{ver}.dist-info/`` directory carrying
``METADATA`` / ``WHEEL`` / ``RECORD``. Building it with :mod:`zipfile` keeps the
fixture reproducible and free of any build toolchain (``build``/``wheel`` need
not be installed), so both the server upload tests (packet 2b-1) and the agent
install/run tests (packet 2b-2) can obtain identical wheel bytes via
:func:`build_demo_wheel`.

The wheel contains only ``main.py`` as the user-facing payload (see
``main.py``); the ``.dist-info`` files are required by the wheel format.
"""

from __future__ import annotations

import base64
import hashlib
import zipfile
from io import BytesIO
from pathlib import Path

DISTRIBUTION = "dopilot_demo"
VERSION = "0.1.0"
WHEEL_FILENAME = f"{DISTRIBUTION}-{VERSION}-py3-none-any.whl"
_DIST_INFO = f"{DISTRIBUTION}-{VERSION}.dist-info"

_METADATA = (
    "Metadata-Version: 2.1\n"
    f"Name: {DISTRIBUTION.replace('_', '-')}\n"
    f"Version: {VERSION}\n"
    "Summary: dopilot phase-2b demo wheel (stdlib httpbin headers).\n"
    "\n"
)
_WHEEL = (
    "Wheel-Version: 1.0\n"
    "Generator: dopilot-demo-builder (0.1.0)\n"
    "Root-Is-Purelib: true\n"
    "Tag: py3-none-any\n"
)


def _record_hash(data: bytes) -> str:
    digest = hashlib.sha256(data).digest()
    encoded = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return f"sha256={encoded}"


def build_demo_wheel(main_source: str | None = None) -> bytes:
    """Return the demo wheel as bytes (deterministic, no build toolchain).

    ``main_source`` overrides the packaged ``main.py`` body (defaults to the
    committed ``main.py`` next to this builder).
    """
    if main_source is None:
        main_source = (Path(__file__).parent / "main.py").read_text("utf-8")
    main_bytes = main_source.encode("utf-8")
    metadata_bytes = _METADATA.encode("utf-8")
    wheel_bytes = _WHEEL.encode("utf-8")

    # RECORD lists every archive member; its own row carries empty hash/size.
    record_lines = [
        f"main.py,{_record_hash(main_bytes)},{len(main_bytes)}",
        f"{_DIST_INFO}/METADATA,{_record_hash(metadata_bytes)},{len(metadata_bytes)}",
        f"{_DIST_INFO}/WHEEL,{_record_hash(wheel_bytes)},{len(wheel_bytes)}",
        f"{_DIST_INFO}/RECORD,,",
    ]
    record_bytes = ("\n".join(record_lines) + "\n").encode("utf-8")

    buf = BytesIO()
    # Fixed ZipInfo timestamps keep the archive byte-stable across builds.
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in (
            ("main.py", main_bytes),
            (f"{_DIST_INFO}/METADATA", metadata_bytes),
            (f"{_DIST_INFO}/WHEEL", wheel_bytes),
            (f"{_DIST_INFO}/RECORD", record_bytes),
        ):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, data)
    return buf.getvalue()


def main() -> int:
    out = Path(__file__).parent / WHEEL_FILENAME
    out.write_bytes(build_demo_wheel())
    print(f"wrote {out} ({out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
