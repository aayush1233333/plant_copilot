import sqlite3
import sys
from pathlib import Path


def open_ro(db_path: str) -> sqlite3.Connection:
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True)


def main(db_path: str) -> None:
    con = open_ro(db_path)
    cur = con.cursor()
    print(f"=== {db_path} ===")
    print("sqlite version:", sqlite3.sqlite_version)

    objects = cur.execute(
        "SELECT type, name, sql FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
    ).fetchall()

    for obj_type, name, sql in objects:
        print(f"\n--- {obj_type.upper()}: {name} ---")
        print(sql)
        if obj_type == "table":
            n = cur.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            print(f"row count: {n}")

    con.close()


if __name__ == "__main__":
    main(sys.argv[1])
