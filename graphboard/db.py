import sqlite3
from pathlib import Path

STATES = ("proposed", "pending", "active", "running", "blocked", "done",
          "rejected", "canceled")
OPEN_STATES = ("pending", "active", "running", "blocked")
TERMINAL_STATES = ("done", "rejected", "canceled")

SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes(
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('proposed','pending','active','running',
                                      'blocked','done','rejected','canceled')),
  parent TEXT,
  on_event TEXT,
  owner TEXT,
  spec TEXT NOT NULL,
  summary TEXT NOT NULL DEFAULT '',
  note TEXT,
  resources TEXT,
  check_after TEXT,
  priority INTEGER NOT NULL DEFAULT 3,
  archived INTEGER NOT NULL DEFAULT 0,
  superseded_by TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS edges(
  from_id TEXT NOT NULL,
  on_event TEXT NOT NULL,
  to_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS outputs(
  node_id TEXT NOT NULL,
  path TEXT NOT NULL,
  note TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS announcements(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  text TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1,
  audience TEXT NOT NULL DEFAULT '*',
  expires_at TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS announcement_reads(
  owner TEXT NOT NULL,
  ann_id INTEGER NOT NULL,
  PRIMARY KEY(owner, ann_id)
);
CREATE TABLE IF NOT EXISTS messages(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  node_id TEXT NOT NULL,
  author TEXT NOT NULL,
  audience TEXT NOT NULL DEFAULT '*',
  text TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS message_reads(
  recipient TEXT NOT NULL,
  msg_id INTEGER NOT NULL,
  PRIMARY KEY(recipient, msg_id)
);
CREATE TABLE IF NOT EXISTS facts(
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  updated_by TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta(
  key TEXT PRIMARY KEY,
  value TEXT
);
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  tool TEXT NOT NULL,
  owner TEXT,
  node_id TEXT,
  detail TEXT
);
CREATE INDEX IF NOT EXISTS idx_nodes_state ON nodes(state);
CREATE INDEX IF NOT EXISTS idx_nodes_parent ON nodes(parent);
CREATE INDEX IF NOT EXISTS idx_edges_to ON edges(to_id);
"""

_NODES_REBUILD = """
BEGIN;
CREATE TABLE nodes_new(
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('proposed','pending','active','running',
                                      'blocked','done','rejected','canceled')),
  parent TEXT,
  on_event TEXT,
  owner TEXT,
  spec TEXT NOT NULL,
  note TEXT,
  resources TEXT,
  check_after TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
INSERT INTO nodes_new (id, type, state, parent, on_event, owner, spec, note,
                       resources, check_after, created_at, updated_at)
  SELECT id, type, state, parent, on_event, owner, spec, note,
         NULL, NULL, created_at, updated_at FROM nodes;
DROP TABLE nodes;
ALTER TABLE nodes_new RENAME TO nodes;
CREATE INDEX idx_nodes_state ON nodes(state);
CREATE INDEX idx_nodes_parent ON nodes(parent);
COMMIT;
"""


def _migrate(conn):
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(nodes)")}
    if cols and not {"resources", "check_after"} <= cols:
        conn.executescript(_NODES_REBUILD)
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(nodes)")}
    for col, decl in (("summary", "TEXT NOT NULL DEFAULT ''"),
                      ("priority", "INTEGER NOT NULL DEFAULT 3"),
                      ("archived", "INTEGER NOT NULL DEFAULT 0"),
                      ("superseded_by", "TEXT")):
        if cols and col not in cols:
            conn.execute(f"ALTER TABLE nodes ADD COLUMN {col} {decl}")
            conn.commit()
    ann_cols = {r["name"] for r in conn.execute("PRAGMA table_info(announcements)")}
    if ann_cols and "expires_at" not in ann_cols:
        conn.execute("ALTER TABLE announcements ADD COLUMN expires_at TEXT")
        conn.commit()
    if ann_cols and "audience" not in ann_cols:
        conn.execute(
            "ALTER TABLE announcements ADD COLUMN audience TEXT NOT NULL DEFAULT '*'")
        conn.commit()


def connect(db_path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript(SCHEMA)
    conn.commit()
    _migrate(conn)
    return conn


def get_meta(conn, key, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(conn, key, value):
    conn.execute(
        "INSERT INTO meta(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    conn.commit()
