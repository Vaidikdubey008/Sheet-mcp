# rate_limiter.py
# Layer 4 — Rate Limiting
# Tracks how many requests each API key has made in the last 60 seconds.
# Rejects requests that exceed the configured limit with a 429 error.
# Uses a sliding window — not a fixed reset — to prevent burst abuse.

import os
import time
from collections import defaultdict
from dotenv import load_dotenv
from error_codes import ErrorCode, ErrorMessage
from audit_logger import log_rate_limit

load_dotenv()

# Read the limit from .env — defaults to 60 if not set
_RATE_LIMIT = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "60"))

# Window size is always 60 seconds
_WINDOW_SECONDS = 60

# In-memory store: maps each api_key to a list of call timestamps
# defaultdict(list) means any new key automatically gets an empty list
_call_timestamps: dict[str, list[float]] = defaultdict(list)


class RateLimitError(Exception):
    """
    Raised when a caller exceeds their request limit.
    Caught by server.py and converted into a 429 response.
    """
    def __init__(self, retry_after: int = 60):  # ADD retry_after
        self.code = ErrorCode.RATE_LIMITED
        self.message = ErrorMessage.RATE_LIMITED
        self.retry_after = retry_after
        super().__init__(self.message)


def check_rate_limit(api_key: str) -> None:
    """
    Checks whether this api_key has exceeded the rate limit.

    How it works:
    1. Get the current timestamp
    2. Remove all timestamps older than 60 seconds from this key's list
    3. Count what remains — these are calls made in the last 60 seconds
    4. If count >= limit, reject with RateLimitError
    5. Otherwise, add the current timestamp and allow the call

    Raises RateLimitError if the limit is exceeded.
    Returns None if the call is allowed.
    """
    now = time.time()
    window_start = now - _WINDOW_SECONDS

    # Step 1 — remove timestamps outside the current window
    # This is what makes it a sliding window rather than a fixed reset
    _call_timestamps[api_key] = [
        ts for ts in _call_timestamps[api_key]
        if ts > window_start
    ]

    # Step 2 — count calls within the window
    call_count = len(_call_timestamps[api_key])

    # Step 3 — reject if at or over the limit
    if call_count >= _RATE_LIMIT:
        log_rate_limit(api_key=api_key)
        oldest = min(_call_timestamps[api_key])
        retry_after = int(_WINDOW_SECONDS - (now - oldest)) + 1
        raise RateLimitError(retry_after=retry_after)

    # Step 4 — record this call and allow it through
    _call_timestamps[api_key].append(now)


def get_current_usage(api_key: str) -> dict:
    """
    Returns the current rate limit status for an api_key.
    Useful for debugging — not called in the main request path.

    Returns a dict showing:
    - calls_in_window: how many calls made in the last 60 seconds
    - limit: the configured maximum
    - remaining: how many calls are left before hitting the limit
    """
    now = time.time()
    window_start = now - _WINDOW_SECONDS

    recent_calls = [
        ts for ts in _call_timestamps[api_key]
        if ts > window_start
    ]

    return {
        "calls_in_window": len(recent_calls),
        "limit": _RATE_LIMIT,
        "remaining": max(0, _RATE_LIMIT - len(recent_calls)),
    }