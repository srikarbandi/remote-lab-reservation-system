"""Database access helpers.

Only the backend touches the database. Use parameterized queries only
(LAB-SR-005); never build SQL by string formatting. Rows come back as dicts.
"""

from contextlib import contextmanager

from flask import current_app

from app.common.errors import ApiError


def connect():
    """Open a PostgreSQL connection using DATABASE_URL from the app config.

    Use as ``with connect() as conn:``. The block commits on success and rolls
    back on error. Services open their own ``conn.transaction()`` for the
    explicit transaction boundary.
    """
    import psycopg
    from psycopg.rows import dict_row

    return psycopg.connect(current_app.config["DATABASE_URL"], row_factory=dict_row)


@contextmanager
def translate_db_errors():
    """Map infrastructure failures to the 503 contract (SAD 4.3.5).

    Wrap the whole ``with connect()`` block so connection failures are covered.
    """
    import psycopg

    try:
        yield
    except psycopg.errors.LockNotAvailable:
        raise ApiError(503, "LOCK_TIMEOUT", "The system is busy. Please retry.") from None
    except psycopg.OperationalError:
        raise ApiError(503, "DATABASE_UNAVAILABLE", "The service is temporarily unavailable.") from None
