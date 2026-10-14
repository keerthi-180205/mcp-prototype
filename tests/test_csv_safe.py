"""CSV exports must not let a stranger's text run as a spreadsheet formula. Offline."""

import csv

import pytest

from server.collection.export import export_job
from server.collection.models import CommentRow
from server.csv_safe import safe_cell, safe_row
from server.professionals.export import export_professionals
from server.professionals.models import ProfessionalRecord
from server.storage import comments as comment_store
from server.storage import professionals as pro_store


@pytest.mark.parametrize("value", ['=1+1', '=HYPERLINK("http://e.example","x")', "+cmd|' /C calc'!A0", "-2+3+cmd", "@SUM(A1)", "\t=1", "\r=1"])
def test_formula_like_text_is_made_inert(value):
    assert safe_cell(value) == "'" + value


@pytest.mark.parametrize("value", ["hello", "", "a=b", "I'm fine", "+919876543210", "+91 98765 43210", "-12", "3.5", "(080) 2345 6789"])
def test_ordinary_text_numbers_and_phone_numbers_are_untouched(value):
    assert safe_cell(value) == value


def test_non_strings_and_whole_rows():
    assert safe_cell(5) == 5 and safe_cell(None) is None and safe_cell(-3) == -3
    assert safe_row({"a": "=1", "b": 2, "c": "ok"}) == {"a": "'=1", "b": 2, "c": "ok"}


def test_collected_comment_export_neutralises_formulas(tmp_path):
    db = str(tmp_path / "t.db")
    comment_store.create_job("job1", "topic", "2026-10-14T00:00:00Z", {}, db_path=db)
    comment_store.save_comments("job1", [
        CommentRow(platform="reddit", username="=cmd|' /C calc'!A0", comment='=HYPERLINK("http://e.example","click")', post_url="https://x"),
        CommentRow(platform="reddit", username="fine", comment="normal text", likes=3, post_url="https://x"),
    ], db_path=db)
    res = export_job("job1", "csv", out_dir=str(tmp_path), db_path=db)
    with open(res["path"], newline="", encoding="utf-8-sig") as fh:
        rows = {r["username"]: r for r in csv.DictReader(fh)}
    assert rows["'=cmd|' /C calc'!A0"]["comment"].startswith("'=HYPERLINK")
    assert rows["fine"]["comment"] == "normal text" and rows["fine"]["likes"] == "3"


def test_professionals_export_neutralises_formulas_but_keeps_phone_numbers_usable(tmp_path):
    db = str(tmp_path / "p.db")
    pid = pro_store.pro_id_for("linkedin:evil")
    pro_store.upsert_professional(ProfessionalRecord(
        pro_id=pid, kind="linkedin", entity_type="person", name='=HYPERLINK("http://e.example","Dr")', role="psychiatrist",
        confidence=0.9, profile_url="https://www.linkedin.com/in/evil", city="Bangalore"), None, db)
    pro_store.set_review(pid, "approved", "checked", db)
    res = export_professionals(["approved"], "csv", out_dir=str(tmp_path), db_path=db)
    with open(res["path"], newline="", encoding="utf-8-sig") as fh:
        (row,) = list(csv.DictReader(fh))
    assert row["name"].startswith("'=HYPERLINK") and row["profile_url"].startswith("https://")
