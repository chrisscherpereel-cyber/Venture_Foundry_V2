"""Classroom burst load test (in-process, like the Streamlit server).

Known harness artifact: running many AppTest sessions in threads of ONE process
produces sporadic "multiple elements with the same key", "SCRIPT_RUN_WITHOUT_ERRORS"
and "form_submit_button must be inside st.form" errors. They occur identically on
the pre-Stage-1 commit and never in sequential renders; they are counted separately
as appTest-thread-artifact. Confirm with a real classroom session.

N simulated users start at the same instant (a barrier). Each user, in its own
thread, renders real pages through Streamlit's AppTest (the full app script, read
path) and performs real writes through the same logic functions the pages call
(log evidence, save a canvas, buy an experiment, record a result). One extra
"instructor" thread renders Director pages and accepts evidence from the review
queue while students write. All threads share one process (one GIL), as on
Streamlit Community Cloud.

This is NOT a browser/network test: websocket, rendering and network time are not
included, and Community Cloud's CPU share is unknown. Use the numbers as relative.

Usage:
  python3 tools/load_test.py --users 35 --teams 10 [--rounds-of-actions 2]
  DATABASE_URL=postgresql://... python3 tools/load_test.py --users 35
Never point it at a live course database: it wipes and seeds its own data.
"""
import argparse
import os
import statistics
import sys
import tempfile
import threading
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
if not os.environ.get("DATABASE_URL"):
    os.environ.setdefault("VF_DB_PATH", os.path.join(tempfile.mkdtemp(), "load.db"))
elif os.environ.get("VF_LOADTEST_ALLOW_PG") != "1":
    sys.exit("Refusing to run against DATABASE_URL without VF_LOADTEST_ALLOW_PG=1 "
             "(this test DROPS the schema). Use a throwaway database.")

import logging  # noqa: E402
logging.getLogger("streamlit").setLevel(logging.ERROR)

import db       # noqa: E402
import logic    # noqa: E402
import content  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = os.path.join(ROOT, "app.py")
PAGES = ["Round Briefing", "Evidence Ledger", "Experiment Marketplace", "Assumption Map",
         "My Venture", "Leaderboard"]
DIRECTOR_PAGES = ["Evidence Review", "Round Scores", "Cohort Overview"]


def reset():
    if db.IS_PG:
        conn = db.get_conn()
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
        conn.commit()
        conn.close()
    else:
        for s in ("", "-wal", "-shm"):
            if os.path.exists(db.DB_PATH + s):
                os.remove(db.DB_PATH + s)


def seed(n_teams, rnd=8):
    reset()
    db.init_db()
    gid = db.list_games()[0]["id"]
    db.set_active_game(gid)
    db.set_setting("strict_round_mode", "0")
    tids = []
    for i in range(n_teams):
        code = db.create_team(f"Team {i+1}", evidence_credits=200, capital=20000, game_id=gid)
        tid = db.get_team_by_code(code)["id"]
        tids.append(tid)
        for j in range(5):
            db.add_assumption(tid, f"Assumption {j} of team {i}", importance=5 - j % 3)
        for ct in ("customer_profile", "vpc", "bmc"):
            db.save_canvas(tid, ct, {"a": "x", "b": "y"}, "v1", "")
        for j in range(6):
            logic.log_evidence(tid, f"seed evidence {j} team {i}",
                               "Customer description of past behavior", f"s{j}", "past behavior")
    db.set_game_round(gid, rnd)
    db.end_request()
    return gid, tids


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=int, default=35)
    ap.add_argument("--teams", type=int, default=10)
    ap.add_argument("--rounds-of-actions", type=int, default=2)
    args = ap.parse_args()
    gid, tids = seed(args.teams)
    card = content.EXPERIMENT_CARD_MAP["Customer interview"]
    lat = {"render": [], "write": [], "director": []}
    errors = []
    lock = threading.Lock()
    barrier = threading.Barrier(args.users + 1)

    def timed(kind, fn):
        t0 = time.perf_counter()
        try:
            fn()
        except Exception:      # noqa: BLE001
            with lock:
                errors.append((kind, traceback.format_exc(limit=3)))
        finally:
            with lock:
                lat[kind].append(time.perf_counter() - t0)

    def render(state):
        at = AppTest.from_file(APP, default_timeout=120)
        for k, v in state.items():
            at.session_state[k] = v
        at.run()
        if at.exception:
            raise RuntimeError(str(at.exception)[:300])

    def student(u):
        tid = tids[u % len(tids)]
        barrier.wait()
        for rep in range(args.rounds_of_actions):
            for p in PAGES[(u + rep) % len(PAGES):] + PAGES[:(u + rep) % len(PAGES)][:1]:
                timed("render", lambda p=p: render({"role": "student", "team_id": tid,
                                                    "student_page": p}))
                break
            db.set_active_game(gid)
            timed("write", lambda: logic.log_evidence(
                tid, f"user {u} rep {rep}: 3 owners described binning stock",
                "Customer description of past behavior", f"u{u}", "past behavior"))
            timed("write", lambda: db.save_canvas(tid, "bmc", {"a": f"u{u}r{rep}"}, "", ""))
            aid = db.list_assumptions(tid)[0]["id"]
            def buy_and_record():
                ok, msg, eid = logic.purchase_experiment(
                    tid, card, aid, "h", "m", "s", "f", "d", "Supported", 60, 5, 1, True,
                    request_key=f"u{u}-r{rep}")
                if ok and eid:
                    logic.record_experiment_result(tid, eid, observed_value=3, observed_n=8)
            timed("write", buy_and_record)
            timed("render", lambda: render({"role": "student", "team_id": tid,
                                            "student_page": PAGES[(u + rep + 1) % len(PAGES)]}))

    def director():
        barrier.wait()
        for p in DIRECTOR_PAGES * args.rounds_of_actions:
            timed("director", lambda p=p: render({"role": "instructor", "instructor_ok": True,
                                                  "instr_page": p, "active_game_id": gid}))
            db.set_active_game(gid)
            for e in logic.review_queue(tids)[:5]:
                logic.review_evidence(e["team_id"], e["id"], "accept", "load test")

    ths = [threading.Thread(target=student, args=(u,)) for u in range(args.users)]
    ths.append(threading.Thread(target=director))
    t0 = time.perf_counter()
    [t.start() for t in ths]
    [t.join() for t in ths]
    wall = time.perf_counter() - t0

    # Consistency checks after the burst.
    db.end_request()
    db.set_active_game(gid)
    bad_versions = 0
    neg = 0
    for tid in tids:
        vs = [c["version"] for c in db.list_canvases(tid, "bmc")]
        bad_versions += len(vs) - len(set(vs))
        t = db.get_team(tid)
        neg += (t["capital"] < 0) + (t["founder_hours"] < 0)
        led = round(sum(x["credits"] for x in db.list_transactions(tid, limit=100000)), 1)
        # credits ledger must reconcile with the balance (200 seed credits)
        if abs((200 + led) - t["evidence_credits"]) > 0.05:
            errors.append(("ledger", f"team {tid}: 200+{led} != {t['evidence_credits']}"))

    def pct(xs, q):
        if not xs:
            return float("nan")
        xs = sorted(xs)
        return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]

    print(f"backend={db.backend_name()} users={args.users} teams={args.teams} "
          f"cpus={os.cpu_count()} python={sys.version.split()[0]} wall={wall:.1f}s")
    for k, xs in lat.items():
        if xs:
            print(f"  {k:9s} n={len(xs):4d} p50={pct(xs, .5):.2f}s p95={pct(xs, .95):.2f}s "
                  f"max={max(xs):.2f}s mean={statistics.mean(xs):.2f}s")
    kinds = {}
    for kind, msg in errors:
        last = msg.strip().splitlines()[-1]
        tag = ("appTest-thread-artifact" if ("multiple elements with the same" in last
                                            or "SCRIPT_RUN_WITHOUT_ERRORS" in last
                                            or "must be used inside an `st.form()`" in last)
               else kind)
        kinds[tag] = kinds.get(tag, 0) + 1
    print(f"  errors={len(errors)} by_kind={kinds} duplicate_canvas_versions={bad_versions} "
          f"negative_balances={neg}")
    for kind, msg in [e for e in errors if "same `key" not in e[1]
                      and "SCRIPT_RUN_WITHOUT_ERRORS" not in e[1]
                      and "inside an `st.form()`" not in e[1]][:5]:
        print("  ---", kind, msg.strip().splitlines()[-1][:300])


if __name__ == "__main__":
    main()
