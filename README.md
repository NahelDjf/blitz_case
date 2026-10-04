# GameSonar

**Identifying emerging mechanics or genres — App Store opportunity discovery for Blitz.**

GameSonar ranks the game mechanics charting in the US App Store by how convertible
they are into a Blitz cash tournament, and explains every verdict with evidence.

It is not a trends dashboard. A trends dashboard would put merge games and survival
4X at the top of this week's list — they are the two highest-demand mechanics in the
dataset. GameSonar scores both at **zero**, because neither can be run as a fair
head-to-head contest. That rejection is the product.

The output on the 2026-10-03 snapshot:

| | |
|---|---|
| **25** mechanics | could be run as a tournament |
| **17** mechanics | fail a structural gate, whatever their demand |
| **1** mechanic | a rival already monetises that Blitz does not operate |

Two findings a designer could act on this week:

- **Mahjong tile match** — two cash competitors already run it (*Mahjong Rumble*,
  *Mahjong Clash*), it charts at #8 free, convertibility 0.86, and Blitz does not
  operate it. Somebody has already done to Mahjong what Blitz did to Pool.
- **Logic deduction grid** (sudoku-type) — **#1 free**, only two charting apps, no
  cash competitor, convertibility 0.87. The highest-upside, thinnest-evidence
  candidate in the data.

---

## Table of contents

