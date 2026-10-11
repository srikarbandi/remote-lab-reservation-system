"""Pure usage-recording rules (LAB-F-016, SAD 4.1.2). No database access.

- Only an Approved reservation can be completed, and only once its end time has passed.
- A no-show has both usage timestamps empty and zero minutes.
- Otherwise usage is one interval, start before end, contained in the reserved interval.
"""

from dataclasses import dataclass
from datetime import datetime

from app.common.errors import ApiError


@dataclass(frozen=True)
class UsageResult:
    used_start: datetime | None
    used_end: datetime | None
    used_minutes: int


def compute_usage(
    reservation_start: datetime,
    reservation_end: datetime,
    reservation_status: str,
    now: datetime,
    *,
    used_start: datetime | None = None,
    used_end: datetime | None = None,
    no_show: bool = False,
) -> UsageResult:
    """Validate a usage submission and return what to store. Whole minutes, rounded down."""
    if reservation_status != "Approved":
        raise ApiError(
            409,
            "INVALID_STATE",
            f"Usage can only be recorded for an Approved reservation, not {reservation_status}.",
        )
    if now < reservation_end:
        raise ApiError(
            409, "RESERVATION_NOT_ENDED", "Usage can only be recorded after the reserved interval has ended."
        )

    if no_show:
        if used_start is not None or used_end is not None:
            raise ApiError(
                422,
                "INVALID_FIELDS",
                "A no-show cannot include usage times.",
                fields={"used_start": "Not allowed with no_show.", "used_end": "Not allowed with no_show."},
            )
        return UsageResult(None, None, 0)

    if used_start is None or used_end is None:
        raise ApiError(
            422,
            "INVALID_FIELDS",
            "Both used_start and used_end are required unless no_show is true.",
            fields={
                name: "Required."
                for name, value in (("used_start", used_start), ("used_end", used_end))
                if value is None
            },
        )
    if used_start >= used_end:
        raise ApiError(422, "INVALID_USAGE", "used_start must be before used_end.")
    if used_start < reservation_start or used_end > reservation_end:
        raise ApiError(
            422,
            "INVALID_USAGE",
            "Usage must fall within the reserved interval and cannot exceed its duration.",
        )
    minutes = int((used_end - used_start).total_seconds() // 60)
    return UsageResult(used_start, used_end, minutes)
