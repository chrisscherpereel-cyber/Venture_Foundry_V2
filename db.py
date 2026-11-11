"""
db.py — SQLite persistence layer for Venture Foundry: From hunch to hard evidence.

A single-file database keeps the whole cohort's state so progress survives
restarts and multiple teams can play in parallel. All access goes through the
helpers here; views never write raw SQL.
"""

import sqlite3
import json
import os
import secrets
import threading
from datetime import datetime, timezone

DB_PATH = os.environ.get(
    "VF_DB_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "venture_foundry.db"),
)


# --------------------------------------------------------------------------- #
# Connection / bootstrap
# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# Per-run read cache
#   A single page render calls the same read helpers hundreds of times (the nav,
#   to-do list, and gating logic each recompute the round checklist). Within ONE
#   script run of ONE session, identical reads are served from memory.
#
#   Safety rules:
#     • Scope: thread-local AND only active between begin_request()/end_request(),
#       which app.py wraps around the script body. Widget callbacks (which run
#       before the script body) and any code outside a run always hit SQLite.
#     • Any commit (from any helper) clears the cache, so a run never reads its
#       own stale data after a write.
#     • Never shared across sessions, so no data can leak between users.
#     • Callers receive a copy, so mutating a result can't corrupt the cache.
# --------------------------------------------------------------------------- #
# Thread-local per-session context: active game + the per-run read cache.
_ctx = threading.local()
_SENTINEL = object()


def _clone(v):
    """Fast deep copy for the JSON-like values these helpers return."""
    if isinstance(v, dict):
        return {k: _clone(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_clone(x) for x in v]
    if isinstance(v, set):
        return set(v)
    return v


def begin_request():
    """Start a fresh per-run read cache (called at the top of every script run)."""
    _ctx.cache = {}


def end_request():
    """Drop the per-run cache (called in a finally block at the end of the run)."""
    _ctx.cache = None


def invalidate_run_cache():
    c = getattr(_ctx, "cache", None)
    if c:
        c.clear()


def run_memo(fn=None, *, copier=_clone):
    """Memoize a pure read for the remainder of the current script run."""
    def deco(f):
        name = f"{f.__module__}.{f.__qualname__}"

        def wrapper(*args, **kwargs):
            cache = getattr(_ctx, "cache", None)
            if cache is None:
                return f(*args, **kwargs)
            try:
                key = (name, getattr(_ctx, "game_id", None), args,
                       tuple(sorted(kwargs.items())))
                hit = cache.get(key, _SENTINEL)
            except TypeError:          # unhashable argument — don't cache
                return f(*args, **kwargs)
            if hit is _SENTINEL:
                hit = f(*args, **kwargs)
                cache[key] = hit
            return copier(hit)

        wrapper.__wrapped__ = f
        wrapper.__name__ = f.__name__
        wrapper.__doc__ = f.__doc__
        return wrapper
    return deco(fn) if fn is not None else deco


class _Conn(sqlite3.Connection):
    """sqlite3 connection that clears the per-run read cache on every commit."""

    def commit(self):
        super().commit()
        invalidate_run_cache()


# --------------------------------------------------------------------------- #
# Backend selection
#   DATABASE_URL set (e.g. a Neon Postgres connection string in Streamlit Secrets,
#   which Streamlit exposes as an environment variable) → Postgres, durable across
#   app restarts. Otherwise → the local SQLite file (development / fallback).
# --------------------------------------------------------------------------- #
def _database_url():
    url = (os.environ.get("DATABASE_URL") or "").strip()
    if not url:
        try:                                  # also read Streamlit secrets directly
            import streamlit as _st
            url = str(_st.secrets.get("DATABASE_URL", "") or "").strip()
        except Exception:                     # no secrets file / not under Streamlit
            url = ""
    return url or None


DATABASE_URL = _database_url()
IS_PG = bool(DATABASE_URL)


def backend_name():
    return "Postgres (Neon)" if IS_PG else "SQLite (local file)"


def get_conn():
    if IS_PG:
        import pgcompat
        if not pgcompat.SERIAL_TABLES:
            pgcompat.register_schema(SCHEMA + _EXTRA_TABLES)
        return pgcompat.PgConn(pgcompat.get_pool(DATABASE_URL), on_commit=invalidate_run_cache)
    # timeout: wait up to 30 s for a competing writer instead of failing fast with
    # "database is locked" when many students save at once.
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30, factory=_Conn)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # Safe with WAL (set in init_db): durable across app crashes, far fewer fsyncs.
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _dumps(obj):
    return json.dumps(obj, ensure_ascii=False)


def _loads(text, default=None):
    if not text:
        return default
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return default


# Tables created inside init_db (not in SCHEMA) that have a serial id.
_EXTRA_TABLES = """
CREATE TABLE IF NOT EXISTS partners (
    id          INTEGER PRIMARY KEY AUTOINCREMENT);
"""

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS games (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    current_round INTEGER DEFAULT 1,   -- each game advances independently
    hours_marker  INTEGER DEFAULT 1,   -- per-game marker for round-change side effects
    created_at    TEXT
);

CREATE TABLE IF NOT EXISTS teams (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    name               TEXT NOT NULL,
    join_code          TEXT UNIQUE NOT NULL,
    opportunity        TEXT,
    founder_card       TEXT,            -- JSON
    ventures           TEXT,            -- JSON list of candidate ventures
    capital            REAL DEFAULT 0,
    evidence_credits   REAL DEFAULT 0,
    venture_tokens     INTEGER DEFAULT 100,
    founder_hours      REAL DEFAULT 0,
    stage              TEXT DEFAULT 'Opportunity formation',
    market_potential   REAL DEFAULT 1000000,
    unresolved_risk    REAL DEFAULT 0,
    created_at         TEXT
);

