from pathlib import Path
import sqlite3

BASE_DIR = Path(__file__).resolve().parent # reslve tam adresi verir parent bulunan klasör
DATABASE_PATH = BASE_DIR / "quiz.db"
SCHEMA_PATH = BASE_DIR / "schema.sql"


def main():
    connection = sqlite3.connect(DATABASE_PATH)

    try:
        connection.execute("PRAGMA foreign_keys = ON")

        schema = SCHEMA_PATH.read_text(encoding="utf-8")

        # Apply the schema as one transaction.
        connection.executescript(
            "BEGIN;\n" + schema + "\nCOMMIT;"
        )

        tables = connection.execute("""
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
            ORDER BY name
        """).fetchall()

        triggers = connection.execute("""
            SELECT name
            FROM sqlite_master
            WHERE type = 'trigger'
            ORDER BY name
        """).fetchall()

        foreign_keys_enabled = connection.execute(
            "PRAGMA foreign_keys"
        ).fetchone()[0]

        integrity_results = connection.execute(
            "PRAGMA integrity_check"
        ).fetchall()

        foreign_key_errors = connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()

        print("Database initialized successfully.")
        print("Database location:", DATABASE_PATH)

        print("\nTables:")
        for (table_name,) in tables:
            print(f"  - {table_name}")

        print("\nTable count:", len(tables))
        print("Trigger count:", len(triggers))
        print("Foreign keys enabled:", foreign_keys_enabled)

        integrity_ok = integrity_results == [("ok",)]
        print("Integrity check:", "OK" if integrity_ok else "FAILED")
        print("Foreign key violations:", len(foreign_key_errors))

        if not integrity_ok:
            print("Integrity details:", integrity_results)

        if foreign_key_errors:
            print("Foreign key details:", foreign_key_errors)

    except sqlite3.Error:
        connection.rollback()
        raise

    finally:
        connection.close()


if __name__ == "__main__":
    main()