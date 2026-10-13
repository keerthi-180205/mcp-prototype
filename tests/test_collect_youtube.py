"""Offline tests for the YouTube (yt-dlp) collector with mocked CLI output."""

import json

import pytest

import server.collection.collectors.youtube as yt
from server.collection.collectors.youtube import YouTubeCollector
from server.collection.harvester import harvest_platform
from server.collection.models import CollectionLimits, PlatformProgress, QueryPlan

PLAN = QueryPlan(topic="Asian Games 2026", keywords=["Asian Games 2026", "asian games"])


def _search_line(vid, title, views=1000):
    return json.dumps({"id": vid, "title": title, "channel": "Chan", "channel_id": "UCchan", "view_count": views})


def _meta(vid, title, comments=50, uploader_id="@chan"):
    return json.dumps({
        "id": vid, "title": title, "description": "about the games", "channel": "Chan", "channel_id": "UCchan",
        "uploader_id": uploader_id, "comment_count": comments, "upload_date": "20261005", "timestamp": 1791166466,
        "view_count": 5000, "like_count": 10,
    })


def _comments_json(vid, n, with_uploader=True):
    comments = [
        {"id": f"c{i}", "parent": "root" if i % 2 == 0 else "c0", "text": f"comment {i} {vid}", "like_count": i,
         "author_id": f"UCfan{i}", "author": f"@fan{i}", "timestamp": 1791244800, "author_is_uploader": False}
        for i in range(n)
    ]
    if with_uploader:
        comments.append({"id": "up", "parent": "root", "text": "pinned by creator", "like_count": 99,
                         "author_id": "UCchan", "author": "@chan", "timestamp": 1791244800, "author_is_uploader": True})
    comments.append({"id": "empty", "parent": "root", "text": "", "like_count": 0, "author_id": "UCz", "author": "@z"})
    return json.dumps({"id": vid, "channel_id": "UCchan", "comments": comments})


@pytest.fixture
def fake_cli(monkeypatch):
    calls = []

    async def run(args, timeout=60.0, env=None, allow_nonzero=False):
        calls.append(args)
        joined = " ".join(args)
        if "--flat-playlist" in args:
            q = args[1]
            if "asian games 2026" in q.lower():
                return 0, "\n".join([_search_line("vidAAAAAAAA", "Asian Games 2026 recap", 9000),
                                     _search_line("vidBBBBBBBB", "Asian Games 2026 final", 5000),
                                     _search_line("vidCCCCCCCC", "Cooking pasta", 99999999)]), ""
            return 0, _search_line("vidAAAAAAAA", "Asian Games 2026 recap", 9000), ""
        if "--write-comments" in args:
            vid = args[-1][-11:]
            return 0, _comments_json(vid, 30), ""
        vid = args[-1][-11:]
        return 0, _meta(vid, f"Asian Games 2026 {vid}", comments=40 if vid.startswith("vidA") else 20), ""

    monkeypatch.setattr(yt, "run_cli", run)
    c = YouTubeCollector(binary="/fake/yt-dlp")
    return c, calls


@pytest.mark.asyncio
async def test_discover_enriches_and_dedupes(fake_cli):
    c, calls = fake_cli
    found = await c.discover(PLAN, 20)
    ids = [p.post_id for p in found]
    assert len(ids) == len(set(ids)) and "vidAAAAAAAA" in ids
    a = next(p for p in found if p.post_id == "vidAAAAAAAA")
    assert a.comment_count == 40 and a.published_at and a.author_id == "UCchan" and a.author_username == "@chan"
    assert a.url == "https://www.youtube.com/watch?v=vidAAAAAAAA"


@pytest.mark.asyncio
async def test_comment_args_and_row_mapping(fake_cli):
    c, calls = fake_cli
    post = (await c.discover(PLAN, 20))[0]
    rows = await c.fetch_post_comments(post, 100)
    cmd = next(a for a in calls if "--write-comments" in a)
    spec = cmd[cmd.index("--extractor-args") + 1]
    assert "max_comments=100,100,100,10" in spec and "player_client=mweb" in spec
    assert "--ignore-no-formats-error" in cmd
    # uploader comment is dropped in the collector; the empty one is dropped later by cleaning
    assert all(r.user_id != "UCchan" for r in rows)
    r = next(r for r in rows if r.comment.startswith("comment 3 "))
    assert (r.platform, r.username, r.user_id, r.likes, r.post_url) == (
        "youtube", "fan3", "UCfan3", 3, post.url)
    assert r.created_at.startswith("2026-")


@pytest.mark.asyncio
async def test_end_to_end_harvest_removes_creator_and_empty(fake_cli):
    c, _ = fake_cli
    prog = PlatformProgress(platform="youtube")
    rows = await harvest_platform(c, PLAN, CollectionLimits(target_comments=50, max_posts=5), prog)
    assert prog.stop_reason == "target_reached"
    assert len(rows) >= 50 and all(r.comment and r.user_id != "UCchan" for r in rows)
    assert "Cooking" not in " ".join(p for p in prog.notes)


@pytest.mark.asyncio
async def test_unavailable_without_binary(monkeypatch):
    monkeypatch.setattr(yt, "find_binary", lambda name: None)
    c = YouTubeCollector()
    assert not c.is_available()
    prog = PlatformProgress(platform="youtube")
    await harvest_platform(c, PLAN, CollectionLimits(), prog)
    assert prog.status == "skipped" and "yt-dlp" in prog.error
