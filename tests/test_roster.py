"""Roster template (stored in the database), roster import in the Example_Template
format, and adding / moving / removing team members."""
import os
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("VF_DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))

import db       # noqa: E402
import logic    # noqa: E402

from test_learning_integrity import _reset_storage  # noqa: E402

ASSET = os.path.join(ROOT, "assets", "Example_Template.xlsx")


@pytest.fixture(autouse=True)
def fresh_db():
    _reset_storage()
    db.end_request()
    db.init_db()
    gid = db.list_games()[0]["id"]
    db.set_active_game(gid)
    yield gid
    db.end_request()


def _asset_bytes():
    with open(ASSET, "rb") as fh:
        return fh.read()


def test_template_is_stored_in_the_database_and_persists():
    data, info = db.get_stored_file("Example_Template.xlsx")
    assert data == _asset_bytes() and info["source"] == "shipped"
    db.put_stored_file("Example_Template.xlsx", b"PK-custom", "uploaded")
    db.init_db()                     # a restart / new login must not overwrite it
    db.invalidate_run_cache()
    data, info = db.get_stored_file("Example_Template.xlsx")
    assert data == b"PK-custom" and info["source"] == "uploaded"
    db.restore_shipped_file("Example_Template.xlsx")
    db.invalidate_run_cache()
    assert db.get_stored_file("Example_Template.xlsx")[0] == _asset_bytes()


def test_template_keeps_formatting_and_has_no_personal_email():
    import zipfile
    z = zipfile.ZipFile(ASSET)
    blob = b"".join(z.read(n) for n in z.namelist())
    assert b"@nau.edu" not in blob
    sheet = z.read("xl/worksheets/sheet1.xml")
    assert b"t=\"array\"" in sheet and b"COUNTIF" in sheet     # helper formulas kept
    assert b"FF92D050" in z.read("xl/styles.xml") or b"92D050" in z.read("xl/styles.xml")


def test_importing_the_template_format():
    headers, rows = logic.read_table(_asset_bytes(), "Example_Template.xlsx")
    parsed, warns = logic.parse_roster(headers, rows)
    assert warns == []                                  # 90+ formula-only rows ignored
    assert [g["game"] for g in parsed] == ["ENT 400 · Section 1"]
    teams = parsed[0]["teams"]
    assert [t["label"] for t in teams] == ["Team 1", "Team 2"]
    assert [m["name"] for m in teams[0]["members"]] == ["Ada Lovelace", "Alan Turing",
                                                         "Grace Hopper"]
    summ = logic.import_roster(parsed)
    assert summ["teams"] == 2 and summ["members"] == 6


def test_class_and_section_carry_down_when_formulas_were_not_calculated():
    headers = ["FirstName", "LastName", "PrimaryEmail", "Class", "Section", "Team"]
    rows = [dict(zip(headers, r)) for r in [
        ("Ada", "L", "a@x.edu", "ENT 400", 1.0, 1.0),
        ("Alan", "T", "b@x.edu", None, None, 1.0),
        ("Kat", "J", "c@x.edu", None, None, 2.0)]]
    parsed, warns = logic.parse_roster(headers, rows)
    assert not warns and parsed[0]["game"] == "ENT 400 · Section 1"
    assert [len(t["members"]) for t in parsed[0]["teams"]] == [2, 1]


def _two_teams(gid):
    a = db.create_team("Team 1", game_id=gid, roster=[{"name": "Ada Lovelace", "email": "a@x.edu"},
                                                      {"name": "Alan Turing", "email": ""}])
    b = db.create_team("Team 2", game_id=gid, roster=[{"name": "Grace Hopper", "email": ""}])
    return db.get_team_by_code(a)["id"], db.get_team_by_code(b)["id"]


def test_add_move_remove_members(fresh_db):
    t1, t2 = _two_teams(fresh_db)
    rows = [{"name": "Ada Lovelace", "email": "a@x.edu", "team": "Team 2"},     # moved
            {"name": "Grace Hopper", "email": "", "team": "Team 2"},
            {"name": "Mae Jemison", "email": "mae@x.edu", "team": "Team 1"},   # added
            {"name": "", "email": "", "team": ""}]                             # blank row
    ok, msg, chg = logic.save_game_members(fresh_db, rows)                     # Alan removed
    assert ok, msg
    assert chg == {"added": 1, "moved": 1, "removed": 1}
    db.invalidate_run_cache()
    assert logic.team_member_names(db.get_team(t1)) == ["Mae Jemison"]
    assert logic.team_member_names(db.get_team(t2)) == ["Ada Lovelace", "Grace Hopper"]


@pytest.mark.parametrize("row,needle", [
    ({"name": "", "email": "x@y.edu", "team": "Team 1"}, "name"),
    ({"name": "Zed", "email": "", "team": "Team 9"}, "choose a team"),
    ({"name": "Zed", "email": "not-an-email", "team": "Team 1"}, "email"),
])
def test_invalid_member_rows_save_nothing(fresh_db, row, needle):
    t1, _t2 = _two_teams(fresh_db)
    ok, msg, _ = logic.save_game_members(fresh_db, [row])
    assert not ok and needle in msg
    db.invalidate_run_cache()
    assert len(logic.team_member_names(db.get_team(t1))) == 2      # untouched


def test_duplicate_in_one_team_is_refused(fresh_db):
    _two_teams(fresh_db)
    rows = [{"name": "Ada Lovelace", "email": "", "team": "Team 1"},
            {"name": "ada lovelace", "email": "", "team": "Team 1"}]
    ok, msg, _ = logic.save_game_members(fresh_db, rows)
    assert not ok and "twice" in msg


def test_rosters_cannot_touch_another_game(fresh_db):
    other = db.create_game("Other section")
    code = db.create_team("Elsewhere", game_id=other, roster=[{"name": "Sally Ride"}])
    foreign = db.get_team_by_code(code)["id"]
    with pytest.raises(ValueError):
        db.set_game_rosters(fresh_db, {foreign: []})
    db.invalidate_run_cache()
    assert logic.team_member_names(db.get_team(foreign)) == ["Sally Ride"]


def test_team_setup_page_renders_with_template_and_members(fresh_db):
    AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
    _two_teams(fresh_db)
    db.end_request()
    at = AppTest.from_file(os.path.join(ROOT, "app.py"), default_timeout=60)
    for k, v in {"role": "instructor", "instructor_ok": True, "instr_page": "Team Setup",
                 "active_game_id": fresh_db}.items():
        at.session_state[k] = v
    at.run()
    assert not at.exception
    assert any(b.label == "💾 Save member changes" for b in at.button)
    assert any("Team members" in m.value for m in at.markdown)
