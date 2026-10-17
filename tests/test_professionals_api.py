"""Run manager, export, REST API, MCP tools and CLI for the finder. Offline."""

import asyncio
import csv
import json
import time

import pytest
from starlette.testclient import TestClient

import server.server as srv
from scripts import find_professionals as cli
from server.professionals.export import FIELDS, export_professionals
from server.professionals.finder import ProfessionalFinder
from server.professionals.models import Channel, ProfessionalRecord
from server.professionals.runs import ProfessionalRunManager, RunError
from server.storage import professionals as store
from tests.test_professionals_finder import INSTAGRAM, LINKEDIN, ROUTES, WEB, FakeProfiles, FakeSerp, make_fetcher, prof
from web.server import app


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "api.db")


def factory(serp=None):
    def make(db_path):
        return ProfessionalFinder(
            serp=serp or FakeSerp({"linkedin": LINKEDIN, "instagram": INSTAGRAM, "web": WEB}),
            profiles=FakeProfiles({"mind.space.isha": prof("Counselling Psychologist | RCI Licensed | Bengaluru", ["https://www.mindspace.in/"], "Dr. Isha")}),
            fetcher=make_fetcher(ROUTES, []), use_llm=False, db_path=db_path)
    return make


def seed(db, key="linkedin:asha-rao", name="Asha Rao", **kw):
    rec = ProfessionalRecord(
        pro_id=store.pro_id_for(key), kind=key.split(":")[0], entity_type="person", name=name, role="clinical_psychologist",
        confidence=0.92, profile_url=f"https://www.linkedin.com/in/{key.split(':')[1]}", city="Bangalore", city_match=True,
        headline="Clinical Psychologist", fit_score=80, credentials=["RCI"],
        channels=[Channel(kind="email", value="asha@clinic.in", found_via="mailto", source_url="https://clinic.in/contact")], **kw)
    store.upsert_professional(rec, "r", db)
    return rec.pro_id


# ---- run manager ----------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_run_in_background_then_completed(db):
    mgr = ProfessionalRunManager(db_path=db, finder_factory=factory())
    info = mgr.start(city="Bangalore", specialties=["psychologist"])
    assert info["status"] == "running" and info["estimate"]["queries"] == 3 and info["run_id"].startswith("pro_")
    await mgr.wait(info["run_id"])
    st = mgr.status(info["run_id"])
    assert st["status"] == "completed" and st["finished"] and st["stats"]["kept"] >= 2
    assert st["counts_by_review_status"]["new"] == st["stats"]["kept"]


@pytest.mark.asyncio
async def test_only_one_run_at_a_time_because_runs_spend_credits(db):
    gate = asyncio.Event()

    class Slow:
        async def run(self, params, run_id=None, on_progress=None):
            await gate.wait()
            return {"stats": {"candidates": 1}, "notes": []}

    mgr = ProfessionalRunManager(db_path=db, finder_factory=lambda d: Slow())
    first = mgr.start(city="Pune")
    with pytest.raises(RunError, match="already in progress"):
        mgr.start(city="Mumbai")
    gate.set()
    await mgr.wait(first["run_id"])
    assert mgr.status(first["run_id"])["status"] == "completed"
    mgr.start(city="Mumbai")  # allowed again once the first has finished


def test_bad_input_is_a_clear_error_and_starts_nothing(db):
    mgr = ProfessionalRunManager(db_path=db, finder_factory=factory())
    for bad in ({"city": ""}, {"city": "Pune", "platforms": ["tiktok"]}, {"city": "Pune", "specialties": [""]}):
        with pytest.raises(RunError):
            mgr.start(**bad)


@pytest.mark.asyncio
async def test_crashes_and_total_search_failure_are_reported_as_failed(db):
    class Boom:
        async def run(self, *a, **k):
            raise RuntimeError("kaboom")

    mgr = ProfessionalRunManager(db_path=db, finder_factory=lambda d: Boom())
    info = mgr.start(city="Pune")
    await mgr.wait(info["run_id"])
    st = mgr.status(info["run_id"])
    assert st["status"] == "failed" and "kaboom" in st["error"]

    class NoCredits:
        async def run(self, *a, **k):
            return {"stats": {"candidates": 0, "search_fatal": 1}, "notes": ["search stopped: no credits"]}

    mgr2 = ProfessionalRunManager(db_path=db, finder_factory=lambda d: NoCredits())
    info2 = mgr2.start(city="Pune")
    await mgr2.wait(info2["run_id"])
    assert mgr2.status(info2["run_id"])["status"] == "failed" and "no credits" in mgr2.status(info2["run_id"])["error"]


def test_unknown_and_interrupted_runs(db):
    mgr = ProfessionalRunManager(db_path=db, finder_factory=factory())
    with pytest.raises(RunError):
        mgr.status("nope")
    store.create_run("pro_old", {"city": "Pune"}, db)           # a run left 'running' by a previous server process
    assert mgr.status("pro_old")["status"] == "interrupted"


