"""Remove rows that earlier versions of the app invented or mislabelled as comments.

Dry run by default. With --apply it first copies the database to data/backups/ and then deletes.

A row is removed when it matches any of:
  placeholder_author  username was generated ("<topic>_influencer", "linkedin_member", ...)
  non_post_url        post_url is a Google News link or a search/tag page, not a real post
  fixture             post_url is an example.com test fixture
  legacy_caption      comes from the old /api/chat path on Instagram / LinkedIn / X, where post
                      captions and news headlines were stored as if they were comments
Platform labels such as "twitter / x" are normalised to "x" for the rows that stay.
"""

import argparse
import datetime
import os
import shutil
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "data", "social_intelligence.db")

RULES = {
    "placeholder_author": (
        "(username LIKE '%\\_creator' ESCAPE '\\' OR username LIKE '%\\_influencer' ESCAPE '\\' "
        "OR username LIKE '%\\_watcher' ESCAPE '\\' OR username LIKE '%\\_trends' ESCAPE '\\' "
        "OR username LIKE '%\\_pulse' ESCAPE '\\' OR username LIKE '%\\_community' ESCAPE '\\' "
        "OR lower(username) IN ('linkedin_member', 'linkedin_professional', '@linkedin professional', "
        "'reddit_user', 'u/reddit_user', 'user', 'instagram_creator') "
        "OR username LIKE 'Industry Lead on %')"
    ),
    "non_post_url": (
        "(post_url LIKE '%news.google.%' OR post_url LIKE '%/explore/tags/%' "
        "OR post_url LIKE '%linkedin.com/search/%' OR post_url LIKE '%x.com/search%' "
        "OR post_url LIKE '%reddit.com/search%')"
    ),
    "fixture": "post_url LIKE '%.example.com%'",
    "legacy_caption": (
        "(job_id LIKE 'job\\_chat\\_%' ESCAPE '\\' AND platform IN ('instagram', 'linkedin', 'twitter / x', 'x'))"
    ),
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=DB)
    ap.add_argument("--apply", action="store_true", help="delete (after making a backup)")
    args = ap.parse_args()

    if not os.path.exists(args.db):
        print(f"no database at {args.db}")
        return 1
    conn = sqlite3.connect(args.db)
    total = conn.execute("SELECT COUNT(*) FROM collected_comments").fetchone()[0]
    any_rule = " OR ".join(RULES.values())

    print(f"{total} rows in collected_comments")
    for name, cond in RULES.items():
        n = conn.execute(f"SELECT COUNT(*) FROM collected_comments WHERE {cond}").fetchone()[0]
        print(f"  {name:20} {n:6} rows")
    doomed = conn.execute(f"SELECT COUNT(*) FROM collected_comments WHERE {any_rule}").fetchone()[0]
    print(f"  {'TOTAL (distinct)':20} {doomed:6} rows would be removed, {total - doomed} kept")
    for plat, n in conn.execute(
        f"SELECT platform, COUNT(*) FROM collected_comments WHERE NOT ({any_rule}) GROUP BY platform"
    ):
        print(f"    kept {plat}: {n}")

    if not args.apply:
        print("\ndry run - nothing changed. Re-run with --apply to delete.")
        return 0

    backup_dir = os.path.join(os.path.dirname(args.db), "backups")
    os.makedirs(backup_dir, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = os.path.join(backup_dir, f"social_intelligence_{stamp}.db")
    shutil.copy2(args.db, backup)
    print(f"\nbackup written: {backup}")

    with conn:
        conn.execute(f"DELETE FROM collected_comments WHERE {any_rule}")
        conn.execute("UPDATE collected_comments SET platform='x' WHERE platform='twitter / x'")
    left = conn.execute("SELECT COUNT(*) FROM collected_comments").fetchone()[0]
    print(f"deleted {total - left} rows, {left} remain")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
