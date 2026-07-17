# server.py
# WorkWitness Sheets MCP Server
# Single tool implementation: get_employee_status
# Production-grade — all 8 layers active

# Fix 1  (Layer 3)  — Explicit rejection when both company_id and sub are missing
# Fix 2  (Layer 4)  — rate_limiter.py bug fixed (company_id → api_key) — see rate_limiter.py
# Fix 3  (Layer 4)  — retry_after_seconds added to rate limit response
# Fix 4  (Layer 7)  — ALL log_tool_call calls wrapped in try/except so a disk-full never kills a successful response
# Fix 5  (Layer 8)  — focus_score: None when not recorded, not 0
# Fix 6  (Layer 8)  — hours_worked: sanity check > 24 = data error
# Fix 7  (Layer 8)  — blockers: expanded NO_BLOCKER_VALUES set
# Fix 8  (Layer 8)  — staleness warning when data > 7 days old
# Fix 9  (Layer 8)  — empty stage returns "Not recorded" not empty string
# Fix 10 (Layer 8)  — _compute_performance_signal handles None focus_score

import os
import sys
import time
from datetime import datetime, timezone, datetime as dt
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP, Context

from auth import verify_token, extract_bearer_token, AuthError
from rate_limiter import check_rate_limit, RateLimitError
from validators import validate_input, ValidationError, EmployeeStatusInput
from supabase_client import (
    get_employee_by_code,
    get_latest_activity_for_employee,
    get_user_permissions,
    SheetsError,
)
from audit_logger import log_tool_call
from error_codes import Errors

load_dotenv()

mcp = FastMCP("workwitness-sheets-mcp", host="0.0.0.0", port=8000)


# ── Expanded no-blocker values (Fix 7) 
NO_BLOCKER_VALUES = {
    "none", "n/a", "nil", "no", "no blockers",
    "no blocker", "-", "—", "", "null", "na", "false", "0"
}


# ── Helper functions 

