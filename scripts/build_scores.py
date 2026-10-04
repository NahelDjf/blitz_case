#!/usr/bin/env python3
"""Combine every layer into one ranked opportunity table.

Four components, each 0-1, then combined:

  demand        chart position and breadth - is anyone playing this?
  openness      publisher fragmentation and carrier age - is the door open?
  fatigue       ad, paywall and unfairness complaint rates across carriers -
                how unhappy are players with how these games make money?
  convertibility the rubric score - can Blitz actually run it?

Convertibility is a MULTIPLIER, not a term. A mechanic that fails a gate
scores 0 and cannot be rescued by demand, which is the entire point of the
tool: a generic trends dashboard would rank survival 4X near the top because
it has 13 carriers and a #7 grossing slot, and it would be useless advice.

No single opaque number is reported without its parts. Weights are CLI flags
so a designer can disagree with them.

Deterministic, no API calls, instant. Run it as often as you like.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

from common import DATA_DIR, read_jsonl, write_jsonl

VOICE_LABELS = ["ads", "paywall", "unfair", "wants_competition", "has_competition", "skillluck"]


def rank_to_score(rank: int | None, depth: int = 100) -> float:
    """Chart rank -> 0-1. Non-linear: the top of the chart is worth far more.

    Rank is ordinal, so #1 vs #5 is a much bigger gap than #50 vs #55.
    A square root of the linear position approximates that without pretending
    to a precision the data does not support.
    """
    if not rank:
        return 0.0
    linear = max(0.0, (depth - rank + 1) / depth)
    return round(linear ** 0.5, 4)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the composite opportunity ranking.")
    parser.add_argument("--w-demand", type=float, default=0.40)
    parser.add_argument("--w-openness", type=float, default=0.35)
    parser.add_argument("--w-fatigue", type=float, default=0.25)
    parser.add_argument("--top", type=int, default=15, help="rows to print")
    args = parser.parse_args()

    total_weight = args.w_demand + args.w_openness + args.w_fatigue
    if abs(total_weight - 1.0) > 1e-6:
        print(f"Weights sum to {total_weight:.3f}, normalising.", file=sys.stderr)

    rubric = json.loads((DATA_DIR / "rubric.json").read_text(encoding="utf-8"))
    excluded = set(rubric["excluded_mechanics"])
    operated = set(rubric["blitz_portfolio"]["operated_mechanics"])
    ua_reference = set(rubric["blitz_portfolio"].get("ua_reference_mechanics", []))

    mechanics = read_jsonl(DATA_DIR / "mechanics" / "mechanics.jsonl")
    convertibility = {r["mechanic_id"]: r for r in read_jsonl(DATA_DIR / "mechanics" / "convertibility.jsonl")}

    # Pool voice rates across each mechanic's carriers, weighting by how many
    # reviews each carrier contributed - so a 500-review app counts more than
    # a 60-review one, and thin apps are excluded entirely.
    voice_dir = DATA_DIR / "voice"
    voice_by_app: dict[str, dict] = {}
    for path in voice_dir.glob("*.json"):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("sufficient"):
            voice_by_app[record["app_id"]] = record

    rows = []
    for mechanic in mechanics:
        mechanic_id = mechanic["mechanic_id"]
        if mechanic_id in excluded:
            continue

        verdict = convertibility.get(mechanic_id, {})
        convert_score = verdict.get("convertibility", 0.0)

        # --- demand -------------------------------------------------------
        free = rank_to_score(mechanic.get("best_rank_free"))
        grossing = rank_to_score(mechanic.get("best_rank_grossing"))
        breadth = min(mechanic["carriers"] / 8.0, 1.0)
        # Grossing presence weighted highest: it proves payers exist, which is
        # what a deposit-based product actually needs.
        demand = round(0.30 * free + 0.45 * grossing + 0.25 * breadth, 4)

        # --- openness -----------------------------------------------------
        # Low publisher concentration = fragmented = enterable. A mechanic
        # with few carriers is penalised on evidence, not on openness, so HHI
        # of 1.0 from a single carrier is handled by the evidence tier.
        fragmentation = 1.0 - mechanic.get("publisher_hhi", 1.0)
        freshness = mechanic.get("share_released_last_year") or 0.0
        openness = round(0.65 * fragmentation + 0.35 * freshness, 4)

        # --- fatigue ------------------------------------------------------
        counts, weights_sum = {label: 0.0 for label in VOICE_LABELS}, 0.0
        carriers_with_voice = 0
        for app_id in mechanic["app_ids"]:
            record = voice_by_app.get(app_id)
            if not record:
                continue
            n = record.get("n_classified") or 0
            carriers_with_voice += 1
            weights_sum += n
            for label in VOICE_LABELS:
                rate = (record.get("rates") or {}).get(label)
                if rate is not None:
                    counts[label] += rate * n
        voice_rates = (
            {label: round(counts[label] / weights_sum, 4) for label in VOICE_LABELS}
            if weights_sum
            else {label: None for label in VOICE_LABELS}
        )
        if weights_sum:
            # Monetisation fatigue: players unhappy with ads, paywalls and
            # perceived cheating are players a no-ads, no-bots, real-stakes
            # alternative can speak to.
            fatigue = round(
                min(
                    1.0,
                    0.40 * (voice_rates["ads"] or 0) / 0.5
                    + 0.35 * (voice_rates["paywall"] or 0) / 0.4
                    + 0.25 * (voice_rates["unfair"] or 0) / 0.3,
                ),
                4,
            )
        else:
            fatigue = None

        # --- composite ----------------------------------------------------
        opportunity = (
            args.w_demand * demand
            + args.w_openness * openness
            + args.w_fatigue * (fatigue if fatigue is not None else 0.0)
        ) / total_weight
        blitz_score = round(convert_score * opportunity, 4)

        if mechanic_id in operated:
            quadrant = "already_operated"
        elif mechanic["cash_carriers"] > 0:
            quadrant = "proven_by_competitor"
        elif mechanic["evidence_tier"] == "scored":
            quadrant = "open_established"
        else:
            quadrant = "open_emerging"

        rows.append(
            {
                "mechanic_id": mechanic_id,
                "label": mechanic["label"],
                "blitz_score": blitz_score,
                "verdict": verdict.get("verdict", "NOT_SCORED"),
                "failed_gates": verdict.get("failed_gates", []),
                "convertibility": convert_score,
                "convertibility_confidence": verdict.get("confidence"),
                "opportunity": round(opportunity, 4),
                "demand": demand,
                "openness": openness,
                "fatigue": fatigue,
                "quadrant": quadrant,
                "evidence_tier": mechanic["evidence_tier"],
                "in_ua_reference": mechanic_id in ua_reference,
                "carriers": mechanic["carriers"],
                "cash_carriers": mechanic["cash_carriers"],
                "cash_carrier_names": mechanic["cash_carrier_names"],
                "carriers_with_voice": carriers_with_voice,
                "best_rank_free": mechanic.get("best_rank_free"),
                "best_rank_grossing": mechanic.get("best_rank_grossing"),
                "publisher_hhi": mechanic.get("publisher_hhi"),
                "voice_rates": voice_rates,
                "dimensions": verdict.get("dimensions", {}),
                "app_ids": mechanic["app_ids"],
                "snapshot_date": mechanic["snapshot_date"],
                "weights": {
                    "demand": args.w_demand,
                    "openness": args.w_openness,
                    "fatigue": args.w_fatigue,
                },
            }
        )

    rows.sort(key=lambda r: -r["blitz_score"])
    out_path = DATA_DIR / "mechanics" / "scores.jsonl"
    write_jsonl(out_path, rows)

    viable = [r for r in rows if r["verdict"] == "VIABLE"]
    rejected = [r for r in rows if r["verdict"] == "REJECTED"]

    print(f"{len(rows)} mechanics scored -> {out_path}", file=sys.stderr)
    print(
        f"  {len(viable)} viable, {len(rejected)} rejected by a gate, "
        f"{len(rows) - len(viable) - len(rejected)} not scored\n",
        file=sys.stderr,
    )

    header = "{:<24} {:>6} {:>6} {:>6} {:>6} {:>6} {:>4} {:>4}  {}"
    print(
        header.format("mechanic", "SCORE", "conv", "dem", "open", "fatig", "car", "cash", "quadrant"),
        file=sys.stderr,
    )
    for row in viable[: args.top]:
        print(
            header.format(
                row["mechanic_id"][:24],
                f"{row['blitz_score']:.3f}",
                f"{row['convertibility']:.2f}",
                f"{row['demand']:.2f}",
                f"{row['openness']:.2f}",
                f"{row['fatigue']:.2f}" if row["fatigue"] is not None else "-",
                row["carriers"],
                row["cash_carriers"],
                row["quadrant"],
            ),
            file=sys.stderr,
        )

    print("\nRejected by a gate (demand is irrelevant once a gate fails):", file=sys.stderr)
    for row in sorted(rejected, key=lambda r: -r["demand"])[:8]:
        print(
            f"  {row['mechanic_id']:<24} demand {row['demand']:.2f} "
            f"-> failed {', '.join(row['failed_gates'])}",
            file=sys.stderr,
        )

    headline = [r for r in viable if r["quadrant"] == "proven_by_competitor"]
    if headline:
        print("\nPROVEN BY A COMPETITOR, NOT OPERATED BY BLITZ:", file=sys.stderr)
        for row in headline:
            print(
                f"  {row['label']} - score {row['blitz_score']:.3f}, "
                f"convertibility {row['convertibility']:.2f}, "
                f"{row['cash_carriers']} cash carrier(s): "
                f"{', '.join(row['cash_carrier_names'])}",
                file=sys.stderr,
            )

    emerging = [
        r for r in viable if r["quadrant"] == "open_emerging" and (r["best_rank_free"] or 999) <= 15
    ]
    if emerging:
        print("\nTOP-15 CHART POSITION, FEW CARRIERS, NO CASH COMPETITOR:", file=sys.stderr)
        for row in emerging:
            print(
                f"  {row['label']} - free #{row['best_rank_free']}, "
                f"{row['carriers']} carrier(s), convertibility {row['convertibility']:.2f}",
                file=sys.stderr,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
