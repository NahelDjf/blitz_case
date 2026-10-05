#!/usr/bin/env python3
"""Assign each charted app to one or two mechanics from the taxonomy.

Design notes:

* The taxonomy sits in the system prompt behind a cache_control breakpoint.
* Apps are sent in batches so the cached prefix is amortised over several
  classifications per call.
* Results cache per app ID in data/mechanics/assignments.jsonl. Re-running
  after a new chart snapshot classifies only the apps that newly appeared.
* Unknown mechanic IDs from the model are coerced to "other" rather than
  trusted.

Requires ANTHROPIC_API_KEY in the environment.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

from common import DATA_DIR, fetch_json, latest_chart_file, post_json, read_jsonl, write_jsonl

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"

# Price per million tokens, for the run-cost estimate only.
PRICING = {
    "claude-sonnet-5-5": {"input": 2.00, "output": 10.00, "cache_read": 0.20},
    "claude-haiku-4-5-20251001": {"input": 1.00, "output": 5.00, "cache_read": 0.10},
    "claude-opus-5-5": {"input": 4.00, "output": 20.00, "cache_read": 0.40},
}

DESCRIPTION_CHARS = 1200  # store descriptions are marketing-padded after this

SYSTEM_TEMPLATE = """You classify mobile games by their CORE GAMEPLAY LOOP.

You will be given a taxonomy of mechanics, then a batch of apps. For each app, \
assign the mechanic whose loop the app actually uses.

Rules:
- Classify by the loop the player repeats, NOT by theme, art style or setting. \
A merge game themed around cooking is still a merge game.
- Assign a primary mechanic. Assign a secondary ONLY when the app genuinely \
runs two distinct loops (for example a match-3 core wrapped in a renovation \
meta). Otherwise set secondary to null.
- If no mechanic in the taxonomy fits, use "other". "other" is a useful signal that the taxonomy has a gap.
- confidence is your own 1-5 rating of how certain the assignment is, where 5 \
means the description states the loop plainly and 1 means you are inferring \
from the title alone.
- evidence must be a short quote or paraphrase (under 15 words) from that \
app's own description that justifies the primary assignment. If the \
description gives you nothing, say "title only".

Respond with ONLY a JSON array, no preamble and no markdown fences:
[{{"app_id": "...", "primary": "...", "secondary": null, "confidence": 4, \
"evidence": "..."}}]

TAXONOMY:
{taxonomy}
"""


def build_app_block(app: dict) -> str:
    description = (app.get("description") or "").strip()
    if len(description) > DESCRIPTION_CHARS:
        description = description[:DESCRIPTION_CHARS] + "..."
    genres = ", ".join(app.get("genres") or [])
    return (
        f"app_id: {app['app_id']}\n"
        f"name: {app.get('trackName')}\n"
        f"genres: {genres}\n"
        f"description: {description}\n"
    )


def call_model(model: str, system_prompt: str, user_content: str, max_tokens: int) -> dict:
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "system": [
            {
                "type": "text",
                "text": system_prompt,
                # Everything before this breakpoint is cached across calls.
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "messages": [{"role": "user", "content": user_content}],
    }
    headers = {
        "x-api-key": os.environ["ANTHROPIC_API_KEY"],
        "anthropic-version": API_VERSION,
    }
    return post_json(API_URL, payload, headers)


def extract_json_array(text: str) -> list[dict]:
    """Models occasionally wrap JSON in fences despite instructions."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1]
        cleaned = cleaned.rsplit("```", 1)[0]
    start, end = cleaned.find("["), cleaned.rfind("]")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON array found in response: {cleaned[:200]}")
    return json.loads(cleaned[start : end + 1])


