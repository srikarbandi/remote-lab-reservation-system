"""Database access helper.

Only the backend touches the database. Use parameterized queries only
(LAB-SR-005); never build SQL by string formatting.
"""

from flask import current_app


def connect():
    """Open a PostgreSQL connection using DATABASE_URL from the app config.

    Imported lazily so the app and unit tests run without a database driver
    connection being made at import time.
    """
    import psycopg

    return psycopg.connect(current_app.config["DATABASE_URL"])
