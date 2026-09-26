"""File HTTP controller."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from nexus.authentication.api.security import CurrentAuthContextDep
from nexus.files.api.dependencies import (
    GetFileDep,
    InitiateFileUploadDep,
    IssueFileDownloadDep,
    ListFilesDep,
)
from nexus.files.api.pagination import decode_file_cursor, encode_file_cursor
from nexus.files.api.schemas import (
    FileDownloadResponseBody,
    FileMetadataResponseBody,
    InitiateFileUploadRequestBody,
    InitiateFileUploadResponseBody,
    ListFilesResponseBody,
    UploadInstructionsResponseBody,
    UploadMetadataResponseBody,
)
from nexus.files.application import DEFAULT_FILE_PAGE_SIZE, MAX_FILE_PAGE_SIZE
from nexus.files.domain import File

router = APIRouter(prefix="/files", tags=["files"])


@router.get("", response_model=ListFilesResponseBody)
async def list_files(
    response: Response,
    auth_context: CurrentAuthContextDep,
    service: ListFilesDep,
    limit: Annotated[int, Query(ge=1, le=MAX_FILE_PAGE_SIZE)] = (
        DEFAULT_FILE_PAGE_SIZE
    ),
    cursor: Annotated[str | None, Query(max_length=512)] = None,
) -> ListFilesResponseBody:
    page = await service.execute(
        organization_public_id=auth_context.organization_public_id,
        user_public_id=auth_context.user_public_id,
        limit=limit,
        cursor=decode_file_cursor(cursor),
    )
    response.headers["Cache-Control"] = "private, no-store"
    return ListFilesResponseBody(
        items=[_to_file_metadata(item) for item in page.items],
        next_cursor=(
            encode_file_cursor(page.next_cursor)
            if page.next_cursor is not None
            else None
        ),
    )


@router.post(
    "/uploads",
    response_model=InitiateFileUploadResponseBody,
    status_code=status.HTTP_200_OK,
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
        upload=UploadInstructionsResponseBody(
            url=result.grant.url,
            method=result.grant.method,
            headers=dict(result.grant.headers),
            metadata=UploadMetadataResponseBody(
                nexus_upload_context=result.protected_context,
            ),
            expires_at=result.grant.expires_at,
        ),
    )


@router.post(
    "/{file_public_id}/download",
    response_model=FileDownloadResponseBody,
    status_code=status.HTTP_200_OK,
)
async def initiate_file_download(
    file_public_id: UUID,
    response: Response,
    auth_context: CurrentAuthContextDep,
    service: IssueFileDownloadDep,
) -> FileDownloadResponseBody:
    grant = await service.execute(
        organization_public_id=auth_context.organization_public_id,
        user_public_id=auth_context.user_public_id,
        file_public_id=file_public_id,
    )
    response.headers["Cache-Control"] = "private, no-store"
    return FileDownloadResponseBody(
        url=grant.url,
        expires_at=grant.expires_at,
    )


@router.get("/{file_public_id}", response_model=FileMetadataResponseBody)
async def get_file(
    file_public_id: UUID,
    response: Response,
    auth_context: CurrentAuthContextDep,
    service: GetFileDep,
) -> FileMetadataResponseBody:
    file = await service.execute(
        organization_public_id=auth_context.organization_public_id,
        user_public_id=auth_context.user_public_id,
        file_public_id=file_public_id,
    )
    response.headers["Cache-Control"] = "private, no-store"
    return _to_file_metadata(file)


def _to_file_metadata(file: File) -> FileMetadataResponseBody:
    return FileMetadataResponseBody(
        public_id=file.public_id,
        original_name=file.original_name,
        mime_type=file.mime_type,
        size_bytes=file.size_bytes,
        storage_status=file.storage_status,
        created_at=file.created_at,
        updated_at=file.updated_at,
    )
