"""SQL translation unit tests (no database needed). The full suite runs against
Postgres with:  DATABASE_URL=postgresql://... pytest -q tests/"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
pgcompat = pytest.importorskip("pgcompat")


def setup_module():
    pgcompat.SERIAL_TABLES.update({"teams"})


def test_placeholders_and_returning():
    assert pgcompat.translate("SELECT * FROM teams WHERE id=?") == "SELECT * FROM teams WHERE id=%s"
    assert pgcompat.translate("INSERT INTO teams(name) VALUES(?)").endswith("RETURNING id")
    assert "RETURNING" not in pgcompat.translate("INSERT INTO settings(key, value) VALUES(?,?)")


def test_insert_or_ignore_and_noops():
    out = pgcompat.translate("INSERT OR IGNORE INTO badges(team_id, code) VALUES(?,?)")
    assert out.startswith("INSERT INTO badges") and out.endswith("ON CONFLICT DO NOTHING")
    assert pgcompat.translate("PRAGMA foreign_keys = ON") is None
    assert pgcompat.translate("BEGIN IMMEDIATE") is None


def test_ddl_types():
    out = pgcompat.translate("CREATE TABLE x (id INTEGER PRIMARY KEY AUTOINCREMENT, v REAL)")
    assert "SERIAL PRIMARY KEY" in out and "DOUBLE PRECISION" in out
    assert "ADD COLUMN IF NOT EXISTS" in pgcompat.translate("ALTER TABLE t ADD COLUMN c TEXT")


def test_row_behaves_like_sqlite_row():
    r = pgcompat.Row([("a", 1), ("b", 2)])
    assert r["b"] == 2 and r[0] == 1 and dict(r) == {"a": 1, "b": 2}
