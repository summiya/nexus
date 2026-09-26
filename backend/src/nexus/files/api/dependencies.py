"""FastAPI dependencies for File application services."""

from typing import Annotated

from fastapi import Depends

from nexus.api.dependencies import AppContainerDep
from nexus.files.application import (
    GetFile,
    InitiateFileUpload,
    IssueFileDownload,
    ListFiles,
)


def get_initiate_file_upload(container: AppContainerDep) -> InitiateFileUpload:
    return container.files.initiate_upload


def get_list_files(container: AppContainerDep) -> ListFiles:
    return container.files.list_files


def get_file(container: AppContainerDep) -> GetFile:
    return container.files.get_file


def get_issue_file_download(container: AppContainerDep) -> IssueFileDownload:
    return container.files.issue_download


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


IssueFileDownloadDep = Annotated[
    IssueFileDownload,
    Depends(get_issue_file_download),
]
