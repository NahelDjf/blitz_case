# Part I — Data Analytics

**Improving deposit performance at Blitz.**

1,060 deposit attempts, January 2022, across Apple Pay, PayPal and bank card.

Reproduce with `python3 data_analytics.py` (requires pandas).

---

## Headline

| | |
|---|---|
| Transactions | 1,060 |
| Successful | 804 |
| Failed | 256 |
| **Success rate** | **75.85%** |

**One in four deposit attempts fails.** For a platform whose revenue starts with a
deposit, that is the headline number — and it is not evenly distributed.

---

## 1. Failure is concentrated in one payment method

| Method | Transactions | Success % | Failure % |
|---|---|---|---|
| Apple Pay | 340 | 81.47 | 18.53 |
| PayPal | 367 | 80.93 | 19.07 |
| **Card** | **353** | **65.16** | **34.84** |

Apple Pay and PayPal are statistically indistinguishable at ~19%. Card fails at
**34.84%** — nearly twice as often.

---

## 2. Failure also rises with amount — but only apparently

Average amount of a failed transaction: **40.45**, against 31.1 for a successful one.

| Amount bucket | Success % | Failure % |
|---|---|---|
| Low (0–25) | 80.92 | 19.08 |
| Medium (25–50) | 77.37 | 22.63 |
| High (50–100) | 62.56 | 37.44 |

Re-bucketing into 10-unit intervals locates the step precisely:

| Bucket | Transactions | Failures | Failure rate |
|---|---|---|---|
| [0, 10) | 163 | 30 | 18.4% |
| [10, 20) | 177 | 33 | 18.6% |
| [20, 30) | 171 | 34 | 19.9% |
| [30, 40) | 276 | 65 | 23.6% |
| **[40, 50)** | 66 | 17 | **25.8%** |
| [50, 60) | 38 | 13 | 34.2% |
| [60, 70) | 37 | 14 | 37.8% |
| [70, 80) | 39 | 17 | 43.6% |
| [80, 90) | 42 | 14 | 33.3% |
| [90, 100) | 44 | 16 | 36.4% |
| [100, 110) | 7 | 3 | 42.9% |

Below 40 the failure rate sits in an 18–24% band. From [40, 50) it steps up and stays
between 33% and 44%.

| | Transactions | Failure rate |
|---|---|---|
| Amount < 40 | 787 | 20.58% |
| Amount ≥ 40 | 273 | 34.43% |

A 14-point gap. The obvious conclusion is a threshold effect around 40 — and it is
wrong.

---

## 3. The two variables are not independent

Each method operates in its own amount range:

| Method | Min | Max | Mean | Count |
|---|---|---|---|---|
| Apple Pay | 5 | 15 | 9.8 | 340 |
| PayPal | 25 | 40 | 32.5 | 367 |
| Card | 20 | 100 | 58.7 | 353 |

Apple Pay tops out at 15, PayPal at 40. **Every transaction above 40 is a card
transaction.** So "high amounts fail more" and "card fails more" are the same
observation seen twice, and the ranges barely overlap.

### Test 1 — hold the amount constant

[20, 40) is the only bucket where two methods coexist:

| Bucket | Card | PayPal |
|---|---|---|
| [20, 40) | **33.0%** (n=97) | **19.1%** (n=350) |

At identical amounts, card fails 14 points more often. **The method effect survives
controlling for amount.**

### Test 2 — hold the method constant

Within card transactions only, does failure rise with amount?

| Amount bucket | Card transactions | Failure rate |
|---|---|---|
| [20, 40) | 97 | 33.0% |
| [40, 60) | 87 | 31.0% |
| [60, 80) | 76 | 40.8% |
| [80, 100] | 93 | 35.5% |

**No trend.** It moves between 31% and 41% with no monotonic relationship to amount —
the [40,60) bucket actually fails *less* than [20,40). **The amount effect does not
survive controlling for method.**

### Conclusion

The threshold at 40 is an artefact of experimental design, not a property of the
payment system. Card has a structurally higher failure rate (~35% vs ~19%) at every
amount, and because card is the only method available above 40, that elevated rate is
inherited by the high-amount segment rather than caused by it.

**Acting on the apparent threshold — capping deposits, splitting large payments,
adding friction above 40 — would address a symptom that does not exist and would cost
revenue.** The problem to fix is card.

---

## 4. What it costs

| | Value |
|---|---|
| Total attempted deposit value | 35,951 |
| Value lost to failed attempts | 10,355 (28.8%) |
| **of which card** | **7,444 (72%)** |

Card accounts for a third of transactions and **72% of lost deposit value**, because it
carries both the worst failure rate and the largest amounts.

If card were brought to PayPal's 19.07% failure rate, roughly **56 additional
transactions per month would succeed, worth about 3,300** at card's mean amount of
58.7 — around **9% of total attempted volume**, from a single workstream.

---

## 5. Recommended actions

### Immediate — diagnose the card failures

The dataset records *whether* a payment failed, not *why*. That is the first gap to
close: instrument the card flow to capture the issuer decline code on every failure.
Without it, any fix is guesswork. The usual distribution splits roughly into:

- **Insufficient funds** — a player problem, not a platform one. Fix with clearer
  balance messaging and a retry prompt, not with engineering.
- **3-D Secure drop-off** — the most likely candidate here, since 3DS challenges are
  triggered far more often above certain amounts and are a known abandonment point.
  Fix with a frictionless-flow exemption request, a better-designed challenge screen,
  or a different acquirer configuration.
- **Issuer or acquirer decline** — fix with retry logic, a second acquirer, or
  network tokenisation.
- **Fraud-rule false positives** — our own risk engine blocking good traffic. Worth
  checking whether the rules are amount-indexed, which would reproduce exactly the
  pattern seen here.

These need different fixes, and the decline codes tell you which.

### Short term — four moves

1. **Add a card retry path.** A declined card today appears to be a dead end. A single
   automatic retry, or a prompt to try another method, recovers a meaningful share of
   soft declines.
2. **Offer Apple Pay and PayPal at higher amounts.** Both currently cap out well below
   card's range, and both run at ~19%. If that is a product constraint rather than a
   provider limit, lifting it is the fastest available improvement — though it should
   be A/B tested, since the ~19% rate is observed only at low amounts and may not hold
   at 80.
3. **Default to the best-performing method** the player has already used, rather than
   presenting card first.
4. **Rescue the failure moment.** A failed deposit is a player who wanted to play. A
   clear error message with a one-tap alternative method is cheap and converts.

### Medium term — measure properly

- **Segment by new vs returning player.** First deposits typically fail far more often
  than repeat ones, and the mix may differ by method. This dataset cannot tell them
  apart.
- **Track retry-adjusted success**, not per-attempt success. The business question is
  whether the player eventually deposits, not whether attempt #1 worked.
- **Run a controlled test** of card at high amounts versus an alternative method at the
  same amounts. The current data cannot separate the two because the ranges do not
  overlap — which is the central limitation of this analysis.

---

## 6. Limitations

- **One month of data** (January 2022), so no seasonality, trend, or
  before/after comparison is possible.
- **No failure reason.** The single most valuable missing field.
- **No player identifier**, so new-vs-returning, retry behaviour and repeat-failure
  concentration cannot be measured. A failure rate of 24% means something very
  different if it is spread across 256 players or concentrated in 40.
- **Amount ranges barely overlap across methods** — only [20, 40) has two methods
  present, which is what makes the confound hard to resolve. Everything above 40 is a
  single-method observation.
- **No geography, device, issuer or currency**, all of which are standard drivers of
  payment success.
