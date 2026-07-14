# validators.py
# Layer 5 — Input Validation
# Pydantic models define the exact shape of valid input for each tool.
# Every tool call is validated against these models before any
# business logic runs. Bad input is rejected here with a clear error —
# it never reaches the Google Sheets API.

import re
from datetime import datetime
from pydantic import BaseModel, Field, field_validator
from error_codes import ErrorCode, ErrorMessage


# ── Date format validator (reused across multiple tools) ──────────────

def validate_date_format(date_str: str) -> str:
    """
    Validates that a date string is in YYYY-MM-DD format.
    Raises ValueError if the format is wrong.
    Used as a reusable validator across multiple input models.
    """
    if not date_str or date_str.lower() == "today":
        return date_str

    pattern = r"^\d{4}-\d{2}-\d{2}$"
    if not re.match(pattern, date_str):
        raise ValueError(
            f"Date '{date_str}' must be in YYYY-MM-DD format, "
            f"e.g. 2026-07-07"
        )

    # Also verify it is a real calendar date, not something like 2026-13-45
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        raise ValueError(
            f"Date '{date_str}' is not a valid calendar date."
        )

    return date_str


# ── Input model for get_employee_status ──────────────────────────────

class EmployeeStatusInput(BaseModel):
    """
    Validates input for the get_employee_status tool.

    employee_code: required, non-empty string.
    Examples of valid values: E001, E002, EMP-101
    """
    employee_code: str = Field(
        min_length=1,
        max_length=20,
        pattern=r'^[A-Za-z0-9\-]+$',  # ADD THIS
        description="Employee code from the Employees sheet, e.g. E001"
    )
    model_config = {"populate_by_name": True}  # ADD THIS for aliases

    @field_validator("employee_code")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        """Remove accidental leading/trailing spaces from employee codes."""
        return v.strip()


# ── Input model for get_team_summary ─────────────────────────────────

class TeamSummaryInput(BaseModel):
    """
    Validates input for the get_team_summary tool.

    date: optional. Defaults to 'today' if not provided.
    Must be in YYYY-MM-DD format if provided.
    """
    date: str = Field(
        default="today",
        description="Date in YYYY-MM-DD format. Defaults to today."
    )

    @field_validator("date")
    @classmethod
    def validate_date(cls, v: str) -> str:
        return validate_date_format(v)


# ── Input model for get_daily_brief ──────────────────────────────────

class DailyBriefInput(BaseModel):
    """
    Validates input for the get_daily_brief tool.

    employee_code: required, non-empty string.
    date: optional. Defaults to 'today' if not provided.
    """
    employee_code: str = Field(
        min_length=1,
        max_length=20,
        description="Employee code from the Employees sheet, e.g. E001"
    )
    date: str = Field(
        default="today",
        description="Date in YYYY-MM-DD format. Defaults to today."
    )

    @field_validator("employee_code")
    @classmethod
    def strip_employee_code(cls, v: str) -> str:
        return v.strip()

    @field_validator("date")
    @classmethod
    def validate_date(cls, v: str) -> str:
        return validate_date_format(v)


# ── Input model for get_employee_history ─────────────────────────────

class EmployeeHistoryInput(BaseModel):
    """
    Validates input for the get_employee_history tool.

    employee_code: required, non-empty string.
    days: optional integer, how many days of history to return.
          Must be between 1 and 30. Defaults to 7.
    """
    employee_code: str = Field(
        min_length=1,
        max_length=20,
        description="Employee code from the Employees sheet, e.g. E001"
    )
    days: int = Field(
        default=7,
        ge=1,       # ge = greater than or equal to 1
        le=30,      # le = less than or equal to 30
        description="Number of days of history to return. Min 1, max 30."
    )

    @field_validator("employee_code")
    @classmethod
    def strip_employee_code(cls, v: str) -> str:
        return v.strip()


# ── Validation helper used by server.py ──────────────────────────────

class ValidationError(Exception):
    """
    Raised when input validation fails.
    Caught by server.py and converted into a clean 400 response.
    """
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def validate_input(model_class, raw_input: dict) -> object:
    """
    Validates raw input against a Pydantic model.

    model_class : one of the Input models above
    raw_input   : dict of parameters from the tool call

    Returns the validated model instance if input is valid.
    Raises ValidationError with a clean message if input is invalid.

    Example usage in server.py:
        validated = validate_input(EmployeeStatusInput, {"employee_code": "E001"})
        code = validated.employee_code  # guaranteed clean string
    """
    try:
        return model_class(**raw_input)
    except Exception as e:
        # Extract the human-readable part of Pydantic's error message
        error_detail = str(e)

        # Check for specific error types to give better messages
        if "date" in error_detail.lower():
            raise ValidationError(
                code=ErrorCode.INVALID_DATE_FORMAT,
                message=ErrorMessage.INVALID_DATE_FORMAT
            )

        raise ValidationError(
            code=ErrorCode.INVALID_PARAMETER,
            message=f"{ErrorMessage.INVALID_PARAMETER} {error_detail}"
        )