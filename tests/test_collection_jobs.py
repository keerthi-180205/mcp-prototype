"""Tests for async collection jobs and the four MCP tools (all offline, fake collectors)."""

import asyncio
import csv
import json

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

import server.server as srv
from server.collection.collectors.base import CollectorFatalError, PlatformCollector
from server.collection.jobs import CollectionJobManager
from server.collection.models import CommentRow, PostCandidate


class Fake(PlatformCollector):
    def __init__(self, platform, per_post=40, fatal=None, available=True, delay=0.0):
        self.platform = platform
        self.per_post = per_post
        self.fatal = fatal
        self.available = available
        self.delay = delay

    def is_available(self):
        return self.available

    def unavailable_reason(self):
        return f"{self.platform} not configured"

    async def discover(self, plan, limit):
        if self.fatal:
            raise CollectorFatalError(self.fatal)
        return [
            PostCandidate(platform=self.platform, post_id=f"p{i}", url=f"https://{self.platform}.test/p{i}",
                          title="Asian Games 2026 post", author_username="creator", comment_count=100)
            for i in range(10)
        ]

    async def fetch_post_comments(self, post, max_comments):
        await asyncio.sleep(self.delay)
        rows = [CommentRow(platform=self.platform, username=f"{self.platform}_u{post.post_id}_{i}", user_id=str(i),
                           comment=f"{self.platform} comment {i} on {post.post_id}", likes=i, post_url=post.url)
                for i in range(self.per_post)]
        rows.append(CommentRow(platform=self.platform, username="creator", comment="my own comment", post_url=post.url))
        return rows


def _manager(tmp_path, **fakes):
    return CollectionJobManager(
        db_path=str(tmp_path / "jobs.db"),
        collector_factory=lambda p: fakes.get(p) or Fake(p),
        use_llm_planner=False,
    )


@pytest.mark.asyncio
async def test_job_runs_all_platforms_concurrently_and_stores_results(tmp_path):
    m = _manager(tmp_path)
    started = m.start("Asian Games 2026", platforms=["instagram", "youtube", "reddit", "x"], target_comments=100)
    assert started["job_id"].startswith("job_") and started["status"] == "running"
    await m.wait(started["job_id"])

    st = m.status(started["job_id"])
    assert st["status"] == "completed" and st["finished"] and st["total_comments"] >= 400
    for plat in ["instagram", "youtube", "reddit", "x"]:
        pr = st["platforms"][plat]
        assert pr["comments_collected"] >= 100 and pr["stop_reason"] == "target_reached" and pr["status"] == "done"
    assert "youtube: " in st["summary"]

    res = m.results(started["job_id"], page=1, page_size=10)
    assert res["total_comments"] >= 400 and len(res["rows"]) == 10 and res["total_pages"] > 1
    assert set(res["top_comments"]) == {"instagram", "youtube", "reddit", "x"} and not res["below_target"]
    assert all(r["username"] != "creator" for r in res["rows"])  # creator comments removed
    assert set(res["rows"][0]) == {"platform", "username", "user_id", "comment", "likes", "created_at", "post_url"}
    only = m.results(started["job_id"], platform="twitter", page_size=5)  # alias for x
    assert {r["platform"] for r in only["rows"]} == {"x"}


@pytest.mark.asyncio
async def test_status_is_available_while_running(tmp_path):
    m = _manager(tmp_path, youtube=Fake("youtube", delay=0.2))
    job = m.start("Asian Games 2026", platforms=["youtube"], target_comments=100)
    mid = m.status(job["job_id"])
    assert mid["status"] == "running" and not mid["finished"]
    await m.wait(job["job_id"])
    assert m.status(job["job_id"])["status"] == "completed"


