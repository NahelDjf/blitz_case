#!/usr/bin/env python3
"""Classify player reviews into the signals that matter for a cash-tournament pivot.

This is the layer a generic App Store trends tool does not have. Chart data
says what people download; reviews say what they want and are not getting.

Five labels, multi-label per review:

  wants_competition  asks for head-to-head play the game does not have -
                direct evidence of unmet demand for exactly what Blitz sells
  has_competition    shows the game already supports head-to-head play -
                evidence the mechanic converts, not evidence of demand
  unfair        alleges bots, rigged outcomes, scripted difficulty, fake
                opponents - the credibility problem Blitz's "no bots" stance
                exists to answer, and a wedge against incumbents
  ads           ad-volume complaints - players signalling willingness to pay
                to escape the current monetisation
  paywall       pay-to-win or paywall complaints
  skillluck     explicitly argues the game is skill-based or luck-based -
                players reasoning about the very property the rubric scores

Why an LLM and not keyword matching: US-storefront reviews are substantially
multilingual (Spanish appears throughout), and the signals are paraphrastic -
"I wish I could play my friends" and "need pvp" are the same label with no
shared words.

Reviews are classified by index, and the model returns indices and labels
only - never the review text. That keeps output tokens, and therefore cost,
roughly an order of magnitude below the input.

Requires ANTHROPIC_API_KEY.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from datetime import datetime, timezone

from common import DATA_DIR, REVIEWS_DIR, post_json, read_jsonl, write_jsonl

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"

PRICING = {
    "claude-haiku-4-5-20251001": {"input": 1.00, "output": 5.00, "cache_read": 0.10},
    "claude-sonnet-5-5": {"input": 2.00, "output": 10.00, "cache_read": 0.20},
}

LABELS = {"wants_competition", "has_competition", "unfair", "ads", "paywall", "skillluck"}
MIN_REVIEWS = 50  # below this a rate is noise, not a signal
REVIEW_CHARS = 400

SYSTEM_PROMPT = """You label mobile game reviews. Reviews may be in any \
language; label them all the same way.

Labels (a review can have several, or none):
- wants_competition: the player ASKS FOR head-to-head competition the game \
does NOT currently offer. "wish I could play against my friends", "needs pvp", \
"please add multiplayer", "there should be leaderboards". This is a REQUEST \
for something absent. If the game already has the feature being discussed, \
this label does NOT apply.
- has_competition: the review shows the game ALREADY has head-to-head play - \
praising it, or complaining about matchmaking, sandbagging, clans, ranked \
ladders, tournament rewards. This is evidence the mechanic already supports \
competition, NOT evidence of unmet demand. Mutually exclusive with \
wants_competition.
- unfair: alleges the game cheats - bots, rigged, scripted, fake opponents, \
"impossible on purpose", difficulty manipulated to force purchases.
- ads: complains about advertising volume, frequency or intrusiveness.
- paywall: complains about pay-to-win, paywalls, or that progress requires money.
- skillluck: explicitly argues about whether the game is skill-based or \
luck-based.

Return ONLY a JSON array, one object per review you were given, no preamble \
and no markdown fences:
[{"i": 0, "l": ["wants_competition"]}, {"i": 1, "l": []}]