- [How to run the project](#how-to-run-the-project)
- [What it does](#what-it-does)
- [Key product decisions](#key-product-decisions)
- [Key technical decisions](#key-technical-decisions)
- [How the scoring is evaluated](#how-the-scoring-is-evaluated)
- [Known limitations](#known-limitations)
- [What I would build with one more week](#what-i-would-build-with-one-more-week)
- [Time spent](#time-spent)

---

## How to run the project

**Standard library only — including the API client.** The whole project runs on a bare
Python 3 interpreter. No `pip install`, no `requirements.txt`, no virtualenv. All data
is committed to this repository.

```bash
git clone https://github.com/NahelDjf/blitz_case.git
cd blitz_case
open app.html          # macOS;  xdg-open app.html on Linux;  start app.html on Windows
```

`app.html` is a single self-contained file. Double-clicking it works. That is the
whole application.

### Rebuilding from the committed data

Deterministic, free, instant — no API calls:

```bash
python3 scripts/aggregate_mechanics.py --chart-date 2026-10-03
python3 scripts/build_scores.py
python3 scripts/build_ui.py
```

Requires Python 3.9+ and **nothing else**. No `pip install`, no virtualenv. Every
script uses only the standard library, including the Anthropic API client.

### Refreshing from Apple and re-scoring

Needs an API key. Costs about $8 for a cold run; re-runs are near-free because every
stage caches.

```bash
export ANTHROPIC_API_KEY="sk-ant-..."

python3 scripts/collect_charts.py           # chart snapshot, 6 storefronts x 3 charts
python3 scripts/enrich_apps.py              # app metadata via the batched lookup API
python3 scripts/fetch_reviews.py            # up to 500 reviews per in-scope app (~30 min)
python3 scripts/classify_mechanics.py       # apps -> mechanics          (Sonnet, ~$0.30)
python3 scripts/score_voice.py              # reviews -> signals         (Haiku,  ~$5)
python3 scripts/score_convertibility.py     # mechanics -> rubric x3     (Opus,   ~$3)
python3 scripts/aggregate_mechanics.py
python3 scripts/build_scores.py
python3 scripts/build_ui.py
```

Pass `--chart-date YYYY-MM-DD` to pin a run to one snapshot. Every script supports
`--limit` for a cheap smoke test and prints its own token usage and cost estimate.

**macOS note:** python.org builds ship without a certificate bundle. If you see
`CERTIFICATE_VERIFY_FAILED`, run `/Applications/Python\ 3.x/Install\ Certificates.command`.

### Using the interface

Three views over one detail panel:

| View | What it answers |
|---|---|
| **Matrix** | Convertibility against market opportunity, on one screen. Dot size is carrier count; colour marks rival-operated, Blitz-operated, or open. |
| **List** | The same mechanics ranked, with every score component visible. |
| **Eliminated** | The 17 mechanics that failed a gate, and which gate each one failed. |

The **weight sliders** recompute the ranking live. They exist because the ranking is
the least reliable output in the tool, and a ranking you can move is honestly
presented — see [Known limitations](#known-limitations).

---

## What it does

```
Apple public feeds          GameSonar pipeline                       Output
─────────────────           ──────────────────                       ──────
charts RSS      ─┐
lookup API      ─┼─► collect → enrich → reviews ─┐
reviews RSS     ─┘                               │
                                                 ├─► classify (LLM)
                   data/charts/*.jsonl           ├─► voice      (LLM)   app.html
                   data/apps/metadata.jsonl      ├─► rubric x3  (LLM)   scores.jsonl
                   data/reviews/{app}.jsonl      ├─► aggregate  (free)
                                                 └─► composite  (free)
```

**Scored unit: the mechanic, not the app.** Apps are evidence; mechanics are what
gets ranked. Ranking apps would produce a leaderboard, which Blitz can already read
for free on the App Store. "Block-fit placement" is a scoreable unit with several
carrier apps behind it.

**Four components, combined so convertibility can veto.**

```
blitz_score = convertibility × ( w₁·demand + w₂·openness + w₃·frustration )
```

Convertibility is a **multiplier, not a term**. Fail a gate and the score is zero,
regardless of demand. This single line of arithmetic is the entire thesis.

**A daily GitHub Action** (`.github/workflows/collect-charts.yml`) snapshots the
charts at 06:17 UTC and commits the result back to this repository. It has been
running since the first commit, because rank history cannot be backfilled. You will
therefore see commits landing after the submission date — that is deliberate, and it
is what makes the momentum work in [next steps](#what-i-would-build-with-one-more-week)
provisioned rather than hypothetical.

---

## Key product decisions

### 1. "Promising" is defined against Blitz's business, not in the abstract

> A promising mechanic is one already demonstrating demand on the App Store, not yet
> saturated, **and convertible into a short, fair, head-to-head skill contest** — the
> only format Blitz can monetize.

Blitz is a real-money skill-gaming platform, not a studio. It does not need to know
which RPG is growing. It needs to know which mechanics can be turned into a seeded,
score-comparable, sub-three-minute tournament. Everything in the tool follows from
that.

### 2. The gates are **symmetric randomness**, not determinism

The critical criterion. Blitz's own site says it best:

> *Compete on a level playing field where every player faces the exact same challenge.*

So the question is **not** "is this mechanic random?" — Solitaire has a shuffled deal
and Bingo has drawn numbers, and Blitz runs both. The question is whether **both
players can be handed an identical randomised instance**, so variance cancels and the
score gap is skill.

That distinction decides real cases:

| Mechanic | Deterministic? | Symmetric? | Verdict |
|---|---|---|---|
| Solitaire | No — shuffled deal | **Yes** — same shuffle to both | Viable (0.88) |
| Poker | No | **No** — you cannot deal two opponents the same hand | Rejected |
| Survival 4X | No | **No** — opponents *are* your instance | Rejected |
| Sudoku | Yes | Yes | Viable (0.87) |

A naive "deterministic vs random" gate would have rejected half of Blitz's actual
portfolio. The second gate, **score comparability**, asks whether a round yields one
number rankable against an opponent's — which is why chess is rejected despite being
the canonical skill game.

### 3. Gates are vetoes, not weights

Two of the eight rubric dimensions are gates. Fail one and the mechanic is reported
as REJECTED with the failing gate named. They are never averaged in, because a
mechanic that cannot be run fairly is not *partly* convertible. The remaining six
dimensions sum to 1.0, with `skill_expression` weighted highest at 0.25.

### 4. Competitor carriers are counted separately from ordinary carriers

Same data, opposite meaning. An ordinary carrier is evidence of **saturation**; a
cash-tournament carrier is evidence the **conversion works**. Blended, Mahjong looks
crowded. Split, it reads as proven demand with two rivals already live — which is the
most actionable line in the whole output.

This produces four groupings, which matter more than the ranking because each implies
a different decision: *already operated*, *proven by a competitor* (fast follow),
*open and established* (build), *open and emerging* (watch).

### 5. Rejections are shown, never hidden

`casino_slots` and `location_ar` are kept in the taxonomy specifically so the tool can
reject them with a reason. An explicit "rejected because players cannot share an
instance" is more useful to a designer than silent omission. The Eliminated view is a
feature, not an appendix.

### 6. US-only analysis, six-storefront collection

Blitz's cash games are US-only with state restrictions, so ranking a mechanic on
Japanese chart performance would be ranking an opportunity Blitz cannot sell.
Collection stayed wide because the marginal cost is twelve HTTP requests a day on a
machine that is not mine.

### 7. `top_paid` is collected but excluded from scoring

Premium monetisation is *opposed* to Blitz's, not merely different: a player paying
upfront is buying out of ads and IAP. The chart is also IP-dominated, session-long,
and barely moves month to month — so as a *trend* source it contributes nothing.
Collection continues because the counter-argument is real and deserves its own study.

---

## Key technical decisions

### Standard library only — including the API client

"A working application, easy to run locally" is a grading criterion, and dependency resolution is the most common way that fails on
someone else's machine. The retry and backoff logic an SDK would provide lives in
`scripts/common.py`.

### A static HTML file rather than a server

Baking the data into `app.html` means it opens on a double-click, works offline, and
cannot fail because of an environment difference. The risk is duplicating the scoring
logic in two languages where they can drift — avoided by precomputing all four
components in Python and leaving the page only the final weighted sum, four
multiplications.

### Dual-source collection with fallback

Apple publishes two incompatible chart feeds. The **legacy** endpoint supports genre
filtering (6014 = Games) and is the only one publishing top-grossing — the chart that
proves payers exist. The **v2** endpoint is current but dropped genre filtering.
We prefer legacy, fall back to v2, and record which source answered on every row.

### Pinned runs and loud coverage reporting

Each pipeline stage originally resolved "the newest chart" independently, and the
daily Action moved that target mid-build — the aggregation silently analysed one day's
162 apps using the previous day's classifications. Three fixes, all shipped:

1. `--chart-date` on every stage, so a run is reproducible.
2. The aggregation **prints coverage** — apps in scope, apps fully covered, and the IDs
   of any missing metadata or a mechanic.
3. Cached stages are re-run when the universe shifts; all of them skip what they
   already have.

### Raw data is immutable and committed

Fetch, normalise, store. All scoring recomputes from raw JSONL, so changing a weight
never re-fetches. ~36 MB of reviews are committed deliberately so a reviewer can run
the app in thirty seconds instead of waiting for a scrape against an unsupported
endpoint.

### Resilience the data forced

The reviews feed intermittently returns a **valid but empty** response under load,
indistinguishable from an app genuinely having no reviews. Six of 164 apps were
affected on the first run, including 8 Ball Pool (4.8M ratings) — one of the
known-positive mechanics. Caching that empty result would have frozen a permanent
hole. The fix: retry with a pause and an alternate sort, **only when the previous page
was full** (an exhausting feed returns a partial page first), and never cache an empty
result. ~30 recoveries fired on the full run.

---

## How the scoring is evaluated

Scoring that cannot be checked is an opinion with a number attached.

**Known positives** — mechanics Blitz already operates must score high:

| Mechanic | Convertibility | Result |
|---|---|---|
| Solitaire card play | 0.88 | pass |
| Cue sports | 0.82 | pass |
| Bingo / number draw | 0.80 | pass |
| Block-fit placement | 0.78 | pass |
| Match-3 swap | 0.73 | pass |

**Known negatives** — high demand must not rescue them:

| Mechanic | Demand | Score | Blocked by |
|---|---|---|---|
| Merge with meta-progression | 0.95 | **0** | symmetric randomness, score comparability |
| Survival 4X | 0.94 | **0** | symmetric randomness, score comparability |
| Shooter / battle royale | 0.86 | **0** | symmetric randomness |
| Dice-roll board raid | 0.81 | **0** | symmetric randomness, score comparability |

**Self-consistency.** Every mechanic is scored three times; the median is reported and
the spread drives a confidence badge. Spread was 0–1 on almost every dimension. Where
it was higher it was informative rather than noisy — `casino_slots` round length came
back 3/5/3, the model genuinely torn between "a spin takes seconds" and "there is no
round at all." A `temperature` parameter was not supported by
the models used, so this measures judgement stability rather than decoder determinism,
which is closer to what the metric is for.

**Groundedness.** Every rubric dimension returns a score, a justification, and the
`app_id` of a carrier supporting it. All three are visible in the interface.

### The one case where evaluation disagreed with ground truth

`territory_io` (Paper.io-style) was in my known-positive list and the rubric **rejected
it** on symmetric randomness — a shared .io board means the opponent's expansion *is*
your instance, so no identical instance exists.

Investigating, the rubric was right and my ground truth was imprecise. Blitz's
portfolio list conflated two different relationships: mechanics it **runs as cash
tournaments** (block-fit, solitaire, bingo, pool, match-3) and mechanics it uses as
**acquisition reference points** because players recognise them from ads. The list is
now split in `rubric.json`, and only the first is the benchmark.

---

## Known limitations

Most were found by measuring rather than by guessing.

**Data**

1. **Review volume comes from `userRatingCount`, never from the review files.** The
   pull is capped at 500 per app and ~70% of apps hit it, so the time span covered
   varies from hours to weeks. Rates over the sample are valid; counts would be
   measuring the cap.
2. **One day of data.** Momentum features are defined but unpopulated — rank deltas do
   not exist on a single snapshot.
3. **Three apps resist classification** (NoomiClone, Lordrush, 82-0.com) and are hand-labelled in data/overrides.json, applied visibly and stamped human_override. NoomiClone is deliberately left as unclassified — 318 ratings inside the US top 100 is a chart anomaly rather than a mechanic.

**Measurement**

4. **Mean star rating is reported but not scored.** The observed range across 44
   mechanics is 4.0–4.93, nearly all between 4.6 and 4.9 — App Store ratings are
   compressed by prompt-gating. The "high rank + mediocre rating = unmet demand"
   heuristic has no signal to detect. Cut after measuring it.
5. **Latent competitive demand is a measured null.** I expected reviews to show players
   asking for head-to-head play. Across six probe apps including the two largest solo
   puzzles on the chart, `wants_competition` was **0%**. The base rate is under 1% —
   too rare to score. What players *do* say, at 12–43% for ads, 6–26% for paywalls and
   3–16% for perceived cheating, reframes the opportunity: the wedge is not "come
   compete", it is "no ads, no bots, real stakes". Which is, independently, how Blitz
   already positions itself.
6. **Aggregate review sentiment is not used.** Reviews are pulled most-recent-first and
   unhappy players review more promptly, so the sample skews negative unevenly. Named
   signals are robust to that skew; a mood score is not.
7. **Voice signals need ≥50 reviews**; thin apps are marked insufficient rather than
   scored, and mechanic rates pool across carriers weighted by review count.
8. **US-storefront reviews are substantially multilingual.** Signals are classified by
   LLM rather than keyword matching, which would silently undercount Spanish.

**Judgement**

9. **Convertibility is judged from store descriptions, not from playing the games.**
    It will be wrong about round length and seeding in individual cases.
10. **`chance_framing` is mildly circular.** Solitaire and Mahjong both score 2 partly
    *because* cash carriers exist, so the competitor's marketing makes the mechanic
    look more gambling-adjacent. The most convertible mechanics systematically carry a
    slightly elevated risk flag.
11. **The single ranked list is the least reliable output in the tool.** The groupings
    carry more signal than the order, because a fast follow and an early bet are
    different decisions rather than different scores. One formula is answering four
    questions. The weights (0.40 / 0.35 / 0.25) are a judgement call with no ground
    truth behind them — which is why they are sliders rather than constants, and why
    the interface leads with groupings.

---

## What I would build with one more week

Ordered by value. The first two need **elapsed time**, which is why collection started
on day one rather than when the analysis was written.

1. **Momentum from accumulated snapshots.** Every demand feature today is a static
   photograph. Joining all `data/charts/*.jsonl` against the existing assignments turns
   "sort puzzles are big" into "sort puzzles gained 14 positions in 7 days while
   match-3 lost 3". ~40 lines, no new API spend, data already accruing.
2. **Cross-market lead/lag.** Six storefronts are being collected. Does a mechanic break
   in BR or JP before the US, and by how long? A study of how closely each market
   correlates with the US one would help here too. A confirmed leading indicator would
   outweigh everything in the current score.
3. **Backtesting, and weights learned rather than asserted.** With 3–4 weeks of history,
   score the charts as they stood at T−3 weeks and check whether the favoured mechanics
   actually rose. This is the only route to defensible weights.
4. **Quadrant-specific scoring.** Replace one global formula with a ranking per
   grouping, since "fast-follow a validated rival" and "bet early on two carriers" do
   not share a weighting.
5. **The top_paid study.** Which mechanics do players pay for unprompted, with no
   ad-pressure confound, and do any clear the convertibility bar? Data already
   collected.
6. **Screenshot vision analysis** for convertibility, instead of marketing copy that
   systematically overstates depth.
7. **Google Play cross-check**, to separate genuine mechanic trends from iOS-specific
   chart artefacts.

---

## Time spent

**~4 hours.**

The chart collector was written first and deployed before anything else, because rank
history is the one input that cannot be recovered later. Data collection has therefore
been running longer than the analysis took to write — deliberately.

Where the time went: roughly a third on the pipeline, a third on the taxonomy and
rubric (the two artifacts that carry the product judgement), and a third on scoring
and the interface. The decision log in [`DECISIONS.md`](DECISIONS.md) was written
during the build, and most of this README is condensed from it.

---

## Repository layout

```
app.html                        the application — open it directly
DECISIONS.md                    decision log written during the build
data/
  taxonomy.json                 46 mechanics, hand-seeded from the live US charts
  rubric.json                   8 dimensions with 1–5 anchors, gates, weights
  overrides.json                hand-labelled corrections, applied visibly
  charts/YYYY-MM-DD.jsonl       daily snapshots, committed by the GitHub Action
  apps/metadata.jsonl           app metadata
  reviews/{app_id}.jsonl        up to 500 reviews per in-scope app
  voice/{app_id}.json           classified review signals
  mechanics/*.jsonl             assignments, features, convertibility, final scores
  _runs.jsonl                   per-feed status and errors for every collector run
scripts/
  common.py                     shared HTTP, retry and JSONL helpers
  collect_charts.py             chart snapshots (runs daily in CI)
  enrich_apps.py                batched metadata lookup
  fetch_reviews.py              review puller with empty-response recovery
  classify_mechanics.py         apps → mechanics
  score_voice.py                reviews → signals
  score_convertibility.py       mechanics → rubric, 3 runs each
  aggregate_mechanics.py        deterministic mechanic-level features
  build_scores.py               composite ranking
  build_ui.py                   generates app.html
.github/workflows/
  collect-charts.yml            daily snapshot at 06:17 UTC
```

Data from Apple's public RSS and lookup endpoints. Mechanic assignment and
convertibility scoring by Claude against the published rubric in `data/rubric.json`.
