"""Offline tests for planner, ranking, cleaning, harvester, storage and export."""

import csv
import datetime
import json
from typing import Dict, List

import pytest

from server.collection.cleaning import clean_comments
from server.collection.collectors.base import CollectorFatalError, PlatformCollector
from server.collection.export import export_job
from server.collection.harvester import harvest_platform
from server.collection.models import (
    STOP_BUDGET,
    STOP_ERROR,
    STOP_MAX_POSTS,
    STOP_NO_MORE,
    STOP_TARGET,
    CollectionLimits,
    CommentRow,
    PlatformProgress,
    PostCandidate,
    QueryPlan,
)
from server.collection.planner import plan_query, plan_with_rules
from server.collection.ranking import rank_candidates, recency_factor, relevance_score
from server.storage import comments as store


def _row(user="a", text="hello", platform="youtube", uid=None, url="https://x/1", likes=0):
    return CommentRow(platform=platform, username=user, user_id=uid, comment=text, likes=likes, post_url=url)


def _post(pid="p1", comments=100, title="Asian Games 2026 recap", author="creator", platform="youtube", published=None):
    return PostCandidate(
        platform=platform, post_id=pid, url=f"https://{platform}/{pid}", title=title,
        author_username=author, comment_count=comments, published_at=published,
    )


# ---------------- planner ----------------
def test_planner_rules():
    plan = plan_with_rules("Asian Games 2026")
    assert plan.keywords[0] == "Asian Games 2026"
    assert "Asian Games" in plan.keywords or "asian games" in [k.lower() for k in plan.keywords]
    assert "asiangames2026" in plan.hashtags and "asiangames" in plan.hashtags
    assert "olympics" in plan.subreddits
    assert plan.planner == "rules"


@pytest.mark.asyncio
async def test_planner_no_llm_without_key():
    class S:
        gemini_api_key = None
        gemini_model = "m"

    plan = await plan_query("iPhone 18 launch", settings=S())
    assert plan.planner == "rules"
    assert "technology" in plan.subreddits


@pytest.mark.asyncio
async def test_planner_merges_gemini(monkeypatch):
    import server.collection.planner as planner

    async def fake(topic, key, model, timeout):
        return {"keywords": ["Aichi Nagoya games"], "hashtags": ["#Aichi2026"], "subreddits": ["r/japan"]}

    monkeypatch.setattr(planner, "_gemini_suggestions", fake)

    class S:
        gemini_api_key = "k"
        gemini_model = "m"

    plan = await plan_query("Asian Games 2026", settings=S())
    assert plan.planner == "rules+gemini"
    assert "Aichi Nagoya games" in plan.keywords and "Aichi2026" in plan.hashtags and "japan" in plan.subreddits
    assert plan.keywords[0] == "Asian Games 2026"  # rules stay first


# ---------------- ranking ----------------
def test_relevance_and_recency():
    assert relevance_score("Asian Games 2026", "Asian Games 2026 medal tally") == 1.0
    assert relevance_score("Asian Games 2026", "asian games 2018") == pytest.approx(0.8)  # core words, other year
    assert relevance_score("Asian Games 2026", "Go team! #asiangames2026 #india") == 1.0  # squashed hashtag
    assert relevance_score("Asian Games 2026", "#asiangames final") == pytest.approx(0.8)
    assert relevance_score("Asian Games 2026", "cooking pasta") == 0.0
    now = datetime.datetime(2026, 10, 8, tzinfo=datetime.timezone.utc)
    assert recency_factor("2026-10-08T00:00:00Z", now) > recency_factor("2025-10-08T00:00:00Z", now)
    assert recency_factor(None, now) == 0.5


def test_rank_filters_offtopic_dedupes_and_orders():
    now = datetime.datetime(2026, 10, 8, tzinfo=datetime.timezone.utc)
    big = _post("big", 5000, published="2026-10-01T00:00:00Z")
    small = _post("small", 10, published="2026-10-01T00:00:00Z")
    old = _post("old", 5000, published="2020-01-01T00:00:00Z")
    off = _post("off", 99999, title="Pasta recipe")
    dup = _post("big", 5000, published="2026-10-01T00:00:00Z")
    ranked = rank_candidates("Asian Games 2026", [small, off, old, big, dup], now=now)
    assert [p.post_id for p in ranked] == ["big", "old", "small"] or [p.post_id for p in ranked][0] == "big"
    assert "off" not in [p.post_id for p in ranked]
    assert [p.post_id for p in ranked].count("big") == 1


