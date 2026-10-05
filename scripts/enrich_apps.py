#!/usr/bin/env python3
"""Enrich charted app IDs with metadata from the iTunes lookup API.

    https://itunes.apple.com/lookup?id=123,456,789&country=us

The lookup endpoint accepts comma-separated IDs, so ~700 charted apps cost
about seven HTTP requests rather than seven hundred. Results are merged into
data/apps/metadata.jsonl, keyed by app_id, and refreshed only when stale -
so re-running is nearly free.

Fields kept are the ones the scoring actually consumes:
  description            -> mechanic extraction
  userRatingCount        -> review-velocity proxy for install volume
  releaseDate            -> mechanic freshness
  currentVersionReleaseDate / releaseNotes -> live-ops cadence
  averageUserRating      -> high rank + mediocre rating = unmet demand
  contentAdvisoryRating  -> age gating, relevant to a 21+ cash product
  screenshotUrls         -> kept for the vision pass listed as next-week work
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone

from common import APPS_DIR, DATA_DIR, fetch_json, latest_chart_file, read_jsonl, write_jsonl
import time

LOOKUP_URL = "https://itunes.apple.com/lookup?id={ids}&country={country}"
BATCH_SIZE = 100  # comma-separated IDs per request

KEEP_FIELDS = [
    "trackId",
    "trackName",
    "bundleId",
    "artistId",
    "artistName",
    "sellerName",
    "primaryGenreName",
    "genres",
    "description",
    "releaseNotes",
    "price",
    "formattedPrice",
    "averageUserRating",
    "userRatingCount",
    "averageUserRatingForCurrentVersion",
    "userRatingCountForCurrentVersion",
    "releaseDate",
    "currentVersionReleaseDate",
    "version",
    "contentAdvisoryRating",
    "minimumOsVersion",
    "fileSizeBytes",
    "languageCodesISO2A",
    "trackViewUrl",
    "artworkUrl512",
    "screenshotUrls",
]


def chunked(items: list, size: int):
    for start in range(0, len(items), size):
        yield items[start : start + size]


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch app metadata for charted apps.")
    parser.add_argument("--chart-file", default=None, help="defaults to the latest snapshot")
    parser.add_argument(
        "--countries",
        nargs="+",
        default=None,
        help="restrict to apps charting in these storefronts (default: all)",
    )
    parser.add_argument("--country", default="us", help="storefront used for the lookup itself")
    parser.add_argument("--max-age-days", type=int, default=7, help="refresh metadata older than this")
    parser.add_argument("--force", action="store_true", help="refetch everything")
    parser.add_argument("--limit", type=int, default=None, help="cap app count (for testing)")
    parser.add_argument("--sleep", type=float, default=1.0)
    args = parser.parse_args()

    chart_path = latest_chart_file() if args.chart_file is None else DATA_DIR / args.chart_file
    if chart_path is None or not chart_path.exists():
        print("No chart snapshot found. Run collect_charts.py first.", file=sys.stderr)
        return 1

    chart_rows = read_jsonl(chart_path)
    if args.countries:
        chart_rows = [r for r in chart_rows if r.get("country") in args.countries]

    app_ids = sorted({r["app_id"] for r in chart_rows})
    if args.limit:
        app_ids = app_ids[: args.limit]

    metadata_path = APPS_DIR / "metadata.jsonl"
    existing = {row["app_id"]: row for row in read_jsonl(metadata_path)}

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=args.max_age_days)

    def is_stale(app_id: str) -> bool:
        if args.force or app_id not in existing:
            return True
        fetched_at = existing[app_id].get("fetched_at")
        if not fetched_at:
            return True
        try:
            return datetime.fromisoformat(fetched_at) < cutoff
        except ValueError:
            return True

    targets = [app_id for app_id in app_ids if is_stale(app_id)]
    print(
        f"{len(app_ids)} charted apps in {chart_path.name}; "
        f"{len(targets)} need fetching, {len(app_ids) - len(targets)} cached.",
        file=sys.stderr,
    )

    fetched = 0
    missing: list[str] = []

    for batch_index, batch in enumerate(chunked(targets, BATCH_SIZE), start=1):
        url = LOOKUP_URL.format(ids=",".join(batch), country=args.country)
        try:
            payload = fetch_json(url)
        except Exception as exc:  # noqa: BLE001
            print(f"[FAIL] batch {batch_index}: {exc}", file=sys.stderr)
            continue

        returned = set()
        for result in payload.get("results", []):
            app_id = str(result.get("trackId"))
            returned.add(app_id)
            record = {key: result.get(key) for key in KEEP_FIELDS}
            record["app_id"] = app_id
            record["fetched_at"] = now.isoformat(timespec="seconds")
            existing[app_id] = record
            fetched += 1

        # An ID can chart in one storefront but be unavailable in the lookup
        # storefront. Recorded rather than silently dropped.
        missing.extend(app_id for app_id in batch if app_id not in returned)
        print(f"[ok ] batch {batch_index}: {len(returned)}/{len(batch)} returned", file=sys.stderr)
        time.sleep(args.sleep)

    write_jsonl(metadata_path, [existing[key] for key in sorted(existing)])

    print(
        f"\n{fetched} apps fetched, {len(missing)} not found in the {args.country} storefront.\n"
        f"{len(existing)} apps total -> {metadata_path}",
        file=sys.stderr,
    )
    if missing:
        print(f"Missing IDs (first 10): {missing[:10]}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
