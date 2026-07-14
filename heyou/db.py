"""SQLite data layer.

Data model (multi-embedding per person, for auto-enroll + clustering):
  * people           — one row per identity (name, cover photo, last_print_date, source).
                       `source` = 'enroll' (manually added regular) | 'auto' (auto-enrolled
                       passerby). `embedding` holds the FIRST/representative embedding for
                       back-compat; the authoritative feature library is face_embeddings.
  * face_embeddings  — one row per captured face (a person's feature library grows here).
  * print_log        — one row per generation/print event.
"""
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
            CREATE TABLE IF NOT EXISTS face_embeddings (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                person_id  INTEGER NOT NULL,
                embedding  BLOB NOT NULL,
                photo_path TEXT,
                sim        REAL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (person_id) REFERENCES people(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_face_person ON face_embeddings(person_id);
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
        # --- migrations (idempotent) ---
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(people)").fetchall()}
        if "source" not in cols:
            # existing rows were all manually enrolled regulars
            conn.execute("ALTER TABLE people ADD COLUMN source TEXT NOT NULL DEFAULT 'enroll'")
        # backfill face_embeddings for any person that has none yet (existing single-embedding
        # rows, or a create path that forgot to append) — copy people.embedding across
        orphans = conn.execute(
            """SELECT p.id, p.embedding, p.photo_path, p.created_at FROM people p
               WHERE NOT EXISTS (SELECT 1 FROM face_embeddings f WHERE f.person_id = p.id)"""
        ).fetchall()
        for r in orphans:
            conn.execute(
                "INSERT INTO face_embeddings (person_id, embedding, photo_path, sim, created_at)"
                " VALUES (?,?,?,?,?)",
                (r["id"], r["embedding"], r["photo_path"], None, r["created_at"]),
            )


def today_str() -> str:
    return dt.date.today().isoformat()


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def add_person(db_path, name: str, embedding: np.ndarray, photo_path: str | Path,
               source: str = "auto", sim: float | None = None) -> int:
    """Create a person and seed their feature library with this first embedding.
    source: 'enroll' (manual regular) | 'auto' (auto-enrolled passerby)."""
    blob = np.asarray(embedding, dtype=EMB_DTYPE).tobytes()
    now = _now()
    with connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO people (name, embedding, photo_path, created_at, source)"
            " VALUES (?,?,?,?,?)",
            (name, blob, str(photo_path), now, source),
        )
        pid = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO face_embeddings (person_id, embedding, photo_path, sim, created_at)"
            " VALUES (?,?,?,?,?)",
            (pid, blob, str(photo_path), sim, now),
        )
        return pid


def add_embedding(db_path, pid: int, embedding: np.ndarray,
                  photo_path: str | Path | None = None, sim: float | None = None) -> None:
    """Append a captured face to a person's feature library."""
    blob = np.asarray(embedding, dtype=EMB_DTYPE).tobytes()
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO face_embeddings (person_id, embedding, photo_path, sim, created_at)"
            " VALUES (?,?,?,?,?)",
            (pid, blob, str(photo_path) if photo_path else None, sim, _now()),
        )


def set_person_photo(db_path, pid: int, path: str | Path) -> None:
    """Set a person's cover photo, and backfill any of their embeddings still missing a crop."""
    with connect(db_path) as conn:
        conn.execute("UPDATE people SET photo_path=? WHERE id=?", (str(path), pid))
        conn.execute(
            "UPDATE face_embeddings SET photo_path=? "
            "WHERE person_id=? AND (photo_path IS NULL OR photo_path='')",
            (str(path), pid),
        )


def person_embedding_count(db_path, pid: int) -> int:
    with connect(db_path) as conn:
        r = conn.execute(
            "SELECT COUNT(*) AS c FROM face_embeddings WHERE person_id=?", (pid,)
        ).fetchone()
        return int(r["c"])


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
    """People with their FULL feature library, for matching. Each entry has
    `embeddings` = float32 ndarray (k, 512) — all captured faces for that person."""
    with connect(db_path) as conn:
        people = conn.execute(
            "SELECT id, name, photo_path, last_print_date, source FROM people"
        ).fetchall()
        embs = conn.execute(
            "SELECT person_id, embedding FROM face_embeddings"
        ).fetchall()
    by_pid: dict[int, list] = {}
    for r in embs:
        by_pid.setdefault(r["person_id"], []).append(
            np.frombuffer(r["embedding"], dtype=EMB_DTYPE)
        )
    gallery: list[dict] = []
    for p in people:
        vecs = by_pid.get(p["id"])
        if not vecs:
            continue  # no embeddings (shouldn't happen — init_db backfills)
        gallery.append(
            {
                "id": p["id"],
                "name": p["name"],
                "photo_path": p["photo_path"],
                "last_print_date": p["last_print_date"],
                "source": p["source"],
                "embeddings": np.stack(vecs).astype(EMB_DTYPE),  # (k, 512)
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
            """SELECT p.id, p.name, p.photo_path, p.last_print_date, p.source,
                      (SELECT COUNT(*) FROM face_embeddings f WHERE f.person_id = p.id) AS emb_count,
                      (SELECT output_path FROM print_log pl
                        WHERE pl.person_id = p.id AND pl.status IN ('generated','printed','print_failed')
                        ORDER BY pl.id DESC LIMIT 1) AS last_output,
                      (SELECT ts FROM print_log pl
                        WHERE pl.person_id = p.id AND pl.status IN ('generated','printed','print_failed')
                        ORDER BY pl.id DESC LIMIT 1) AS last_gen_ts
                 FROM people p ORDER BY p.id DESC LIMIT ? OFFSET ?""",
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


def purge_inactive_visitors(db_path, days: int) -> int:
    """Delete AUTO-enrolled visitors with no activity in `days` days (their embeddings +
    print_log cascade). Manually-enrolled regulars (source='enroll') are never purged.
    'Activity' = created_at or any print_log timestamp. Returns the count removed."""
    if days <= 0:
        return 0
    cutoff = cutoff_date(days)
    with connect(db_path) as conn:
        stale = conn.execute(
            """SELECT p.id FROM people p
                WHERE p.source = 'auto'
                  AND substr(p.created_at, 1, 10) < ?
                  AND NOT EXISTS (
                      SELECT 1 FROM print_log pl
                       WHERE pl.person_id = p.id AND substr(pl.ts, 1, 10) >= ?)""",
            (cutoff, cutoff),
        ).fetchall()
        ids = [r["id"] for r in stale]
        for pid in ids:
            conn.execute("DELETE FROM people WHERE id=?", (pid,))
    return len(ids)


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