# ---------------- cleaning ----------------
def test_clean_drops_empty_creator_and_duplicates():
    post = _post(author="@Creator", platform="youtube")
    post.author_id = "UC123"
    rows = [
        _row("fan1", "  Great   game  "),
        _row("FAN1", "great game"),          # duplicate (case/whitespace-insensitive)
        _row("creator", "thanks all"),        # creator by username
        _row("someone", "reply", uid="UC123"),  # creator by id
        _row("fan2", "   "),                  # empty
        _row("fan2", "Great game"),           # same text, other user -> kept
    ]
    out = clean_comments(rows, post)
    assert [(r.username, r.comment) for r in out] == [("fan1", "Great game"), ("fan2", "Great game")]


def test_clean_shared_seen_across_posts():
    seen = set()
    a = clean_comments([_row("u", "same")], None, seen)
    b = clean_comments([_row("u", "same", url="https://x/2")], None, seen)
    assert len(a) == 1 and b == []


# ---------------- harvester ----------------
class FakeCollector(PlatformCollector):
    platform = "youtube"

    def __init__(self, posts, per_post=100, fail_urls=(), batch_size=1, fatal=False, budget_after=None):
        self.posts = posts
        self.per_post = per_post
        self.fail_urls = set(fail_urls)
        self.batch_size = batch_size
        self.fatal = fatal
        self.calls: List[List[str]] = []
        self.budget_after = budget_after
        self.fetched_batches = 0

    async def discover(self, plan, limit):
        return list(self.posts)

    async def fetch_post_comments(self, post, max_comments):
        if self.fatal:
            raise CollectorFatalError("bad credentials")
        if post.url in self.fail_urls:
            raise RuntimeError("boom")
        return [_row(f"u{post.post_id}_{i}", f"comment {i} on {post.post_id}", url=post.url) for i in range(self.per_post)]

    async def fetch_comments(self, posts, per_post_limit):
        self.calls.append([p.post_id for p in posts])
        self.fetched_batches += 1
        return await super().fetch_comments(posts, per_post_limit)

    def budget_exhausted(self):
        return self.budget_after is not None and self.fetched_batches >= self.budget_after


PLAN = QueryPlan(topic="Asian Games 2026", keywords=["Asian Games 2026"])


@pytest.mark.asyncio
async def test_harvest_moves_to_next_post_until_target():
    posts = [_post(f"p{i}", 1000 - i) for i in range(10)]
    c = FakeCollector(posts, per_post=100)
    prog = PlatformProgress(platform="youtube")
    rows = await harvest_platform(c, PLAN, CollectionLimits(target_comments=250, max_posts=10), prog)
    assert len(rows) == 300 and prog.posts_processed == 3
    assert prog.stop_reason == STOP_TARGET and prog.status == "done"
    assert c.calls == [["p0"], ["p1"], ["p2"]]  # best-ranked first, one at a time


@pytest.mark.asyncio
async def test_harvest_batches_posts_when_collector_allows():
    posts = [_post(f"p{i}", 100) for i in range(10)]
    c = FakeCollector(posts, per_post=100, batch_size=5)
    prog = PlatformProgress(platform="youtube")
    rows = await harvest_platform(c, PLAN, CollectionLimits(target_comments=250, max_posts=10), prog)
    assert len(c.calls) == 1 and len(c.calls[0]) == 4  # 3 x 100 < 250*1.3 margin -> 4 posts, one run
    assert len(rows) == 400


@pytest.mark.asyncio
async def test_harvest_respects_max_posts():
    c = FakeCollector([_post(f"p{i}", 100) for i in range(10)], per_post=10)
    prog = PlatformProgress(platform="youtube")
    rows = await harvest_platform(c, PLAN, CollectionLimits(target_comments=500, max_posts=4), prog)
    assert prog.stop_reason == STOP_MAX_POSTS and prog.posts_processed == 4 and len(rows) == 40


