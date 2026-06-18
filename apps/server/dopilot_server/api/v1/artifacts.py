"""Scrapy artifact (egg) endpoints.

Phase 1 supports uploading a PRE-BUILT egg only (no source/Git/CI build). The
server forwards the egg to a chosen agent which calls its local scrapyd
``/addversion.json``, then records the deployment in ``scrapy_artifacts``.
"""

from __future__ import annotations

import hashlib
import time
import uuid

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.dependencies import AdminContext, get_current_admin
from ...clients.agent import (
    AgentClient,
    AgentResponseError,
    AgentUnreachableError,
    get_agent_client,
)
from ...db.engine import get_session
from ...models.execution import ScrapyArtifact
from ...nodes.service import pick_deploy_node
from .schemas import ArtifactView, EggDeployResult

router = APIRouter(tags=["artifacts"])


@router.post("/artifacts/scrapy/egg", response_model=EggDeployResult)
async def upload_scrapy_egg(
    file: UploadFile = File(...),
    project: str = Form(...),
    version: str | None = Form(default=None),
    node_ids: list[str] = Form(default=[]),
    _admin: AdminContext = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
    agent_client: AgentClient = Depends(get_agent_client),
) -> EggDeployResult:
    egg_bytes = await file.read()
    sha256 = hashlib.sha256(egg_bytes).hexdigest()
    resolved_version = version or str(int(time.time()))
    filename = file.filename or f"{project}-{resolved_version}.egg"

    node = await pick_deploy_node(session, node_ids or None)

    try:
        deploy = await agent_client.deploy_egg(
            node.endpoint, project, resolved_version, filename, egg_bytes
        )
    except (AgentUnreachableError, AgentResponseError) as exc:
        raise exc.to_api_error() from exc

    artifact = ScrapyArtifact(
        id=uuid.uuid4().hex,
        project=deploy.project or project,
        version=deploy.version or resolved_version,
        filename=filename,
        sha256=sha256,
        size_bytes=len(egg_bytes),
        agent_id=node.agent_id,
        endpoint=node.endpoint,
    )
    session.add(artifact)
    await session.commit()

    return EggDeployResult(
        artifact=ArtifactView(
            id=artifact.id,
            project=artifact.project,
            version=artifact.version,
            filename=artifact.filename,
            sha256=artifact.sha256,
            size_bytes=artifact.size_bytes,
            created_at=artifact.created_at.isoformat()
            if artifact.created_at
            else None,
        ),
        spiders=deploy.spiders,
        agent_id=node.agent_id,
        endpoint=node.endpoint,
    )
