"""File HTTP controller."""

from fastapi import APIRouter, Response, status

from nexus.authentication.api.security import CurrentAuthContextDep
from nexus.files.api.dependencies import InitiateFileUploadDep
from nexus.files.api.schemas import (
    InitiatedFileResponseBody,
    InitiateFileUploadRequestBody,
    InitiateFileUploadResponseBody,
    UploadInstructionsResponseBody,
)

router = APIRouter(prefix="/files", tags=["files"])


@router.post(
    "/uploads",
    response_model=InitiateFileUploadResponseBody,
    status_code=status.HTTP_201_CREATED,
)
async def initiate_file_upload(
    body: InitiateFileUploadRequestBody,
    response: Response,
    auth_context: CurrentAuthContextDep,
    service: InitiateFileUploadDep,
) -> InitiateFileUploadResponseBody:
    result = await service.execute(
        organization_public_id=auth_context.organization_public_id,
        user_public_id=auth_context.user_public_id,
        original_name=body.original_name,
        mime_type=body.mime_type,
        declared_size_bytes=body.size_bytes,
    )
    response.headers["Cache-Control"] = "no-store"
    return InitiateFileUploadResponseBody(
        file=InitiatedFileResponseBody(
            public_id=result.file.public_id,
            original_name=result.file.original_name,
            mime_type=result.file.mime_type,
            storage_status=result.file.storage_status,
            created_at=result.file.created_at,
        ),
        upload=UploadInstructionsResponseBody(
            url=result.grant.url,
            method=result.grant.method,
            headers=dict(result.grant.headers),
            expires_at=result.grant.expires_at,
        ),
    )
