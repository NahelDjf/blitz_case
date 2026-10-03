#!/usr/bin/env python3
"""Aggregate app-level data into mechanic-level features.

Everything here is deterministic arithmetic over data already on disk - no
LLM, no network, no cost. Run it as often as you like. The expensive
judgement passes (convertibility, review voice) layer on top of this.

Produces data/mechanics/mechanics.jsonl, one row per mechanic, with:

  demand      best chart rank, how many carriers, grossing presence
  saturation  publisher concentration, mean rating, clone density proxy
  freshness   carrier age, share released in the last year
  competitive cash_carriers - how many carriers are already skill-cash apps
  context     whether Blitz already operates the mechanic

The competitive column is the one that does not exist in any off-the-shelf
tool: a carrier that is already a cash-tournament app is not evidence of
saturation, it is evidence that the conversion works. Counting those
separately is what lets the tool answer "which mechanics has a competitor
already proven, that Blitz does not operate?".
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone

from common import DATA_DIR, latest_chart_file, read_jsonl, write_jsonl

# Titles that advertise cash play. Deterministic and auditable on purpose -
# no LLM call, and the rule can be read and argued with.
CASH_TITLE_PATTERN = re.compile(
    r"win real (cash|money)|real cash|real money|cash tournament|win cash",
    re.IGNORECASE,
)

MIN_CARRIERS_FOR_SCORING = 3


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def herfindahl(names: list[str]) -> float:
    """Publisher concentration: 1.0 means a single publisher owns the mechanic."""
    if not names:
        return 0.0
    counts: dict[str, int] = {}
    for name in names:
        counts[name] = counts.get(name, 0) + 1
    total = len(names)
    return round(sum((count / total) ** 2 for count in counts.values()), 3)


def median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def main() -> int:
    parser = argparse.ArgumentParser(description="Build mechanic-level features.")
    parser.add_argument("--country", default="us")
    parser.add_argument("--charts", nargs="+", default=["top_free", "top_grossing"])
    parser.add_argument(
        "--chart-date",
        default=None,
        help="YYYY-MM-DD snapshot to analyse; defaults to the newest on disk. "
        "Pin it to make a run reproducible.",
    )
    args = parser.parse_args()

    rubric = json.loads((DATA_DIR / "rubric.json").read_text(encoding="utf-8"))
    taxonomy = json.loads((DATA_DIR / "taxonomy.json").read_text(encoding="utf-8"))
    labels = {m["id"]: m["label"] for m in taxonomy["mechanics"]}
    labels["other"] = "Unclassified"

    excluded = set(rubric["excluded_mechanics"])
    portfolio = set(rubric["blitz_portfolio"]["mechanic_ids"])

    if args.chart_date:
        chart_path = DATA_DIR / "charts" / f"{args.chart_date}.jsonl"
        if not chart_path.exists():
            print(f"No snapshot for {args.chart_date}.", file=sys.stderr)
            return 1
    else:
        chart_path = latest_chart_file()
        if chart_path is None:
            print("No chart snapshot found.", file=sys.stderr)
            return 1
    snapshot_date = chart_path.stem

    metadata = {r["app_id"]: r for r in read_jsonl(DATA_DIR / "apps" / "metadata.jsonl")}
    assignments = {r["app_id"]: r for r in read_jsonl(DATA_DIR / "mechanics" / "assignments.jsonl")}

    # Optional hand-labelled corrections, applied visibly rather than silently.
    overrides_path = DATA_DIR / "overrides.json"
    overrides = {}
    if overrides_path.exists():
        overrides = json.loads(overrides_path.read_text(encoding="utf-8"))
        for app_id, override in overrides.items():
            if app_id in assignments:
                assignments[app_id].update(override)
                assignments[app_id]["source"] = "human_override"

    # Best rank per app per chart in the analysis scope.
    ranks: dict[str, dict[str, int]] = {}
    for row in read_jsonl(chart_path):
        if row.get("country") != args.country or row.get("chart") not in args.charts:
            continue
        app_ranks = ranks.setdefault(row["app_id"], {})
        chart = row["chart"]
        app_ranks[chart] = min(app_ranks.get(chart, 999), row["rank"])

    # Coverage is reported loudly. Each stage of the pipeline can run against
    # a different snapshot, and an analysis that quietly covers 150 of 162 apps
    # is worse than one that refuses to run.
    missing_metadata = sorted(a for a in ranks if a not in metadata)
    missing_assignment = sorted(
        a for a in ranks if a in metadata and a not in assignments
    )
    covered = len(ranks) - len(set(missing_metadata) | set(missing_assignment))
    print(
        f"Snapshot {snapshot_date}: {len(ranks)} apps in scope, {covered} fully covered "
        f"({covered / len(ranks) * 100:.0f}%).",
        file=sys.stderr,
    )
    if missing_metadata:
        print(
            f"  !! {len(missing_metadata)} without metadata - run enrich_apps.py: "
            f"{missing_metadata[:6]}",
            file=sys.stderr,
        )
    if missing_assignment:
        print(
            f"  !! {len(missing_assignment)} without a mechanic - run classify_mechanics.py: "
            f"{missing_assignment[:6]}",
            file=sys.stderr,
        )

    now = datetime.now(timezone.utc)
    by_mechanic: dict[str, list[dict]] = {}

    for app_id in ranks:
        assignment = assignments.get(app_id)
        app = metadata.get(app_id)
        if not assignment or not app:
            continue

        name = app.get("trackName") or ""
        slots = {assignment.get("primary"), assignment.get("secondary")}
        is_skill_cash = bool(CASH_TITLE_PATTERN.search(name)) or "skill_cash_arcade" in slots

        release = parse_date(app.get("releaseDate"))
        updated = parse_date(app.get("currentVersionReleaseDate"))

        record = {
            "app_id": app_id,
            "name": name,
            "publisher": app.get("artistName"),
            "rank_free": ranks[app_id].get("top_free"),
            "rank_grossing": ranks[app_id].get("top_grossing"),
            "rating": app.get("averageUserRating"),
            "rating_count": app.get("userRatingCount") or 0,
            "age_days": (now - release).days if release else None,
            "days_since_update": (now - updated).days if updated else None,
            "is_skill_cash": is_skill_cash,
            "is_secondary": False,
        }

        # An app counts fully toward its primary mechanic and is also recorded
        # against its secondary, flagged, so hybrid titles are visible without
        # double-counting as full carriers.
        primary = assignment.get("primary")
        if primary:
            by_mechanic.setdefault(primary, []).append(record)
        secondary = assignment.get("secondary")
        if secondary and secondary != primary:
            by_mechanic.setdefault(secondary, []).append({**record, "is_secondary": True})

    rows = []
    for mechanic_id, apps in by_mechanic.items():
        # "other" is the taxonomy's escape hatch, not a mechanic - it has no
        # shared loop, so aggregating over it would be meaningless.
        if mechanic_id == "other":
            continue
        primaries = [a for a in apps if not a["is_secondary"]]
        # A mechanic that appears only as a secondary has no carrier of its own.
        if not primaries:
            continue
        cash_carriers = [a for a in apps if a["is_skill_cash"]]
        ages = [a["age_days"] for a in primaries if a["age_days"] is not None]
        ratings = [a["rating"] for a in primaries if a["rating"]]
        free_ranks = [a["rank_free"] for a in apps if a["rank_free"]]
        grossing_ranks = [a["rank_grossing"] for a in apps if a["rank_grossing"]]

        in_portfolio = mechanic_id in portfolio
        has_cash_proof = len(cash_carriers) > 0

        if in_portfolio:
            quadrant = "already_operated"
        elif has_cash_proof:
            quadrant = "proven_by_competitor"
        elif len(primaries) >= MIN_CARRIERS_FOR_SCORING:
            quadrant = "unproven_established"
        else:
            quadrant = "unproven_emerging"

        rows.append(
            {
                "mechanic_id": mechanic_id,
                "label": labels.get(mechanic_id, mechanic_id),
                "snapshot_date": snapshot_date,
                "evidence_tier": (
                    "scored" if len(primaries) >= MIN_CARRIERS_FOR_SCORING else "watchlist"
                ),
                "excluded": mechanic_id in excluded,
                "exclusion_reason": rubric["excluded_mechanics"].get(mechanic_id),
                "in_blitz_portfolio": in_portfolio,
                "quadrant": quadrant,
                "carriers": len(primaries),
                "carriers_incl_secondary": len(apps),
                "cash_carriers": len(cash_carriers),
                "cash_carrier_names": [a["name"] for a in cash_carriers],
                "best_rank_free": min(free_ranks) if free_ranks else None,
                "best_rank_grossing": min(grossing_ranks) if grossing_ranks else None,
                "n_in_grossing": len(grossing_ranks),
                "publisher_hhi": herfindahl([a["publisher"] for a in primaries if a["publisher"]]),
                "distinct_publishers": len({a["publisher"] for a in primaries if a["publisher"]}),
                # Informational only, deliberately NOT scored: App Store ratings are
                # compressed by prompt-gating (observed range 4.0-4.93, nearly all
                # between 4.6 and 4.9), so "high rank + mediocre rating = unmet
                # demand" has no signal to detect here. Unmet demand comes from
                # review text instead.
                "mean_rating": round(sum(ratings) / len(ratings), 2) if ratings else None,
                "median_rating_count": median([a["rating_count"] for a in primaries]),
                "median_age_days": median(ages),
                "share_released_last_year": (
                    round(sum(1 for a in ages if a < 365) / len(ages), 2) if ages else None
                ),
                "median_days_since_update": median(
                    [a["days_since_update"] for a in primaries if a["days_since_update"] is not None]
                ),
                "app_ids": [a["app_id"] for a in primaries],
            }
        )

    rows.sort(key=lambda r: (-r["carriers"], r["mechanic_id"]))
    out_path = DATA_DIR / "mechanics" / "mechanics.jsonl"
    write_jsonl(out_path, rows)

    scored = [r for r in rows if r["evidence_tier"] == "scored" and not r["excluded"]]
    watchlist = [r for r in rows if r["evidence_tier"] == "watchlist" and not r["excluded"]]

    print(f"{len(rows)} mechanics -> {out_path}", file=sys.stderr)
    print(
        f"  {len(scored)} scored (>= {MIN_CARRIERS_FOR_SCORING} carriers), "
        f"{len(watchlist)} watchlist, "
        f"{sum(1 for r in rows if r['excluded'])} excluded"
        + (f", {len(overrides)} human overrides applied" if overrides else ""),
        file=sys.stderr,
    )

    print(
        "\n{:<26} {:>3} {:>5} {:>6} {:>6} {:>5} {:>5}  {}".format(
            "mechanic", "car", "cash", "free#", "gross#", "rate", "hhi", "quadrant"
        ),
        file=sys.stderr,
    )
    for row in rows:
        if row["excluded"]:
            continue
        print(
            "{:<26} {:>3} {:>5} {:>6} {:>6} {:>5} {:>5}  {}".format(
                row["mechanic_id"][:26],
                row["carriers"],
                row["cash_carriers"],
                row["best_rank_free"] or "-",
                row["best_rank_grossing"] or "-",
                row["mean_rating"] or "-",
                row["publisher_hhi"],
                row["quadrant"],
            ),
            file=sys.stderr,
        )

    headline = [
        r for r in rows
        if r["quadrant"] == "proven_by_competitor" and not r["excluded"]
    ]
    if headline:
        print("\nProven by a competitor, not in Blitz's portfolio:", file=sys.stderr)
        for row in sorted(headline, key=lambda r: -r["cash_carriers"]):
            print(
                f"  {row['label']}: {row['cash_carriers']} cash carrier(s) - "
                f"{', '.join(row['cash_carrier_names'])}",
                file=sys.stderr,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
