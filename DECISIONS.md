# Decisions & assumptions

Working log kept during the build of GameSonar. Decisions were written down when they
were made, not reconstructed at the end, so several entries record things that turned
out to be wrong.

The [README](README.md) is the deliverable and condenses this. This file keeps the
detail the README compresses: the alternatives considered, the numbers measured, and
the three places where the evidence contradicted an assumption and the assumption
changed.

---

## 1. The problem

**A promising mechanic is one already demonstrating demand on the App Store, not yet
saturated, and convertible into a short, fair, head-to-head skill contest — the only
format Blitz can monetize.**

GameSonar does not invent games. It ranks mechanics visible in chart data by how
convertible they are into a Blitz tournament, and explains every verdict.

Two consequences, both deliberate:

- A mechanic with strong demand and low convertibility (survival 4X, merge) is
  **correctly rejected**, though a generic trends tool would surface it as a top
  opportunity. That rejection is the product.
- "New" means new *to Blitz's portfolio*, not new to the world. Blitz's edge is
  operating familiar mechanics as cash tournaments, so an old mechanic nobody has
  converted beats a genuinely novel genre.

## 2. Scored unit: the mechanic, not the app

Apps are evidence; mechanics are what gets ranked. Ranking apps would produce a
leaderboard, which Blitz can already read for free on the App Store.

An app carries at most two mechanics. It counts fully toward its primary and is
recorded against its secondary with a flag, so hybrid-casual titles are visible
without inflating every mechanic they touch. The cap is arbitrary and probably too
tight for hybrid titles that deliberately stack loops — Gardenscapes is match-3 inside
a renovation meta, and a third loop would not be surprising.

**Evidence tiers.** A mechanic needs **≥3 carriers** to be scored on demand and
saturation; below that, publisher concentration and carrier-age statistics are
meaningless. Mechanics with 1–2 carriers go to a **watchlist**: convertibility-scored,
with demand and openness marked weakly evidenced.

The tail is kept rather than discarded, and it earned that. On the 2026-10-03
snapshot `logic_deduction` sits at **#1 free with two carriers** and scores 0.87 on
convertibility — the highest-upside candidate in the data, and invisible to any tool
that requires a minimum carrier count to appear at all.

## 3. Where the data comes from

Free, keyless, public HTTP endpoints served by Apple. No market-intelligence vendor,
no SDK, no account. Everything joins on Apple's numeric app ID.

| Endpoint | Answers | Note |
|---|---|---|
| `itunes.apple.com/{cc}/rss/{chart}/limit=N/genre=6014/json` | What is ranked today? | Primary. Genre-scoped to Games and the only source publishing top-grossing. Undocumented, so best-effort. |
| `rss.marketingtools.apple.com/api/v2/...` | Same, fallback | Current feed, but dropped genre filtering and publishes no grossing chart. |
| `itunes.apple.com/lookup?id=...` | What is this app? | Batched: comma-separated IDs, ~700 apps in ~7 requests. |
| `itunes.apple.com/{cc}/rss/customerreviews/...` | What do players say? | 50 per page, 10 pages max. |

A **daily GitHub Action** snapshots the charts at 06:17 UTC — an odd minute, because
jobs queued at :00 are the most delayed under load — and commits the result back to
the repo. It started before the analysis was written, because rank history cannot be
backfilled.

Reviews (~36 MB) are committed deliberately. "Easy to run locally" is a grading
criterion, and an app that needs a 30-minute scrape against an unsupported endpoint
before it renders anything does not meet it.

## 4. Scope: collection vs analysis

Deliberately different, because rank history cannot be backfilled but can be ignored
at analysis time for free.

**Collection (wide, daily):** 6 storefronts × 3 charts, Games genre, top 100 each.

**Analysis (narrow):** US only, top_free and top_grossing only, one pinned snapshot.

- **US only** — the only market where Blitz's cash games operate, and even there state
  restrictions apply. Ranking a mechanic on Japanese chart performance would be
  ranking an opportunity Blitz cannot sell.
- The extra storefronts cost ~12 requests a day on a machine that isn't mine, so the
  cross-market work in §10 is provisioned rather than hypothetical.

### Why top_paid is collected but excluded from scoring

- **Monetisation is opposed, not merely different.** A player paying upfront is
  explicitly buying out of ads and IAP. Blitz is deposit-driven.
- **Session structure.** The paid chart is campaign, sandbox and simulation titles
  played for hours across weeks. The bar is a 1–3 minute seeded round.
- **It is an IP chart**, skewed to franchises whose mechanics cannot be reused without
  the brand that sells them.
