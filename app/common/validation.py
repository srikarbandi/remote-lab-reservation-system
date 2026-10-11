"""Request parsing and validation helpers (SAD 4.3.5).

Rules: free text is trimmed, non-empty and at most 500 characters; datetimes are
ISO 8601 with an explicit UTC offset; dates are YYYY-MM-DD; unknown writable
fields are rejected; list pages default to 20 and are capped at 100.
"""

import re
from datetime import date, datetime, timezone
from uuid import UUID

from flask import request

from app.common.errors import ApiError

MAX_TEXT_LENGTH = 500
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _invalid(field: str, message: str) -> ApiError:
    return ApiError(422, "INVALID_FIELDS", f"Invalid value for '{field}'.", fields={field: message})


def json_body() -> dict:
    """Return the request JSON object or raise 400."""
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ApiError(400, "MALFORMED_JSON", "Request body must be a JSON object.")
    return payload


def check_fields(payload: dict, required: set[str], optional: set[str] | frozenset = frozenset()) -> None:
    """Reject missing required fields and any unexpected writable field."""
    problems = {name: "This field is required." for name in sorted(required - set(payload))}
    problems.update({name: "Unexpected field." for name in sorted(set(payload) - required - set(optional))})
    if problems:
        raise ApiError(
            422, "INVALID_FIELDS", "One or more fields are missing or not allowed.", fields=problems
        )


def parse_uuid(value, field: str) -> UUID:
    if isinstance(value, UUID):
        return value
    if not isinstance(value, str):
        raise _invalid(field, "Must be a UUID string.")
    try:
        return UUID(value)
    except ValueError:
        raise _invalid(field, "Must be a UUID string.") from None


def parse_datetime(value, field: str) -> datetime:
    """Parse ISO 8601 with an explicit offset and return it in UTC."""
    if not isinstance(value, str):
        raise _invalid(field, "Must be an ISO 8601 datetime string.")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise _invalid(field, "Must be an ISO 8601 datetime string.") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _invalid(field, "Must include an explicit UTC offset, for example +05:30.")
    return parsed.astimezone(timezone.utc)


def parse_date(value, field: str) -> date:
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise _invalid(field, "Must be a date in YYYY-MM-DD format.")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise _invalid(field, "Must be a real calendar date.") from None


def parse_int(value, field: str, minimum: int = 0, maximum: int | None = None) -> int:
    if isinstance(value, bool):
        raise _invalid(field, "Must be an integer.")
    if isinstance(value, str) and re.fullmatch(r"-?\d+", value):
        value = int(value)
    if not isinstance(value, int):
        raise _invalid(field, "Must be an integer.")
    if value < minimum or (maximum is not None and value > maximum):
        bound = f"at least {minimum}" if maximum is None else f"between {minimum} and {maximum}"
        raise _invalid(field, f"Must be {bound}.")
    return value


def clean_text(value, field: str, max_length: int = MAX_TEXT_LENGTH) -> str:
    if not isinstance(value, str):
        raise _invalid(field, "Must be text.")
    text = value.strip()
    if not text:
        raise _invalid(field, "Must not be empty.")
    if len(text) > max_length:
        raise _invalid(field, f"Must be at most {max_length} characters.")
    return text


def parse_page(args) -> tuple[int, int]:
    """Read ?page= and ?page_size= from a query string mapping."""
    page = parse_int(args.get("page", 1), "page", minimum=1)
    size = parse_int(args.get("page_size", DEFAULT_PAGE_SIZE), "page_size", minimum=1, maximum=MAX_PAGE_SIZE)
    return page, size
