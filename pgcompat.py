"""Postgres (Neon) backend that mimics the small slice of the sqlite3 API db.py uses.

When DATABASE_URL is set, db.get_conn() returns a PgConn from a shared connection
pool instead of a sqlite3 connection. SQL in db.py stays SQLite-style; this module
translates it on the fly (cached per statement):

  • `?` placeholders            → `%s`
  • INSERT OR IGNORE            → INSERT … ON CONFLICT DO NOTHING
  • INTEGER PRIMARY KEY AUTOINCREMENT → SERIAL PRIMARY KEY;  REAL → DOUBLE PRECISION
  • ALTER TABLE … ADD COLUMN    → … ADD COLUMN IF NOT EXISTS
  • INSERT into a table with a serial id → … RETURNING id  (so cursor.lastrowid works)
  • PRAGMA / BEGIN IMMEDIATE    → no-ops (psycopg opens a transaction implicitly;
                                  db.py adds SELECT … FOR UPDATE where it must lock)

Rows behave like sqlite3.Row: row["col"], row[0], and dict(row) all work.
Connections come from a psycopg_pool pool, because opening a TLS connection to a
network database per query (the SQLite pattern) would be far too slow.
"""
import functools
import re
import threading

import psycopg
from psycopg import adapters
from psycopg.types.numeric import FloatLoader

# Postgres NUMERIC (e.g. SUM over BIGINT) would load as Decimal, which doesn't mix
# with float arithmetic the app does; SQLite returned int/float.
adapters.register_loader("numeric", FloatLoader)

# Tables whose primary key is a serial `id` (filled in from the schema at init).
SERIAL_TABLES = set()

_pool = None
_pool_lock = threading.Lock()


class Row(dict):
    """dict that also supports positional access, like sqlite3.Row."""
    __slots__ = ()

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return dict.__getitem__(self, key)


def _row_factory(cursor):
    names = [c.name for c in cursor.description] if cursor.description else []

    def make(values):
        return Row(zip(names, values))
    return make


def _to_pg_types(sql):
    sql = re.sub(r"INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT", "SERIAL PRIMARY KEY", sql, flags=re.I)
    return re.sub(r"\bREAL\b", "DOUBLE PRECISION", sql)


@functools.lru_cache(maxsize=1024)
def translate(sql):
    """SQLite-dialect SQL → Postgres. Returns None for statements to skip."""
    s = sql.strip()
    head = s[:20].upper()
    if head.startswith("PRAGMA") or head.startswith("BEGIN"):
        return None
    s = _to_pg_types(s)
    s = re.sub(r"ADD\s+COLUMN\s+(?!IF\s)", "ADD COLUMN IF NOT EXISTS ", s, flags=re.I)
    ignore = re.match(r"INSERT\s+OR\s+IGNORE\s+INTO", s, flags=re.I)
    if ignore:
        s = "INSERT INTO" + s[ignore.end():] + " ON CONFLICT DO NOTHING"
    # Placeholders (db.py never uses literal '?' or '%' inside SQL strings).
    s = s.replace("%", "%%").replace("?", "%s")
    m = re.match(r"INSERT\s+INTO\s+(\w+)", s, flags=re.I)
    if m and m.group(1).lower() in SERIAL_TABLES and "RETURNING" not in s.upper():
        s += " RETURNING id"
    return s


def register_schema(schema_sql):
    for m in re.finditer(r"CREATE TABLE IF NOT EXISTS (\w+)\s*\(\s*id\s+INTEGER\s+PRIMARY KEY",
                         schema_sql, flags=re.I):
        SERIAL_TABLES.add(m.group(1).lower())


class _EmptyCursor:
    lastrowid = None
    rowcount = 0

    def fetchone(self):
        return None

    def fetchall(self):
        return []


class PgCursor:
    def __init__(self, cur, returning_id):
        self._cur = cur
        self.rowcount = cur.rowcount
        self.lastrowid = None
        if returning_id:
            row = cur.fetchone()
            self.lastrowid = row[0] if row else None

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    def __iter__(self):
        return iter(self._cur.fetchall())


class PgConn:
    """sqlite3.Connection look-alike over a pooled psycopg connection."""

    def __init__(self, pool, on_commit=None):
        self._pool = pool
        self._conn = pool.getconn()
        self._on_commit = on_commit

    def execute(self, sql, params=()):
        pg = translate(sql)
        if pg is None:
            return _EmptyCursor()
        cur = self._conn.cursor(row_factory=_row_factory)
        if params:
            cur.execute(pg, tuple(params))
        else:
            cur.execute(pg.replace("%%", "%"))
        return PgCursor(cur, pg.endswith("RETURNING id"))

    def executemany(self, sql, seq):
        pg = translate(sql)
        with self._conn.cursor() as cur:
            cur.executemany(pg, [tuple(r) for r in seq])

    def executescript(self, script):
        script = re.sub(r"--[^\n]*", "", script)       # comments may contain ';'
        for stmt in script.split(";"):
            if stmt.strip():
                pg = translate(stmt)
                if pg:
                    self._conn.execute(pg.replace("%%", "%"))

    def commit(self):
        self._conn.commit()
        if self._on_commit:
            self._on_commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        if self._conn is None:
            return
        try:
            # Anything not committed is discarded, matching sqlite3's close().
            if self._conn.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
                self._conn.rollback()
        finally:
            self._pool.putconn(self._conn)
            self._conn = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def get_pool(url):
    """One pool per process. Small: Streamlit runs every session in one process and
    a page render holds a connection only for one query at a time."""
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                from psycopg_pool import ConnectionPool
                _pool = ConnectionPool(
                    url, min_size=1, max_size=10, timeout=30,
                    max_idle=300,          # let Neon scale to zero when the class is idle
                    kwargs={"prepare_threshold": None},   # required behind PgBouncer
                    check=ConnectionPool.check_connection,  # survive Neon suspends
                    open=True)
                import atexit
                atexit.register(_pool.close)
    return _pool