- **It barely moves** month to month, so as a *trend* source it contributes nothing.
- **Scale.** Paid download volume is a rounding error against free.

The counter-argument is real — top_paid shows what players pay for unprompted, with no
ad-pressure confound — so collection continues and it gets its own study in §10.

### Also out of scope

Google Play (a second taxonomy and scraper for marginal gain); download and revenue
estimates (paid data); ad creative and UA intelligence (a different product); building
a game (the output is a ranked brief).

## 5. One pinned snapshot, and the bug that forced it

The universe is the apps charting on **one** day, pinned to `2026-10-03`.

**Latest rather than union:** a mechanic that charted last week and does not today is
not an opportunity worth routing a designer toward. Historical snapshots serve
momentum, not membership. It also keeps enrichment bounded and the dataset legible —
one universe, one `captured_at`, one set of claims.

**Pinned rather than "newest on disk"** because of a real failure. Every stage
originally resolved the latest chart independently, and the daily Action moved that
target underneath them mid-build: the aggregation analysed one day's 162 apps using
the previous day's 164 classifications, silently. Three fixes:

1. `--chart-date` on every stage, so a run is reproducible.
2. The aggregation **reports coverage** — apps in scope, apps fully covered, and the
   IDs of anything missing metadata or a mechanic.
3. Cached stages are re-run when the universe shifts; all of them skip what they have.

This is the kind of bug that only appears once a pipeline runs on a schedule rather
than once by hand.

## 6. The taxonomy was corrected twice by its own failures

Started at 38 mechanics, hand-seeded from the live US top 100 rather than invented in
the abstract — mechanics are defined by the loop the player repeats, not by theme, so
Gossip Harbor and Merge Mansion are one mechanic despite different art.

The classifier's `other` bucket then exposed real gaps, twice:

- **Round 1** (12 unclassified): location-based AR, tap-to-blast (genuinely distinct
  from match-3 swap — no swapping, different skill expression), poker, precision aim,
  jigsaw, dress-up. → 44 mechanics.
- **Round 2**: idle/incremental, seeded empty in anticipation. → 46.

Three apps still resist classification (NoomiClone, Lordrush, 82-0.com) and are
handled by `data/overrides.json`, applied visibly and stamped `human_override` rather
than blended in. 82-0.com matters because it is one of the cash competitors; leaving
it in `other` would undercount the headline finding.

Keeping `casino_slots` and `location_ar` in the taxonomy is deliberate: the tool
should reject them **with a reason** rather than never consider them.

## 7. Scoring design

### Symmetric randomness, not determinism

This criterion changed during the build, and the change came from a question about
poker.

The first draft had a `determinism` dimension. That is wrong, and it would have
rejected half of Blitz's actual portfolio: Solitaire has a shuffled deal, Bingo has
drawn numbers, and Blitz runs both. What makes those work is that the randomness is
**symmetric** — both players get the identical deal or draw, so variance cancels and
the score gap is skill.

Poker cannot do that. You cannot deal two opponents the same hand; the asymmetry *is*
the game. Hence the gate as written:

> Can both players face an identical randomised instance — same seed, same deal, same
> sequence — so that luck cancels and the score gap reflects skill alone?

Blitz's own site states the same requirement: *"compete on a level playing field where
every player faces the exact same challenge."* The criterion is theirs, not mine.

### Gates are vetoes, not weights

`symmetric_seeding` and `score_comparability` are gates. Fail one and the mechanic is
REJECTED with the gate named. They are never averaged in, because a mechanic that
cannot be run fairly is not *partly* convertible. The other six sum to 1.0, with
`skill_expression` highest at 0.25 — it is what makes the product skill gaming rather
than gambling.

`score_comparability` turns out to be the more surprising gate: it rejects **chess**,
the canonical skill game, because win/loss has no margin and produces unbreakable ties
at scale. Correct, and not something I would have predicted.

### Gambling adjacency on its own axis

Not folded into convertibility, because it is a brand and compliance risk rather than
a design property. A mechanic can be provably skill-based and still read as a casino
product to a platform reviewer, and Blitz positions explicitly away from a "win big"
pitch.

Known weakness: it is mildly circular. Solitaire and Mahjong both score 2 partly
*because* cash carriers exist, so a competitor's marketing makes the mechanic look
more gambling-adjacent. The most convertible mechanics therefore carry a slightly
elevated flag.

### Competitor carriers counted separately

Same data, opposite meaning. An ordinary carrier is evidence of **saturation**; a
cash-tournament carrier is evidence the **conversion works**. Blended, Mahjong looks
crowded; split, it reads as proven demand with two rivals live.

