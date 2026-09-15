from pydantic import BaseModel

from nexus.errors.codes import ErrorCode


class ErrorBody(BaseModel):
    code: ErrorCode
    message: str
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody
