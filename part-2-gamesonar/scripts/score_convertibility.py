#!/usr/bin/env python3
"""Score each mechanic against the convertibility rubric.

This is the judgement layer and the reason the tool is not a generic App
Store trends dashboard. It asks: could Blitz actually run this as a fair,
short, head-to-head cash tournament?

Design:

* The rubric lives in data/rubric.json, not in this file. Criteria are an
  artifact that can be reviewed and versioned, not a string buried in code.
* Two dimensions are GATES. Scoring at or below their threshold rejects the
  mechanic outright and names the failing gate. Gates are not averaged in -
  a mechanic that cannot be run fairly is not partially convertible.
* Every mechanic is scored N times (default 3). The spread across runs is
  the confidence signal: 4/4/4 means the model understands the mechanic,
  5/2/4 means the taxonomy entry is ambiguous, the mechanic genuinely varies
  across its carriers, or the rubric wording is vague. 
* Each dimension must return a score, a justification, and the app_id of a
  carrier that evidences it. 

Note: current Sonnet and Opus models no longer accept a temperature
parameter, so run-to-run spread measures genuine judgement stability rather
than decoder determinism - which is closer to what this metric is for.

Requires ANTHROPIC_API_KEY.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone

from common import DATA_DIR, post_json, read_jsonl, write_jsonl

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"

PRICING = {
    "claude-opus-5-5": {"input": 4.00, "output": 20.00, "cache_read": 0.40},
    "claude-sonnet-5-5": {"input": 2.00, "output": 10.00, "cache_read": 0.20},
}

MAX_CARRIERS_IN_PROMPT = 5
DESCRIPTION_CHARS = 700


def build_rubric_prompt(rubric: dict) -> str:
    lines = [
        "You assess whether a mobile game MECHANIC could be operated as a "
        "real-money skill tournament by Blitz, a platform where two players "
        "pay to enter, play the same game, and the higher score wins cash.",
        "",
        "You will be given a mechanic, its definition, and several real apps "
        "that use it. Score the MECHANIC, not any single app.",
        "",
        "GATES - a low score here disqualifies the mechanic entirely:",
    ]
    for dimension in rubric["dimensions"]:
        if dimension["type"] != "gate":
            continue
        lines.append(f"\n{dimension['id']} ({dimension['label']}) "
                     f"- fails at <= {dimension['fail_below']}")
        lines.append(f"  {dimension['question']}")
        if dimension.get("note"):
            lines.append(f"  NOTE: {dimension['note']}")
        for score, anchor in sorted(dimension["anchors"].items()):
            lines.append(f"  {score} = {anchor}")

    lines.append("\nWEIGHTED DIMENSIONS:")
    for dimension in rubric["dimensions"]:
        if dimension["type"] != "weighted":
            continue
        lines.append(f"\n{dimension['id']} ({dimension['label']}) "
                     f"- weight {dimension['weight']}")
        lines.append(f"  {dimension['question']}")
        if dimension.get("note"):
            lines.append(f"  NOTE: {dimension['note']}")
        for score, anchor in sorted(dimension["anchors"].items()):
            lines.append(f"  {score} = {anchor}")

    for flag in rubric["risk_flags"]:
        lines.append(f"\nRISK FLAG - {flag['id']} ({flag['label']}):")
        lines.append(f"  {flag['question']}")
        if flag.get("note"):
            lines.append(f"  NOTE: {flag['note']}")
        for score, anchor in sorted(flag["anchors"].items()):
            lines.append(f"  {score} = {anchor}")

    dimension_ids = [d["id"] for d in rubric["dimensions"]]
    flag_ids = [f["id"] for f in rubric["risk_flags"]]
    lines += [
        "",
        "Return ONLY a JSON object, no preamble and no markdown fences, with "
        "one key per dimension and risk flag:",
        "{",
        ",\n".join(
            f'  "{key}": {{"score": 3, "justification": "...", "evidence_app_id": "..."}}'
            for key in dimension_ids + flag_ids
        ),
        "}",
        "",
        "justification: one sentence under 25 words saying why this score and "
        "not the one above or below.",
        "evidence_app_id: the app_id of a carrier whose description supports "
        "this score, or null with the justification starting 'no carrier "
        "evidence:'.",
    ]
    return "\n".join(lines)


def build_mechanic_prompt(mechanic: dict, definition: str, carriers: list[dict]) -> str:
    lines = [
        f"MECHANIC: {mechanic['label']} ({mechanic['mechanic_id']})",
        f"DEFINITION: {definition}",
        f"CARRIERS CHARTING IN THE US TOP 100: {mechanic['carriers']}",
        "",
        "Apps using this mechanic:",
    ]
    for carrier in carriers[:MAX_CARRIERS_IN_PROMPT]:
        description = (carrier.get("description") or "").strip()[:DESCRIPTION_CHARS]
        lines.append(
            f"\napp_id: {carrier['app_id']}\nname: {carrier.get('trackName')}\n"
            f"description: {description}"
        )
    return "\n".join(lines)


def call_model(model: str, system_prompt: str, user_content: str) -> dict:
    payload = {
        "model": model,
        "max_tokens": 2000,
        "system": [
            {"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}
        ],
        "messages": [{"role": "user", "content": user_content}],
    }
    headers = {
        "x-api-key": os.environ["ANTHROPIC_API_KEY"],
        "anthropic-version": API_VERSION,
    }
    return post_json(API_URL, payload, headers)


def extract_json_object(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON object in response: {cleaned[:200]}")
    return json.loads(cleaned[start : end + 1])


def main() -> int:
    parser = argparse.ArgumentParser(description="Score mechanics for convertibility.")
    parser.add_argument("--model", default="claude-opus-5-5")
    parser.add_argument("--runs", type=int, default=3, help="repeat runs for self-consistency")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--mechanics", nargs="+", default=None, help="specific mechanic IDs")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--sleep", type=float, default=0.5)
    args = parser.parse_args()

    if "ANTHROPIC_API_KEY" not in os.environ:
        print("ANTHROPIC_API_KEY is not set.", file=sys.stderr)
        return 1

    rubric = json.loads((DATA_DIR / "rubric.json").read_text(encoding="utf-8"))
    taxonomy = json.loads((DATA_DIR / "taxonomy.json").read_text(encoding="utf-8"))
    definitions = {m["id"]: m["definition"] for m in taxonomy["mechanics"]}

    gates = {d["id"]: d["fail_below"] for d in rubric["dimensions"] if d["type"] == "gate"}
    weights = {d["id"]: d["weight"] for d in rubric["dimensions"] if d["type"] == "weighted"}
    flag_ids = [f["id"] for f in rubric["risk_flags"]]
    all_keys = list(gates) + list(weights) + flag_ids

    system_prompt = build_rubric_prompt(rubric)

    mechanics = [m for m in read_jsonl(DATA_DIR / "mechanics" / "mechanics.jsonl")]
    metadata = {r["app_id"]: r for r in read_jsonl(DATA_DIR / "apps" / "metadata.jsonl")}

    if args.mechanics:
        mechanics = [m for m in mechanics if m["mechanic_id"] in set(args.mechanics)]
    if args.limit:
        mechanics = mechanics[: args.limit]

    out_path = DATA_DIR / "mechanics" / "convertibility.jsonl"
    cached = {r["mechanic_id"]: r for r in read_jsonl(out_path)}
    todo = [m for m in mechanics if args.force or m["mechanic_id"] not in cached]

    print(
        f"{len(mechanics)} mechanics; {len(todo)} to score x {args.runs} runs "
        f"= {len(todo) * args.runs} calls. Model: {args.model}",
        file=sys.stderr,
    )

    usage_totals = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for index, mechanic in enumerate(todo, start=1):
        carriers = [metadata[a] for a in mechanic["app_ids"] if a in metadata]
        if not carriers:
            print(f"       {mechanic['mechanic_id']}: no carrier metadata, skipped", file=sys.stderr)
            continue

        user_content = build_mechanic_prompt(
            mechanic, definitions.get(mechanic["mechanic_id"], ""), carriers
        )

        runs: list[dict] = []
        for run_number in range(args.runs):
            try:
                response = call_model(args.model, system_prompt, user_content)
                text = "".join(b.get("text", "") for b in response.get("content", []))
                runs.append(extract_json_object(text))
            except Exception as exc:  # noqa: BLE001
                print(f"       {mechanic['mechanic_id']} run {run_number}: {exc}", file=sys.stderr)
                continue
            usage = response.get("usage", {})
            usage_totals["input"] += usage.get("input_tokens", 0)
            usage_totals["output"] += usage.get("output_tokens", 0)
            usage_totals["cache_read"] += usage.get("cache_read_input_tokens", 0)
            usage_totals["cache_write"] += usage.get("cache_creation_input_tokens", 0)
            time.sleep(args.sleep)

        if not runs:
            continue

        # Median across runs is the reported score; spread is the confidence.
        dimensions: dict[str, dict] = {}
        for key in all_keys:
            scores = [
                r[key]["score"]
                for r in runs
                if isinstance(r.get(key), dict) and isinstance(r[key].get("score"), int)
            ]
            if not scores:
                continue
            first = next(r[key] for r in runs if isinstance(r.get(key), dict))
            dimensions[key] = {
                "score": round(statistics.median(scores)),
                "scores_all_runs": scores,
                "spread": max(scores) - min(scores),
                "justification": first.get("justification"),
                "evidence_app_id": first.get("evidence_app_id"),
            }

        failed_gates = [
            gate
            for gate, threshold in gates.items()
            if gate in dimensions and dimensions[gate]["score"] <= threshold
        ]

        if failed_gates:
            total = 0.0
            verdict = "REJECTED"
        else:
            weighted = [
                (dimensions[key]["score"] / 5.0) * weight
                for key, weight in weights.items()
                if key in dimensions
            ]
            total = round(sum(weighted), 4)
            verdict = "VIABLE"

        spreads = [d["spread"] for d in dimensions.values()]
        max_spread = max(spreads) if spreads else 0
        confidence = "high" if max_spread <= 1 else ("medium" if max_spread == 2 else "low")

        cached[mechanic["mechanic_id"]] = {
            "mechanic_id": mechanic["mechanic_id"],
            "label": mechanic["label"],
            "verdict": verdict,
            "failed_gates": failed_gates,
            "convertibility": total,
            "confidence": confidence,
            "max_spread": max_spread,
            "mean_spread": round(statistics.mean(spreads), 2) if spreads else None,
            "dimensions": dimensions,
            "runs": len(runs),
            "model": args.model,
            "scored_at": now,
        }

        print(
            f"[{index}/{len(todo)}] {mechanic['mechanic_id']}: {verdict} "
            f"{total:.2f} (confidence {confidence}"
            + (f", failed {', '.join(failed_gates)}" if failed_gates else "")
            + ")",
            file=sys.stderr,
        )

    write_jsonl(out_path, [cached[k] for k in sorted(cached)])

    price = PRICING.get(args.model)
    if price:
        cost = (
            usage_totals["input"] / 1e6 * price["input"]
            + usage_totals["output"] / 1e6 * price["output"]
            + usage_totals["cache_read"] / 1e6 * price["cache_read"]
            + usage_totals["cache_write"] / 1e6 * price["input"] * 1.25
        )
        print(f"\nestimated cost ${cost:.2f}", file=sys.stderr)
    print(
        f"tokens: {usage_totals['input']} in, {usage_totals['output']} out, "
        f"{usage_totals['cache_read']} cache-read",
        file=sys.stderr,
    )

    viable = sorted(
        (r for r in cached.values() if r["verdict"] == "VIABLE"),
        key=lambda r: -r["convertibility"],
    )
    rejected = [r for r in cached.values() if r["verdict"] == "REJECTED"]

    print(f"\n{len(viable)} viable, {len(rejected)} rejected\n", file=sys.stderr)
    print("{:<26} {:>6} {:>8}  {}".format("mechanic", "score", "conf", "top reason"), file=sys.stderr)
    for row in viable[:15]:
        skill = row["dimensions"].get("skill_expression", {})
        print(
            "{:<26} {:>6.2f} {:>8}  {}".format(
                row["mechanic_id"][:26],
                row["convertibility"],
                row["confidence"],
                (skill.get("justification") or "")[:60],
            ),
            file=sys.stderr,
        )
    if rejected:
        print("\nrejected:", file=sys.stderr)
        for row in rejected:
            print(
                f"  {row['mechanic_id']}: failed {', '.join(row['failed_gates'])}",
                file=sys.stderr,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
