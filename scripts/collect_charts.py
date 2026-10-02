#!/usr/bin/env python3
"""Snapshot Apple App Store game charts into a dated JSONL file.

Two sources, in priority order:

  1. LEGACY  itunes.apple.com/{cc}/rss/{chart}/limit=200/genre=6014/json
     Supports genre filtering (6014 = Games) and top-grossing. Not an
     officially supported Apple product -> treated as best-effort.

  2. V2      rss.marketingtools.apple.com/api/v2/{cc}/apps/{chart}/200/apps.json
     Current Apple feed, but it dropped genre filtering, so results are
     overall charts and must be filtered to games downstream (via the
     iTunes lookup API). Rank is the array position; there is no rank field.

Output: data/charts/<YYYY-MM-DD>.jsonl, one record per (source, country,
chart, rank). Re-running on the same day overwrites that day's file, so the
job is idempotent.

Stdlib only, on purpose: no dependency resolution in CI means fewer ways for
the daily job to break silently.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone

from common import CHARTS_DIR, REPO_ROOT, RUNS_LOG, fetch_json, label

GAMES_GENRE_ID = 6014

DEFAULT_COUNTRIES = ["us", "gb", "de", "fr", "jp", "br"]

# canonical chart name -> (legacy path segment, v2 path segment or None)
CHARTS = {
    "top_free": ("topfreeapplications", "top-free"),
    "top_paid": ("toppaidapplications", "top-paid"),
    # Grossing is the chart that proves payers exist, and as far as I can tell
    # only the legacy feed publishes it. The v2 attempt is left in and allowed
    # to fail so the manifest records whether that is still true.
    "top_grossing": ("topgrossingapplications", "top-grossing"),
}

def legacy_url(country: str, chart_segment: str, limit: int) -> str:
    return (
        f"https://itunes.apple.com/{country}/rss/{chart_segment}"
        f"/limit={limit}/genre={GAMES_GENRE_ID}/json"
    )


def v2_url(country: str, chart_segment: str, limit: int) -> str:
    return (
        f"https://rss.marketingtools.apple.com/api/v2/{country}"
        f"/apps/{chart_segment}/{limit}/apps.json"
    )


# --------------------------------------------------------------------------
# normalisation - both feeds collapse into one record shape
# --------------------------------------------------------------------------

def parse_legacy(payload: dict) -> list[dict]:
    entries = payload.get("feed", {}).get("entry", [])
    if isinstance(entries, dict):  # limit=1 returns an object, not a list
        entries = [entries]

    rows = []
    for position, entry in enumerate(entries, start=1):
        identifier = entry.get("id", {})
        app_id = identifier.get("attributes", {}).get("im:id")
        if not app_id:
            continue
        artist = entry.get("im:artist", {})
        category = entry.get("category", {}).get("attributes", {})
        rows.append(
            {
                "rank": position,
                "app_id": str(app_id),
                "app_name": label(entry.get("im:name")),
                "artist_name": label(artist),
                "artist_id": (artist.get("attributes", {}) or {}).get("href"),
                "app_url": label(identifier),
                "release_date": label(entry.get("im:releaseDate")),
                "genre_id": str(category.get("im:id")) if category.get("im:id") else None,
                "genre_name": category.get("term"),
            }
        )
    return rows


def parse_v2(payload: dict) -> list[dict]:
    results = payload.get("feed", {}).get("results", [])
    rows = []
    for position, item in enumerate(results, start=1):  # rank == array position
        app_id = item.get("id")
        if not app_id:
            continue
        genres = item.get("genres") or []
        primary = genres[0] if genres else {}
        rows.append(
            {
                "rank": position,
                "app_id": str(app_id),
                "app_name": item.get("name"),
                "artist_name": item.get("artistName"),
                "artist_id": item.get("artistId"),
                "app_url": item.get("url"),
                "release_date": item.get("releaseDate"),
                "genre_id": str(primary.get("genreId")) if primary.get("genreId") else None,
                "genre_name": primary.get("name"),
                # v2 cannot be genre-scoped at request time; keep every genre so
                # the games filter can run downstream without a second lookup.
                "all_genres": [g.get("name") for g in genres],
            }
        )
    return rows


# --------------------------------------------------------------------------
# collection
# --------------------------------------------------------------------------

def collect_one(country: str, chart: str, limit: int, allow_fallback: bool) -> tuple[list[dict], dict]:
    """Return (rows, status) for a single country x chart pull."""
    legacy_segment, v2_segment = CHARTS[chart]
    attempts: list[dict] = []

    url = legacy_url(country, legacy_segment, limit)
    try:
        rows = parse_legacy(fetch_json(url))
        if rows:
            return rows, {
                "country": country,
                "chart": chart,
                "source": "legacy",
                "url": url,
                "rows": len(rows),
                "ok": True,
                "attempts": attempts,
            }
        attempts.append({"source": "legacy", "url": url, "error": "empty feed"})
    except Exception as exc:  # noqa: BLE001
        attempts.append({"source": "legacy", "url": url, "error": str(exc)})

    if allow_fallback and v2_segment:
        url = v2_url(country, v2_segment, limit)
        try:
            rows = parse_v2(fetch_json(url))
            if rows:
                return rows, {
                    "country": country,
                    "chart": chart,
                    "source": "v2",
                    "url": url,
                    "rows": len(rows),
                    "ok": True,
                    "attempts": attempts,
                }
            attempts.append({"source": "v2", "url": url, "error": "empty feed"})
        except Exception as exc:  # noqa: BLE001
            attempts.append({"source": "v2", "url": url, "error": str(exc)})

    return [], {
        "country": country,
        "chart": chart,
        "source": None,
        "rows": 0,
        "ok": False,
        "attempts": attempts,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Snapshot Apple App Store game charts.")
    parser.add_argument("--countries", nargs="+", default=DEFAULT_COUNTRIES)
    parser.add_argument("--charts", nargs="+", default=list(CHARTS), choices=list(CHARTS))
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--date", default=None, help="YYYY-MM-DD, defaults to today (UTC)")
    parser.add_argument("--sleep", type=float, default=1.0, help="pause between requests, seconds")
    parser.add_argument("--no-fallback", action="store_true", help="legacy feed only")
    args = parser.parse_args()

    captured_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    snapshot_date = args.date or captured_at[:10]

    CHARTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = CHARTS_DIR / f"{snapshot_date}.jsonl"

    all_rows: list[dict] = []
    statuses: list[dict] = []

    for country in args.countries:
        for chart in args.charts:
            rows, status = collect_one(country, chart, args.limit, not args.no_fallback)
            statuses.append(status)
            marker = "ok " if status["ok"] else "FAIL"
            print(
                f"[{marker}] {country:>2} {chart:<13} "
                f"{status['rows']:>3} rows via {status['source'] or '-'}",
                file=sys.stderr,
            )
            for row in rows:
                all_rows.append(
                    {
                        "snapshot_date": snapshot_date,
                        "captured_at": captured_at,
                        "source": status["source"],
                        "country": country,
                        "chart": chart,
                        **row,
                    }
                )
            time.sleep(args.sleep)  # be a polite client

    # Write whole-file so a same-day re-run replaces rather than duplicates.
    with out_path.open("w", encoding="utf-8") as handle:
        for row in all_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    succeeded = sum(1 for s in statuses if s["ok"])
    run_record = {
        "captured_at": captured_at,
        "snapshot_date": snapshot_date,
        "feeds_attempted": len(statuses),
        "feeds_ok": succeeded,
        "rows": len(all_rows),
        "unique_apps": len({r["app_id"] for r in all_rows}),
        "output": str(out_path.relative_to(REPO_ROOT)),
        "statuses": statuses,
    }
    RUNS_LOG.parent.mkdir(parents=True, exist_ok=True)
    with RUNS_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(run_record, ensure_ascii=False) + "\n")

    print(
        f"\n{len(all_rows)} rows / {run_record['unique_apps']} unique apps "
        f"-> {out_path}  ({succeeded}/{len(statuses)} feeds ok)",
        file=sys.stderr,
    )

    # Partial failures are normal and must not fail the daily job; a total
    # wipeout means both feeds changed and does need a red build.
    return 0 if succeeded else 1


if __name__ == "__main__":
    raise SystemExit(main())
