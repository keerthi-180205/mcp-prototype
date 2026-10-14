"""Care queue over REST (default-deny, bearer token) and the MCP tools (redacted for the assistant). Offline."""

import pytest
from starlette.testclient import TestClient

import server.server as srv
from server.audience.models import AudienceComment
from server.audience.triage import triage
from server.storage import audience as store
from web.server import app

TOKEN = "care-token-for-tests"


def comment(i, text, user=None, **kw):
    return AudienceComment(platform="instagram", account="mmtf_official", post_url="https://www.instagram.com/p/AAA/", username=user or f"user{i}",
                           comment=text, created_at="2026-10-01T10:00:00Z", comment_id=f"c{i}", triage=triage(text), **kw)


@pytest.fixture
def seeded():
    store.upsert_comments([comment(1, "I want to die", "worried_user"), comment(2, "please help me"), comment(3, "love this")])


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth(monkeypatch):
    monkeypatch.setenv("AUDIENCE_API_TOKEN", TOKEN)
    return {"Authorization": f"Bearer {TOKEN}"}


# ---- default deny ------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("method,path", [("get", "/api/care/queue"), ("get", "/api/care/stats"), ("post", "/api/care/abcdef123456/handle")])
def test_routes_are_disabled_until_a_token_is_configured(client, seeded, method, path):
    r = getattr(client, method)(path)
    assert r.status_code == 403 and "AUDIENCE_API_TOKEN" in r.json()["message"]
    assert "worried_user" not in r.text and "want to die" not in r.text


def test_wrong_or_missing_token_is_rejected_even_when_configured(client, seeded, auth):
    assert client.get("/api/care/queue").status_code == 401
    assert client.get("/api/care/queue", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get("/api/care/queue", headers={"Authorization": TOKEN}).status_code == 401


def test_the_finder_token_does_not_open_the_care_queue(client, seeded, monkeypatch):
    monkeypatch.setenv("PROFESSIONALS_API_TOKEN", "finder-token")
    assert client.get("/api/care/queue", headers={"Authorization": "Bearer finder-token"}).status_code == 403


# ---- the queue ---------------------------------------------------------------------------------------------------------
def test_queue_returns_most_urgent_first_with_drafts(client, seeded, auth):
    body = client.get("/api/care/queue", headers=auth).json()
    assert body["count"] == 2 and [i["label"] for i in body["items"]] == ["crisis", "seeking_help"]
    first = body["items"][0]
    assert first["comment"] == "I want to die" and first["username"] == "worried_user" and "14416" in first["draft"] and first["handling"]


def test_queue_filters_and_validates(client, seeded, auth):
    assert client.get("/api/care/queue?label=seeking_help", headers=auth).json()["count"] == 1
    assert client.get("/api/care/queue?label=positive", headers=auth).json()["count"] == 0      # not a care label
    assert client.get("/api/care/queue?limit=abc", headers=auth).status_code == 400
    assert client.get("/api/care/queue?status=replied", headers=auth).json()["count"] == 0


def test_handling_an_item_records_who_and_removes_it_from_the_new_queue(client, seeded, auth):
    key = client.get("/api/care/queue", headers=auth).json()["items"][0]["key"]
    r = client.post(f"/api/care/{key[:10]}/handle", headers=auth, json={"status": "replied", "handled_by": "Asha", "note": "public reply posted"})
    assert r.status_code == 200 and r.json()["item"]["status"] == "replied"
    assert "worried_user" not in r.text                                             # the response is redacted
    assert [i["label"] for i in client.get("/api/care/queue", headers=auth).json()["items"]] == ["seeking_help"]
    done = client.get("/api/care/queue?status=replied", headers=auth).json()["items"][0]
    assert done["handled_by"] == "Asha" and done["handler_note"] == "public reply posted"


def test_handle_errors(client, seeded, auth):
    assert client.post("/api/care/abcdef123456/handle", headers=auth, json={"status": "replied"}).status_code == 400    # unknown key
    key = client.get("/api/care/queue", headers=auth).json()["items"][0]["key"]
    assert client.post(f"/api/care/{key}/handle", headers=auth, json={"status": "archived"}).status_code == 400
    assert client.post(f"/api/care/{key}/handle", headers=auth, content=b"[1]").status_code == 400
    assert client.post("/api/care/abc/handle", headers=auth, json={"status": "replied"}).status_code == 400            # too short


def test_stats(client, seeded, auth):
    body = client.get("/api/care/stats", headers=auth).json()
    assert body["comments"] == 3 and body["waiting_for_a_reply"] == {"crisis": 1, "seeking_help": 1}


# ---- MCP tools ---------------------------------------------------------------------------------------------------------
def test_assistant_tools_never_expose_usernames_or_comment_text(seeded):
    out = srv.list_care_queue()
    blob = repr(out)
    assert out["status"] == "ok" and out["stats"]["comments"] == 3 and [i["label"] for i in out["items"]] == ["crisis", "seeking_help"]
    assert "worried_user" not in blob and "want to die" not in blob and "please help me" not in blob and "14416" not in blob
    assert srv.list_care_queue(label="distress")["items"] == []


def test_assistant_can_record_that_a_person_handled_an_item(seeded):
    key = srv.list_care_queue()["items"][0]["key"]
    out = srv.update_care_item(key[:8], "replied", "Asha", "done")
    assert out["status"] == "ok" and out["item"]["status"] == "replied" and "comment" not in out["item"]
    assert srv.update_care_item("zzzzzzzz", "replied")["status"] == "error"
    assert srv.update_care_item(key, "archived")["status"] == "error"


@pytest.mark.asyncio
async def test_collect_tool_reports_guard_errors_as_messages(monkeypatch):
    out = await srv.collect_own_comments(platform="instagram")
    assert out["status"] == "error" and "MMTF_OWN_ACCOUNTS" in out["message"]
    monkeypatch.setenv("MMTF_OWN_ACCOUNTS", "instagram:ours")
    out = await srv.collect_own_comments(platform="reddit")
    assert out["status"] == "error" and "cannot be ownership-checked" in out["message"]
    out = await srv.collect_own_comments(platform="instagram", account="someone_else")
    assert out["status"] == "error" and "not one of MMTF's" in out["message"]
