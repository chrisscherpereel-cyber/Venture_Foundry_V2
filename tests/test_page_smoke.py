"""Render every student and Director page with Streamlit's AppTest on a seeded game
that includes Stage 1 data (pending/accepted/practice evidence, numeric experiments,
results, a finalized round). Catches exceptions in page code paths. This is a
headless script run — not a browser test.
"""
import os
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("VF_DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))

import db       # noqa: E402
import logic    # noqa: E402
import content  # noqa: E402

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest

STUDENT_PAGES = ["Round Briefing", "Inbox", "Concept Check", "Decision Journal",
                 "Founder & Opportunity", "Founder & Team", "Canvases", "VP Auction",
                 "Assumption Map", "Experiment Marketplace", "Evidence Ledger",
                 "Market Events", "Pivot Petition", "My Venture", "Leaderboard",
                 "Demo Day", "AI Assist Log"]
DIRECTOR_PAGES = ["🏠 Start here", "Games", "Cohort Overview", "Auto-Director", "Team Setup",
                  "Schedule & Timing", "Round Control", "Resources", "Market Events",
                  "VP Auction", "Pivot Committee", "Dashboard Scoring", "Round Scores",
                  "Evidence Review", "Misconception Radar", "Demo Day", "Backup & Restore"]


def _reset_storage():
    if db.IS_PG:
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


@pytest.fixture(scope="module")
def seeded():
    _reset_storage()
    db.end_request()
    db.init_db()
    gid = db.list_games()[0]["id"]
    db.set_active_game(gid)
    db.set_setting("strict_round_mode", "0")        # every tool editable → more code paths
    tids = []
    for name in ("Alpha", "Beta"):
        code = db.create_team(name, evidence_credits=40, game_id=gid)
        tids.append(db.get_team_by_code(code)["id"])
    db.set_game_round(gid, 8)
    db.invalidate_run_cache()
    card = content.EXPERIMENT_CARD_MAP["Preorder"]
    for tid in tids:
        db.add_assumption(tid, "Students will prepay a kit", importance=5)
        aid = db.list_assumptions(tid)[0]["id"]
        db.save_canvas(tid, "bmc", {"revenue_streams": "subscription"}, "v1", "first")
        logic.log_evidence(tid, "4 described binning food last week",
                           "Customer description of past behavior", "hall B", "past behavior",
                           assumption_id=aid, direction="Supports")
        logic.log_evidence(tid, "Owner signed LOI", "Customer signs a letter of intent",
                           "cafe", "signed", assumption_id=aid, direction="Supports")
        logic.log_evidence(tid, "Persona said yes", "Founder opinion", "AI", "practice",
                           origin="AI practice")
        ok, _, eid = logic.purchase_experiment(
            tid, card, aid, "We believe 20% prepay", "deposits", ">=8", "<=3", "rule",
            predicted_outcome="Supported", confidence=70, success_value=8, failure_value=3,
            higher_is_better=True, request_key=f"k{tid}")
        logic.record_experiment_result(tid, eid, observed_value=2, observed_n=52,
                                       result_text="2 of 52")
        logic.finalize_round_result(tid, 7, source="advance")
    db.end_request()
    return gid, tids


def _run(state):
    at = AppTest.from_file(os.path.join(ROOT, "app.py"), default_timeout=60)
    for k, v in state.items():
        at.session_state[k] = v
    at.run()
    return at


@pytest.mark.parametrize("page", STUDENT_PAGES)
def test_student_page_renders(seeded, page):
    gid, tids = seeded
    at = _run({"role": "student", "team_id": tids[0], "student_page": page})
    assert not at.exception, f"{page}: {at.exception}"


@pytest.mark.parametrize("page", DIRECTOR_PAGES)
def test_director_page_renders(seeded, page):
    gid, tids = seeded
    at = _run({"role": "instructor", "instructor_ok": True, "instr_page": page,
               "active_game_id": gid})
    assert not at.exception, f"{page}: {at.exception}"


def test_evidence_review_accept_flow(seeded):
    """Click 'Accept' on the first queued item and confirm credits are released."""
    gid, tids = seeded
    queue = logic.review_queue(tids)
    assert queue
    first = queue[0]
    before = db.get_team(first["team_id"])["evidence_credits"]
    at = _run({"role": "instructor", "instructor_ok": True, "instr_page": "Evidence Review",
               "active_game_id": gid})
    at.button(key=f"rv_acc_{first['id']}").click().run()
    assert not at.exception
    db.end_request()
    e = db.get_evidence(first["team_id"], first["id"])
    assert e["review_status"] == "Accepted"
    assert db.get_team(first["team_id"])["evidence_credits"] > before


def test_student_logs_evidence_through_the_page(seeded):
    """Fill the Evidence Ledger form and click Log: one item is stored, the base credit
    is paid, and a duplicate click-through of the same text is refused."""
    gid, tids = seeded
    tid = tids[1]
    n0 = len(db.list_evidence(tid))
    c0 = db.get_team(tid)["evidence_credits"]
    at = _run({"role": "student", "team_id": tid, "student_page": "Evidence Ledger"})
    at.text_input(key="ev_desc").input("2 of 9 residents asked for the sign-up link")
    at.text_input(key="ev_src").input("Hall C residents")
    at.text_input(key="ev_just").input("They asked for the link — a small action")
    at.run()
    log_btn = [b for b in at.button if b.label == "Log evidence"][0]
    log_btn.click().run()
    assert not at.exception
    db.end_request()
    assert len(db.list_evidence(tid)) == n0 + 1
    assert db.get_team(tid)["evidence_credits"] > c0
    # same text again → duplicate refused, error shown, inputs kept
    at.text_input(key="ev_desc").input("2 of 9 residents asked for the sign-up link")
    at.text_input(key="ev_src").input("Hall C residents")
    at.text_input(key="ev_just").input("They asked for the link — a small action")
    at.run()
    [b for b in at.button if b.label == "Log evidence"][0].click().run()
    db.end_request()
    assert len(db.list_evidence(tid)) == n0 + 1
    assert any("copy of evidence item" in e.value for e in at.error)
    assert at.text_input(key="ev_desc").value.startswith("2 of 9")
