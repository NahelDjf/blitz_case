#!/usr/bin/env python3
"""Pull App Store customer reviews for the apps inside the analysis scope.

    https://itunes.apple.com/us/rss/customerreviews/page=N/id={app_id}/sortby=mostrecent/json

Reviews are the only free source of player *voice*, which is where the
differentiating signals live: competitive intent ("I wish I could play
against people"), fairness complaints ("bots", "rigged"), and ad fatigue.

Scope is US top_free + top_grossing by default (the analysis scope from
DECISIONS.md) which is roughly 150 unique apps rather than the
~700 charting worldwide. At one request per page per app, that difference is
the difference between a five-minute run and an hour of hammering Apple.

One file per app (data/reviews/{app_id}.jsonl) so the cache is trivially
resumable: kill the run, restart it, and it picks up where it stopped.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone

from common import (
    DATA_DIR,
    REVIEWS_DIR,
    fetch_json,
    label,
    latest_chart_file,
    read_jsonl,
    write_jsonl,
)

REVIEWS_URL = (
    "https://itunes.apple.com/{country}/rss/customerreviews"
    "/page={page}/id={app_id}/sortby={sort}/json"
)

PAGE_SIZE = 50  # Apple serves 50 reviews per page


def parse_reviews(payload: dict, app_id: str, country: str, page: int) -> list[dict]:
    entries = payload.get("feed", {}).get("entry", [])
    if isinstance(entries, dict):
        entries = [entries]

    rows = []
    for entry in entries:
        # The first entry of page 1 describes the app itself, not a review.
        # It has no rating, which is the reliable way to spot and skip it.
        rating = label(entry.get("im:rating"))
        if rating is None:
            continue
        author = entry.get("author", {}) or {}
        rows.append(
            {
                "app_id": app_id,
                "country": country,
                "page": page,
                "review_id": label(entry.get("id")),
                "author": label(author.get("name")),
                "rating": int(rating),
                "title": label(entry.get("title")),
                "content": label(entry.get("content")),
                "app_version": label(entry.get("im:version")),
                "vote_sum": label(entry.get("im:voteSum")),
                "vote_count": label(entry.get("im:voteCount")),
                "updated": label(entry.get("updated")),
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch customer reviews for in-scope apps.")
    parser.add_argument("--chart-file", default=None, help="defaults to the latest snapshot")
    parser.add_argument("--country", default="us")
    parser.add_argument("--charts", nargs="+", default=["top_free", "top_grossing"])
    parser.add_argument("--pages", type=int, default=5, help="50 reviews per page, Apple caps at 10")
    parser.add_argument("--sort", default="mostrecent", choices=["mostrecent", "mosthelpful"])
    parser.add_argument("--sleep", type=float, default=1.2, help="pause between requests")
    parser.add_argument("--force", action="store_true", help="refetch apps already cached")
    parser.add_argument("--limit", type=int, default=None, help="cap app count (for testing)")
    args = parser.parse_args()

    chart_path = latest_chart_file() if args.chart_file is None else DATA_DIR / args.chart_file
    if chart_path is None or not chart_path.exists():
        print("No chart snapshot found. Run collect_charts.py first.", file=sys.stderr)
        return 1

    rows = read_jsonl(chart_path)
    in_scope = [r for r in rows if r.get("country") == args.country and r.get("chart") in args.charts]
    app_ids = sorted({r["app_id"] for r in in_scope})
    if args.limit:
        app_ids = app_ids[: args.limit]

    REVIEWS_DIR.mkdir(parents=True, exist_ok=True)
    todo = [a for a in app_ids if args.force or not (REVIEWS_DIR / f"{a}.jsonl").exists()]

    print(
        f"{len(app_ids)} apps in scope ({args.country}, {'+'.join(args.charts)}); "
        f"{len(todo)} to fetch, {len(app_ids) - len(todo)} cached.\n"
        f"Estimated time: ~{len(todo) * args.pages * args.sleep / 60:.0f} min",
        file=sys.stderr,
    )

    total_reviews = 0
    failed: list[str] = []
    empty: list[str] = []

    def fetch_page(app_id: str, page: int, sort: str) -> list[dict]:
        url = REVIEWS_URL.format(
            country=args.country, page=page, app_id=app_id, sort=sort
        )
        return parse_reviews(fetch_json(url), app_id, args.country, page)

    for index, app_id in enumerate(todo, start=1):
        collected: list[dict] = []
        for page in range(1, args.pages + 1):
            try:
                page_rows = fetch_page(app_id, page, args.sort)
            except Exception as exc:  # noqa: BLE001
                if page == 1:
                    failed.append(app_id)
                    print(f"[FAIL] {app_id} page {page}: {exc}", file=sys.stderr)
                break

            # An empty page is ambiguous: the feed may genuinely be exhausted,
            # or Apple may have throttled us and returned a valid-but-empty
            # response. Both look identical, and caching the empty one freezes
            # a permanent hole in the dataset.
            #
            # The tell: an exhausting feed returns a PARTIAL page first. So an
            # empty page is only suspicious when the previous page was full -
            # which is exactly the case where the cached total lands on an
            # exact multiple of 50. 
            previous_was_full = collected and len(collected) % PAGE_SIZE == 0
            if not page_rows and (page == 1 or previous_was_full):
                alternate = "mosthelpful" if args.sort == "mostrecent" else "mostrecent"
                for retry_sort in (args.sort, alternate):
                    time.sleep(5.0)
                    try:
                        page_rows = fetch_page(app_id, page, retry_sort)
                    except Exception:  # noqa: BLE001
                        page_rows = []
                    if page_rows:
                        print(
                            f"       {app_id}: page {page} recovered via {retry_sort}",
                            file=sys.stderr,
                        )
                        break

            if not page_rows:
                break  # feed exhausted
            collected.extend(page_rows)
            if len(page_rows) < PAGE_SIZE:
                break  # partial page: genuinely the end, no need to ask again
            time.sleep(args.sleep)

        if collected:
            write_jsonl(REVIEWS_DIR / f"{app_id}.jsonl", collected)
            total_reviews += len(collected)
        elif app_id not in failed:
            # No file is written. Caching an empty result would freeze a
            # transient failure into the dataset forever; leaving the file
            # absent means the next run simply retries this app.
            empty.append(app_id)

        print(f"[{index}/{len(todo)}] {app_id}: {len(collected)} reviews", file=sys.stderr)

    cached_files = list(REVIEWS_DIR.glob("*.jsonl"))
    print(
        f"\n{total_reviews} reviews fetched this run across {len(todo) - len(failed)} apps.\n"
        f"{len(cached_files)} apps cached in total -> {REVIEWS_DIR}\n"
        f"captured_at {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        file=sys.stderr,
    )
    if failed:
        print(f"Failed (network): {failed}", file=sys.stderr)
    if empty:
        print(
            f"Empty after retries, no file cached, will retry next run: {empty}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
