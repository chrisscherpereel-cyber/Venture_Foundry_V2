"""Regression tests for defects found in the Stage 1 pilot-readiness review."""
import os
import sys
import tempfile
import threading

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("VF_DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))

import db       # noqa: E402
import logic    # noqa: E402
import content  # noqa: E402

from test_learning_integrity import _reset_storage, _team, _credits, _assumption  # noqa: E402,F401


@pytest.fixture(autouse=True)
def fresh_db():
    _reset_storage()
    db.end_request()
    db.init_db()
    gid = db.list_games()[0]["id"]
    db.set_active_game(gid)
    yield gid
    db.end_request()


def test_pending_claims_do_not_move_scores_until_accepted():
    tid = _team()
    r = logic.log_evidence(tid, "Cafe signed LOI: will subscribe at launch",
                           "Customer pays or makes a binding commitment", "Cafe B", "signed")
    assert r["status"] == "Pending review"
    assert logic.evidence_summary(tid)["count"] == 0
    assert logic.strongest_evidence(tid) is None
    assert logic._deliverable_done(tid, "evidence_ge_2", 1) is False   # 1 counted item
    logic.review_evidence(tid, r["evidence_id"], "accept")
    assert logic.evidence_summary(tid)["behavioral"] == 1


@pytest.mark.parametrize("text,typ", [
    ("She said she would have paid if it existed", "Customer pays or makes a binding commitment"),
    ("He'd have signed a letter if we had a product", "Customer signs a letter of intent"),
    ("They said they would pay us", "Customer description of past behavior"),
])
def test_conditional_wording_is_flagged_even_with_action_words(text, typ):
    s = content.EVIDENCE_LADDER_MAP[typ]
    assert logic.evidence_flags(text, "interview", s)


def test_plain_past_behavior_is_not_flagged():
    assert logic.evidence_flags("4 of 6 owners described binning stock last Friday",
                                "6 owners", 4) == []


def test_ai_persona_source_is_flagged_and_routed_to_review():
    tid = _team()
    r = logic.log_evidence(tid, "Maria, 41, described paying a tutor last week",
                           "Customer description of past behavior", "ChatGPT persona", "past")
    assert r["flags"] and r["status"] == "Pending review"


def test_concurrent_canvas_saves_get_distinct_versions():
    tid = _team()
    gid = db.active_game_id()

    def save(i):
        db.set_active_game(gid)
        db.save_canvas(tid, "bmc", {"k": f"v{i}"}, f"v{i}", "")
    ths = [threading.Thread(target=save, args=(i,)) for i in range(10)]
    [t.start() for t in ths]
    [t.join() for t in ths]
    vers = sorted(c["version"] for c in db.list_canvases(tid, "bmc"))
    assert vers == list(range(1, 11))


def test_mini_pivot_reward_needs_evidence_and_pays_once_per_round():
    tid = _team()
    assert logic.log_mini_pivot(tid, "x", "", "y") == 0
    assert logic.log_mini_pivot(tid, "x", "2 of 52 paid", "y") == logic.MINI_PIVOT_CREDIT
    assert logic.log_mini_pivot(tid, "x2", "another", "y2") == 0
    assert _credits(tid) == 10 + logic.MINI_PIVOT_CREDIT
    assert len([p for p in db.list_pivots(tid) if p["kind"] == "mini"]) == 3   # all logged


def test_double_clicked_partner_reward_pays_once():
    tid = _team()
    gid = db.active_game_id()
    ths = [threading.Thread(target=lambda: (db.set_active_game(gid),
                                            logic.log_partner_commitment(tid, "Cafe", "stock", "email")))
           for _ in range(4)]
    [t.start() for t in ths]
    [t.join() for t in ths]
    assert _credits(tid) == 10 + logic.PARTNER_CREDIT


def test_advance_retry_after_crash_does_not_double_charge(fresh_db, monkeypatch):
    t1, t2 = _team(gid=fresh_db), _team(gid=fresh_db)
    for t in (t1, t2):
        db.add_hire(t, "finance", "CFO", "part_time", 1, 100.0, 2)
    cap = {t: db.get_team(t)["capital"] for t in (t1, t2)}
    real = logic._apply_round_learning
    calls = {"n": 0}

    def flaky(tid, r):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("crash mid-advance")
        return real(tid, r)
    monkeypatch.setattr(logic, "_apply_round_learning", flaky)
    with pytest.raises(RuntimeError):
        logic.director_advance(2)
    monkeypatch.setattr(logic, "_apply_round_learning", real)
    db.invalidate_run_cache()
    logic.director_advance(2)
    logic.director_advance(2)          # and a plain double-click
    db.invalidate_run_cache()
    for t in (t1, t2):
        assert cap[t] - db.get_team(t)["capital"] == 100.0
        assert db.get_round_result(t, 1) is not None


def test_pivot_autopilot_needs_disconfirming_evidence_on_record():
    tid = _team()
    pet = {"team_id": tid, "original_assum": "a", "challenge_evid": "we feel like it",
           "proposed_change": "b", "new_assumptions": "c", "evidence_needed": "d"}
    assert logic.recommend_pivot(pet)[0] == "NeedsEvidence"
    aid = _assumption(tid)
    db.set_assumption_status(tid, aid, "Refuted", "derived")
    assert logic.recommend_pivot(pet)[0] == "Approved"


def test_pitch_page_shows_attribution(fresh_db):
    AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
    tid = _team(gid=fresh_db)
    db.set_game_round(fresh_db, 15)
    db.end_request()
    at = AppTest.from_file(os.path.join(ROOT, "app.py"), default_timeout=60)
    at.session_state["role"] = "student"
    at.session_state["team_id"] = tid
    at.session_state["student_page"] = "Demo Day"
    at.run()
    assert not at.exception
    assert any("CC BY-SA 4.0" in c.value for c in at.caption)