# ---- export -------------------------------------------------------------------------------------------
def test_export_csv_and_json_are_approved_only_with_provenance(db, tmp_path):
    a, b = seed(db, "linkedin:asha-rao", "Asha Rao"), seed(db, "linkedin:ben-joseph", "Ben Joseph")
    store.set_review(a, "approved", "ok", db)
    out = str(tmp_path / "out")
    res = export_professionals(["approved"], "csv", out_dir=out, db_path=db)
    assert res["rows"] == 1
    raw = open(res["path"], "rb").read()
    assert raw.startswith(b"\xef\xbb\xbf")                                   # BOM: Excel opens non-Latin names correctly
    rows = list(csv.DictReader(open(res["path"], encoding="utf-8-sig")))
    assert list(rows[0].keys()) == FIELDS and rows[0]["name"] == "Asha Rao"
    assert rows[0]["best_channel_value"] == "asha@clinic.in" and rows[0]["best_channel_source"] == "https://clinic.in/contact"
    js = export_professionals(["approved"], "json", out_dir=out, db_path=db)
    data = json.load(open(js["path"], encoding="utf-8"))
    assert data[0]["channels"][0]["source_url"] == "https://clinic.in/contact"
    store.set_review(b, "do_not_contact", "asked", db)
    assert export_professionals(["do_not_contact"], "csv", out_dir=out, db_path=db)["rows"] == 0   # never exported
    with pytest.raises(ValueError):
        export_professionals(["approved"], "xlsx", out_dir=out, db_path=db)
    with pytest.raises(ValueError):
        export_professionals(["maybe"], "csv", out_dir=out, db_path=db)


# ---- REST ---------------------------------------------------------------------------------------------------
@pytest.fixture
def client(db):
    app.state.professionals_manager = ProfessionalRunManager(db_path=db, finder_factory=factory())
    with TestClient(app) as c:
        yield c
    del app.state.professionals_manager