@pytest.mark.asyncio
async def test_harvest_stops_when_candidates_run_out():
    c = FakeCollector([_post("p0", 50)], per_post=20)
    prog = PlatformProgress(platform="youtube")
    rows = await harvest_platform(c, PLAN, CollectionLimits(target_comments=500), prog)
    assert prog.stop_reason == STOP_NO_MORE and len(rows) == 20


@pytest.mark.asyncio
async def test_harvest_survives_failed_post():
    posts = [_post("bad", 900), _post("ok", 100)]
    c = FakeCollector(posts, per_post=60, fail_urls=["https://youtube/bad"])
    prog = PlatformProgress(platform="youtube")
    rows = await harvest_platform(c, PLAN, CollectionLimits(target_comments=50), prog)
    assert len(rows) == 60 and prog.stop_reason == STOP_TARGET and prog.status == "done"
    assert any("fetch failed" in n for n in prog.notes)


@pytest.mark.asyncio
async def test_harvest_fatal_error_marks_failed():
    c = FakeCollector([_post("p0", 100)], fatal=True)
    prog = PlatformProgress(platform="youtube")
    rows = await harvest_platform(c, PLAN, CollectionLimits(target_comments=50), prog)
    assert rows == [] and prog.status == "failed" and prog.stop_reason == STOP_ERROR
    assert "bad credentials" in prog.error


@pytest.mark.asyncio
async def test_harvest_budget_cap_stops():
    c = FakeCollector([_post(f"p{i}", 100) for i in range(10)], per_post=10, budget_after=2)
    prog = PlatformProgress(platform="youtube")
    await harvest_platform(c, PLAN, CollectionLimits(target_comments=500, max_posts=10), prog)
    assert prog.stop_reason == STOP_BUDGET and prog.posts_processed == 2


@pytest.mark.asyncio
async def test_harvest_unavailable_is_skipped():
    class Off(FakeCollector):
        def is_available(self):
            return False

    prog = PlatformProgress(platform="youtube")
    rows = await harvest_platform(Off([]), PLAN, CollectionLimits(), prog)
    assert rows == [] and prog.status == "skipped"


@pytest.mark.asyncio
async def test_harvest_streams_rows_to_sink():
    got: Dict[str, int] = {}
    c = FakeCollector([_post("p0", 100)], per_post=5)
    await harvest_platform(c, PLAN, CollectionLimits(target_comments=5), PlatformProgress(platform="youtube"),
                           on_rows=lambda url, rows: got.__setitem__(url, len(rows)))
    assert got == {"https://youtube/p0": 5}


# ---------------- storage + export ----------------
def test_store_dedupes_pages_and_exports(tmp_path):
    db = str(tmp_path / "t.db")
    store.create_job("job1", "topic", "2026-10-08T00:00:00Z", {"x": 1}, db_path=db)
    rows = [_row("a", "hi", likes=5), _row("A", "HI", likes=9), _row("b", "emoji 😀, \"quoted\"\nnewline", platform="reddit", likes=7)]
    assert store.save_comments("job1", rows, db_path=db) == 2
    assert store.save_comments("job1", rows, db_path=db) == 0  # idempotent
    assert store.count_by_platform("job1", db_path=db) == {"youtube": 1, "reddit": 1}
    assert store.top_comments("job1", 1, db_path=db)["reddit"][0]["username"] == "b"
    assert len(store.get_comments("job1", offset=1, limit=5, db_path=db)) == 1
    store.update_job("job1", "completed", {"youtube": {"comments_collected": 1}}, "2026-10-08T00:01:00Z", db_path=db)
    job = store.get_job("job1", db_path=db)
    assert job["status"] == "completed" and job["progress"]["youtube"]["comments_collected"] == 1

    res = export_job("job1", "csv", out_dir=str(tmp_path), db_path=db)
    with open(res["path"], newline="", encoding="utf-8-sig") as fh:
        data = list(csv.DictReader(fh))
    assert res["rows"] == 2 and data[1]["comment"].startswith("emoji 😀")
    assert list(data[0].keys()) == ["platform", "username", "user_id", "comment", "likes", "created_at", "post_url"]

    res = export_job("job1", "json", out_dir=str(tmp_path), db_path=db)
    assert len(json.load(open(res["path"], encoding="utf-8"))) == 2
    with pytest.raises(ValueError):
        export_job("job1", "xml", out_dir=str(tmp_path), db_path=db)
