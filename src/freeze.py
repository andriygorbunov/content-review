"""Data freezing — the core of the eval story.

Live content drifts: posts get edited, comments get deleted, moderation changes
state. If evals read live data, the same eval run gives different results over
time and you can no longer tell a model regression from a data change.

Fix: a snapshot copies the content at freeze time into an immutable table.
Evals read ONLY frozen_items. Runs stay byte-for-byte replayable forever.
"""
from datetime import datetime, timezone


def create(conn, name, source="hn", note=""):
    """Freeze every currently-live item into a named snapshot."""
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        "INSERT INTO snapshots (name, created_at, note) VALUES (?,?,?)",
        (name, now, note),
    )
    sid = cur.lastrowid
    rows = conn.execute(
        "SELECT * FROM items WHERE source=?", (source,)
    ).fetchall()
    for r in rows:
        conn.execute(
            """INSERT INTO frozen_items
               (snapshot_id, source_id, kind, parent_source_id, author, text, content_hash)
               VALUES (?,?,?,?,?,?,?)""",
            (sid, r["source_id"], r["kind"], r["parent_source_id"],
             r["author"], r["text"], r["content_hash"]),
        )
    conn.commit()
    return sid, len(rows)


def get_id(conn, name):
    row = conn.execute("SELECT id FROM snapshots WHERE name=?", (name,)).fetchone()
    return row["id"] if row else None


def items(conn, snapshot_id):
    return conn.execute(
        "SELECT * FROM frozen_items WHERE snapshot_id=? ORDER BY source_id",
        (snapshot_id,),
    ).fetchall()


def live_items(conn, source="hn"):
    """Only for comparison/demo — evals must NOT use this."""
    return conn.execute(
        "SELECT * FROM items WHERE source=? ORDER BY source_id", (source,)
    ).fetchall()


def verify(conn, snapshot_id):
    """Integrity check: does frozen text still hash to the stored hash?
    Also reports how far LIVE has drifted from the freeze."""
    from . import db
    frozen = items(conn, snapshot_id)
    tampered, drifted = [], []
    for f in frozen:
        if db.content_hash(f["text"]) != f["content_hash"]:
            tampered.append(f["source_id"])
        live = conn.execute(
            "SELECT content_hash FROM items WHERE source_id=?", (f["source_id"],)
        ).fetchone()
        if live and live["content_hash"] != f["content_hash"]:
            drifted.append(f["source_id"])
    return {"frozen": len(frozen), "tampered": tampered, "drifted_vs_live": drifted}