def _parse_int(value, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        return default


def _parse_float(value, default: float = 0.0) -> float:
    try:
        return float(str(value).strip())
    except (ValueError, TypeError):
        return default


def _parse_focus_score(value):
    if value is None:
        return None
    raw = str(value).strip()
    if raw == "" or not raw.lstrip("-").isdigit():
        return None
    return int(raw)


def _parse_hours(value):
    try:
        hours = float(str(value).strip())
        if hours > 24:
            return None
        return hours
    except (ValueError, TypeError):
        return 0.0


def _compute_performance_signal(focus_score, tasks_completed: int, blockers: str) -> str:
    has_blocker = (
        blockers and
        blockers.strip().lower() not in NO_BLOCKER_VALUES
    )
    if has_blocker:
        return "blocked"
    if focus_score is None:
        return "data_missing"
    if focus_score >= 80 and tasks_completed >= 4:
        return "strong"
    if focus_score >= 60:
        return "steady"
    return "needs_attention"


def _build_error_response(error, message: str | None = None) -> dict:
    return {
        "error": True,
        "code": error.code,
        "message": message or error.message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _safe_log(api_key: str, tool: str, inputs: dict, outcome: str, duration_ms: int):
    try:
        log_tool_call(
            api_key=api_key,
            tool=tool,
            inputs=inputs,
            outcome=outcome,
            duration_ms=duration_ms,
        )
    except Exception as log_error:
        print(f"AUDIT LOG FAILURE: {log_error}", file=sys.stderr)

def _get_permissions(claims: dict) -> dict:
    """
    Looks up user permissions from Supabase.
    Falls back to default permissions if user not found.
    """
    user_sub = claims.get("sub", "")
    perms = get_user_permissions(user_sub)
    if perms is None:
        return {
            "role": "viewer",
            "allowed_tools": ["get_employee_status"],
            "allowed_employees": None,
        }
    return perms


def _check_tool_permission(user_permissions: dict, tool_name: str) -> None:
    allowed_tools = user_permissions.get("allowed_tools")
    if allowed_tools is None:
        return
    if tool_name not in allowed_tools:
        raise AuthError(
            Errors.FORBIDDEN,
            message=f"Your account does not have permission to use '{tool_name}'. "
                    f"Contact your administrator for access."
        )


def _check_employee_permission(user_permissions: dict, employee_code: str) -> None:
    allowed_employees = user_permissions.get("allowed_employees")
    if allowed_employees is None:
        return
    if employee_code.upper() not in [e.upper() for e in allowed_employees]:
        raise AuthError(
            Errors.FORBIDDEN,
            message=f"You do not have permission to view employee '{employee_code}'. "
                    f"Contact your administrator for access."
        )
# ── The single tool 

@mcp.tool()
def get_employee_status(
    employee_code: str,
    ctx: Context
) -> dict:
    """
    Returns the current activity status for one employee.

    Use this tool when someone asks about a specific employee —
    their current productivity stage, focus score, hours worked,
    tasks completed, any blockers, and overall performance signal.

    Requires:
    - employee_code : the employee's unique code, e.g. E001, E002

    Authentication is handled automatically via the connection's
    Bearer token — never ask the user for an API key or token.

    Returns a structured response containing:
    - Employee profile (name, department, joining date)
    - Current activity (stage, focus score, hours, tasks, blockers)
    - Performance signal (strong / steady / needs_attention / blocked / data_missing)
    - Last active date
    - data_warning if data is stale (> 7 days old) or hours look wrong

    If the employee does not exist, returns EMPLOYEE_NOT_FOUND.
    If the employee exists but has no activity data, returns their
    profile with a status of no_activity_data.
    """
    start_time = time.time()
    tool_name = "get_employee_status"
    company_id = "unauthenticated"

    try:


        # LAYER 2 — AUTHENTICATION (OAuth 2.1 / JWT)
      
        request = ctx.request_context.request
        request_headers = dict(request.headers) if request is not None else {}
        api_key = extract_bearer_token(request_headers)
        claims = verify_token(api_key)

        # TEMPORARY DEBUG — remove after testing
        if employee_code.upper() == "DEBUG":
            return {
                "debug": True,
                "token_claims": {k: str(v) for k, v in claims.items()},
            }
    
        # LAYER 3 — IDENTITY EXTRACTION
  
        company_id = claims.get("company_id") or claims.get("sub")
        if not company_id:
            raise AuthError(
                Errors.UNAUTHENTICATED,
                message="Token is missing required identity claims."
            )

    
        # LAYER 3.5 — PERMISSION LOOKUP
    
        user_permissions = _get_permissions(claims)
        _check_tool_permission(user_permissions, tool_name)

        # LAYER 3.6 — EMPLOYEE DATA SCOPING
    
        _check_employee_permission(user_permissions, employee_code)

        # LAYER 4 — RATE LIMITING
        check_rate_limit(company_id)

   
        # LAYER 5 — INPUT VALIDATION
      
        validated = validate_input(
            EmployeeStatusInput,
            {"employee_code": employee_code}
        )

     
        # LAYER 6 — DATA FETCH (Google Sheets API)
  
        employee = get_employee_by_code(validated.employee_code)

        if not employee:
            duration = int((time.time() - start_time) * 1000)
            _safe_log(
                api_key=company_id,
                tool=tool_name,
                inputs={"employee_code": employee_code},
                outcome=Errors.EMPLOYEE_NOT_FOUND.code,
                duration_ms=duration,
            )
            return _build_error_response(
                Errors.EMPLOYEE_NOT_FOUND,
                message=f"No employee found with code '{validated.employee_code}'. "
                        f"Please check the employee code and try again."
            )

        activity = get_latest_activity_for_employee(validated.employee_code)

  
        # LAYER 7 — AUDIT LOGGING
   
        duration = int((time.time() - start_time) * 1000)
        _safe_log(
            api_key=company_id,
            tool=tool_name,
            inputs={"employee_code": employee_code},
            outcome="success",
            duration_ms=duration,
        )

        # LAYER 8 — RESPONSE SHAPING
  
        base = {
            "employee_code": employee.get("employee_code", "").upper(),
            "name": employee.get("name", "Unknown"),
            "department": employee.get("department", "Unknown"),
            "joining_date": employee.get("joining_date", "Unknown"),
        }

        if not activity:
            return {
                **base,
                "status": "no_activity_data",
                "message": (
                    f"{base['name']} is registered in the system "
                    f"but has no recorded activity data yet."
                ),
            }

        focus_score = _parse_focus_score(activity.get("focus_score"))
        hours_worked = _parse_hours(activity.get("hours_worked"))
        tasks_completed = _parse_int(activity.get("tasks_completed"), default=0)

        raw_blockers = (activity.get("blockers") or "").strip()
        blockers = (
            "None"
            if raw_blockers.lower() in NO_BLOCKER_VALUES
            else raw_blockers
        )

        data_warning = None
        last_date_str = activity.get("date", "Unknown")
        try:
            last_date = dt.strptime(last_date_str, "%Y-%m-%d")
            days_old = (dt.now() - last_date).days
            if days_old > 7:
                data_warning = (
                    f"This data is {days_old} days old. "
                    f"Activity tracking may not be current."
                )
        except (ValueError, TypeError):
            pass

        response = {
            **base,
            "status": "active",
            "current_stage": activity.get("stage") or "Not recorded",
            "focus_score": focus_score,
            "hours_worked": hours_worked,
            "tasks_completed": tasks_completed,
            "blockers": blockers,
            "last_active_date": last_date_str,
            "performance_signal": _compute_performance_signal(
                focus_score=focus_score,
                tasks_completed=tasks_completed,
                blockers=blockers,
            ),
        }

        if data_warning:
            response["data_warning"] = data_warning

        if hours_worked is None:
            response["data_warning"] = (
                "Hours worked value appears incorrect — please check the sheet."
            )

        return response

    except AuthError as e:
        duration = int((time.time() - start_time) * 1000)
        _safe_log(api_key="unauthenticated", tool=tool_name, inputs={}, outcome=e.error.code, duration_ms=duration)
        return _build_error_response(e.error, message=e.message)

    except RateLimitError as e:
        duration = int((time.time() - start_time) * 1000)
        _safe_log(api_key=company_id, tool=tool_name, inputs={"employee_code": employee_code}, outcome=e.error.code, duration_ms=duration)
        response = _build_error_response(e.error)
        response["retry_after_seconds"] = e.retry_after
        return response

    except ValidationError as e:
        duration = int((time.time() - start_time) * 1000)
        _safe_log(api_key=company_id, tool=tool_name, inputs={"employee_code": employee_code}, outcome=e.error.code, duration_ms=duration)
        return _build_error_response(e.error, message=e.message)

    except SheetsError as e:
        duration = int((time.time() - start_time) * 1000)
        _safe_log(api_key=company_id, tool=tool_name, inputs={"employee_code": employee_code}, outcome=e.error.code, duration_ms=duration)
        return _build_error_response(e.error, message=e.message)

    except Exception:
        duration = int((time.time() - start_time) * 1000)
        _safe_log(api_key=company_id, tool=tool_name, inputs={"employee_code": employee_code}, outcome=Errors.INTERNAL_ERROR.code, duration_ms=duration)
        return _build_error_response(Errors.INTERNAL_ERROR)


# ── OAuth endpoints ───────────────────────────────────────────────────

@mcp.custom_route("/.well-known/oauth-authorization-server", methods=["GET"])
async def discovery(request):
    from starlette.responses import JSONResponse
    clerk_issuer = os.environ.get("CLERK_ISSUER", "")
    mcp_base = os.environ.get("MCP_BASE_URL", "http://localhost:8000")
    return JSONResponse({
        "issuer": clerk_issuer,
        "authorization_endpoint": f"{clerk_issuer}/oauth/authorize",
        "token_endpoint": f"{clerk_issuer}/oauth/token",
        "registration_endpoint": f"{mcp_base}/oauth/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["client_secret_basic", "none"],
    })

@mcp.custom_route("/oauth/register", methods=["POST"])
async def oauth_register(request):
    from starlette.responses import JSONResponse
    client_id = os.environ.get("CLERK_OAUTH_CLIENT_ID", "")
    client_secret = os.environ.get("CLERK_OAUTH_CLIENT_SECRET", "")
    return JSONResponse({
        "client_id": client_id,
        "client_secret": client_secret,
        "client_id_issued_at": 0,
        "client_secret_expires_at": 0,
    })
    
if __name__ == "__main__":
    mcp.run(transport="streamable-http")