@pytest.mark.asyncio
async def test_one_failing_platform_does_not_fail_the_job(tmp_path):
    m = _manager(tmp_path, x=Fake("x", fatal="X rejected TWITTER_AUTH_TOKEN"), instagram=Fake("instagram", available=False))
    job = m.start("Asian Games 2026", platforms=["youtube", "x", "instagram"], target_comments=50)
    await m.wait(job["job_id"])
    st = m.status(job["job_id"])
    assert st["status"] == "partial"
    assert st["platforms"]["x"]["status"] == "failed" and "TWITTER_AUTH_TOKEN" in st["platforms"]["x"]["error"]
    assert st["platforms"]["instagram"]["status"] == "skipped"
    res = m.results(job["job_id"])
    assert set(res["below_target"]) == {"x", "instagram"} and res["counts_per_platform"].keys() == {"youtube"}


@pytest.mark.asyncio
async def test_all_platforms_failing_marks_job_failed(tmp_path):
    m = _manager(tmp_path, x=Fake("x", fatal="bad"))
    job = m.start("topic", platforms=["x"], target_comments=10)
    await m.wait(job["job_id"])
    assert m.status(job["job_id"])["status"] == "failed"


@pytest.mark.asyncio
async def test_validation_and_unknown_job(tmp_path):
    from server.collection.jobs import JobError

    m = _manager(tmp_path)
    with pytest.raises(JobError):
        m.start("   ")
    with pytest.raises(JobError):
        m.start("topic", platforms=["myspace"])
    with pytest.raises(JobError):
        m.status("job_missing")
    j = m.start("topic", platforms=["youtube"], target_comments=10**9, max_posts=10**6, max_minutes=10**6)
    cfg = m._jobs[j["job_id"]].limits
    assert cfg.target_comments == 5000 and cfg.max_posts == 100 and cfg.max_seconds == 1800
    await m.wait(j["job_id"])


@pytest.mark.asyncio
async def test_job_survives_manager_restart_via_sqlite(tmp_path):
    m = _manager(tmp_path)
    job = m.start("Asian Games 2026", platforms=["youtube"], target_comments=50)
    await m.wait(job["job_id"])
    fresh = _manager(tmp_path)  # new process: no in-memory state
    st = fresh.status(job["job_id"])
    assert st["status"] == "completed" and st["total_comments"] >= 50
    assert fresh.results(job["job_id"])["total_comments"] == st["total_comments"]


@pytest.mark.asyncio
async def test_mcp_tools_end_to_end_with_export(tmp_path, monkeypatch):
    m = _manager(tmp_path)
    monkeypatch.setattr(srv, "collection_jobs", m)
    monkeypatch.setattr("server.collection.export.DEFAULT_EXPORT_DIR", str(tmp_path / "exports"))

    started = await srv.start_comment_collection("Asian Games 2026", ["youtube", "reddit"], target_comments=60)
    assert "job_id" in started
    await m.wait(started["job_id"])
    st = srv.get_collection_status(started["job_id"])
    assert st["status"] == "completed"
    res = srv.get_collection_results(started["job_id"], page=2, page_size=20)
    assert res["page"] == 2 and len(res["rows"]) == 20

    out = srv.export_collection_results(started["job_id"], "csv")
    assert out["status"] == "ok" and out["rows"] == res["total_comments"]
    with open(out["path"], newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == out["rows"] and rows[0]["platform"] in ("youtube", "reddit")
    js = srv.export_collection_results(started["job_id"], "json")
    assert len(json.load(open(js["path"], encoding="utf-8"))) == js["rows"]

    assert srv.export_collection_results(started["job_id"], "xml")["status"] == "error"
    assert srv.get_collection_status("job_nope")["status"] == "error"
    assert (await srv.start_comment_collection("", None))["status"] == "error"


@pytest.mark.asyncio
async def test_new_tools_are_listed_over_mcp_stdio():
    params = StdioServerParameters(command="python3", args=["-m", "server.server"], env=None)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            names = {t.name for t in (await session.list_tools()).tools}
            assert {"start_comment_collection", "get_collection_status",
                    "get_collection_results", "export_collection_results"} <= names
            res = await session.call_tool("get_collection_status", {"job_id": "job_does_not_exist"})
            assert not res.is_error and "unknown job_id" in res.content[0].text
