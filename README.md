# Operations Engineer (VIE) — Case Study

**Nahel Djeffal**

## [Part I — Data Analytics](part-1-data-analytics/)

Why one deposit in four fails, and what to do about it. 1,060 transactions across
Apple Pay, PayPal and card.

The apparent "failures rise above €40" threshold is an artefact: card is the only
method available above 40, and card fails at ~35% at *every* amount while the others
fail at ~19%. Card carries 72% of all lost deposit value. Closing that gap is worth
roughly 9% of attempted volume.

## [Part II — Product Builder: GameSonar](part-2-gamesonar/)

Option A. Identifies App Store mechanics that could be run as Blitz cash tournaments,
and rejects the ones that couldn't — including the two highest-demand mechanics in the
dataset.

The application is a single self-contained HTML file: open
[`part-2-gamesonar/app.html`](part-2-gamesonar/app.html) directly, no install, no API
key. Product and technical decisions, limitations and next steps are in its
[README](part-2-gamesonar/README.md); the working decision log is in
[DECISIONS.md](part-2-gamesonar/DECISIONS.md).