The flag is derived deterministically, not classified — either mechanic slot being
`skill_cash_arcade`, or a title matching "win real cash/money". Auditable, free, and
the rule can be read.

`skill_cash_arcade` is excluded from the scored set because it is not a gameplay loop
at all: Triumph Arcade and Playtest Pro are tournament wrappers around other people's
mechanics. They are competitors, not opportunities.

### The composite

```
blitz_score = convertibility × ( 0.40·demand + 0.35·openness + 0.25·frustration )
```

Convertibility multiplies rather than adds, so a gate failure cannot be rescued by
demand. Within demand, grossing rank outweighs free rank (0.45 vs 0.30) because
grossing proves payers exist, which is what a deposit product needs. Rank is
square-rooted, not linear — #1 vs #5 is a far bigger gap than #50 vs #55, and rank is
ordinal anyway.

## 8. Three things measurement contradicted

**Mean star rating is reported but not scored.** The plan was "high rank + mediocre
rating = unmet demand". Measured across 44 mechanics the range is 4.0–4.93, nearly all
between 4.6 and 4.9 — App Store ratings are compressed by prompt-gating. There is no
signal to detect. Cut, and unmet demand taken from review text instead.

**Latent competitive demand is a measured null.** The expectation was that reviews
would show players asking for head-to-head play. Across six probe apps including the
two largest solo puzzles on the chart, `wants_competition` came back at **0%**; the
base rate is under 1%, far too rare to score on a 250-review sample.

What players *do* say is more useful: ads 12–43%, paywall 6–26%, unfair 3–16%. So the
opportunity is not *"players want competition"* but *"players are exhausted by ads and
paywalls and a meaningful minority believe the games cheat them."* The wedge is "no
ads, no bots, real stakes" — which is, independently, how Blitz already positions
itself.

Two quotes worth keeping. *"I downloaded it because the ad showed it was a game where
you go against someone, when I played it wasn't even the same"* — UA creative already
sells competition these games don't deliver. And *"we play the game not to compete
with others, it does become stressful"* — a genuine counter-signal that part of this
audience actively does not want competition.

**The label had to be split.** The first `competitive` label fired on Golf Clash
matchmaking complaints, which is the opposite of latent demand. Now two labels:
`wants_competition` (asks for what is absent) and `has_competition` (evidence the
mechanic already supports head-to-head). 8 Ball Pool validates the split: 8% has, 0%
wants.

**Aggregate sentiment is not used at all.** Reviews are pulled most-recent-first and
unhappy players review more promptly, so the sample skews negative unevenly. Named
signals survive that skew; a mood score does not.

## 9. Technical decisions

- **Standard library only, including the API client.** Nothing to install; the project
  runs on a bare Python 3 interpreter. Dependency resolution is the most common way
  "run it locally" fails on someone else's machine.
- **A static HTML file rather than a server.** Opens on a double-click, works offline,
  cannot fail on an environment difference. The risk — duplicating scoring logic in
  two languages where they drift — is avoided by precomputing all four components in
  Python and leaving the page only the final weighted sum.
- **Model routing: cheap on volume, expensive on judgement.** Haiku 4.5 for review
  classification (~95% of token volume, near-zero judgement, $4.73), Sonnet 5.5 for
  mechanic extraction ($0.31), Opus 5.5 for the rubric and pitches ($2.96). One model
  throughout would either overpay on volume or underperform on scoring.
- **Prompt caching, measured.** Taxonomy and rubric are ~1,900-token cached prefixes:
  76,380 tokens read from cache against 3,819 written on the classification run, 162
  apps for $0.29. It did *not* engage on the review pass — that system prompt is below
  the minimum cacheable length.
- **Raw snapshots are immutable.** All scoring recomputes from raw JSONL, so changing
  a weight never re-fetches.
- **Partial failure is not job failure.** The collector exits non-zero only when every
  feed fails — the signal that Apple's APIs moved.
- **Scoring criteria live in `data/rubric.json`**, not inside a prompt string, so they
  can be reviewed, versioned and argued with as an artifact.
- **Invented mechanic IDs are coerced to `other` and logged.** A model inventing a
  category is a taxonomy gap for a human to review, not a new class appearing
  unannounced.
- **`data/_runs.jsonl`** records per-feed status and errors for every collector run,
  union-merged via `.gitattributes` so the daily Action never conflicts with local
  work.
- **macOS:** python.org builds ship without a certificate bundle; without
  `Install Certificates.command` every HTTPS call fails with `CERTIFICATE_VERIFY_FAILED`.

### Resilience the data forced

