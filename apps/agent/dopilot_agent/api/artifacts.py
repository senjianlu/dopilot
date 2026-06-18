"""Scrapy egg deploy endpoint.

``POST /artifacts/scrapy/egg`` accepts a multipart upload (``project``,
``version``, ``file``) and forwards the egg to local scrapyd's
``addversion.json``. The deployed spider list scrapyd reports is returned in the
:class:`~dopilot_protocol.EggDeployResponse`. Behind the shared-token guard.
"""

from __future__ import annotations

from dopilot_protocol import EggDeployResponse
from fastapi import APIRouter, Depends, File, Form, UploadFile

from ..auth.dependencies import require_agent_token
from ..deps import get_scrapyd_client
from ..errors import upstream_error
from ..scrapyd.client import ScrapydClient, ScrapydError

router = APIRouter()

# Module-level singletons for the multipart field markers: FastAPI's Form()/File()
# are DI idioms (like Query/Depends) but ruff's B008 flags them in arg defaults,
# so we bind them once here per B008's "module-level singleton" guidance.
_PROJECT_FIELD = Form(...)
_VERSION_FIELD = Form(...)
_EGG_FILE = File(...)


@router.post("/artifacts/scrapy/egg", response_model=EggDeployResponse)
async def deploy_egg(
    project: str = _PROJECT_FIELD,
    version: str = _VERSION_FIELD,
    file: UploadFile = _EGG_FILE,
    client: ScrapydClient = Depends(get_scrapyd_client),
    _: None = Depends(require_agent_token),
) -> EggDeployResponse:
    egg_bytes = await file.read()
    try:
        body = await client.addversion(project, version, egg_bytes)
    except ScrapydError as exc:
        raise upstream_error(
            "agent.addversion_failed", "errors.upstream", exc.detail
        ) from exc

    spiders_raw = body.get("spiders")
    spiders = list(spiders_raw) if isinstance(spiders_raw, list) else []
    return EggDeployResponse(
        project=project,
        version=version,
        spiders=spiders,
        detail={"scrapyd": {k: v for k, v in body.items() if k != "spiders"}},
    )