CREATE TABLE IF NOT EXISTS canvases (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id    INTEGER NOT NULL,
    ctype      TEXT NOT NULL,           -- customer_profile | vpc | bmc
    version    INTEGER NOT NULL,
    label      TEXT,
    data       TEXT,                    -- JSON block->text
    note       TEXT,
    created_at TEXT,
    FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS assumptions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id        INTEGER NOT NULL,
    text           TEXT NOT NULL,
    risk_type      TEXT,                -- Desirability | Feasibility | Viability | Adaptability
    importance     INTEGER DEFAULT 3,   -- 1..5
    evidence_level INTEGER DEFAULT 1,   -- 1..5 (how much we already know)
    testability    INTEGER DEFAULT 3,   -- 1..5
    status         TEXT DEFAULT 'Untested',  -- Untested|Testing|Supported|Refuted|Ignored
    created_at     TEXT,
    FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS experiments (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id           INTEGER NOT NULL,
    assumption_id     INTEGER,
    card_type         TEXT,
    cost_money        REAL DEFAULT 0,
    cost_time         REAL DEFAULT 0,
    cost_credits      REAL DEFAULT 0,
    evidence_strength INTEGER DEFAULT 0,
    hypothesis        TEXT,
    metric            TEXT,
    success_threshold TEXT,
    failure_threshold TEXT,
    decision_rule     TEXT,
    result            TEXT,
    outcome           TEXT DEFAULT 'Designed',  -- Designed|Running|Supported|Refuted|Inconclusive
    created_at        TEXT,
    FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS evidence (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id       INTEGER NOT NULL,
    description   TEXT,
    evidence_type TEXT,
    strength      INTEGER DEFAULT 0,
    source        TEXT,
    assumption_id INTEGER,
    credits_award REAL DEFAULT 0,
    created_at    TEXT,
    FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id    INTEGER,                 -- NULL => broadcast to all teams
    round      INTEGER,
    category   TEXT,
    text       TEXT,
    exposes    TEXT,
    resolved   INTEGER DEFAULT 0,
    created_at TEXT,
    FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS pivots (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id          INTEGER NOT NULL,
    original_assum   TEXT,
    challenge_evid   TEXT,
    affected_block   TEXT,
    proposed_change  TEXT,
    change_cost      REAL DEFAULT 0,
    new_assumptions  TEXT,
    evidence_needed  TEXT,
    status           TEXT DEFAULT 'Submitted',  -- Submitted|Approved|Conditional|NeedsEvidence|Rejected|RandomChange
    committee_note   TEXT,
    created_at       TEXT,
    FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS reflections (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id      INTEGER NOT NULL,
    student_name TEXT,
    round        INTEGER,
    expected     TEXT,
    occurred     TEXT,
    assumption   TEXT,
    overlooked   TEXT,
    differently  TEXT,
    contribution TEXT,
    created_at   TEXT,
    FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS scores (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id    INTEGER NOT NULL,
    round      INTEGER,
    dimension  TEXT,
    score      REAL,                    -- 0..100
    created_at TEXT,
    FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS transactions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id     INTEGER NOT NULL,
    kind        TEXT,
    money       REAL DEFAULT 0,
    credits     REAL DEFAULT 0,
    hours       REAL DEFAULT 0,
    description TEXT,
    created_at  TEXT,
    FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS value_props (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id          INTEGER NOT NULL,
    name             TEXT NOT NULL,
    description      TEXT,
    evidence_strength INTEGER DEFAULT 0,   -- 0..10, should reflect the evidence ledger
    tokens           INTEGER DEFAULT 0,    -- current Venture Token allocation
    prev_tokens      INTEGER,              -- allocation at previous auction (NULL until first run)
    created_at       TEXT,
    FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS vp_results (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id        INTEGER NOT NULL,
    round          INTEGER,
    total_tokens   INTEGER,
    alignment      REAL,
    prev_alignment REAL,
    tax            REAL,
    dividend       REAL,
    net_credits    REAL,
    note           TEXT,
    created_at     TEXT,
    FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ai_logs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id       INTEGER NOT NULL,
    round         INTEGER,
    tool_area     TEXT,
    prompt        TEXT,
    ai_output     TEXT,
    audit_a       TEXT,   -- Assumptions surfaced
    audit_u       TEXT,   -- Unsupported claims flagged
    audit_d       TEXT,   -- Data & sources checked
    audit_i       TEXT,   -- Independent test designed
    audit_t       TEXT,   -- Translate to evidence
    status        TEXT DEFAULT 'Unverified',
    created_at    TEXT,
    FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS schedule (
    round      INTEGER PRIMARY KEY,   -- 1..total_rounds
    topic_key  TEXT,                  -- legacy single-topic column (unused; kept for compat)
    advance_at TEXT                   -- ISO datetime this round should begin (optional)
);

CREATE TABLE IF NOT EXISTS round_topics (
    topic_key TEXT PRIMARY KEY,       -- each curriculum topic is placed in exactly one round
    round     INTEGER,                -- which round covers this material
    position  INTEGER                 -- order of the material within that round
);

CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id    INTEGER NOT NULL,
    round      INTEGER,
    subject    TEXT,
    body       TEXT,
    sender     TEXT,
    read       INTEGER DEFAULT 0,
    created_at TEXT,
    FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS team_skills (
    team_id   INTEGER NOT NULL,
    skill_key TEXT NOT NULL,
    level     INTEGER DEFAULT 1,
    PRIMARY KEY (team_id, skill_key),
    FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS round_answers (
    team_id    INTEGER NOT NULL,
    round      INTEGER NOT NULL,
    concept    TEXT NOT NULL,
    answer     TEXT,
    created_at TEXT,
    PRIMARY KEY (team_id, round, concept),
    FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS acknowledgments (
    team_id    INTEGER NOT NULL,
    key        TEXT NOT NULL,
    created_at TEXT,
    PRIMARY KEY (team_id, key),
    FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS hires (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id    INTEGER NOT NULL,
    skill_key  TEXT NOT NULL,
    role       TEXT,
    kind       TEXT,          -- part_time | full_time
    boost      INTEGER DEFAULT 0,
    per_round  REAL DEFAULT 0,
    manage_hours REAL DEFAULT 0,
    created_at TEXT,
    FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS skill_xp (
    team_id   INTEGER NOT NULL,
    skill_key TEXT NOT NULL,
    xp        INTEGER DEFAULT 0,
    PRIMARY KEY (team_id, skill_key),
    FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS commitments (
    team_id      INTEGER NOT NULL,
    round        INTEGER NOT NULL,
    committed    INTEGER DEFAULT 0,     -- 1 = team has locked in this round's work
    committed_at TEXT,                  -- ISO datetime the team committed
    due_at       TEXT,                  -- ISO decision deadline captured at commit time
    snapshot     TEXT,                  -- JSON snapshot of the checklist at commit time
    PRIMARY KEY (team_id, round),
    FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS metrics_history (
    team_id    INTEGER NOT NULL,
    round      INTEGER NOT NULL,
    metrics    TEXT,                    -- JSON snapshot of learning metrics for the round
    created_at TEXT,
    PRIMARY KEY (team_id, round),
    FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE
);
"""


def _ensure_column(conn, pg, table, column, decl):
    if pg:          # translated to ADD COLUMN IF NOT EXISTS
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
        return
    cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def _create_schema(conn, pg):
    """All tables and column migrations, for either backend (also used to build a
    SQLite backup file from a Postgres database)."""
    conn.executescript(SCHEMA)
    _ensure_column(conn, pg, "teams", "hours_per_round", "REAL DEFAULT 60")
    _ensure_column(conn, pg, "teams", "build_pct", "INTEGER DEFAULT 60")
    _ensure_column(conn, pg, "teams", "effort_hours", "REAL DEFAULT 60")
    _ensure_column(conn, pg, "teams", "hours_round", "INTEGER DEFAULT 0")
    _ensure_column(conn, pg, "teams", "build_budget", "REAL DEFAULT 34")
    _ensure_column(conn, pg, "teams", "spent_build", "REAL DEFAULT 0")
    _ensure_column(conn, pg, "teams", "spent_train", "REAL DEFAULT 0")
    _ensure_column(conn, pg, "teams", "spent_other", "REAL DEFAULT 0")
    _ensure_column(conn, pg, "hires", "manage_hours", "REAL DEFAULT 0")
    # Evidence: teams justify why a piece of evidence is the strength they chose.
    _ensure_column(conn, pg, "evidence", "justification", "TEXT")
    # Experiments: calibration — the team's prediction + confidence before results.
    _ensure_column(conn, pg, "experiments", "predicted_outcome", "TEXT")
    _ensure_column(conn, pg, "experiments", "confidence", "INTEGER")
    # Pivots: lightweight "mini" course-corrections available from early rounds.
    _ensure_column(conn, pg, "pivots", "kind", "TEXT DEFAULT 'formal'")
    _ensure_column(conn, pg, "pivots", "round", "INTEGER")
    _ensure_column(conn, pg, "pivots", "pivot_type", "TEXT")   # Lean Startup pivot taxonomy
    # Learning Card — structured result capture for an experiment.
    _ensure_column(conn, pg, "experiments", "learned", "TEXT")     # the insight
    _ensure_column(conn, pg, "experiments", "decision", "TEXT")    # persevere / pivot / stop / next
    _ensure_column(conn, pg, "experiments", "signal", "TEXT")      # evidence signal (commitment ladder)
    # Effectuation — "lemonade": how a team turns a market event into opportunity.
    _ensure_column(conn, pg, "events", "exploit", "TEXT")
    # Effectuation — "crazy quilt": self-selected partners who pre-commit.
    conn.execute("""CREATE TABLE IF NOT EXISTS partners (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        team_id     INTEGER NOT NULL,
        name        TEXT,
        commitment  TEXT,
        evidence    TEXT,
        round       INTEGER,
        created_at  TEXT,
        FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE)""")
    # AI logs: faster structured capture + link an AI claim to a real test so it
    # can auto-verify when that test resolves.
    _ensure_column(conn, pg, "ai_logs", "claim_type", "TEXT")     # fact | prediction | opinion
    _ensure_column(conn, pg, "ai_logs", "data_source", "TEXT")    # none | cited-unchecked | verified
    _ensure_column(conn, pg, "ai_logs", "verify_plan", "TEXT")    # how they'll check it
    _ensure_column(conn, pg, "ai_logs", "assumption_id", "INTEGER")
    _ensure_column(conn, pg, "ai_logs", "experiment_id", "INTEGER")
    _ensure_column(conn, pg, "ai_logs", "use_type", "TEXT")   # how the AI was used
    _ensure_column(conn, pg, "ai_logs", "ai_model", "TEXT")   # which AI tool/model was used
    # Multi-game: teams belong to a game (cohort); each game advances on its own.
    _ensure_column(conn, pg, "teams", "game_id", "INTEGER")
    _ensure_column(conn, pg, "teams", "roster", "TEXT")       # JSON member roster
    # Team identity — a chosen display name, colour, and mascot.
    _ensure_column(conn, pg, "teams", "display_name", "TEXT")
    _ensure_column(conn, pg, "teams", "color", "TEXT")
    _ensure_column(conn, pg, "teams", "mascot", "TEXT")
    # Venture naming — the team's chosen product/company name + its scored evaluation.
    _ensure_column(conn, pg, "teams", "venture_name", "TEXT")
    _ensure_column(conn, pg, "teams", "venture_name_scores", "TEXT")   # JSON eval
    conn.execute("""CREATE TABLE IF NOT EXISTS badges (
        team_id  INTEGER NOT NULL,
        code     TEXT NOT NULL,
        earned_at TEXT,
        PRIMARY KEY (team_id, code),
        FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE)""")
    # Demo Day / Evidence Exchange finale — pitches + peer votes.
    conn.execute("""CREATE TABLE IF NOT EXISTS demo_pitches (
        team_id       INTEGER PRIMARY KEY,
        game_id       INTEGER,
        headline      TEXT,
        pitch         TEXT,
        best_evidence TEXT,
        ask           TEXT,
        updated_at    TEXT,
        FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS demo_votes (
        game_id       INTEGER NOT NULL,
        voter_team_id INTEGER NOT NULL,
        votee_team_id INTEGER NOT NULL,
        created_at    TEXT,
        PRIMARY KEY (game_id, voter_team_id, votee_team_id))""")
    # Demo Day money allocation — dollars a voter invests in each pitch.
    _ensure_column(conn, pg, "demo_votes", "amount", "INTEGER DEFAULT 0")
    # Structured Pitch Canvas (JSON of block -> text) behind the Demo Day pitch.
    _ensure_column(conn, pg, "demo_pitches", "canvas", "TEXT")
    # Decision Journal: one round-adaptive focus question per entry.
    _ensure_column(conn, pg, "reflections", "focus_prompt", "TEXT")
    _ensure_column(conn, pg, "reflections", "focus_answer", "TEXT")
    # Rotating perspective (lens) taken for this journal entry, + the lens answer.
    _ensure_column(conn, pg, "reflections", "perspective", "TEXT")
    _ensure_column(conn, pg, "reflections", "perspective_note", "TEXT")


def init_db():
    conn = get_conn()
    try:
        if IS_PG:
            # One-time DDL; serialize across server processes with an advisory lock.
            conn.execute("SELECT pg_advisory_xact_lock(424242)")
        # Write-ahead logging lets readers proceed while one session writes, which
        # sharply reduces lock contention with many concurrent students. The mode is
        # stored in the database file, so this only needs to run once.
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError:
            pass   # e.g. a filesystem that can't do WAL — fall back to the default
        _create_schema(conn, IS_PG)
        # Seed default settings once.
        cur = conn.execute("SELECT value FROM settings WHERE key='current_round'")
        if cur.fetchone() is None:
            conn.execute(
                "INSERT INTO settings(key, value) VALUES(?,?)",
                ("current_round", "1"),
            )
            conn.execute(
                "INSERT INTO settings(key, value) VALUES(?,?)",
                ("instructor_pin", "foundry"),
            )
        conn.commit()
    finally:
        conn.close()
    # Seed the default schedule/total-rounds on first run (import here to avoid a
    # circular import at module load).
    import content
    if get_setting("total_rounds") is None:
        set_setting("total_rounds", content.DEFAULT_TOTAL_ROUNDS)
    if not get_schedule_rows():
        for i in range(content.DEFAULT_TOTAL_ROUNDS):
            upsert_schedule_row(i + 1, None, None)   # advance-time rows only
    if not get_round_topics():
        for i, key in enumerate(content.DEFAULT_TOPIC_ORDER):
            set_topic_placement(key, i + 1, 0)       # one topic per round by default
    # Ensure at least one game exists; migrate any legacy team into it.
    if not list_games():
        gid = create_game("Game 1")
        legacy_round = int(get_setting("current_round", "1") or 1)
        set_game_round(gid, legacy_round)
        conn = get_conn()
        try:
            conn.execute("UPDATE teams SET game_id=? WHERE game_id IS NULL", (gid,))
            conn.commit()
        finally:
            conn.close()


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #
@run_memo
def get_setting(key, default=None):
    conn = get_conn()
    try:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default
    finally:
        conn.close()


def set_setting(key, value):
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Games (cohorts) — multiple can run at once, each with its own round pointer.
# An "active game" context (set per request) makes current_round(), list_teams(),
# and the round-change markers resolve to whichever game is being played/managed.
# --------------------------------------------------------------------------- #
# Thread-local (_ctx, defined above) so concurrent sessions (each a Streamlit
# ScriptRunner thread) never clobber each other's active-game context.


def set_active_game(game_id):
    _ctx.game_id = int(game_id) if game_id else None


def active_game_id():
    return getattr(_ctx, "game_id", None)


def create_game(name):
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO games(name, current_round, hours_marker, created_at) VALUES(?,1,1,?)",
            (name, now()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


@run_memo
def list_games():
    conn = get_conn()
    try:
        rows = conn.execute("SELECT * FROM games ORDER BY id").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@run_memo
def get_game(game_id):
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM games WHERE id=?", (game_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def rename_game(game_id, name):
    conn = get_conn()
    try:
        conn.execute("UPDATE games SET name=? WHERE id=?", (name, game_id))
        conn.commit()
    finally:
        conn.close()


def delete_game(game_id):
    conn = get_conn()
    try:
        conn.execute("DELETE FROM teams WHERE game_id=?", (game_id,))
        conn.execute("DELETE FROM games WHERE id=?", (game_id,))
        conn.commit()
    finally:
        conn.close()


def set_game_round(game_id, rnd):
    conn = get_conn()
    try:
        conn.execute("UPDATE games SET current_round=? WHERE id=?", (int(rnd), game_id))
        conn.commit()
    finally:
        conn.close()


def get_game_marker(game_id):
    g = get_game(game_id)
    return int(g["hours_marker"]) if g and g.get("hours_marker") is not None else 1


def set_game_marker(game_id, marker):
    conn = get_conn()
    try:
        conn.execute("UPDATE games SET hours_marker=? WHERE id=?", (int(marker), game_id))
        conn.commit()
    finally:
        conn.close()


def current_round():
    gid = active_game_id()
    if gid:
        g = get_game(gid)
        if g:
            return int(g["current_round"])
    return int(get_setting("current_round", "1"))


def set_current_round(rnd):
    """Set the round for the active game (or the legacy global if no game context)."""
    gid = active_game_id()
    if gid:
        set_game_round(gid, rnd)
    else:
        set_setting("current_round", int(rnd))


# --------------------------------------------------------------------------- #
# Teams
# --------------------------------------------------------------------------- #
def create_team(name, opportunity="", founder_card=None, capital=2000,
                evidence_credits=10, founder_hours=40, market_potential=1000000,
                hours_per_round=None, game_id=None, roster=None):
    conn = get_conn()
    try:
        code = secrets.token_hex(3).upper()
        # `founder_hours` here is the per-round time budget; teams start with one
        # round's worth and are topped up each round.
        hpr = hours_per_round if hours_per_round is not None else founder_hours
        gid = game_id if game_id is not None else active_game_id()
        cur = conn.execute(
            """INSERT INTO teams(name, join_code, opportunity, founder_card, ventures,
                                 capital, evidence_credits, venture_tokens, founder_hours,
                                 market_potential, hours_per_round, game_id, roster, created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (name, code, opportunity, _dumps(founder_card or {}), _dumps([]),
             capital, evidence_credits, 100, founder_hours, market_potential, hpr,
             gid, _dumps(roster or []), now()),
        )
        team_id = cur.lastrowid
        # Seed structured founder skills from the card archetype.
        import content
        levels = content.card_skill_levels((founder_card or {}).get("name", ""))
        for skill_key, level in levels.items():
            conn.execute(
                "INSERT INTO team_skills(team_id, skill_key, level) VALUES(?,?,?) "
                "ON CONFLICT(team_id, skill_key) DO UPDATE SET level=excluded.level",
                (team_id, skill_key, level),
            )
        conn.commit()
        return code
    finally:
        conn.close()


@run_memo
def list_teams(game_id="__active__"):
    """Teams for a game. With no argument, returns the ACTIVE game's teams (or all
    teams if no game context is set). Pass game_id=None to force all teams."""
    if game_id == "__active__":
        game_id = active_game_id()
    conn = get_conn()
    try:
        if game_id is None:
            rows = conn.execute("SELECT * FROM teams ORDER BY name").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM teams WHERE game_id=? ORDER BY name", (game_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@run_memo
def get_team(team_id):
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM teams WHERE id=?", (team_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_team_by_code(code):
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM teams WHERE join_code=?", (code.strip().upper(),)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_team(team_id, **fields):
    if not fields:
        return
    conn = get_conn()
    try:
        cols = ", ".join(f"{k}=?" for k in fields)
        conn.execute(f"UPDATE teams SET {cols} WHERE id=?", (*fields.values(), team_id))
        conn.commit()
    finally:
        conn.close()


def delete_team(team_id):
    conn = get_conn()
    try:
        conn.execute("DELETE FROM teams WHERE id=?", (team_id,))
        conn.commit()
    finally:
        conn.close()


def set_ventures(team_id, ventures):
    update_team(team_id, ventures=_dumps(ventures))


@run_memo
def get_ventures(team_id):
    t = get_team(team_id)
    return _loads(t["ventures"], []) if t else []


@run_memo
def get_founder_card(team_id):
    t = get_team(team_id)
    return _loads(t["founder_card"], {}) if t else {}


# --------------------------------------------------------------------------- #
# Resource ledger — the ONLY path that changes money/credits/hours
# --------------------------------------------------------------------------- #
def adjust_resources(team_id, money=0, credits=0, hours=0, kind="adjust",
                     description="", allow_negative=False):
    """Apply a resource change and record a transaction.

    Returns (ok, message). If allow_negative is False and the change would push
    money/credits/hours below zero, nothing is written.

    The balance check and update run inside one IMMEDIATE transaction, so two
    teammates spending at the same moment can't overwrite each other's change or
    both pass the "enough credits?" check against the same stale balance.
    """
    conn = get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        t = conn.execute(
            "SELECT capital, evidence_credits, founder_hours FROM teams WHERE id=?"
            + (" FOR UPDATE" if IS_PG else ""),          # row lock on Postgres
            (team_id,)).fetchone()
        if not t:
            conn.rollback()
            return False, "Team not found."
        new_money = t["capital"] + money
        new_credits = t["evidence_credits"] + credits
        new_hours = t["founder_hours"] + hours
        if not allow_negative:
            msg = None
            if new_money < 0:
                msg = "Not enough capital."
            elif new_credits < 0:
                msg = "Not enough Evidence Credits."
            elif new_hours < 0:
                msg = "Not enough founder-hours."
            if msg:
                conn.rollback()
                return False, msg
        conn.execute(
            "UPDATE teams SET capital=?, evidence_credits=?, founder_hours=? WHERE id=?",
            (new_money, new_credits, new_hours, team_id),
        )
        conn.execute(
            """INSERT INTO transactions(team_id, kind, money, credits, hours, description, created_at)
               VALUES(?,?,?,?,?,?,?)""",
            (team_id, kind, money, credits, hours, description, now()),
        )
        conn.commit()
        return True, "OK"
    finally:
        conn.close()


_INCREMENTABLE_TEAM_FIELDS = {"spent_build", "spent_train", "spent_other"}


def increment_team_field(team_id, field, delta):
    """Atomically add `delta` to a numeric team column (no read-modify-write race)."""
    if field not in _INCREMENTABLE_TEAM_FIELDS:
        raise ValueError(f"not an incrementable field: {field}")
    conn = get_conn()
    try:
        conn.execute(f"UPDATE teams SET {field}=COALESCE({field},0)+? WHERE id=?",
                     (delta, team_id))
        conn.commit()
    finally:
        conn.close()


@run_memo
def list_transactions(team_id, limit=100):
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM transactions WHERE team_id=? ORDER BY id DESC LIMIT ?",
            (team_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Canvases (versioned)
# --------------------------------------------------------------------------- #
def next_version(team_id, ctype):
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT MAX(version) AS m FROM canvases WHERE team_id=? AND ctype=?",
            (team_id, ctype),
        ).fetchone()
        return (row["m"] or 0) + 1
    finally:
        conn.close()


def save_canvas(team_id, ctype, data, label="", note=""):
    v = next_version(team_id, ctype)
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO canvases(team_id, ctype, version, label, data, note, created_at)
               VALUES(?,?,?,?,?,?,?)""",
            (team_id, ctype, v, label, _dumps(data), note, now()),
        )
        conn.commit()
        return v
    finally:
        conn.close()


@run_memo
def list_canvases(team_id, ctype=None):
    # Inside a page render, answer per-type lookups from the team's full canvas list
    # (one query instead of one per canvas type — matters on a network database).
    if ctype and getattr(_ctx, "cache", None) is not None:
        return [c for c in list_canvases(team_id) if c["ctype"] == ctype]
    conn = get_conn()
    try:
        if ctype:
            rows = conn.execute(
                "SELECT * FROM canvases WHERE team_id=? AND ctype=? ORDER BY version",
                (team_id, ctype),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM canvases WHERE team_id=? ORDER BY ctype, version",
                (team_id,),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["data"] = _loads(d["data"], {})
            out.append(d)
        return out
    finally:
        conn.close()


@run_memo
def latest_canvas(team_id, ctype):
    cs = list_canvases(team_id, ctype)
    return cs[-1] if cs else None


# --------------------------------------------------------------------------- #
# Assumptions
# --------------------------------------------------------------------------- #
def add_assumption(team_id, text, risk_type="Desirability", importance=3,
                   evidence_level=1, testability=3):
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO assumptions(team_id, text, risk_type, importance,
                                       evidence_level, testability, status, created_at)
               VALUES(?,?,?,?,?,?, 'Untested', ?)""",
            (team_id, text, risk_type, importance, evidence_level, testability, now()),
        )
        conn.commit()
    finally:
        conn.close()


@run_memo
def list_assumptions(team_id):
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM assumptions WHERE team_id=? ORDER BY importance DESC, id",
            (team_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def update_assumption(assum_id, **fields):
    if not fields:
        return
    conn = get_conn()
    try:
        cols = ", ".join(f"{k}=?" for k in fields)
        conn.execute(f"UPDATE assumptions SET {cols} WHERE id=?",
                     (*fields.values(), assum_id))
        conn.commit()
    finally:
        conn.close()


def delete_assumption(assum_id):
    conn = get_conn()
    try:
        conn.execute("DELETE FROM assumptions WHERE id=?", (assum_id,))
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Experiments
# --------------------------------------------------------------------------- #
def add_experiment(team_id, assumption_id, card_type, cost_money, cost_time,
                   cost_credits, evidence_strength, hypothesis, metric,
                   success_threshold, failure_threshold, decision_rule,
                   predicted_outcome=None, confidence=None):
    conn = get_conn()
    try:
        cur = conn.execute(
            """INSERT INTO experiments(team_id, assumption_id, card_type, cost_money,
                cost_time, cost_credits, evidence_strength, hypothesis, metric,
                success_threshold, failure_threshold, decision_rule,
                predicted_outcome, confidence, outcome, created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'Designed', ?)""",
            (team_id, assumption_id, card_type, cost_money, cost_time, cost_credits,
             evidence_strength, hypothesis, metric, success_threshold,
             failure_threshold, decision_rule, predicted_outcome, confidence, now()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


@run_memo
def list_experiments(team_id):
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM experiments WHERE team_id=? ORDER BY id DESC", (team_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def update_experiment(exp_id, **fields):
    if not fields:
        return
    conn = get_conn()
    try:
        cols = ", ".join(f"{k}=?" for k in fields)
        conn.execute(f"UPDATE experiments SET {cols} WHERE id=?",
                     (*fields.values(), exp_id))
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Evidence ledger
# --------------------------------------------------------------------------- #
def add_evidence(team_id, description, evidence_type, strength, source,
                 assumption_id=None, credits_award=0, justification=None):
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO evidence(team_id, description, evidence_type, strength,
                                    source, assumption_id, credits_award,
                                    justification, created_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (team_id, description, evidence_type, strength, source,
             assumption_id, credits_award, justification, now()),
        )
        conn.commit()
    finally:
        conn.close()


@run_memo
def list_evidence(team_id):
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM evidence WHERE team_id=? ORDER BY id DESC", (team_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Market events
# --------------------------------------------------------------------------- #
def add_event(team_id, round_no, category, text, exposes=""):
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO events(team_id, round, category, text, exposes, resolved, created_at)
               VALUES(?,?,?,?,?,0,?)""",
            (team_id, round_no, category, text, exposes, now()),
        )
        conn.commit()
    finally:
        conn.close()


@run_memo
def list_events(team_id=None, include_broadcast=True):
    conn = get_conn()
    try:
        if team_id is None:
            rows = conn.execute("SELECT * FROM events ORDER BY id DESC").fetchall()
        elif include_broadcast:
            rows = conn.execute(
                "SELECT * FROM events WHERE team_id=? OR team_id IS NULL ORDER BY id DESC",
                (team_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM events WHERE team_id=? ORDER BY id DESC", (team_id,)
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def resolve_event(event_id, resolved=1):
    conn = get_conn()
    try:
        conn.execute("UPDATE events SET resolved=? WHERE id=?", (resolved, event_id))
        conn.commit()
    finally:
        conn.close()


def set_event_exploit(event_id, text):
    conn = get_conn()
    try:
        conn.execute("UPDATE events SET exploit=?, resolved=1 WHERE id=?", (text, event_id))
        conn.commit()
    finally:
        conn.close()


@run_memo
def get_event(event_id):
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Partners / pre-commitments (effectuation — crazy quilt)
# --------------------------------------------------------------------------- #
def add_partner(team_id, name, commitment, evidence, round_no=None):
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO partners(team_id, name, commitment, evidence, round, created_at) "
            "VALUES(?,?,?,?,?,?)", (team_id, name, commitment, evidence, round_no, now()))
        conn.commit()
    finally:
        conn.close()


@run_memo
def list_partners(team_id):
    conn = get_conn()
    try:
        rows = conn.execute("SELECT * FROM partners WHERE team_id=? ORDER BY id DESC",
                            (team_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Pivot petitions
# --------------------------------------------------------------------------- #
def add_pivot(team_id, data, kind="formal", status="Submitted", round_no=None):
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO pivots(team_id, original_assum, challenge_evid, affected_block,
                proposed_change, change_cost, new_assumptions, evidence_needed,
                status, kind, round, pivot_type, created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (team_id, data.get("original_assum", ""), data.get("challenge_evid", ""),
             data.get("affected_block", ""), data.get("proposed_change", ""),
             data.get("change_cost", 0), data.get("new_assumptions", ""),
             data.get("evidence_needed", ""), status, kind, round_no,
             data.get("pivot_type", ""), now()),
        )
        conn.commit()
    finally:
        conn.close()


@run_memo
def list_pivots(team_id=None):
    conn = get_conn()
    try:
        if team_id is None:
            rows = conn.execute("SELECT * FROM pivots ORDER BY id DESC").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM pivots WHERE team_id=? ORDER BY id DESC", (team_id,)
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def decide_pivot(pivot_id, status, note=""):
    conn = get_conn()
    try:
        conn.execute("UPDATE pivots SET status=?, committee_note=? WHERE id=?",
                     (status, note, pivot_id))
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Reflections
# --------------------------------------------------------------------------- #
def _reflection_id(conn, team_id, student_name, round_no):
    row = conn.execute(
        "SELECT id FROM reflections WHERE team_id=? AND lower(student_name)=lower(?) AND round=?",
        (team_id, student_name, round_no),
    ).fetchone()
    return row["id"] if row else None


def add_reflection(team_id, data):
    """Insert or UPDATE a student's journal entry for a round (one per student/round),
    so returning to edit doesn't create duplicates."""
    conn = get_conn()
    try:
        existing = _reflection_id(conn, team_id, data.get("student_name", ""),
                                  data.get("round", 1))
        vals = (data.get("expected", ""), data.get("occurred", ""),
                data.get("assumption", ""), data.get("overlooked", ""),
                data.get("differently", ""), data.get("contribution", ""),
                data.get("focus_prompt", ""), data.get("focus_answer", ""),
                data.get("perspective", ""), data.get("perspective_note", ""))
        if existing:
            conn.execute(
                """UPDATE reflections SET expected=?, occurred=?, assumption=?, overlooked=?,
                    differently=?, contribution=?, focus_prompt=?, focus_answer=?,
                    perspective=?, perspective_note=?, created_at=?
                   WHERE id=?""",
                (*vals, now(), existing),
            )
        else:
            conn.execute(
                """INSERT INTO reflections(team_id, student_name, round, expected, occurred,
                    assumption, overlooked, differently, contribution, focus_prompt,
                    focus_answer, perspective, perspective_note, created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (team_id, data.get("student_name", ""), data.get("round", 1), *vals, now()),
            )
        conn.commit()
    finally:
        conn.close()


@run_memo
def get_reflection(team_id, student_name, round_no):
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM reflections WHERE team_id=? AND lower(student_name)=lower(?) AND round=?",
            (team_id, student_name, round_no),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


@run_memo
def list_reflections(team_id=None):
    conn = get_conn()
    try:
        if team_id is None:
            rows = conn.execute("SELECT * FROM reflections ORDER BY id DESC").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM reflections WHERE team_id=? ORDER BY id DESC", (team_id,)
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Dashboard scores
# --------------------------------------------------------------------------- #
def set_score(team_id, round_no, dimension, score):
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO scores(team_id, round, dimension, score, created_at)
               VALUES(?,?,?,?,?)""",
            (team_id, round_no, dimension, score, now()),
        )
        conn.commit()
    finally:
        conn.close()


@run_memo
def latest_scores(team_id):
    """Return {dimension: score} using the most recent entry per dimension."""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT dimension, score FROM scores WHERE team_id=? "
            "ORDER BY id ASC", (team_id,)
        ).fetchall()
        out = {}
        for r in rows:
            out[r["dimension"]] = r["score"]
        return out
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Value Proposition Auction
# --------------------------------------------------------------------------- #
def add_value_prop(team_id, name, description="", evidence_strength=0):
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO value_props(team_id, name, description, evidence_strength,
                                       tokens, prev_tokens, created_at)
               VALUES(?,?,?,?,0,NULL,?)""",
            (team_id, name, description, evidence_strength, now()),
        )
        conn.commit()
    finally:
        conn.close()


@run_memo
def list_value_props(team_id):
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM value_props WHERE team_id=? ORDER BY id", (team_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def update_value_prop(vp_id, **fields):
    if not fields:
        return
    conn = get_conn()
    try:
        cols = ", ".join(f"{k}=?" for k in fields)
        conn.execute(f"UPDATE value_props SET {cols} WHERE id=?",
                     (*fields.values(), vp_id))
        conn.commit()
    finally:
        conn.close()


def delete_value_prop(vp_id):
    conn = get_conn()
    try:
        conn.execute("DELETE FROM value_props WHERE id=?", (vp_id,))
        conn.commit()
    finally:
        conn.close()


def record_vp_result(team_id, round_no, total_tokens, alignment, prev_alignment,
                     tax, dividend, net_credits, note=""):
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO vp_results(team_id, round, total_tokens, alignment,
                prev_alignment, tax, dividend, net_credits, note, created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (team_id, round_no, total_tokens, alignment, prev_alignment, tax,
             dividend, net_credits, note, now()),
        )
        conn.commit()
    finally:
        conn.close()


@run_memo
def list_vp_results(team_id=None):
    conn = get_conn()
    try:
        if team_id is None:
            rows = conn.execute("SELECT * FROM vp_results ORDER BY id DESC").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM vp_results WHERE team_id=? ORDER BY id DESC", (team_id,)
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Generative-AI assist logs (AUDIT verification)
# --------------------------------------------------------------------------- #
def add_ai_log(team_id, data):
    conn = get_conn()
    try:
        cur = conn.execute(
            """INSERT INTO ai_logs(team_id, round, tool_area, prompt, ai_output,
                audit_a, audit_u, audit_d, audit_i, audit_t, status,
                claim_type, data_source, verify_plan, assumption_id, experiment_id,
                use_type, ai_model, created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (team_id, data.get("round", 1), data.get("tool_area", ""),
             data.get("prompt", ""), data.get("ai_output", ""),
             data.get("audit_a", ""), data.get("audit_u", ""), data.get("audit_d", ""),
             data.get("audit_i", ""), data.get("audit_t", ""),
             data.get("status", "Unverified"),
             data.get("claim_type"), data.get("data_source"),
             data.get("verify_plan", ""), data.get("assumption_id"),
             data.get("experiment_id"), data.get("use_type"),
             data.get("ai_model"), now()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


@run_memo
def list_ai_logs(team_id=None):
    conn = get_conn()
    try:
        if team_id is None:
            rows = conn.execute("SELECT * FROM ai_logs ORDER BY id DESC").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM ai_logs WHERE team_id=? ORDER BY id DESC", (team_id,)
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def update_ai_log(log_id, **fields):
    if not fields:
        return
    conn = get_conn()
    try:
        cols = ", ".join(f"{k}=?" for k in fields)
        conn.execute(f"UPDATE ai_logs SET {cols} WHERE id=?", (*fields.values(), log_id))
        conn.commit()
    finally:
        conn.close()


def delete_ai_log(log_id):
    conn = get_conn()
    try:
        conn.execute("DELETE FROM ai_logs WHERE id=?", (log_id,))
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Schedule (round -> topic -> advance datetime). Raw CRUD; higher-level seeding
# and derived queries live in logic.py.
# --------------------------------------------------------------------------- #
@run_memo
def get_schedule_rows():
    conn = get_conn()
    try:
        rows = conn.execute("SELECT * FROM schedule ORDER BY round").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def upsert_schedule_row(round_no, topic_key, advance_at=None):
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO schedule(round, topic_key, advance_at) VALUES(?,?,?) "
            "ON CONFLICT(round) DO UPDATE SET topic_key=excluded.topic_key, "
            "advance_at=excluded.advance_at",
            (round_no, topic_key, advance_at),
        )
        conn.commit()
    finally:
        conn.close()


def set_schedule_topic(round_no, topic_key):
    conn = get_conn()
    try:
        conn.execute("UPDATE schedule SET topic_key=? WHERE round=?", (topic_key, round_no))
        conn.commit()
    finally:
        conn.close()


def set_schedule_advance(round_no, advance_at):
    conn = get_conn()
    try:
        conn.execute("UPDATE schedule SET advance_at=? WHERE round=?", (advance_at, round_no))
        conn.commit()
    finally:
        conn.close()


def delete_schedule_rows_above(max_round):
    conn = get_conn()
    try:
        conn.execute("DELETE FROM schedule WHERE round > ?", (max_round,))
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Round topics — many pieces of material per round (topic placed in one round)
# --------------------------------------------------------------------------- #
@run_memo
def get_round_topics():
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT topic_key, round, position FROM round_topics "
            "ORDER BY round, position"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def next_topic_position(round_no):
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT MAX(position) AS m FROM round_topics WHERE round=?", (round_no,)
        ).fetchone()
        return (row["m"] + 1) if row and row["m"] is not None else 0
    finally:
        conn.close()


def set_topic_placement(topic_key, round_no, position=None):
    """Place a topic in a round (moves it if already placed elsewhere)."""
    if position is None:
        position = next_topic_position(round_no)
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO round_topics(topic_key, round, position) VALUES(?,?,?) "
            "ON CONFLICT(topic_key) DO UPDATE SET round=excluded.round, "
            "position=excluded.position",
            (topic_key, round_no, position),
        )
        conn.commit()
    finally:
        conn.close()


def remove_round_topic(topic_key):
    """Unassign a topic (leaves it in the unassigned pool)."""
    conn = get_conn()
    try:
        conn.execute("DELETE FROM round_topics WHERE topic_key=?", (topic_key,))
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Messages — in-app "email" inbox per team
# --------------------------------------------------------------------------- #
def add_message(team_id, subject, body, round_no=None, sender="Venture Foundry Director"):
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO messages(team_id, round, subject, body, sender, read, created_at)
               VALUES(?,?,?,?,?,0,?)""",
            (team_id, round_no, subject, body, sender, now()),
        )
        conn.commit()
    finally:
        conn.close()


@run_memo
def list_messages(team_id):
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM messages WHERE team_id=? ORDER BY id DESC", (team_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@run_memo
def unread_count(team_id):
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM messages WHERE team_id=? AND read=0", (team_id,)
        ).fetchone()
        return row["c"] if row else 0
    finally:
        conn.close()


def mark_message_read(msg_id, read=1):
    conn = get_conn()
    try:
        conn.execute("UPDATE messages SET read=? WHERE id=?", (read, msg_id))
        conn.commit()
    finally:
        conn.close()


def mark_all_read(team_id):
    conn = get_conn()
    try:
        conn.execute("UPDATE messages SET read=1 WHERE team_id=?", (team_id,))
        conn.commit()
    finally:
        conn.close()


def delete_message(msg_id):
    conn = get_conn()
    try:
        conn.execute("DELETE FROM messages WHERE id=?", (msg_id,))
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Team skills
# --------------------------------------------------------------------------- #
@run_memo
def get_team_skills(team_id):
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT skill_key, level FROM team_skills WHERE team_id=?", (team_id,)
        ).fetchall()
        return {r["skill_key"]: r["level"] for r in rows}
    finally:
        conn.close()


def set_skill_level(team_id, skill_key, level):
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO team_skills(team_id, skill_key, level) VALUES(?,?,?) "
            "ON CONFLICT(team_id, skill_key) DO UPDATE SET level=excluded.level",
            (team_id, skill_key, int(level)),
        )
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Concept-check answers (per team, per round, per concept)
# --------------------------------------------------------------------------- #
@run_memo
def _round_answers_by_round(team_id):
    conn = get_conn()
    try:
        out = {}
        for r in conn.execute(
                "SELECT round, concept, answer FROM round_answers WHERE team_id=?",
                (team_id,)).fetchall():
            out.setdefault(r["round"], {})[r["concept"]] = r["answer"]
        return out
    finally:
        conn.close()


@run_memo
def get_round_answers(team_id, round_no):
    # In a page render, every prior round's answers are needed: fetch all at once.
    if getattr(_ctx, "cache", None) is not None:
        return dict(_round_answers_by_round(team_id).get(round_no, {}))
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT concept, answer FROM round_answers WHERE team_id=? AND round=?",
            (team_id, round_no),
        ).fetchall()
        return {r["concept"]: r["answer"] for r in rows}
    finally:
        conn.close()


def set_round_answer(team_id, round_no, concept, answer):
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO round_answers(team_id, round, concept, answer, created_at) "
            "VALUES(?,?,?,?,?) ON CONFLICT(team_id, round, concept) "
            "DO UPDATE SET answer=excluded.answer, created_at=excluded.created_at",
            (team_id, round_no, concept, answer, now()),
        )
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Acknowledgments — one-time "I did this" markers (e.g., reviewed founder card)
# --------------------------------------------------------------------------- #
def set_ack(team_id, key):
    conn = get_conn()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO acknowledgments(team_id, key, created_at) VALUES(?,?,?)",
            (team_id, key, now()),
        )
        conn.commit()
    finally:
        conn.close()


@run_memo
def _ack_keys(team_id):
    conn = get_conn()
    try:
        return {r["key"] for r in conn.execute(
            "SELECT key FROM acknowledgments WHERE team_id=?", (team_id,)).fetchall()}
    finally:
        conn.close()


@run_memo
def has_ack(team_id, key):
    if getattr(_ctx, "cache", None) is not None:
        return key in _ack_keys(team_id)
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT 1 FROM acknowledgments WHERE team_id=? AND key=?", (team_id, key)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Hires — specialists filling skill gaps
# --------------------------------------------------------------------------- #
def add_hire(team_id, skill_key, role, kind, boost, per_round, manage_hours=0):
    conn = get_conn()
    try:
        cur = conn.execute(
            """INSERT INTO hires(team_id, skill_key, role, kind, boost, per_round,
                                 manage_hours, created_at)
               VALUES(?,?,?,?,?,?,?,?)""",
            (team_id, skill_key, role, kind, boost, per_round, manage_hours, now()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Skill XP (learning by doing)
# --------------------------------------------------------------------------- #
@run_memo
def get_skill_xp(team_id, skill_key):
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT xp FROM skill_xp WHERE team_id=? AND skill_key=?", (team_id, skill_key)
        ).fetchone()
        return row["xp"] if row else 0
    finally:
        conn.close()


def set_skill_xp(team_id, skill_key, xp):
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO skill_xp(team_id, skill_key, xp) VALUES(?,?,?) "
            "ON CONFLICT(team_id, skill_key) DO UPDATE SET xp=excluded.xp",
            (team_id, skill_key, int(xp)),
        )
        conn.commit()
    finally:
        conn.close()


@run_memo
def list_hires(team_id):
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM hires WHERE team_id=? ORDER BY id", (team_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def remove_hire(hire_id):
    conn = get_conn()
    try:
        conn.execute("DELETE FROM hires WHERE id=?", (hire_id,))
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Round commitments — a team locks in a round's work; can withdraw before the
# decision due date. The snapshot records what was complete at commit time.
# --------------------------------------------------------------------------- #
@run_memo
def get_commitment(team_id, round_no):
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM commitments WHERE team_id=? AND round=?",
            (team_id, round_no),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def set_commitment(team_id, round_no, committed, due_at=None, snapshot=None):
    """Insert or update a team's commitment for a round."""
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO commitments(team_id, round, committed, committed_at, due_at, snapshot)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(team_id, round) DO UPDATE SET
                 committed=excluded.committed,
                 committed_at=excluded.committed_at,
                 due_at=excluded.due_at,
                 snapshot=excluded.snapshot""",
            (team_id, round_no, 1 if committed else 0,
             now() if committed else None, due_at, snapshot),
        )
        conn.commit()
    finally:
        conn.close()


@run_memo
def list_commitments(round_no=None):
    conn = get_conn()
    try:
        if round_no is None:
            rows = conn.execute("SELECT * FROM commitments").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM commitments WHERE round=?", (round_no,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Metrics history — a per-round snapshot of each team's learning metrics, so the
# team can see its own progress trend over time.
# --------------------------------------------------------------------------- #
def save_metrics_snapshot(team_id, round_no, metrics_json):
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO metrics_history(team_id, round, metrics, created_at)
               VALUES(?,?,?,?)
               ON CONFLICT(team_id, round) DO UPDATE SET
                 metrics=excluded.metrics, created_at=excluded.created_at""",
            (team_id, round_no, metrics_json, now()),
        )
        conn.commit()
    finally:
        conn.close()


@run_memo
def list_metrics_history(team_id):
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT round, metrics FROM metrics_history WHERE team_id=? ORDER BY round",
            (team_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Badges — earned achievements (first-earned time is recorded for celebrations).
# --------------------------------------------------------------------------- #
@run_memo
def get_earned_badges(team_id):
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT code FROM badges WHERE team_id=?", (team_id,)).fetchall()
        return {r["code"] for r in rows}
    finally:
        conn.close()


def award_badge(team_id, code):
    conn = get_conn()
    try:
        conn.execute("INSERT OR IGNORE INTO badges(team_id, code, earned_at) VALUES(?,?,?)",
                     (team_id, code, now()))
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Demo Day — pitches and peer votes
# --------------------------------------------------------------------------- #
def save_pitch(team_id, game_id, headline, pitch, best_evidence, ask, canvas=None):
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO demo_pitches(team_id, game_id, headline, pitch, best_evidence,
                                        ask, canvas, updated_at)
               VALUES(?,?,?,?,?,?,?,?)
               ON CONFLICT(team_id) DO UPDATE SET
                 game_id=excluded.game_id, headline=excluded.headline, pitch=excluded.pitch,
                 best_evidence=excluded.best_evidence, ask=excluded.ask,
                 canvas=excluded.canvas, updated_at=excluded.updated_at""",
            (team_id, game_id, headline, pitch, best_evidence, ask,
             _dumps(canvas) if canvas is not None else None, now()),
        )
        conn.commit()
    finally:
        conn.close()


@run_memo
def get_pitch_canvas(team_id):
    """The structured Pitch Canvas dict for a team (block key -> text)."""
    p = get_pitch(team_id)
    if not p or not p.get("canvas"):
        return {}
    return _loads(p["canvas"], {})


@run_memo
def get_pitch(team_id):
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM demo_pitches WHERE team_id=?", (team_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


@run_memo
def list_pitches(game_id):
    conn = get_conn()
    try:
        rows = conn.execute("SELECT * FROM demo_pitches WHERE game_id=?", (game_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def cast_vote(game_id, voter_team_id, votee_team_id):
    conn = get_conn()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO demo_votes(game_id, voter_team_id, votee_team_id, created_at) "
            "VALUES(?,?,?,?)", (game_id, voter_team_id, votee_team_id, now()))
        conn.commit()
    finally:
        conn.close()


def remove_vote(game_id, voter_team_id, votee_team_id):
    conn = get_conn()
    try:
        conn.execute("DELETE FROM demo_votes WHERE game_id=? AND voter_team_id=? "
                     "AND votee_team_id=?", (game_id, voter_team_id, votee_team_id))
        conn.commit()
    finally:
        conn.close()


def clear_votes(game_id, voter_team_id):
    conn = get_conn()
    try:
        conn.execute("DELETE FROM demo_votes WHERE game_id=? AND voter_team_id=?",
                     (game_id, voter_team_id))
        conn.commit()
    finally:
        conn.close()


@run_memo
def votes_by_voter(game_id, voter_team_id):
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT votee_team_id FROM demo_votes WHERE game_id=? AND voter_team_id=?",
            (game_id, voter_team_id)).fetchall()
        return {r["votee_team_id"] for r in rows}
    finally:
        conn.close()


@run_memo
def vote_tally(game_id):
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT votee_team_id, COUNT(*) AS n FROM demo_votes WHERE game_id=? "
            "GROUP BY votee_team_id", (game_id,)).fetchall()
        return {r["votee_team_id"]: r["n"] for r in rows}
    finally:
        conn.close()


# ---- Demo Day money allocation --------------------------------------------- #
def set_investment(game_id, voter_team_id, votee_team_id, amount):
    """Set the dollars a voter invests in one pitch (0 removes it)."""
    conn = get_conn()
    try:
        if amount and amount > 0:
            conn.execute(
                "INSERT INTO demo_votes(game_id, voter_team_id, votee_team_id, amount, created_at) "
                "VALUES(?,?,?,?,?) ON CONFLICT(game_id, voter_team_id, votee_team_id) "
                "DO UPDATE SET amount=excluded.amount, created_at=excluded.created_at",
                (game_id, voter_team_id, votee_team_id, int(amount), now()))
        else:
            conn.execute("DELETE FROM demo_votes WHERE game_id=? AND voter_team_id=? "
                         "AND votee_team_id=?", (game_id, voter_team_id, votee_team_id))
        conn.commit()
    finally:
        conn.close()


@run_memo
def investments_by_voter(game_id, voter_team_id):
    """{votee_team_id: amount} for one voting team."""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT votee_team_id, amount FROM demo_votes WHERE game_id=? AND voter_team_id=?",
            (game_id, voter_team_id)).fetchall()
        return {r["votee_team_id"]: (r["amount"] or 0) for r in rows}
    finally:
        conn.close()


@run_memo
def investment_tally(game_id):
    """{votee_team_id: total dollars raised} across all voters."""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT votee_team_id, COALESCE(SUM(amount),0) AS d FROM demo_votes WHERE game_id=? "
            "GROUP BY votee_team_id", (game_id,)).fetchall()
        return {r["votee_team_id"]: r["d"] for r in rows}
    finally:
        conn.close()


# ---- Venture name ---------------------------------------------------------- #
def set_venture_name(team_id, name, scores=None):
    conn = get_conn()
    try:
        conn.execute("UPDATE teams SET venture_name=?, venture_name_scores=? WHERE id=?",
                     (name, _dumps(scores or {}), team_id))
        conn.commit()
    finally:
        conn.close()


@run_memo
def get_venture_name(team_id):
    conn = get_conn()
    try:
        row = conn.execute("SELECT venture_name, venture_name_scores FROM teams WHERE id=?",
                           (team_id,)).fetchone()
        if not row:
            return {"name": "", "scores": {}}
        return {"name": row["venture_name"] or "",
                "scores": _loads(row["venture_name_scores"]) if row["venture_name_scores"] else {}}
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Backup & restore
#   Streamlit Community Cloud does not keep local files across a reboot or
#   redeploy, so the Director needs a way to take the whole game home and put it
#   back. Both directions use SQLite's online backup API, which produces a
#   consistent copy even while students are writing (WAL mode).
# --------------------------------------------------------------------------- #
_REQUIRED_TABLES = {"settings", "games", "teams"}


def backup_bytes():
    """A consistent snapshot of the whole database as bytes (a .db file).
    On Postgres the data is exported into the same SQLite file format, so one
    backup file works with either backend (and moves data between them)."""
    if IS_PG:
        return _pg_backup_bytes()
    import tempfile
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        src = get_conn()
        dst = sqlite3.connect(tmp)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        with open(tmp, "rb") as fh:
            return fh.read()
    finally:
        os.remove(tmp)


def validate_backup(data):
    """(ok, message, summary) for an uploaded backup file — never touches the live DB."""
    import tempfile
    if not data or not data.startswith(b"SQLite format 3\x00"):
        return False, "That isn't a SQLite database file.", None
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
        conn = sqlite3.connect(tmp)
        conn.row_factory = sqlite3.Row
        try:
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                return False, "The file is damaged (integrity check failed).", None
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            missing = _REQUIRED_TABLES - tables
            if missing:
                return False, ("This doesn't look like a Venture Foundry backup "
                               f"(missing: {', '.join(sorted(missing))})."), None
            summary = {
                "games": conn.execute("SELECT COUNT(*) FROM games").fetchone()[0],
                "teams": conn.execute("SELECT COUNT(*) FROM teams").fetchone()[0],
            }
            return True, "Looks good.", summary
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        return False, f"Couldn't read that file: {exc}", None
    finally:
        os.remove(tmp)


def restore_from_bytes(data):
    """Replace ALL live data with a validated backup. Returns (ok, message)."""
    import tempfile
    ok, msg, _ = validate_backup(data)
    if not ok:
        return False, msg
    if IS_PG:
        return _pg_restore(data)
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
        src = sqlite3.connect(tmp)
        dst = get_conn()
        try:
            src.backup(dst)          # page-by-page copy into the live database
        finally:
            src.close()
            dst.close()
    finally:
        os.remove(tmp)
    invalidate_run_cache()
    init_db()                         # apply any schema migrations to older backups
    return True, "Restored."


# ---- Postgres ⇄ SQLite-file backups --------------------------------------- #
_PARENT_TABLES = ("settings", "games", "teams")      # load before child tables


def _sqlite_tables(sconn):
    return [r[0] for r in sconn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]


def _pg_columns(conn):
    """{table: {column: data_type}} for the app's Postgres schema."""
    out = {}
    for r in conn.execute(
            "SELECT table_name, column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = current_schema()").fetchall():
        out.setdefault(r["table_name"], {})[r["column_name"]] = r["data_type"]
    return out


def _pg_backup_bytes():
    import tempfile
    fd = tempfile.mkdtemp()
    tmp = os.path.join(fd, "backup.db")
    try:
        sconn = sqlite3.connect(tmp)
        sconn.row_factory = sqlite3.Row
        _create_schema(sconn, False)
        pconn = get_conn()
        try:
            pg_cols = _pg_columns(pconn)
            for table in _sqlite_tables(sconn):
                if table not in pg_cols:
                    continue
                s_cols = [r["name"] for r in sconn.execute(f"PRAGMA table_info({table})")]
                cols = [c for c in s_cols if c in pg_cols[table]]
                col_sql = ", ".join(cols)
                rows = pconn.execute(f"SELECT {col_sql} FROM {table}").fetchall()
                if rows:
                    sconn.executemany(
                        f"INSERT INTO {table}({col_sql}) VALUES({', '.join('?' * len(cols))})",
                        [tuple(r[c] for c in cols) for r in rows])
        finally:
            pconn.close()
        sconn.commit()
        sconn.close()
        with open(tmp, "rb") as fh:
            return fh.read()
    finally:
        import shutil
        shutil.rmtree(fd, ignore_errors=True)


def _coerce(value, pg_type):
    """SQLite is loosely typed; make a value acceptable to the Postgres column."""
    if value is None:
        return None
    if pg_type in ("integer", "bigint", "smallint"):
        if isinstance(value, (int, float)):
            return int(value)
        txt = str(value).strip()
        if not txt:
            return None
        try:
            return int(float(txt))
        except ValueError:
            return None
    if pg_type in ("double precision", "real", "numeric"):
        if isinstance(value, (int, float)):
            return float(value)
        try:
            return float(str(value).strip()) if str(value).strip() else None
        except ValueError:
            return None
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value if isinstance(value, str) else str(value)


def _pg_restore(data):
    """Load a SQLite backup into Postgres in ONE transaction (all or nothing)."""
    import tempfile
    tdir = tempfile.mkdtemp()
    tmp = os.path.join(tdir, "restore.db")
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
        sconn = sqlite3.connect(tmp)
        sconn.row_factory = sqlite3.Row
        pconn = get_conn()
        try:
            pg_cols = _pg_columns(pconn)
            src_tables = [t for t in _sqlite_tables(sconn) if t in pg_cols]
            ordered = ([t for t in _PARENT_TABLES if t in src_tables]
                       + [t for t in src_tables if t not in _PARENT_TABLES])
            app_tables = ", ".join(sorted(pg_cols))
            pconn.execute(f"TRUNCATE {app_tables} RESTART IDENTITY CASCADE")
            for table in ordered:
                s_cols = [r["name"] for r in sconn.execute(f"PRAGMA table_info({table})")]
                cols = [c for c in s_cols if c in pg_cols[table]]
                rows = sconn.execute(f"SELECT {', '.join(cols)} FROM {table}").fetchall()
                if not rows:
                    continue
                types = [pg_cols[table][c] for c in cols]
                pconn.executemany(
                    f"INSERT INTO {table}({', '.join(cols)}) "
                    f"VALUES({', '.join('?' * len(cols))}) ON CONFLICT DO NOTHING",
                    [tuple(_coerce(r[i], types[i]) for i in range(len(cols))) for r in rows])
            for table, cols in pg_cols.items():   # keep serial ids ahead of restored rows
                if "id" in cols and cols["id"] == "integer":
                    pconn.execute(
                        f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                        f"COALESCE((SELECT MAX(id) FROM {table}), 1), "
                        f"(SELECT MAX(id) FROM {table}) IS NOT NULL)")
            pconn.commit()
        except Exception as exc:                   # noqa: BLE001
            pconn.rollback()
            return False, f"Restore failed; nothing was changed. ({exc})"
        finally:
            pconn.close()
            sconn.close()
    finally:
        import shutil
        shutil.rmtree(tdir, ignore_errors=True)
    invalidate_run_cache()
    init_db()
    return True, "Restored."
