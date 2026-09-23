"""SQLite storage. Stdlib only — no server, no setup."""
import sqlite3
import hashlib
import os

DB_PATH = os.environ.get("CR_DB", "review.db")

SCHEMA = """
-- LIVE cache. Mutable: re-fetching can change these rows (this is the drift).
CREATE TABLE IF NOT EXISTS items (
  source            TEXT NOT NULL,
  source_id         TEXT NOT NULL,
  kind              TEXT NOT NULL,          -- post | comment
  parent_source_id  TEXT,
  author            TEXT,
  text              TEXT,
  url               TEXT,
  fetched_at        TEXT,
  content_hash      TEXT,
  PRIMARY KEY (source, source_id)
);

-- A named freeze point.
CREATE TABLE IF NOT EXISTS snapshots (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  name        TEXT UNIQUE NOT NULL,
  created_at  TEXT,
  note        TEXT
);

-- IMMUTABLE copies. Evals read ONLY from here, never from `items`.
-- This is the whole point: live data drifts, eval inputs do not.
CREATE TABLE IF NOT EXISTS frozen_items (
  snapshot_id       INTEGER NOT NULL,
  source_id         TEXT NOT NULL,
  kind              TEXT,
  parent_source_id  TEXT,
  author            TEXT,
  text              TEXT,
  content_hash      TEXT,
  PRIMARY KEY (snapshot_id, source_id)
);

CREATE TABLE IF NOT EXISTS reviews (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  snapshot_id   INTEGER,
  status        TEXT,                        -- open | complete
  opened_by     TEXT,
  opened_at     TEXT,
  completed_at  TEXT
);

CREATE TABLE IF NOT EXISTS labels (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  review_id   INTEGER,
  source_id   TEXT,
  label       TEXT,                          -- violating | ok
  reason      TEXT,
  confidence  REAL,
  labeled_by  TEXT,                          -- human:<name> | agent:<labeler>
  created_at  TEXT
);

CREATE TABLE IF NOT EXISTS eval_runs (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  snapshot_id   INTEGER,
  labeler       TEXT,
  created_at    TEXT,
  metrics_json  TEXT,
  passed        INTEGER
);
"""


def connect(path=None):
    conn = sqlite3.connect(path or DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init(path=None):
    conn = connect(path)
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.commit()
    return conn


def _migrate(conn):
    """Additive migrations for databases created before a column existed.

    `version` stamps each eval run with a hash of the labeler's prompt +
    policy. Without it "I changed the prompt and precision went up" is a claim,
    not a measurement — you cannot attribute a delta to a change you can't
    identify.
    """
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(eval_runs)")}
    if "version" not in cols:
        conn.execute("ALTER TABLE eval_runs ADD COLUMN version TEXT")

    # `snapshot_id` scopes a stored label to the snapshot it was produced from.
    # Without it a cached label could be replayed against different frozen text
    # carrying the same source_id -- the exact class of bug freezing exists to
    # prevent, reintroduced by the cache.
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(labels)")}
    if "snapshot_id" not in cols:
        conn.execute("ALTER TABLE labels ADD COLUMN snapshot_id INTEGER")


def labeler_version(labeler, policy_path="policy.md"):
    """Hash what actually determines the labeler's behaviour."""
    parts = [getattr(labeler, "name", labeler.__class__.__name__)]
    for attr in ("PROMPT", "PATTERNS"):
        if hasattr(labeler, attr):
            parts.append(repr(getattr(labeler, attr)))
    if os.path.exists(policy_path):
        parts.append(open(policy_path).read())
    return content_hash("\n".join(parts))


def content_hash(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]
