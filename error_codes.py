# error_codes.py
# Single source of truth for every error this server can return.
# Every other file imports from here — never hardcode error strings elsewhere.

class ErrorCode:

    # ── Client errors (caller's fault) ──────────────────────────
    EMPLOYEE_NOT_FOUND   = "EMPLOYEE_NOT_FOUND"
    INVALID_PARAMETER    = "INVALID_PARAMETER"
    INVALID_DATE_FORMAT  = "INVALID_DATE_FORMAT"
    NO_DATA_FOR_DATE     = "NO_DATA_FOR_DATE"

    # ── Security errors ──────────────────────────────────────────
    UNAUTHENTICATED      = "UNAUTHENTICATED"
    FORBIDDEN            = "FORBIDDEN"
    RATE_LIMITED         = "RATE_LIMITED"

    # ── Server errors (our fault) ────────────────────────────────
    SHEETS_UNAVAILABLE   = "SHEETS_UNAVAILABLE"
    INTERNAL_ERROR       = "INTERNAL_ERROR"


class ErrorMessage:

    # ── Client errors ────────────────────────────────────────────
    EMPLOYEE_NOT_FOUND   = "No employee found with that code."
    INVALID_PARAMETER    = "One or more parameters are invalid."
    INVALID_DATE_FORMAT  = "Date must be in YYYY-MM-DD format, e.g. 2026-07-07."
    NO_DATA_FOR_DATE     = "No activity data found for that date."

    # ── Security errors ──────────────────────────────────────────
    UNAUTHENTICATED      = "Missing or invalid API key."
    FORBIDDEN            = "You do not have permission to access this resource."
    RATE_LIMITED         = "Too many requests. Please wait before trying again."

    # ── Server errors ────────────────────────────────────────────
    SHEETS_UNAVAILABLE   = "Could not reach the data source. Please try again shortly."
    INTERNAL_ERROR       = "An unexpected error occurred."


HTTP_STATUS = {
    ErrorCode.EMPLOYEE_NOT_FOUND  : 404,
    ErrorCode.INVALID_PARAMETER   : 400,
    ErrorCode.INVALID_DATE_FORMAT : 400,
    ErrorCode.NO_DATA_FOR_DATE    : 404,
    ErrorCode.UNAUTHENTICATED     : 401,
    ErrorCode.FORBIDDEN           : 403,
    ErrorCode.RATE_LIMITED        : 429,
    ErrorCode.SHEETS_UNAVAILABLE  : 503,
    ErrorCode.INTERNAL_ERROR      : 500,
}