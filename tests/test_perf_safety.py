"""Regression tests for the performance/concurrency changes.

Run:  pip install pytest && pytest -q tests/
Each test uses a throwaway SQLite file, never venture_foundry.db.
"""
import os
import sys
import tempfile
import threading
from datetime import datetime, timedelta, timezone

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_TMP = tempfile.mkdtemp()
os.environ["VF_DB_PATH"] = os.path.join(_TMP, "test.db")

import db      # noqa: E402
import logic   # noqa: E402


def _reset_storage():
    if db.IS_PG:            # set DATABASE_URL to run this suite against Postgres
        conn = db.get_conn()
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
        conn.commit()
        conn.close()
        return
    for suffix in ("", "-wal", "-shm"):
        p = db.DB_PATH + suffix
        if os.path.exists(p):
            os.remove(p)


def _raw_commit(conn):
    """Commit WITHOUT the cache-clearing hook (simulates another session's write)."""
    if db.IS_PG:
        conn._conn.commit()
    else:
        super(type(conn), conn).commit()


@pytest.fixture(autouse=True)
def fresh_db():
    _reset_storage()
    db.end_request()
    db.init_db()
    gid = db.list_games()[0]["id"]
    db.set_active_game(gid)
    yield gid
    db.end_request()


def _team(credits=10):
    code = db.create_team("T", evidence_credits=credits)
    return db.get_team_by_code(code)["id"]


# ---- per-run read cache ---------------------------------------------------- #
@pytest.mark.skipif(db.IS_PG, reason="SQLite-only")
def test_wal_enabled():
    conn = db.get_conn()
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    finally:
        conn.close()


def test_no_caching_outside_a_run():
    db.set_setting("k", "1")
    assert db.get_setting("k") == "1"
    conn = db.get_conn()            # raw write that bypasses helpers, no commit hook
    conn.execute("UPDATE settings SET value='2' WHERE key='k'")
    _raw_commit(conn)
    conn.close()
    assert db.get_setting("k") == "2"


def test_cache_hits_within_run_and_clears_on_write():
    db.set_setting("k", "1")
    db.begin_request()
    assert db.get_setting("k") == "1"
    # A write by another connection that doesn't go through our commit hook is not
    # seen within the same run (snapshot semantics) ...
    conn = db.get_conn()
    conn.execute("UPDATE settings SET value='2' WHERE key='k'")
    _raw_commit(conn)
    conn.close()
    assert db.get_setting("k") == "1"
    # ... but any helper write clears the cache.
    db.set_setting("other", "x")
    assert db.get_setting("k") == "2"
    db.end_request()


def test_cached_results_are_copies():
    tid = _team()
    db.begin_request()
    t = db.get_team(tid)
    t["name"] = "MUTATED"
    assert db.get_team(tid)["name"] == "T"
    rows = logic.get_schedule()
    rows[0]["topics"].clear()
    assert logic.get_schedule()[0]["topics"] is not rows[0]["topics"]
    db.end_request()


def test_checklist_identical_with_and_without_cache():
    tid = _team()
    rnd = db.current_round()
    plain = logic.round_checklist(tid, rnd)
    db.begin_request()
    cached1 = logic.round_checklist(tid, rnd)
    cached2 = logic.round_checklist(tid, rnd)
    db.end_request()
    assert plain == cached1 == cached2


