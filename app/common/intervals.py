"""Interval rules shared by every module.

Intervals are half-open: [start, end). Adjacent intervals do not overlap
(SRS 2.5). Use this one predicate everywhere instead of re-implementing it.
"""

from datetime import datetime


def overlaps(
    new_start: datetime, new_end: datetime, existing_start: datetime, existing_end: datetime
) -> bool:
    """True when the intervals overlap: new_start < existing_end and new_end > existing_start."""
    return new_start < existing_end and new_end > existing_start


def is_valid_interval(start: datetime, end: datetime) -> bool:
    """An interval must have start strictly before end."""
    return start < end
