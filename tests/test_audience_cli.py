"""scripts/audience.py end to end against a temp database. Offline."""

import importlib.util
import os

import pytest

from server.audience.models import AudienceComment
from server.audience.triage import triage
from server.storage import audience as store

_SPEC = importlib.util.spec_from_file_location("audience_cli", os.path.join(os.path.dirname(__file__), "..", "scripts", "audience.py"))
cli = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cli)


def comment(i, text, user=None, **kw):
    return AudienceComment(platform="instagram", account="mmtf_official", post_url="https://www.instagram.com/p/AAA/", username=user or f"user{i}",
                           comment=text, created_at="2026-10-01T10:00:00Z", comment_id=f"c{i}", triage=triage(text), **kw)


@pytest.fixture
def seeded():
    store.upsert_comments([comment(1, "I want to die", "worried_user"), comment(2, "can someone suggest a good counsellor?"),
                           comment(3, "I feel so anxious before every exam"), comment(4, "love this")])


def run(capsys, *argv):
    code = cli.main(list(argv))
    return code, capsys.readouterr().out


def test_accounts_command(monkeypatch, capsys):
    monkeypatch.delenv("MMTF_OWN_ACCOUNTS", raising=False)
    code, out = run(capsys, "accounts")
    assert code == 1 and "MMTF_OWN_ACCOUNTS" in out
    monkeypatch.setenv("MMTF_OWN_ACCOUNTS", "instagram:ours; reddit:u/ours_too")
    code, out = run(capsys, "accounts")
    assert code == 0 and "@ours" in out and "not supported yet" in out


def test_queue_shows_the_most_urgent_first_with_why_and_a_draft(seeded, capsys):
    code, out = run(capsys, "queue")
    assert code == 0
    assert out.index("[CRISIS") < out.index("[SEEKING_HELP") < out.index("[DISTRESS")
    assert "love this" not in out                              # ordinary comments are not in the care queue
    assert "why flagged" in out and "draft reply" in out and "Tele-MANAS" in out and "@worried_user" in out


def test_queue_can_hide_text_for_screen_sharing(seeded, capsys):
    _, out = run(capsys, "queue", "--no-text")
    assert "worried_user" not in out and "want to die" not in out and "Tele-MANAS" not in out and "CRISIS" in out


def test_queue_filters_and_empty_state(seeded, capsys):
    _, out = run(capsys, "queue", "--label", "distress")
    assert "[DISTRESS" in out and "[CRISIS" not in out
    _, out = run(capsys, "queue", "--status", "replied")
    assert "empty" in out


def test_handle_by_key_prefix_and_the_item_leaves_the_queue(seeded, capsys):
    key = store.list_queue()[0]["comment_key"]
    code, out = run(capsys, "handle", key[:8], "replied", "--by", "Asha", "--note", "public reply posted")
    assert code == 0 and "replied" in out
    _, out = run(capsys, "queue")
    assert "[CRISIS" not in out and "[SEEKING_HELP" in out
    _, out = run(capsys, "queue", "--status", "replied")
    assert "public reply posted" in out


def test_handle_rejects_short_or_unknown_keys(seeded, capsys):
    assert run(capsys, "handle", "abc", "replied")[0] == 2
    assert run(capsys, "handle", "ffffffff", "replied")[0] == 2


def test_stats_purge_and_forget(seeded, capsys):
    _, out = run(capsys, "stats")
    assert "4 comments" in out and "crisis" in out and "waiting for a person" in out
    _, out = run(capsys, "purge", "--days", "90")
    assert "deleted 0 handled care item(s)" in out and "kept" in out
    _, out = run(capsys, "forget", "--platform", "instagram", "--username", "@WORRIED_USER")
    assert "erased 1" in out
    assert [r["label"] for r in store.list_queue()] == ["seeking_help", "distress"]


def test_collect_command_reports_the_summary_and_refuses_unconfigured_accounts(monkeypatch, capsys):
    code, out = run(capsys, "collect", "--platform", "instagram")
    assert code == 2 and "MMTF_OWN_ACCOUNTS" in out

    seen = {}

    async def fake_collect(platform, **kw):
        seen.update(kw, platform=platform)
        return {"platform": platform, "account": "ours", "posts_found": 3, "posts_with_comments": 2, "comments": 40, "new": 30, "updated": 10,
                "new_care_items": 2, "by_label": {"positive": 30, "crisis": 1, "distress": 1}, "credits_used": 7.0, "stopped": "credit cap reached",
                "notes": ["skipped 1 collab post"]}

    monkeypatch.setattr(cli, "collect_own_comments", fake_collect)
    code, out = run(capsys, "collect", "--platform", "instagram", "--posts", "3", "--comments", "200", "--max-credits", "9", "--post-url", "u1")
    assert code == 0 and seen["max_posts"] == 3 and seen["max_comments_per_post"] == 200 and seen["max_credits"] == 9 and seen["post_urls"] == ["u1"]
    assert "3 post(s) confirmed as ours" in out and "2 new item(s) need a person" in out and "credit cap reached" in out and "skipped 1 collab post" in out


def test_export_command_writes_a_private_csv(seeded, capsys, tmp_path):
    code, out = run(capsys, "export", "--label", "crisis")
    assert code == 0 and "1 rows" in out and "personal data" in out
