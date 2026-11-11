"""Stage 1 ("trustworthy record") regression tests.

Covers the five weaknesses verified in the audit (category inflation, duplicate
rewards, non-atomic experiment purchase, hand-set assumption status, drifting
historical scores) plus the new rules that replace them.

Run:  pytest -q tests/
Uses a throwaway SQLite file (or DATABASE_URL Postgres if set), never venture_foundry.db.
"""
import os
import sys
import tempfile
import threading
from datetime import datetime, timedelta, timezone

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("VF_DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))

import db       # noqa: E402
import logic    # noqa: E402
import content  # noqa: E402

LOI = "Customer signs a letter of intent"           # strength 9
PAYS = "Customer pays or makes a binding commitment"  # strength 10
PAST = "Customer description of past behavior"       # strength 4


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


@pytest.fixture(autouse=True)
def fresh_db():
    _reset_storage()
    db.end_request()
    db.init_db()
    gid = db.list_games()[0]["id"]
    db.set_active_game(gid)
    yield gid
    db.end_request()


def _team(credits=10, capital=2000, hours=40, gid=None):
    code = db.create_team("T", evidence_credits=credits, capital=capital,
                          founder_hours=hours, game_id=gid)
    return db.get_team_by_code(code)["id"]


def _credits(tid):
    return db.get_team(tid)["evidence_credits"]


def _assumption(tid, text="Students will prepay", importance=5):
    db.add_assumption(tid, text, importance=importance)
    return [a for a in db.list_assumptions(tid) if a["text"] == text][0]["id"]


CARD = content.EXPERIMENT_CARD_MAP["Preorder"]   # $100, 10 h, 4 credits, strength 9


# ---- Evidence: category inflation, flags, duplicates, practice ------------- #
def test_inflated_category_pays_only_base_until_reviewed():
    tid = _team()
    res = logic.log_evidence(tid, "my friend thinks it is cool", PAYS, "me", "they said so")
    assert res["ok"] and res["status"] == "Pending review"
    assert res["paid"] == content.EVIDENCE_BASE_CREDIT
    assert _credits(tid) == 10 + content.EVIDENCE_BASE_CREDIT


def test_unflagged_low_strength_is_auto_accepted():
    tid = _team()
    res = logic.log_evidence(tid, "4 of 6 owners described throwing stock away last week",
                             PAST, "6 owners", "they described a past action")
    assert res["status"] == "Auto-accepted"
    assert res["paid"] == content.EVIDENCE_BASE_CREDIT + 4 * content.EVIDENCE_RELEASE_PER_STRENGTH


def test_flagged_low_strength_still_goes_to_review():
    tid = _team()
    # strength 4 but wording reads like opinion → not flagged by the >=6 rule; use a
    # behavior-claim at strength 2 to trigger the under-crediting flag instead
    res = logic.log_evidence(tid, "they paid a deposit", "Customer statement about a "
                             "hypothetical action", "x", "y")
    assert res["flags"] and res["status"] == "Pending review"


def test_duplicate_is_refused_and_pays_nothing():
    tid = _team()
    first = logic.log_evidence(tid, "Same LOI from cafe", LOI, "Cafe A", "signed")
    before = _credits(tid)
    again = logic.log_evidence(tid, "  same LOI, from cafe! ", LOI, "cafe a", "signed")
    assert first["ok"] and not again["ok"] and again["status"] == "duplicate"
    assert _credits(tid) == before
    assert len(db.list_counted_evidence(tid)) == 1


def test_withdrawn_item_can_be_relogged_and_credits_return():
    tid = _team()
    r = logic.log_evidence(tid, "Owner signed LOI", LOI, "Cafe", "signed")
    ok, _, delta = logic.withdraw_evidence(tid, r["evidence_id"])
    assert ok and delta == -content.EVIDENCE_BASE_CREDIT and _credits(tid) == 10
    assert db.list_counted_evidence(tid) == []
    assert logic.log_evidence(tid, "Owner signed LOI", LOI, "Cafe", "signed")["ok"]


def test_ai_practice_earns_nothing_and_cannot_link():
    tid = _team()
    aid = _assumption(tid)
    bad = logic.log_evidence(tid, "Persona said yes", LOI, "AI", "practice",
                             assumption_id=aid, direction="Supports", origin="AI practice")
    assert not bad["ok"]
    ok = logic.log_evidence(tid, "Persona said yes", LOI, "AI", "practice", origin="AI practice")
    assert ok["ok"] and ok["paid"] == 0 and ok["status"] == "Practice"
    assert db.list_counted_evidence(tid) == []
    assert logic.evidence_summary(tid)["count"] == 0


def test_direction_required_when_linked_and_contradiction_pays_the_same():
    tid = _team()
    aid = _assumption(tid)
    assert not logic.log_evidence(tid, "x happened", PAST, "s", "j", assumption_id=aid)["ok"]
    sup = logic.log_evidence(tid, "4 described buying again", PAST, "s1", "past action",
                             assumption_id=aid, direction="Supports")
    con = logic.log_evidence(tid, "4 described never buying", PAST, "s2", "past action",
                             assumption_id=aid, direction="Contradicts")
    assert sup["paid"] == con["paid"] > 0


def test_foreign_assumption_cannot_be_linked():
    a, b = _team(), _team()
    other = _assumption(b)
    res = logic.log_evidence(a, "x", PAST, "s", "j", assumption_id=other, direction="Supports")
    assert not res["ok"]


def test_per_round_credit_cap():
    tid = _team(credits=0)
    words = ["apples", "bakery", "canteen", "delivery", "espresso", "farmers", "grocer",
             "hostel", "icecream", "juicebar", "kiosk", "library", "market", "noodles",
             "orchard", "pantry", "quiche", "ramen", "salads", "tacos"]
    for i, w in enumerate(words):        # genuinely different items (no near-duplicates)
        r = logic.log_evidence(tid, f"{w} owner described weekly {w} waste routine", PAST,
                               f"{w} shop", "past")
        assert r["ok"]
    assert _credits(tid) == content.EVIDENCE_CREDIT_CAP_PER_ROUND


# ---- Review: settle-to-target, idempotent, legacy untouched --------------- #
def test_review_accept_is_idempotent_and_downgrade_settles():
    tid = _team()
    r = logic.log_evidence(tid, "Owner signed LOI for 3 months", LOI, "Cafe", "signed")
    eid = r["evidence_id"]
    ok, _, d1 = logic.review_evidence(tid, eid, "accept")
    ok2, _, d2 = logic.review_evidence(tid, eid, "accept")
    assert ok and ok2 and d1 == 9 * content.EVIDENCE_RELEASE_PER_STRENGTH and d2 == 0
    assert not logic.review_evidence(tid, eid, "downgrade", "", PAST)[0]   # reason required
    ok, _, d3 = logic.review_evidence(tid, eid, "downgrade", "LOI was a verbal promise", PAST)
    assert ok and d3 == (4 - 9) * content.EVIDENCE_RELEASE_PER_STRENGTH
    e = db.get_evidence(tid, eid)
    assert e["strength"] == 4 and e["review_status"] == "Downgraded"
    assert e["credits_award"] == content.EVIDENCE_BASE_CREDIT + 4 * content.EVIDENCE_RELEASE_PER_STRENGTH
    ok, _, d4 = logic.review_evidence(tid, eid, "duplicate", "same as #1")
    assert ok and db.get_evidence(tid, eid)["credits_award"] == 0
    assert _credits(tid) == 10       # everything returned


def test_concurrent_accepts_pay_once():
    tid = _team()
    eid = logic.log_evidence(tid, "Signed LOI", LOI, "Cafe", "signed")["evidence_id"]
    results = []

    def go():
        results.append(logic.review_evidence(tid, eid, "accept")[2])
    ths = [threading.Thread(target=go) for _ in range(8)]
    [t.start() for t in ths]
    [t.join() for t in ths]
    assert sum(results) == 9 * content.EVIDENCE_RELEASE_PER_STRENGTH
    assert _credits(tid) == 10 + content.EVIDENCE_BASE_CREDIT + 9 * content.EVIDENCE_RELEASE_PER_STRENGTH


def test_legacy_evidence_keeps_credits_and_is_not_reviewable():
    tid = _team()
    db.add_evidence(tid, "old item", PAYS, 10, "src", None, 10.0, "j")   # legacy path
    e = db.list_evidence(tid)[0]
    assert e["review_status"] is None and e["credits_award"] == 10.0
    ok, msg, _ = logic.review_evidence(tid, e["id"], "accept")
    assert not ok and "Legacy" in msg
    assert logic.evidence_review_label(e).startswith("Legacy")
    assert len(db.list_counted_evidence(tid)) == 1


def test_review_cannot_cross_teams():
    a, b = _team(), _team()
    eid = logic.log_evidence(a, "Signed LOI", LOI, "Cafe", "signed")["evidence_id"]
    ok, _, _ = logic.review_evidence(b, eid, "accept")
    assert not ok and _credits(b) == 10


# ---- Experiments: atomic, idempotent, computed, locked -------------------- #
def _buy(tid, aid, key=None, sv=8.0, fv=3.0, hib=True):
    return logic.purchase_experiment(
        tid, CARD, aid, "We believe 20% will prepay", "deposits", "≥8", "≤3", "rule",
        predicted_outcome="Supported", confidence=75, success_value=sv, failure_value=fv,
        higher_is_better=hib, request_key=key)


def test_purchase_is_atomic_on_failure(monkeypatch):
    tid = _team()
    aid = _assumption(tid)
    before = db.get_team(tid)
    n_tx = len(db.list_transactions(tid))
    real_now = db.now
    calls = {"n": 0}

    def boom():
        calls["n"] += 1
        raise RuntimeError("simulated failure mid-transaction")
    monkeypatch.setattr(db, "now", boom)
    with pytest.raises(RuntimeError):
        _buy(tid, aid)
    monkeypatch.setattr(db, "now", real_now)
    after = db.get_team(tid)
    assert (after["capital"], after["evidence_credits"], after["founder_hours"]) == \
        (before["capital"], before["evidence_credits"], before["founder_hours"])
    assert db.list_experiments(tid) == [] and len(db.list_transactions(tid)) == n_tx
    assert db.get_assumption(tid, aid)["status"] == "Untested"


def test_purchase_retry_with_same_key_charges_once():
    tid = _team()
    aid = _assumption(tid)
    ok1, _, e1 = _buy(tid, aid, key="abc")
    ok2, msg2, e2 = _buy(tid, aid, key="abc")
    assert ok1 and ok2 and e1 == e2 and "Already" in msg2
    assert len(db.list_experiments(tid)) == 1
    assert db.get_team(tid)["capital"] == 2000 - CARD["money"]
    assert db.get_assumption(tid, aid)["status"] == "Testing"


def test_concurrent_double_click_charges_once():
    tid = _team()
    aid = _assumption(tid)
    errs = []

    def go():
        try:
            _buy(tid, aid, key="same")
        except Exception as exc:     # noqa: BLE001
            errs.append(exc)
    ths = [threading.Thread(target=go) for _ in range(10)]
    [t.start() for t in ths]
    [t.join() for t in ths]
    assert not errs
    assert len(db.list_experiments(tid)) == 1
    assert db.get_team(tid)["capital"] == 2000 - CARD["money"]


def test_purchase_rejects_bad_thresholds_and_insufficient_funds():
    tid = _team(credits=1)
    aid = _assumption(tid)
    ok, msg, _ = _buy(tid, aid, sv=2, fv=5, hib=True)
    assert not ok and "ABOVE" in msg
    ok, msg, _ = _buy(tid, aid)
    assert not ok and "Credits" in msg and db.list_experiments(tid) == []


def test_outcome_computed_and_inconclusive_keeps_testing():
    tid = _team()
    aid = _assumption(tid)
    _, _, eid = _buy(tid, aid)
    exp = [e for e in db.list_experiments(tid) if e["id"] == eid][0]
    assert logic.compute_outcome(exp, 9) == "Supported"
    assert logic.compute_outcome(exp, 2) == "Refuted"
    assert logic.compute_outcome(exp, 5) == "Inconclusive"
    ok, msg = logic.record_experiment_result(tid, eid, observed_value=5, observed_n=40,
                                             result_text="5 of 40")
    assert ok and "Inconclusive" in msg
    assert db.get_assumption(tid, aid)["status"] == "Testing"
    ev = db.list_evidence(tid)
    assert len(ev) == 1 and ev[0]["direction"] == "Inconclusive" and ev[0]["experiment_id"] == eid


def test_refuted_result_settles_assumption_and_earns_like_support():
    tid = _team()
    aid1, aid2 = _assumption(tid, "A1"), _assumption(tid, "A2")
    _, _, e1 = _buy(tid, aid1)
    _, _, e2 = _buy(tid, aid2)
    c0 = _credits(tid)
    logic.record_experiment_result(tid, e1, observed_value=2, observed_n=52)
    c1 = _credits(tid)
    logic.record_experiment_result(tid, e2, observed_value=10, observed_n=52)
    c2 = _credits(tid)
    assert db.get_assumption(tid, aid1)["status"] == "Refuted"
    assert db.get_assumption(tid, aid2)["status"] == "Supported"
    assert round(c1 - c0, 1) == round(c2 - c1, 1)          # same credit either direction
    # strength 9 card → pending review; review accept releases the same for both
    for e in db.list_evidence(tid):
        assert e["review_status"] == "Pending review"


def test_override_needs_reason_and_resave_does_not_double_pay():
    tid = _team()
    aid = _assumption(tid)
    _, _, eid = _buy(tid, aid)
    ok, msg = logic.record_experiment_result(tid, eid, observed_value=2, outcome="Supported")
    assert not ok and "Refuted" in msg
    ok, _ = logic.record_experiment_result(tid, eid, observed_value=2, outcome="Supported",
                                           override_reason="Two more deposits arrived late")
    assert ok
    c = _credits(tid)
    ok, _ = logic.record_experiment_result(tid, eid, observed_value=2, outcome="Refuted")
    assert ok and _credits(tid) == c and len(db.list_evidence(tid)) == 1
    assert db.list_evidence(tid)[0]["direction"] == "Contradicts"


def test_result_locks_after_round_ends(fresh_db):
    tid = _team(gid=fresh_db)
    aid = _assumption(tid)
    _, _, eid = _buy(tid, aid)
    assert logic.record_experiment_result(tid, eid, observed_value=9)[0]
    db.set_game_round(fresh_db, 2)
    db.invalidate_run_cache()
    ok, msg = logic.record_experiment_result(tid, eid, observed_value=1)
    assert not ok and "locked" in msg


# ---- Assumption status rules --------------------------------------------- #
def test_team_cannot_hand_set_supported():
    tid = _team()
    aid = _assumption(tid)
    ok, msg = logic.set_assumption_status_by_team(tid, aid, "Supported")
    assert not ok
    assert logic.set_assumption_status_by_team(tid, aid, "Ignored")[0]
    assert logic.evidence_coverage(tid) < 0.5


def test_reviewed_evidence_can_settle_an_assumption():
    tid = _team()
    aid = _assumption(tid)
    ids = [logic.log_evidence(tid, f"Owner {i} refused to pay deposit", "Observed customer behavior",
                              f"cafe {i}", "watched them decline", assumption_id=aid,
                              direction="Contradicts")["evidence_id"] for i in range(2)]
    assert db.get_assumption(tid, aid)["status"] == "Testing"    # strength 6 → pending
    for i in ids:
        logic.review_evidence(tid, i, "accept")
    assert db.get_assumption(tid, aid)["status"] == "Refuted"


def test_instructor_override_survives_new_evidence():
    tid = _team()
    aid = _assumption(tid)
    assert not logic.instructor_set_assumption_status(tid, aid, "Supported", "")[0]
    assert logic.instructor_set_assumption_status(tid, aid, "Supported", "verified in class")[0]
    _, _, eid = _buy(tid, aid)
    logic.record_experiment_result(tid, eid, observed_value=1)
    assert db.get_assumption(tid, aid)["status"] == "Supported"
    assert not logic.set_assumption_status_by_team(tid, aid, "Untested")[0]
    ok, msg = logic.instructor_set_assumption_status(tid, aid, "auto", "release")
    assert ok and db.get_assumption(tid, aid)["status"] == "Refuted"


def test_legacy_hand_set_status_is_grandfathered():
    tid = _team()
    aid = _assumption(tid)
    db.update_assumption(aid, status="Supported", status_source=None)   # pre-Stage-1 row
    logic.log_evidence(tid, "one person described buying", PAST, "s", "past",
                       assumption_id=aid, direction="Supports")
    assert db.get_assumption(tid, aid)["status"] == "Supported"


# ---- Frozen round results --------------------------------------------------- #
def test_finalized_round_is_stable(fresh_db):
    tid = _team(gid=fresh_db)
    db.set_game_round(fresh_db, 6)
    db.invalidate_run_cache()
    logic.commit_round(tid, 6)
    logic.director_advance(7)                     # freezes round 6
    frozen = logic.round_score(tid, 6)
    assert frozen["finalized"]
    for i in range(6):
        logic.log_evidence(tid, f"paid deposit {i}", PAYS, f"c{i}", "paid")
    cfg = logic.get_round_score_config()
    cfg["strictness"] = 95
    logic.set_round_score_config(cfg["weights"], 95)
    again = logic.round_score(tid, 6, logic.get_round_score_config())
    assert again["score"] == frozen["score"] and again["components"] == frozen["components"]
    assert logic.round_score(tid, 6, live=True)["finalized"] is False


def test_finalize_is_idempotent_under_concurrency(fresh_db):
    tid = _team(gid=fresh_db)
    db.set_game_round(fresh_db, 3)
    db.invalidate_run_cache()
    ths = [threading.Thread(target=lambda: (db.set_active_game(fresh_db),
                                            logic.finalize_round_result(tid, 2)))
           for _ in range(8)]
    [t.start() for t in ths]
    [t.join() for t in ths]
    fr = db.get_round_result(tid, 2)
    assert fr and len(fr["history"]) == 1


def test_corrections_require_reason_and_are_logged(fresh_db):
    tid = _team(gid=fresh_db)
    db.set_game_round(fresh_db, 2)
    db.invalidate_run_cache()
    base = logic.round_score(tid, 1)              # lazily finalized (backfill)
    assert base["finalized"] and base["finalized_source"] == "backfill"
    assert not logic.adjust_round_result(tid, 1, 5, "")[0]
    assert logic.adjust_round_result(tid, 1, 5, "late-submission policy")[0]
    adj = logic.round_score(tid, 1)
    assert adj["adjustment"] == 5 and adj["score"] == min(100, base["auto_score"] + 5)
    assert not logic.recompute_round_result(tid, 1, "")[0]
    assert logic.recompute_round_result(tid, 1, "fixed a data error")[0]
    hist = db.get_round_result(tid, 1)["history"]
    assert [h["action"] for h in hist] == ["finalized", "adjust", "recompute"]


# ---- Deadline lock ----------------------------------------------------------- #
def test_deadline_locks_uncommitted_team(fresh_db):
    tid = _team(gid=fresh_db)
    assert not logic.editing_locked(tid, 1)
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    db.upsert_schedule_row(2, None, past)
    db.invalidate_run_cache()
    assert logic.editing_locked(tid, 1)
    assert not logic.commitment_state(tid, 1)["committed"]


# ---- Counted evidence feeds deliverables ---------------------------------- #
def test_withdrawn_and_practice_dont_satisfy_deliverables():
    tid = _team()
    logic.log_evidence(tid, "AI persona interview", PAST, "AI", "practice", origin="AI practice")
    r = logic.log_evidence(tid, "one real interview described buying", PAST, "s", "past")
    logic.withdraw_evidence(tid, r["evidence_id"])
    assert not logic._deliverable_done(tid, "evidence_ge_2", 1)
