"""FastAPI dependencies for File application services."""

from typing import Annotated

from fastapi import Depends

from nexus.api.dependencies import AppContainerDep
from nexus.files.application import GetFile, InitiateFileUpload, ListFiles


def get_initiate_file_upload(container: AppContainerDep) -> InitiateFileUpload:
    return container.files.initiate_upload


def get_list_files(container: AppContainerDep) -> ListFiles:
    return container.files.list_files


def get_file(container: AppContainerDep) -> GetFile:
    return container.files.get_file


InitiateFileUploadDep = Annotated[
    InitiateFileUpload,
    Depends(get_initiate_file_upload),
]
ListFilesDep = Annotated[
    ListFiles,
    Depends(get_list_files),
]
GetFileDep = Annotated[
    GetFile,
    Depends(get_file),
]