The reviews feed intermittently returns a **valid but empty** response under load,
indistinguishable from an app genuinely having no reviews. Six of 164 apps were
affected on the first run, including 8 Ball Pool (4.8M ratings) — a known positive
that would have been silently lost.

Caching an empty result freezes a permanent hole, so: retry with a pause and an
alternate sort order, **only when the previous page was full** (an exhausting feed
returns a partial page first, so an exact multiple of 50 is the suspicious case), and
never cache an empty result. ~30 recoveries fired on the full run.

## 10. Interface decisions

- **Groupings lead, the number sorts within them.** The single ranked list is the
  least reliable output in the tool: one formula is answering four different
  questions, and "fast-follow a validated rival" and "bet early on two carriers" do
  not share a weighting. Leading with groupings makes that structural rather than a
  caveat the reader has to notice.
- **Weights are sliders, not constants.** 0.40/0.35/0.25 is a judgement call with no
  ground truth behind it. A ranking you can move is honestly presented; one you can't
  is a claim.
- **Every score shows its components.** No composite without its decomposition, so
  "logic deduction ranks 12th because breadth is 2 of 8" is visible rather than buried.
- **Eliminated mechanics are a view, not a strip below the matrix.** First built as a
  strip; it failed in use, because a section below the fold cannot share a detail
  panel above it — selecting a mechanic meant scrolling up to read it. As a view with
  its own table (mechanic, apps, best rank, demand, gate failed), nothing scrolls.
- **The y-axis runs 0.50–1.00.** Nothing scores below it; plotting 0–1 wasted half the
  chart.
- **Colour and type follow Blitz's own site** — deep violet, gold from the logo,
  Barlow Condensed and Archivo. Green marks mechanics Blitz operates and pink marks
  rival-operated ones, taken from their fairness chart where green is "You" and pink
  is an opponent. The ground uses their panel violet rather than the full-brightness
  hero colour, which is built for large marketing type, not dense data.

## 11. Evaluation

Scoring that cannot be checked is an opinion with a number attached.

- **Known positives pass.** Solitaire 0.88, cue sports 0.82, bingo 0.80, block-fit
  0.78, match-3 0.73 — all in the viable set.
- **Known negatives rejected.** Merge (demand 0.95), survival 4X (0.94), battle royale
  (0.86), dice-roll board raid (0.81) all score zero.
- **Self-consistency.** Three runs per mechanic; median reported, spread drives a
  confidence badge. Spread was 0–1 almost everywhere. Where higher it was informative:
  `casino_slots` round length came back 3/5/3, the model genuinely torn between "a
  spin takes seconds" and "there is no round at all". A `temperature` parameter was
  not supported by the models used, so this measures judgement stability rather than
  decoder determinism — closer to what the metric is for.
- **Groundedness.** Every dimension returns a score, a justification and a supporting
  `app_id`, all three visible in the interface.

### Where evaluation disagreed with ground truth

`territory_io` was in the known-positive list and the rubric **rejected** it on
symmetric randomness: a shared .io board means the opponent's expansion *is* your
instance.

The rubric was right and the ground truth was imprecise. The portfolio list conflated
mechanics Blitz **runs as cash tournaments** with mechanics it uses as **acquisition
reference points** because players recognise them from ads. Both relationships are
real; only the first is a benchmark. `rubric.json` now splits
`operated_mechanics` from `ua_reference_mechanics`.

## 12. What a further week would buy

Ordered by value. The first two need **elapsed time**, which is why collection started
on day one.

1. **Momentum from accumulated snapshots.** Every demand feature today is a static
   photograph. ~40 lines, no new API spend, data already accruing.
2. **Cross-market lead/lag**, plus a study of how closely each market correlates with
   the US. A confirmed leading indicator would outweigh everything in the score.
3. **Backtesting, and weights learned rather than asserted.**
4. **Quadrant-specific scoring** — one ranking per grouping instead of one global
   formula.
5. **The top_paid study** (§4).
6. **Screenshot vision analysis** instead of marketing copy that overstates depth.
7. **Google Play cross-check.**

## 13. Open questions

- The weights need either Blitz's own portfolio performance or a hand-ranked reference
  set to be defensible rather than asserted.
- Whether two mechanics per app is too tight for hybrid-casual titles.
- Whether `logic_deduction` at #1 free with two carriers is a genuine breakout or a
  chart artefact. The watchlist tier exists precisely because the tool cannot yet tell.
- Whether `mahjong_tile_match` scoring only 0.45 on demand is real or a measurement
  artefact: its cash carriers monetise outside App Store IAP, so they are invisible to
  the grossing chart that demand leans on.
