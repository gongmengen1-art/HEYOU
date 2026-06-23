"""SQLite data layer: enrolled people (name + face embedding) and print log."""
from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path

import numpy as np

EMB_DTYPE = np.float32


def connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: str | Path) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS people (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                name            TEXT NOT NULL,
                embedding       BLOB NOT NULL,
                photo_path      TEXT NOT NULL,
                created_at      TEXT NOT NULL,
                last_print_date TEXT
            );
            CREATE TABLE IF NOT EXISTS print_log (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                person_id  INTEGER NOT NULL,
                ts         TEXT NOT NULL,
                output_path TEXT,
                status     TEXT NOT NULL,
                detail     TEXT,
                FOREIGN KEY (person_id) REFERENCES people(id) ON DELETE CASCADE
            );
            """
        )


def today_str() -> str:
    return dt.date.today().isoformat()


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def add_person(db_path, name: str, embedding: np.ndarray, photo_path: str | Path) -> int:
    blob = np.asarray(embedding, dtype=EMB_DTYPE).tobytes()
    with connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO people (name, embedding, photo_path, created_at) VALUES (?,?,?,?)",
            (name, blob, str(photo_path), _now()),
        )
        return int(cur.lastrowid)


def list_people(db_path) -> list[dict]:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, name, photo_path, created_at, last_print_date FROM people ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]


def get_person(db_path, pid: int) -> dict | None:
    with connect(db_path) as conn:
        r = conn.execute("SELECT * FROM people WHERE id=?", (pid,)).fetchone()
        return dict(r) if r else None


def delete_person(db_path, pid: int) -> None:
    with connect(db_path) as conn:
        conn.execute("DELETE FROM people WHERE id=?", (pid,))


def get_gallery(db_path) -> list[dict]:
    """Enrolled people with decoded float32 embeddings (for matching)."""
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, name, embedding, photo_path, last_print_date FROM people"
        ).fetchall()
    gallery: list[dict] = []
    for r in rows:
        gallery.append(
            {
                "id": r["id"],
                "name": r["name"],
                "embedding": np.frombuffer(r["embedding"], dtype=EMB_DTYPE),
                "photo_path": r["photo_path"],
                "last_print_date": r["last_print_date"],
            }
        )
    return gallery


def mark_printed(db_path, pid: int, date_str: str | None = None) -> None:
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE people SET last_print_date=? WHERE id=?",
            (date_str or today_str(), pid),
        )


def add_print_log(db_path, pid: int, output_path: str | None, status: str, detail: str = "") -> None:
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO print_log (person_id, ts, output_path, status, detail) VALUES (?,?,?,?,?)",
            (pid, _now(), str(output_path) if output_path else None, status, detail),
        )


def recent_activity(db_path, limit: int = 30) -> list[dict]:
    """Recent generation/print events joined with the person's name (newest first)."""
    with connect(db_path) as conn:
        rows = conn.execute(
            """SELECT pl.ts AS ts, pl.status AS status, pl.output_path AS output_path,
                      pl.detail AS detail, p.name AS name
                 FROM print_log pl
                 LEFT JOIN people p ON p.id = pl.person_id
                ORDER BY pl.id DESC
                LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def cutoff_date(days: int) -> str:
    return (dt.date.today() - dt.timedelta(days=days)).isoformat()


def list_people_state(db_path, limit: int, offset: int) -> tuple[list[dict], int]:
    """A page of people, each with their latest successful cartoon + timestamp."""
    with connect(db_path) as conn:
        rows = conn.execute(
            """SELECT p.id, p.name, p.photo_path, p.last_print_date,
                      (SELECT output_path FROM print_log pl
                        WHERE pl.person_id = p.id AND pl.status IN ('generated','printed','print_failed')
                        ORDER BY pl.id DESC LIMIT 1) AS last_output,
                      (SELECT ts FROM print_log pl
                        WHERE pl.person_id = p.id AND pl.status IN ('generated','printed','print_failed')
                        ORDER BY pl.id DESC LIMIT 1) AS last_gen_ts
                 FROM people p ORDER BY p.id LIMIT ? OFFSET ?""",
            (limit, offset),
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) AS c FROM people").fetchone()["c"]
    return [dict(r) for r in rows], int(total)


def person_last_output(db_path, pid: int) -> str | None:
    """Path of the person's most recent generated cartoon image (regardless of print outcome)."""
    with connect(db_path) as conn:
        r = conn.execute(
            """SELECT output_path FROM print_log
                WHERE person_id = ? AND output_path IS NOT NULL
                  AND status IN ('generated','printed','print_failed')
                ORDER BY id DESC LIMIT 1""",
            (pid,),
        ).fetchone()
    return r["output_path"] if r else None


def person_history(db_path, pid: int, cutoff: str) -> list[dict]:
    with connect(db_path) as conn:
        rows = conn.execute(
            """SELECT ts, status, output_path FROM print_log
                WHERE person_id = ? AND substr(ts, 1, 10) >= ?
                ORDER BY id DESC""",
            (pid, cutoff),
        ).fetchall()
        return [dict(r) for r in rows]


def purge_old_history(db_path, days: int, output_dir) -> int:
    """Delete print_log rows (and their output images) older than `days` days."""
    cutoff = cutoff_date(days)
    with connect(db_path) as conn:
        old = conn.execute(
            "SELECT output_path FROM print_log WHERE substr(ts, 1, 10) < ?", (cutoff,)
        ).fetchall()
        conn.execute("DELETE FROM print_log WHERE substr(ts, 1, 10) < ?", (cutoff,))
    removed = 0
    for r in old:
        op = r["output_path"]
        if op and Path(op).exists():
            Path(op).unlink(missing_ok=True)
            removed += 1
    return removed
