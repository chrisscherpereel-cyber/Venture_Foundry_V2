"""Migration test: a database created by the PRE-Stage-1 code (commit 70f5079) opens
under the current code with every row, balance and status intact, gains the new
columns/tables, and can be migrated twice safely.

The legacy database is built by running the old db.py/content.py from git history
in a subprocess, so this tests a real previous schema rather than a hand-made copy.
Skipped when git history for that commit isn't available, or when running against
Postgres (the legacy builder is SQLite-only).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEGACY_COMMIT = "70f5079"

SEED = r"""
import os, sys, json
sys.path.insert(0, os.environ["LEGACY_DIR"])
import db
db.init_db()
gid = db.list_games()[0]["id"]
db.set_active_game(gid)
code = db.create_team("Legacy Team", capital=1500, evidence_credits=33, founder_hours=40)
tid = db.get_team_by_code(code)["id"]
db.add_assumption(tid, "Students prepay", importance=5)
aid = db.list_assumptions(tid)[0]["id"]
db.update_assumption(aid, status="Supported")
db.add_evidence(tid, "They paid", "Customer pays or makes a binding commitment", 10,
                "cafe", aid, 10.0, "paid")
db.add_evidence(tid, "They paid", "Customer pays or makes a binding commitment", 10,
                "cafe", aid, 10.0, "paid")            # a legacy duplicate
eid = db.add_experiment(tid, aid, "Preorder", 100, 10, 4, 9, "h", "m", ">=5", "<=1", "rule")
db.update_experiment(eid, outcome="Refuted", result="1 of 40")
db.save_canvas(tid, "bmc", {"revenue_streams": "subscription"}, "v1", "first")
db.set_commitment(tid, 1, True, None, json.dumps({"total": 2, "done": 1}))
print(json.dumps({"tid": tid, "aid": aid, "eid": eid}))
"""

CHECK = r"""
import os, sys, json
sys.path.insert(0, os.environ["NEW_DIR"])
import db, logic
db.init_db()
db.init_db()                                  # migrations must be repeatable
gid = db.list_games()[0]["id"]
db.set_active_game(gid)
ids = json.loads(os.environ["IDS"])
tid, aid, eid = ids["tid"], ids["aid"], ids["eid"]
t = db.get_team(tid)
ev = db.list_evidence(tid)
exp = db.list_experiments(tid)[0]
a = db.get_assumption(tid, aid)
conn = db.get_conn()
cols = {r["name"] for r in conn.execute("PRAGMA table_info(evidence)")}
tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
conn.close()
# the legacy duplicate can't be re-logged a third time under the new rules
dup = logic.log_evidence(tid, "They paid", "Customer pays or makes a binding commitment",
                         "cafe", "paid")
print(json.dumps({
    "capital": t["capital"], "credits_before_dup": t["evidence_credits"],
    "n_evidence": len(ev), "credits_awards": [e["credits_award"] for e in ev],
    "review_status": [e["review_status"] for e in ev],
    "labels": [logic.evidence_review_label(e) for e in ev],
    "dedupe_filled": all(e["dedupe_key"] for e in ev),
    "assumption_status": a["status"], "assumption_source": a["status_source"],
    "exp_outcome": exp["outcome"], "exp_locked": logic.experiment_locked(exp),
    "canvases": len(db.list_canvases(tid)),
    "commitment": db.get_commitment(tid, 1)["committed"],
    "has_cols": all(c in cols for c in ("origin", "direction", "review_status", "round")),
    "has_round_results": "round_results" in tables,
    "dup_refused": (not dup["ok"]) and dup["status"] == "duplicate",
}))
"""


def _git_show(path):
    return subprocess.run(["git", "-C", ROOT, "show", f"{LEGACY_COMMIT}:{path}"],
                          capture_output=True, check=True).stdout


@pytest.fixture
def legacy_dir():
    if os.environ.get("DATABASE_URL"):
        pytest.skip("legacy builder is SQLite-only")
    try:
        files = {p: _git_show(p) for p in ("db.py", "content.py", "pgcompat.py")}
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip(f"git history for {LEGACY_COMMIT} not available")
    d = tempfile.mkdtemp()
    for p, data in files.items():
        with open(os.path.join(d, p), "wb") as fh:
            fh.write(data)
    yield d
    shutil.rmtree(d, ignore_errors=True)


def _run(script, env):
    full = {**os.environ, **env}
    full.pop("DATABASE_URL", None)
    out = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                         env=full, cwd=tempfile.gettempdir())
    assert out.returncode == 0, out.stderr[-2000:]
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_legacy_database_migrates_without_loss(legacy_dir, tmp_path):
    legacy_db = str(tmp_path / "legacy.db")
    ids = _run(SEED, {"LEGACY_DIR": legacy_dir, "VF_DB_PATH": legacy_db})
    # migrate a COPY, as the handoff instructions require
    copy_db = str(tmp_path / "copy.db")
    shutil.copy(legacy_db, copy_db)
    res = _run(CHECK, {"NEW_DIR": ROOT, "VF_DB_PATH": copy_db, "IDS": json.dumps(ids)})
    assert res["capital"] == 1500 and res["credits_before_dup"] == 33
    assert res["n_evidence"] == 2 and res["credits_awards"] == [10.0, 10.0]
    assert res["review_status"] == [None, None]
    assert all(lbl.startswith("Legacy") for lbl in res["labels"])
    assert res["dedupe_filled"]
    assert res["assumption_status"] == "Supported" and res["assumption_source"] is None
    assert res["exp_outcome"] == "Refuted" and res["exp_locked"] is False
    assert res["canvases"] == 1 and res["commitment"] == 1
    assert res["has_cols"] and res["has_round_results"]
    assert res["dup_refused"]