def main() -> int:
    parser = argparse.ArgumentParser(description="Classify charted apps into mechanics.")
    parser.add_argument("--model", default="claude-sonnet-5-5")
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--country", default="us")
    parser.add_argument("--charts", nargs="+", default=["top_free", "top_grossing"])
    parser.add_argument("--limit", type=int, default=None, help="cap app count (for testing)")
    parser.add_argument("--force", action="store_true", help="reclassify cached apps")
    parser.add_argument("--sleep", type=float, default=0.5)
    parser.add_argument(
        "--chart-date", default=None, help="YYYY-MM-DD snapshot; defaults to newest on disk"
    )
    args = parser.parse_args()

    if "ANTHROPIC_API_KEY" not in os.environ:
        print("ANTHROPIC_API_KEY is not set. export it and retry.", file=sys.stderr)
        return 1

    taxonomy = json.loads((DATA_DIR / "taxonomy.json").read_text(encoding="utf-8"))
    valid_ids = {m["id"] for m in taxonomy["mechanics"]} | {"other"}

    taxonomy_text = "\n".join(
        f"- {m['id']}: {m['label']} — {m['definition']} "
        f"(examples: {', '.join(m['seed_apps'][:4])})"
        for m in taxonomy["mechanics"]
    )
    system_prompt = SYSTEM_TEMPLATE.format(taxonomy=taxonomy_text)

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
    chart_rows = read_jsonl(chart_path)
    in_scope = {
        row["app_id"]
        for row in chart_rows
        if row.get("country") == args.country and row.get("chart") in args.charts
    }

    metadata = {row["app_id"]: row for row in read_jsonl(DATA_DIR / "apps" / "metadata.jsonl")}
    apps = [metadata[app_id] for app_id in sorted(in_scope) if app_id in metadata]
    if args.limit:
        apps = apps[: args.limit]

    cache_path = DATA_DIR / "mechanics" / "assignments.jsonl"
    cached = {row["app_id"]: row for row in read_jsonl(cache_path)}
    todo = [app for app in apps if args.force or app["app_id"] not in cached]

    print(
        f"{len(apps)} apps in scope; {len(todo)} to classify, "
        f"{len(apps) - len(todo)} cached. Model: {args.model}",
        file=sys.stderr,
    )
    if not todo:
        return 0

    usage_totals = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for start in range(0, len(todo), args.batch_size):
        batch = todo[start : start + args.batch_size]
        user_content = "Classify these apps:\n\n" + "\n---\n".join(
            build_app_block(app) for app in batch
        )

        try:
            response = call_model(
                args.model, system_prompt, user_content, max_tokens=400 * len(batch)
            )
            text = "".join(
                block.get("text", "") for block in response.get("content", [])
            )
            results = extract_json_array(text)
        except Exception as exc:  # noqa: BLE001
            print(f"[FAIL] batch at {start}: {exc}", file=sys.stderr)
            continue

        usage = response.get("usage", {})
        usage_totals["input"] += usage.get("input_tokens", 0)
        usage_totals["output"] += usage.get("output_tokens", 0)
        usage_totals["cache_read"] += usage.get("cache_read_input_tokens", 0)
        usage_totals["cache_write"] += usage.get("cache_creation_input_tokens", 0)

        by_id = {app["app_id"]: app for app in batch}
        for result in results:
            app_id = str(result.get("app_id"))
            if app_id not in by_id:
                continue
            primary = result.get("primary")
            secondary = result.get("secondary")
            # Never trust an ID the taxonomy does not define.
            if primary not in valid_ids:
                print(f"       invented id '{primary}' -> other ({app_id})", file=sys.stderr)
                primary = "other"
            if secondary not in valid_ids:
                secondary = None
            cached[app_id] = {
                "app_id": app_id,
                "app_name": by_id[app_id].get("trackName"),
                "primary": primary,
                "secondary": secondary,
                "confidence": result.get("confidence"),
                "evidence": result.get("evidence"),
                "model": args.model,
                "classified_at": now,
            }

        done = min(start + args.batch_size, len(todo))
        print(f"[ok ] {done}/{len(todo)} classified", file=sys.stderr)
        time.sleep(args.sleep)

    write_jsonl(cache_path, [cached[key] for key in sorted(cached)])

    price = PRICING.get(args.model)
    if price:
        cost = (
            usage_totals["input"] / 1e6 * price["input"]
            + usage_totals["output"] / 1e6 * price["output"]
            + usage_totals["cache_read"] / 1e6 * price["cache_read"]
            + usage_totals["cache_write"] / 1e6 * price["input"] * 1.25
        )
        cost_line = f"estimated cost ${cost:.3f}"
    else:
        cost_line = "cost unknown for this model"

    distribution: dict[str, int] = {}
    for row in cached.values():
        distribution[row["primary"]] = distribution.get(row["primary"], 0) + 1

    print(f"\n{len(cached)} apps classified in total -> {cache_path}", file=sys.stderr)
    print(
        f"tokens: {usage_totals['input']} in, {usage_totals['output']} out, "
        f"{usage_totals['cache_read']} cache-read, {usage_totals['cache_write']} cache-write; "
        f"{cost_line}",
        file=sys.stderr,
    )
    print("\nmechanic distribution:", file=sys.stderr)
    for mechanic, count in sorted(distribution.items(), key=lambda kv: -kv[1]):
        print(f"  {count:>3}  {mechanic}", file=sys.stderr)

    others = [r["app_name"] for r in cached.values() if r["primary"] == "other"]
    if others:
        print(f"\nunclassified ({len(others)}): {', '.join(others)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
