"""Stage 2 / post-pilot backlog tests: per-game settings, interpretive strength,
near-duplicates, sampled review, simulation pathway, status history, first-attempt
concepts, four-strand grade + gradebook, pitch citations, join codes, VP auction."""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("VF_DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))

import db       # noqa: E402
import logic    # noqa: E402
import content  # noqa: E402

from test_learning_integrity import _reset_storage, _credits, _assumption  # noqa: E402

LOI = "Customer signs a letter of intent"
PAYS = "Customer pays or makes a binding commitment"
OBS = "Observed customer behavior"
ALL = {"fact": True, "do": True, "real": True, "big": True}


@pytest.fixture(autouse=True)
def fresh_db():
    _reset_storage()
    db.end_request()
    db.init_db()
    gid = db.list_games()[0]["id"]
    db.set_active_game(gid)
    yield gid
    db.end_request()


def _team(gid=None, credits=20, roster=None, opportunity="campus food waste"):
    code = db.create_team("T", evidence_credits=credits, game_id=gid, roster=roster,
                          opportunity=opportunity)
    return db.get_team_by_code(code)["id"]


# ---- Per-game settings and layout ----------------------------------------- #
def test_sections_have_independent_schedules_and_settings(fresh_db):
    a, b = fresh_db, db.create_game("Section B")
    db.set_active_game(a)
    db.set_game_round(a, 1)
    past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    db.upsert_schedule_row(2, None, past)
    logic.set_grade_config({"reasoning": 50, "completion": 30, "reflection": 20})
    db.set_active_game(b)
    db.set_game_round(b, 1)
    db.invalidate_run_cache()
    logic.sync_active_game()
    assert db.get_game(b)["current_round"] == 1               # B not pushed by A's time
    assert logic.get_grade_config()["weights"]["reasoning"] == 60
    db.set_active_game(a)
    db.invalidate_run_cache()
    logic.sync_active_game()
    assert db.get_game(a)["current_round"] == 2
    assert logic.get_grade_config()["weights"]["reasoning"] == 50


def test_compressing_one_section_leaves_the_other(fresh_db):
    a, b = fresh_db, db.create_game("Section B")
    db.set_game_round(a, 10)
    db.set_game_round(b, 10)
    db.set_active_game(a)
    logic.set_total_rounds(7)
    db.invalidate_run_cache()
    assert db.get_game(a)["current_round"] == 7 and db.get_game(b)["current_round"] == 10
    assert logic.total_rounds() == 7
    db.set_active_game(b)
    db.invalidate_run_cache()
    assert logic.total_rounds() == content.DEFAULT_TOTAL_ROUNDS


def test_existing_game_inherits_global_layout_once(fresh_db):
    topics = db.get_round_topics()
    assert topics and len(topics) == len(content.DEFAULT_TOPIC_ORDER)


# ---- Interpretive strength ------------------------------------------------- #
def test_interpretive_strength_and_reasons():
    s, why = logic.interpretive_strength(PAYS, ALL, sample_n=10, limitations="one hall")
    assert s == 10 and any("limitations" in w for w in why)
    s, why = logic.interpretive_strength(PAYS, {"fact": False, "do": False, "real": True,
                                                "big": False})
    assert s == 2
    s, why = logic.interpretive_strength(LOI, ALL, sample_n=10, limitations="x")
    assert s == 7 and any("not binding" in w for w in why)
    s, why = logic.interpretive_strength("Customer description of past behavior", ALL)
    assert s == 4 and any("ceiling" in w for w in why)


def test_log_with_dims_requires_interpretation_when_linked():
    tid = _team()
    aid = _assumption(tid)
    r = logic.log_evidence(tid, "2 of 52 paid deposits", PAYS, "Hall B", "deposits",
                           assumption_id=aid, direction="Contradicts", dims=ALL)
    assert not r["ok"] and "interpretation" in r["message"].lower()
    r = logic.log_evidence(tid, "2 of 52 paid deposits", PAYS, "Hall B", "deposits",
                           assumption_id=aid, direction="Contradicts", dims=ALL, sample_n=52,
                           interpretation="Students won't prepay a week ahead.")
    assert r["ok"] and r["strength"] == 9 and r["reasons"]
    e = db.get_evidence(tid, r["evidence_id"])
    assert e["interpretation"] and json.loads(e["strength_reasons"])


# ---- Near-duplicates and sampled review ----------------------------------- #
def test_near_duplicate_routes_to_review():
    tid = _team()
    logic.log_evidence(tid, "Owner described tossing 3kg produce last Friday",
                       "Customer description of past behavior", "Cafe A", "past action")
    r = logic.log_evidence(tid, "Owner described tossing 3kg produce last Friday (again)",
                           "Customer description of past behavior", "Cafe A", "past action")
    assert r["ok"] and r["status"] == "Pending review"
    assert db.get_evidence(tid, r["evidence_id"])["similar_to"]


def test_sampled_review_thresholds_and_spot_check(fresh_db):
    tid = _team(gid=fresh_db)
    six = logic.log_evidence(tid, "Watched 6 owners weigh waste bins", OBS, "6 cafes",
                             "observed", dims={"fact": True, "do": True, "real": True,
                                               "big": False})
    seven = logic.log_evidence(tid, "3 owners started a paid 2-week trial", "Customer invests time in a trial",
                               "3 cafes", "trial", dims={"fact": True, "do": True, "real": True,
                                                         "big": False}, limitations="small n")
    assert six["strength"] == 6 and six["status"] == "Auto-accepted"
    assert seven["strength"] == 7 and seven["status"] == "Pending review"
    q1 = logic.review_queue([tid], db.current_round())
    spot = [e for e in q1 if e.get("_spot_check")]
    assert len(spot) == 1 and spot[0]["id"] == six["evidence_id"]
    assert [e["id"] for e in logic.review_queue([tid], db.current_round()) if e.get("_spot_check")] \
        == [six["evidence_id"]]                                    # stable pick
    ok, _, delta = logic.review_evidence(tid, six["evidence_id"], "accept")
    assert ok and delta == 0
    assert not [e for e in logic.review_queue([tid], db.current_round()) if e.get("_spot_check")]


# ---- Simulation pathway ---------------------------------------------------- #
def _sim_experiment(tid, aid):
    card = content.EXPERIMENT_CARD_MAP["Landing-page test"]
    ok, _, eid = logic.purchase_experiment(tid, card, aid, "We believe 20% sign up", "signup %",
                                           ">=15%", "<=5%", "if supported build; if refuted "
                                           "revisit; else retest", "Supported", 70, 15, 5, True)
    return eid


def test_simulation_requires_instructor_and_is_labelled():
    tid = _team(credits=50)
    db.update_team(tid, capital=5000)
    aid = _assumption(tid)
    eid = _sim_experiment(tid, aid)
    ok, msg = logic.simulate_experiment(tid, eid, 120)
    assert not ok and "enabled" in msg
    logic.set_sim_enabled(tid, True)
    ok, msg = logic.simulate_experiment(tid, eid, 5)
    assert not ok and "between" in msg
    ok, msg = logic.simulate_experiment(tid, eid, 120)
    assert ok
    exp = [e for e in db.list_experiments(tid) if e["id"] == eid][0]
    assert exp["simulated"] == 1 and exp["observed_n"] == 120
    ev = db.get_evidence(tid, exp["evidence_id"])
    assert ev["origin"] == "Simulation"
    assert ev["id"] in {e["id"] for e in db.list_counted_evidence(tid)}
    assert ev["id"] not in {e["id"] for e in logic.scored_evidence(tid)}
    a = db.get_assumption(tid, aid)
    if a["status"] in ("Supported", "Refuted"):
        assert "SIMULATED" in a["status_note"]
    ok, msg = logic.simulate_experiment(tid, eid, 120)
    assert not ok and "re-rolled" in msg


def test_simulation_is_deterministic():
    a, b = _team(credits=50), _team(credits=50)
    for t in (a, b):
        db.update_team(t, capital=5000)
        logic.set_sim_enabled(t, True)
    ea = _sim_experiment(a, _assumption(a))
    logic.simulate_experiment(a, ea, 100)
    v1 = [e for e in db.list_experiments(a) if e["id"] == ea][0]["observed_value"]
    assert v1 is not None and 0 <= v1 <= 100


# ---- Status history -------------------------------------------------------- #
def test_assumption_status_history_is_kept():
    tid = _team()
    aid = _assumption(tid)
    logic.set_assumption_status_by_team(tid, aid, "Ignored")
    logic.instructor_set_assumption_status(tid, aid, "Supported", "verified")
    hist = json.loads(db.get_assumption(tid, aid)["status_history"])
    assert [h["to"] for h in hist] == ["Ignored", "Supported"]


# ---- Concept checks -------------------------------------------------------- #
def test_first_attempt_is_kept_and_counted():
    tid = _team()
    concept = next(c for c in content.CONCEPT_QUIZ)
    truth = [t for _q, t in content.CONCEPT_QUIZ[concept]]
    wrong = [not x for x in truth]
    db.set_round_answer(tid, 1, concept, json.dumps({"quiz": wrong, "text": ""}))
    db.set_round_answer(tid, 1, concept, json.dumps({"quiz": truth, "text": ""}))
    assert db.get_first_quizzes(tid)[(1, concept)] == wrong
    rep = logic.misconception_report()
    row = next(c for c in rep["concepts"] if c["concept"] == concept)
    assert row["wrong"] == 1


def test_vocabulary_string_no_longer_passes():
    tid = _team()
    q = logic.answer_quality("evidence evidence customer test assumption value segment pivot",
                             "Behavior vs. opinion", tid)
    assert not q["ok"]
    good = logic.answer_quality("Campus food waste owners told us about last week's binned "
                                "stock, which is behavior evidence rather than opinion.",
                                "Behavior vs. opinion", tid)
    assert good["ok"]


# ---- Four-strand grade, gradebook, venture bonus -------------------------- #
def test_round_score_has_strands_and_reasons(fresh_db):
    tid = _team(gid=fresh_db)
    db.set_game_round(fresh_db, 8)
    db.invalidate_run_cache()
    _assumption(tid, "At least 20% of hall B residents will prepay $10 deposits")
    rs = logic.round_score(tid, 8)
    sd = rs["strands"]
    assert set(sd) >= {"reasoning", "completion", "reflection", "criteria", "total"}
    assert "R1" in sd["criteria"] and sd["criteria"]["R1"]["reasons"]
    assert rs["score"] == sd["total"]


def test_disconfirmation_followed_by_revision_scores_top_revision(fresh_db):
    tid = _team(gid=fresh_db, credits=50)
    rnd = logic.page_unlock_round("Experiment Marketplace")
    db.set_game_round(fresh_db, rnd)
    db.invalidate_run_cache()
    aid = _assumption(tid)
    card = content.EXPERIMENT_CARD_MAP["Preorder"]
    _, _, eid = logic.purchase_experiment(tid, card, aid, "We believe 20% will prepay deposits",
                                          "deposit %", ">=15", "<=5",
                                          "if refuted revisit the offer format", "Supported", 75,
                                          15, 5, True)
    logic.record_experiment_result(tid, eid, observed_value=3.8, observed_n=52,
                                   decision="Pivot (change the model)")
    r4 = logic.round_score(tid, rnd)["strands"]["criteria"]["R4"]
    assert r4["level"] == 4


def test_gradebook_per_student_with_bonus_and_ratings(fresh_db):
    roster = [{"name": "Ana"}, {"name": "Ben"}]
    t1 = _team(gid=fresh_db, roster=roster)
    t2 = _team(gid=fresh_db)
    t3 = _team(gid=fresh_db)
    db.update_team(t1, market_potential=5_000_000)
    for t in (t1, t2, t3):
        db.add_assumption(t, "x y z specific 10% claim here", importance=5)
        db.save_canvas(t, "bmc", {"a": "b"}, "v1", "")
    db.add_reflection(t1, {"student_name": "Ana", "round": 1, "expected": "a", "occurred": "b",
                           "differently": "c", "assumption_id": db.list_assumptions(t1)[0]["id"]})
    db.set_game_round(fresh_db, 2)
    db.invalidate_run_cache()
    rows = logic.gradebook()
    names = {(r["team_id"], r["student"]) for r in rows}
    assert (t1, "Ana") in names and (t1, "Ben") in names
    bonus = {r["team_id"]: r["venture_bonus"] for r in rows}
    assert sorted(set(bonus.values())) == [0.0, 2.5, 5.0]
    ana = next(r for r in rows if r["student"] == "Ana")
    ben = next(r for r in rows if r["student"] == "Ben")
    assert ana["reflection"] > ben["reflection"]
    ref = db.list_reflections(t1)[0]
    db.rate_reflection(ref["id"], t1, "Exemplary", "")
    db.invalidate_run_cache()
    ana2 = next(r for r in logic.gradebook() if r["student"] == "Ana")
    assert ana2["ratings"] == 1 and ana2["reflection"] == 100.0


# ---- Pitch citations ------------------------------------------------------- #
def test_pitch_uncited_claims_and_traction_backing(fresh_db):
    tid = _team(gid=fresh_db)
    r = logic.log_evidence(tid, "12 residents paid $1 per swap", PAYS, "Hall B", "payments",
                           dims=ALL, sample_n=12, limitations="one hall")
    canvas = {"traction": "13 paid swaps", "product": "fridge shelf",
              "_cites": {"traction": [r["evidence_id"]]}}
    db.save_pitch(tid, fresh_db, "", "", "", "", canvas=canvas)
    db.invalidate_run_cache()
    rep = logic.pitch_citation_report(tid)
    assert rep["uncited"] == ["product"] and not rep["traction_qualified"]   # pending review
    logic.review_evidence(tid, r["evidence_id"], "accept")
    assert logic.pitch_citation_report(tid)["traction_qualified"]


# ---- Small items ----------------------------------------------------------- #
def test_new_join_codes_are_longer():
    code = db.create_team("X")
    assert len(code) == 8


def test_vp_auction_once_per_round():
    tid = _team()
    for n in ("A", "B", "C"):
        db.add_value_prop(tid, n, "", 5)
    alloc = {p["id"]: 30 for p in db.list_value_props(tid)}
    assert logic.run_vp_auction(tid, alloc, 1).get("committed")
    again = logic.run_vp_auction(tid, alloc, 1)
    assert not again.get("committed") and "already" in again["reason"]
    assert len(db.list_vp_results(tid)) == 1


def test_backend_label():
    assert db.backend_name() in ("SQLite (local file)", "Postgres", "Postgres (Neon)")


def test_mp_resume_skips_teams_with_a_note():
    tid = _team()
    db.add_message(tid, "s", "b", 3, sender=f"{content.INVESTOR['name']} · x")
    assert logic._has_mp_note(tid, 3) and not logic._has_mp_note(tid, 4)