# ---- atomic resource updates ------------------------------------------------ #
def test_concurrent_spending_never_overdraws():
    tid = _team(credits=10)
    results = []

    def spend():
        results.append(db.adjust_resources(tid, credits=-1)[0])

    threads = [threading.Thread(target=spend) for _ in range(25)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results.count(True) == 10
    assert db.get_team(tid)["evidence_credits"] == 0
    assert len([x for x in db.list_transactions(tid) if x["credits"] == -1]) == 10


def test_increment_team_field_is_atomic():
    tid = _team()
    threads = [threading.Thread(target=db.increment_team_field, args=(tid, "spent_build", 1))
               for _ in range(30)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert db.get_team(tid)["spent_build"] == 30
    with pytest.raises(ValueError):
        db.increment_team_field(tid, "capital", 1)


# ---- serialized round advance ---------------------------------------------- #
def test_simultaneous_loads_advance_round_once(fresh_db):
    gid = fresh_db
    tid = _team()
    db.add_hire(tid, "sales", "Rep", "part-time", 1, 100)
    start_capital = db.get_team(tid)["capital"]
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    db.set_schedule_advance(2, past)

    barrier = threading.Barrier(12)

    def load():
        db.set_active_game(gid)
        db.begin_request()
        barrier.wait()
        try:
            logic.sync_active_game()
        finally:
            db.end_request()

    threads = [threading.Thread(target=load) for _ in range(12)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    db.set_active_game(gid)
    assert db.current_round() == 2
    # Exactly one round's salary charged, not one per simultaneous session.
    assert db.get_team(tid)["capital"] == start_capital - 100


# ---- backup & restore ------------------------------------------------------- #
def test_backup_roundtrip_restores_everything():
    tid = _team(credits=7)
    db.set_setting("marker", "before")
    blob = db.backup_bytes()
    ok, _, summ = db.validate_backup(blob)
    assert ok and summ["teams"] == 1
    db.delete_team(tid)
    db.set_setting("marker", "after")
    assert db.get_team(tid) is None
    ok, msg = db.restore_from_bytes(blob)
    assert ok, msg
    assert db.get_team(tid)["evidence_credits"] == 7
    assert db.get_setting("marker") == "before"


def test_restore_rejects_junk_and_foreign_dbs(tmp_path):
    assert not db.validate_backup(b"not a database")[0]
    other = tmp_path / "other.db"
    import sqlite3
    c = sqlite3.connect(other)
    c.execute("create table x(a)")
    c.commit()
    c.close()
    ok, msg, _ = db.validate_backup(other.read_bytes())
    assert not ok and "missing" in msg
    n_before = len(db.list_games())
    assert not db.restore_from_bytes(b"junk")[0]
    assert len(db.list_games()) == n_before


# ---- PIN ------------------------------------------------------------------- #
def test_pin_secret_overrides_db(monkeypatch):
    assert logic.pin_is_default() and logic.check_pin("foundry")
    db.set_setting("instructor_pin", "s3cret!")
    assert logic.check_pin("s3cret!") and not logic.check_pin("foundry")
    monkeypatch.setenv("VF_INSTRUCTOR_PIN", "from-secrets")
    assert logic.check_pin("from-secrets") and not logic.check_pin("s3cret!")
    assert not logic.check_pin("") and not logic.check_pin(None)


# ---- background Managing Partner notes ------------------------------------- #
def test_mp_notes_run_in_background_once(fresh_db, monkeypatch):
    import time
    gid = fresh_db
    ids = [_team() for _ in range(3)]
    calls = []

    def slow_note(tid, rnd):
        time.sleep(0.2)
        calls.append(tid)
        return {"subject": "s", "body": "b"}

    monkeypatch.setattr(logic, "send_managing_partner_note", slow_note)
    t0 = time.perf_counter()
    assert logic.send_managing_partner_notes_async(ids, 1, gid) == 3
    assert time.perf_counter() - t0 < 0.15          # caller doesn't wait
    assert logic.send_managing_partner_notes_async(ids, 1, gid) == 0   # no duplicate job
    for _ in range(50):
        if logic.mp_job_status(gid, 1).startswith("done"):
            break
        time.sleep(0.05)
    assert logic.mp_job_status(gid, 1) == "done 3/3"
    assert sorted(calls) == sorted(ids)


# ---- skill progress -------------------------------------------------------- #
def test_concurrent_skill_progress_is_not_lost():
    tid = _team()
    key = next(iter(db.get_team_skills(tid)))
    lvl0, xp0, _ = logic.skill_progress(tid, key)

    threads = [threading.Thread(target=logic.add_skill_progress, args=(tid, key, 1))
               for _ in range(20)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    lvl, xp, _ = logic.skill_progress(tid, key)
    # Total banked effort is conserved: replay 20 hours serially from the start.
    exp_lvl, exp_xp = lvl0, xp0 + 20
    import content
    while exp_lvl < content.SKILL_MAX and exp_xp >= logic.cost_to_next(exp_lvl):
        exp_xp -= logic.cost_to_next(exp_lvl)
        exp_lvl += 1
    if exp_lvl >= content.SKILL_MAX:
        exp_xp = 0
    assert (lvl, xp) == (exp_lvl, exp_xp)
