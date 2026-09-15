from enum import StrEnum


class ErrorCode(StrEnum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    BAD_REQUEST = "BAD_REQUEST"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    RATE_LIMITED = "RATE_LIMITED"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


ERROR_STATUS_CODES: dict[ErrorCode, int] = {
    ErrorCode.VALIDATION_ERROR: 422,
    ErrorCode.BAD_REQUEST: 400,
    ErrorCode.UNAUTHORIZED: 401,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.CONFLICT: 409,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.SERVICE_UNAVAILABLE: 503,
    ErrorCode.INTERNAL_ERROR: 500,
}

HTTP_STATUS_ERROR_CODES: dict[int, ErrorCode] = {
    status_code: code for code, status_code in ERROR_STATUS_CODES.items()
}

ERROR_DEFAULT_MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.VALIDATION_ERROR: "The request validation failed.",
    ErrorCode.BAD_REQUEST: "The request could not be processed.",
    ErrorCode.UNAUTHORIZED: "Authentication is required.",
    ErrorCode.FORBIDDEN: "You are not allowed to perform this action.",
    ErrorCode.NOT_FOUND: "The requested resource was not found.",
    ErrorCode.CONFLICT: "The request conflicts with the current resource state.",
    ErrorCode.RATE_LIMITED: "Too many requests. Please try again later.",
    ErrorCode.SERVICE_UNAVAILABLE: "The service is temporarily unavailable.",
    ErrorCode.INTERNAL_ERROR: "An internal server error occurred.",
}
