"""FastAPI dependencies for File application services."""

from typing import Annotated

from fastapi import Depends

from nexus.api.dependencies import AppContainerDep
from nexus.files.application import InitiateFileUpload


def get_initiate_file_upload(container: AppContainerDep) -> InitiateFileUpload:
    return container.files.initiate_upload


InitiateFileUploadDep = Annotated[
    InitiateFileUpload,
    Depends(get_initiate_file_upload),
]