"i" is the index given in the input. "l" is a list of label names, empty if \
none apply. Do not invent labels. Do not return the review text."""


def call_model(model: str, user_content: str, max_tokens: int) -> dict:
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "system": [
            {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
        ],
        "messages": [{"role": "user", "content": user_content}],
    }
    headers = {
        "x-api-key": os.environ["ANTHROPIC_API_KEY"],
        "anthropic-version": API_VERSION,
    }
    return post_json(API_URL, payload, headers)


def extract_json_array(text: str) -> list[dict]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
    start, end = cleaned.find("["), cleaned.rfind("]")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON array in response: {cleaned[:200]}")
    return json.loads(cleaned[start : end + 1])


def main() -> int:
    parser = argparse.ArgumentParser(description="Classify reviews into voice signals.")
    parser.add_argument("--model", default="claude-haiku-4-5-20251001")
    parser.add_argument("--sample", type=int, default=250, help="reviews per app")
    parser.add_argument("--batch-size", type=int, default=30)
    parser.add_argument("--chart-date", default=None)
    parser.add_argument("--country", default="us")
    parser.add_argument("--charts", nargs="+", default=["top_free", "top_grossing"])
    parser.add_argument("--limit", type=int, default=None, help="cap app count (for testing)")
    parser.add_argument("--app-ids", nargs="+", default=None, help="probe specific app IDs")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--seed", type=int, default=42, help="sampling seed, for reproducibility")
    args = parser.parse_args()

    if "ANTHROPIC_API_KEY" not in os.environ:
        print("ANTHROPIC_API_KEY is not set.", file=sys.stderr)
        return 1

    charts_dir = DATA_DIR / "charts"
    if args.chart_date:
        chart_path = charts_dir / f"{args.chart_date}.jsonl"
    else:
        files = sorted(charts_dir.glob("*.jsonl"))
        chart_path = files[-1] if files else None
    if chart_path is None or not chart_path.exists():
        print("No chart snapshot found.", file=sys.stderr)
        return 1

    in_scope = sorted(
        {
            row["app_id"]
            for row in read_jsonl(chart_path)
            if row.get("country") == args.country and row.get("chart") in args.charts
        }
    )
    if args.app_ids:
        in_scope = [a for a in in_scope if a in set(args.app_ids)]
    if args.limit:
        in_scope = in_scope[: args.limit]

    voice_dir = DATA_DIR / "voice"
    voice_dir.mkdir(parents=True, exist_ok=True)

    todo = [
        app_id
        for app_id in in_scope
        if args.force or not (voice_dir / f"{app_id}.json").exists()
    ]
    print(
        f"{len(in_scope)} apps in scope; {len(todo)} to classify, "
        f"{len(in_scope) - len(todo)} cached. Model: {args.model}, "
        f"sample {args.sample}/app",
        file=sys.stderr,
    )

    usage_totals = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    skipped_thin = []

    for index, app_id in enumerate(todo, start=1):
        reviews = read_jsonl(REVIEWS_DIR / f"{app_id}.jsonl")
        if len(reviews) < MIN_REVIEWS:
            # Recorded rather than silently dropped: a rate over 21 reviews is
            # noise, and pretending otherwise would be the worst outcome.
            skipped_thin.append(app_id)
            (voice_dir / f"{app_id}.json").write_text(
                json.dumps(
                    {
                        "app_id": app_id,
                        "sufficient": False,
                        "n_reviews": len(reviews),
                        "reason": f"fewer than {MIN_REVIEWS} reviews",
                        "classified_at": now,
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            print(f"[{index}/{len(todo)}] {app_id}: thin ({len(reviews)}), skipped", file=sys.stderr)
            continue

        # Deterministic sample so a re-run reproduces the same rates.
        rng = random.Random(args.seed)
        sample = reviews if len(reviews) <= args.sample else rng.sample(reviews, args.sample)

        counts = {label: 0 for label in LABELS}
        classified = 0
        examples: dict[str, list[str]] = {label: [] for label in LABELS}

        for start in range(0, len(sample), args.batch_size):
            batch = sample[start : start + args.batch_size]
            lines = []
            for offset, review in enumerate(batch):
                text = f"{review.get('title') or ''}. {review.get('content') or ''}".strip()
                lines.append(f"[{offset}] {text[:REVIEW_CHARS]}")
            user_content = "Label these reviews:\n\n" + "\n".join(lines)

            try:
                response = call_model(args.model, user_content, max_tokens=40 * len(batch) + 200)
                text_out = "".join(b.get("text", "") for b in response.get("content", []))
                results = extract_json_array(text_out)
            except Exception as exc:  # noqa: BLE001
                print(f"       {app_id} batch {start}: {exc}", file=sys.stderr)
                continue

            usage = response.get("usage", {})
            usage_totals["input"] += usage.get("input_tokens", 0)
            usage_totals["output"] += usage.get("output_tokens", 0)
            usage_totals["cache_read"] += usage.get("cache_read_input_tokens", 0)
            usage_totals["cache_write"] += usage.get("cache_creation_input_tokens", 0)

            for result in results:
                offset = result.get("i")
                if not isinstance(offset, int) or not 0 <= offset < len(batch):
                    continue
                classified += 1
                for label in result.get("l") or []:
                    if label in counts:
                        counts[label] += 1
                        if len(examples[label]) < 3:
                            quote = (batch[offset].get("content") or "")[:120]
                            examples[label].append(
                                {"review_id": batch[offset].get("review_id"), "quote": quote}
                            )

        record = {
            "app_id": app_id,
            "sufficient": classified >= MIN_REVIEWS,
            "n_reviews_available": len(reviews),
            "n_classified": classified,
            "counts": counts,
            "rates": {
                label: round(counts[label] / classified, 4) if classified else None
                for label in LABELS
            },
            "examples": examples,
            "model": args.model,
            "sample_seed": args.seed,
            "classified_at": now,
        }
        (voice_dir / f"{app_id}.json").write_text(
            json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8"
        )

        top = ", ".join(
            f"{label} {counts[label] / classified * 100:.0f}%"
            for label in sorted(counts, key=lambda k: -counts[k])[:2]
            if classified and counts[label]
        )
        print(
            f"[{index}/{len(todo)}] {app_id}: {classified} classified" + (f" | {top}" if top else ""),
            file=sys.stderr,
        )

    price = PRICING.get(args.model)
    cost = None
    if price:
        cost = (
            usage_totals["input"] / 1e6 * price["input"]
            + usage_totals["output"] / 1e6 * price["output"]
            + usage_totals["cache_read"] / 1e6 * price["cache_read"]
            + usage_totals["cache_write"] / 1e6 * price["input"] * 1.25
        )

    print(
        f"\ntokens: {usage_totals['input']} in, {usage_totals['output']} out, "
        f"{usage_totals['cache_read']} cache-read"
        + (f"; estimated cost ${cost:.2f}" if cost is not None else ""),
        file=sys.stderr,
    )
    if skipped_thin:
        print(
            f"{len(skipped_thin)} apps had fewer than {MIN_REVIEWS} reviews and were "
            f"marked insufficient rather than scored.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
