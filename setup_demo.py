import getpass
import os
from pathlib import Path

import psycopg

from app.auth.passwords import hash_password

database_url = os.environ.get("TEST_DATABASE_URL")

if not database_url:
    raise SystemExit("TEST_DATABASE_URL is missing. Use the terminal where tests passed.")

identifier = input("New administrator identifier: ").strip()
password = getpass.getpass("New administrator password: ")
confirmation = getpass.getpass("Enter it again: ")

if not identifier or len(identifier) > 100:
    raise SystemExit("Enter an identifier between 1 and 100 characters.")

if not password or len(password) > 1024 or password != confirmation:
    raise SystemExit("Passwords must match and contain 1 to 1024 characters.")

schema_path = Path(__file__).resolve().parent / "db" / "schema.sql"

with psycopg.connect(database_url) as conn:
    with conn.cursor() as cursor:
        cursor.execute("SET search_path TO public")
        cursor.execute(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
        )
        table_count = cursor.fetchone()[0]

        if table_count == 0:
            cursor.execute(schema_path.read_text(encoding="utf-8"))

        cursor.execute("SELECT to_regclass('public.users')")
        if cursor.fetchone()[0] is None:
            raise SystemExit("An existing schema needs checking. No data was changed.")

        cursor.execute(
            "SELECT id FROM users WHERE identifier = %s",
            (identifier,),
        )
        if cursor.fetchone():
            raise SystemExit("That identifier already exists. Choose a new identifier.")

        cursor.execute(
            "INSERT INTO labs (name) VALUES (%s) "
            "ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name "
            "RETURNING id",
            ("Demonstration Laboratory",),
        )
        lab_id = cursor.fetchone()[0]

        cursor.execute(
            "INSERT INTO users (identifier, password_hash) "
            "VALUES (%s, %s) RETURNING id",
            (identifier, hash_password(password)),
        )
        user_id = cursor.fetchone()[0]

        cursor.execute(
            "INSERT INTO lab_memberships (user_id, lab_id, role) "
            "VALUES (%s, %s, %s)",
            (user_id, lab_id, "Administrator"),
        )

print("Administrator created successfully.")
print(f"Identifier: {identifier}")
print(f"User ID: {user_id}")
print(f"Laboratory ID: {lab_id}")