def wait_for(client, run_id, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        st = client.get(f"/api/professionals/runs/{run_id}").json()
        if st["finished"]:
            return st
        time.sleep(0.05)
    raise AssertionError("run did not finish")


def test_rest_full_review_flow(client):
    started = client.post("/api/professionals/runs", json={"city": "Bangalore", "specialties": ["psychologist"], "pages": 1, "evil": "ignored"})
    assert started.status_code == 200 and started.json()["status"] == "running"
    run = wait_for(client, started.json()["run_id"])
    assert run["status"] == "completed"

    listing = client.get("/api/professionals").json()
    assert listing["total"] == run["stats"]["kept"] and listing["items"][0]["review_status"] == "new"
    assert listing["items"][0]["fit_score"] >= listing["items"][-1]["fit_score"]
    assert client.get("/api/professionals?has_channel=any&status=new").json()["total"] >= 1
    assert client.get("/api/professionals?status=bogus").status_code == 400

    # nothing is exportable before a human approves
    assert client.get("/api/professionals/export").status_code == 200
    first = listing["items"][0]
    assert first["pro_id"] and "channels" in first and all(c["source_url"] for c in first["channels"])

    assert client.post(f"/api/professionals/{first['pro_id']}/review", json={"decision": "approve", "note": "RCI checked", "licence_verified": True}).json()["review_status"] == "approved"
    detail = client.get(f"/api/professionals/{first['pro_id']}").json()
    assert detail["review_status"] == "approved" and detail["licence"]["verified"] is True
    exported = client.get("/api/professionals/export?status=approved")
    assert exported.status_code == 200 and "attachment" in exported.headers["content-disposition"]
    text = exported.content.decode("utf-8-sig")
    assert first["name"] in text and text.count("\n") == 2             # header + exactly the one approved person

    assert client.post(f"/api/professionals/{first['pro_id']}/review", json={"decision": "dnc"}).json()["review_status"] == "do_not_contact"
    assert first["name"] not in client.get("/api/professionals/export?status=approved").content.decode("utf-8-sig")
    assert client.get("/api/professionals/suppression").json()["items"]


def test_rest_errors(client):
    assert client.post("/api/professionals/runs", json={}).status_code == 400
    assert client.post("/api/professionals/runs", json={"city": "Pune", "platforms": ["tiktok"]}).status_code == 400
    assert client.get("/api/professionals/runs/nope").status_code == 404
    assert client.get("/api/professionals/doesnotexist").status_code == 404
    assert client.post("/api/professionals/doesnotexist/review", json={"decision": "approve"}).status_code == 404
    assert client.get("/api/professionals/export?format=xlsx").status_code == 400
    assert client.post("/api/professionals/suppress", json={"kind": "domain", "value": "gmail.com"}).status_code == 400
    assert client.post("/api/professionals/suppress", json={"kind": "email", "value": "x@y.in", "reason": "asked"}).status_code == 200


def test_rest_review_rejects_unknown_decisions(client, db):
    pid = seed(db)
    assert client.post(f"/api/professionals/{pid}/review", json={"decision": "maybe"}).status_code == 400
    assert client.post(f"/api/professionals/{pid}/review", json={}).status_code == 400


def test_export_route_is_not_swallowed_by_the_id_route(client, db):
    seed(db)
    assert client.get("/api/professionals/export").headers["content-type"].startswith("text/csv")
    assert client.get("/api/professionals/suppression").json() == {"items": []}


# ---- MCP tools ----------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_mcp_tools_end_to_end(monkeypatch):
    mgr = ProfessionalRunManager(finder_factory=factory())          # default database: the isolated per-test one
    monkeypatch.setattr(srv, "professional_runs", mgr)

    plan = await srv.find_professionals(city="Bangalore", dry_run=True)
    assert plan["status"] == "plan" and plan["estimate"]["queries"] == 9 and not mgr._tasks     # nothing started, nothing spent
    assert (await srv.find_professionals(city=""))["status"] == "error"

    started = await srv.find_professionals(city="Bangalore", specialties=["psychologist"])
    await mgr.wait(started["run_id"])
    assert srv.get_professionals_run(started["run_id"])["status"] == "completed"
    assert srv.get_professionals_run("nope")["status"] == "error"

    listing = srv.list_professionals(status="all", page_size=5)
    assert listing["total"] >= 2 and srv.list_professionals(status="bogus")["status"] == "error"
    pid = listing["items"][0]["pro_id"]
    assert srv.export_professionals()["rows"] == 0                                    # nothing approved yet
    assert srv.review_professional(pid, "approve", "checked")["review_status"] == "approved"
    assert srv.export_professionals()["rows"] == 1
    assert srv.review_professional("missing", "approve")["status"] == "error"
    assert srv.review_professional(pid, "perhaps")["status"] == "error"
    assert srv.export_professionals(format="xlsx")["status"] == "error"


def test_mcp_tool_registration():
    names = {"find_professionals", "get_professionals_run", "list_professionals", "review_professional", "export_professionals"}
    assert names <= {n for n in dir(srv)}


# ---- CLI --------------------------------------------------------------------------------------------------------------
def test_cli_plan_spends_nothing(capsys):
    assert cli.main(["plan", "--city", "Pune", "--specialties", "psychiatrist"]) == 0
    out = capsys.readouterr().out
    assert "site:linkedin.com/in psychiatrist Pune" in out and "at most" in out


def test_cli_review_loop(db, capsys):
    pid = seed(db)
    assert cli.main(["--db", db, "list", "--has-channel", "personal_email"]) == 0
    assert "Asha Rao" in capsys.readouterr().out
    assert cli.main(["--db", db, "show", pid[:6]]) == 0
    shown = capsys.readouterr().out
    assert "asha@clinic.in" in shown and "https://clinic.in/contact" in shown
    assert cli.main(["--db", db, "review", pid[:6], "approve", "--note", "checked"]) == 0
    assert cli.main(["--db", db, "licence", pid[:6], "verified"]) == 0
    assert cli.main(["--db", db, "export"]) == 0
    assert "1 row(s)" in capsys.readouterr().out
    assert cli.main(["--db", db, "review", pid[:6], "dnc"]) == 0
    assert "do-not-contact list" in capsys.readouterr().out
    assert cli.main(["--db", db, "export"]) == 0
    assert "0 row(s)" in capsys.readouterr().out


def test_cli_errors_are_readable(db, capsys):
    seed(db)
    assert cli.main(["--db", db, "show", "zzzzzz"]) == 2
    assert "no professional" in capsys.readouterr().out
    assert cli.main(["--db", db, "show", "ab"]) == 2
    with pytest.raises(SystemExit):
        cli.main(["--db", db, "suppress", "domain", "gmail.com"])
    with pytest.raises(SystemExit):
        cli.main(["plan", "--city", "Pune", "--platforms", "tiktok"])


# ---- optional bearer token ----------------------------------------------------------------------------------------------
def test_finder_routes_require_the_token_when_one_is_configured(client, db, monkeypatch):
    seed(db)
    assert client.get("/api/professionals").status_code == 200                      # no token configured: open, like the other local routes
    monkeypatch.setenv("PROFESSIONALS_API_TOKEN", "s3cret-token")
    for method, path in (("get", "/api/professionals"), ("get", "/api/professionals/export"), ("post", "/api/professionals/runs"),
                         ("get", "/api/professionals/suppression"), ("get", "/api/professionals/runs/x")):
        assert getattr(client, method)(path).status_code == 401, path
    assert client.get("/api/professionals", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/api/professionals", headers={"Authorization": "s3cret-token"}).status_code == 401      # scheme required
    ok = client.get("/api/professionals", headers={"Authorization": "Bearer s3cret-token"})
    assert ok.status_code == 200 and ok.json()["total"] == 1
    assert client.get("/api/collect/platforms").status_code == 200                  # other routes are unaffected
