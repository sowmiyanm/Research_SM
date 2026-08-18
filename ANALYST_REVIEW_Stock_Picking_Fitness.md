# Analyst Review — Is this good enough to pick stocks with?

**Date:** 18 Aug 2026
**Perspective:** financial analyst assessing the instrument, not the code
**Evidence:** decomposed both composite scores into their individual factors and measured firing rates and cross-correlations across 247 stocks from the backup cache.

---

## Verdict

**Good enough to generate candidates. Not yet good enough to trust the ranking, and not yet validated at all.**

The funnel is legitimate: 1,000+ stocks → stage/RS/liquidity/delivery filters → ~25 names → ~5 sitting at a buy pivot with a defined stop. That is a real screening process and the mechanics are faithful to Weinstein.

But two things a careful analyst has to know before acting on it:

1. **The composite scores are blunt instruments.** Two of the seven buy factors fire for ~85% of the market, so every stock starts with free points. Three of the ten sell factors measure the same thing and are counted separately. The exit score's red alert threshold sits at a level almost nothing reaches.
2. **Nothing has been tested against forward returns — and I can now show exactly why.** It isn't an oversight. At the current data depth the stage isn't even defined until row 152 of 192, leaving 40 days of signal history and **zero** dates with three months of future data to measure against. The system has never been testable. The backfill changes that.

---

## 1. What the accumulation score actually measures

Decomposed across 247 stocks — how often each factor fires:

| Factor | Fires |
|---|---|
| A3 delivery trend Increasing or Stable | **83.0%** |
| A5 30WMA Flat or Rising | **88.7%** |
| A7 RS > 0 | 65.6% |
| A4 price within −5%/+10% of 30WMA | 58.7% |
| A1 1-month ROC in 0–15% | 38.1% |
| A2 30-day delivery ≥ 55% | 25.1% |
| A6 volume above average 5 of last 10 days | 21.5% |

**A3 and A5 are close to constants.** "Stable" spans a ±3pp band and "Flat or Rising" catches everything except an actively falling MA — so 8 or 9 stocks in 10 collect both points regardless of merit. Every stock effectively starts at 1.7 out of 7.

The consequence shows in the distribution:

```
score:  0   1   2   3   4   5   6   7
count:  1   8  23  35  87  73  15   5
```

**65% of the universe sits at 4 or 5.** The score separates the top (20 stocks at 6–7) from the bottom, but across the bulk of the market it barely discriminates — which is precisely where you need it to.

**Good news on redundancy:** the highest pairwise correlation among the seven is only +0.39 (A5 vs A7). The factors are genuinely independent. The problem is base rates, not double-counting — and that's the easier of the two to fix.

**Mitigating point worth stating:** shortlist *membership* doesn't depend on `accum_score` at all — it filters on stage, RS, exit score, delivery and liquidity, and uses the score only for *ordering*. So this weakness degrades the ranking within the shortlist rather than letting bad names in.

## 2. What the exit score actually measures

| Factor | Fires |
|---|---|
| E4 price below 10-day MA | **60.7%** |
| E8 RS weakening | **48.2%** |
| E1 Stage 3 or 4 | 33.6% |
| E5 Lower High | 20.6% |
| E10 momentum breaking down | 19.8% |
| E3 delivery momentum declining | 16.6% |
| E9 bearish price/delivery divergence | 11.7% |
| E7 **cross below 30WMA** | 6.5% |
| E2 distribution alert | 3.6% |
| E6 RSI overbought while in Stage 3/4 | **0.8%** |

Three problems here, and they matter more than the buy-side ones because this is your risk control.

**A. The delivery-deterioration cluster is one signal counted three times.**

```
E3 (delivery momentum declining)  vs  E9 (bearish divergence)   +0.61
E2 (distribution alert)           vs  E9                        +0.47
E2                                vs  E3                        +0.44
```

E2, E3 and E9 all reduce to "delivery is falling". A stock with deteriorating delivery collects up to 3 of 10 points from what is essentially a single observation.

**B. Weighting is inverted relative to importance.** Being below a 10-day MA — a daily-noise condition that's true 61% of the time — carries the same one point as a **confirmed weekly close below the 30WMA**, which is Weinstein's primary sell trigger and fires 6.5% of the time. The most important signal in the framework is worth exactly as much as the least.

**C. The red alert is effectively unreachable.** Measured across every row of 197 stocks' full history:

```
maximum exit_score ever observed:  6   (column is labelled "of 10")
tickers that ever reach >= 6:      9 / 197  (4.6%)
```

The red highlight fires at `>= 6`. So the strongest sell warning the report can give appears for under 5% of stocks *ever*, and in the 296-stock snapshot I generated earlier the highest current reading was 5 — meaning **it did not fire for a single stock.** This is the same failure mode as the old "Stage 3 Alert" problem: a red flag that structurally can't turn red.

---

## 3. Why nothing has been validated — and when it can be

I tried to run a point-in-time forward-return test. It isn't possible yet:

```
rows available:                192
first valid weekly_wma30:      row 133   (needs 30 weekly bars)
first valid wma_slope:         row 152   (needs 4 more weekly bars)
first defined stage:           row 152
usable signal history:         40 trading days
signal dates with 63 days of forward return available:   0
```

The 30-week moving average consumes 30 weeks; the slope consumes 4 more. With 192 days there is no window where a signal exists *and* three months of subsequent price action exists to score it against.

**After the backfill (~490 rows) this becomes possible:** stage would be defined from roughly row 152 onward, giving ~338 days of signal history and ~275 dates with a full 3-month forward window. That is enough for a genuine walk-forward test.

**The test to run then** — this is the single most valuable thing you can do with this system:

1. For each stock and each week-end date `t` where the stage is defined and `t + 63` trading days exists, record: stage, accum_score, exit_score, `dist_to_pivot_pct`, triple_confirm, and whether it would have passed the shortlist.
2. Compute forward return from `close[t]` to `close[t+63]`.
3. Subtract the equal-weight universe return over the same window — that controls for market direction, which otherwise dominates everything.
4. Report mean excess return, hit rate and average win/loss, bucketed by each signal.

If `accum_score` 6–7 doesn't beat 4–5 on excess return, the score isn't earning its place and should be re-weighted or replaced. If shortlist-passing names don't beat the universe, the filter set needs revisiting. **Until you've run this, every number in the report is a hypothesis.**

---

## 4. Method gaps that aren't code bugs

Ranked by how much they'd change your picks:

**No market-regime filter.** Weinstein's first instruction is to establish the market's own stage before buying anything. NIFTYBEES is fetched purely as an RS denominator; its stage is never computed. Buying Stage 2 breakouts in a Stage 4 market is the standard way to lose money with this method. Running the same stage logic on the index and printing it at the top of the Shortlist would be a small change with a large effect.

**Relative strength is absolute, not cross-sectional.** `rs_ratio` is a 52-day ROC spread versus the index. It tells you a stock beat the market by 12%; it doesn't tell you whether that's top-decile or middling. Weinstein wants the *strongest* names, which is inherently a ranking question. Converting to a 1–99 percentile across the universe would make `RS %` directly comparable between stocks.

**No sector/industry-group strength.** "Strongest stocks in the strongest groups" is central to the framework. The Sector Analysis sheet ranks sectors by *delivery colour-band counts*, which is a liquidity/participation measure, not sector relative strength. Ranking sectors by constituent price performance and then filtering to leaders in top-quartile sectors would align it with the method.

**Corporate actions are excluded, not adjusted.** Safe, but it creates permanent blind spots — a stock that split 18 months ago stays unshortlistable even though its recent history is clean. Back-adjusting prices would fix the signals and return those names.

**The delivery overlay needs honest positioning.** NSE delivery data is a genuine edge that Western Weinstein practitioners don't have, and it's the most original part of this system. But it currently carries roughly equal weight with the actual stage criteria in both composites. I'd report it as a separate confirmation score rather than blending it into the trend signal, so you can see when the two disagree.

---

## 5. What's genuinely sound

Worth being clear about, because it's most of the system:

- **Stage classification is faithful** — price versus a slope-classified 30WMA, with Stage 2 pullbacks separated out rather than mislabelled
- **Cross detection is honest** — keyed to the week-end close, not broadcast across the week, and volume-confirmed at Weinstein's 2×
- **Entry and exit levels are properly constructed** — pivot anchored to pre-breakout resistance, stop trailing at `max(base low, 30WMA)`. Verified: zero cases of a stop above the entry price, median risk 10%
- **Corporate-action quarantine works** — the three most tempting false bargains in the universe are flagged and excluded
- **Liquidity screen is real** — median (not mean) 20-day turnover, so a single block deal can't sneak an illiquid name through
- **The funnel produces a workable number** — ~5 actionable names from 1,000+ is the right order of magnitude for a weekly review

---

## 6. Recommendations, in order of value

| # | Change | Why |
|---|---|---|
| 1 | Run the backfill, then the forward-return test in §3 | Everything else is guesswork until you know whether the signals work |
| 2 | Fix the exit score: collapse E2/E3/E9 into one delivery factor, weight E7 and E1 at 2 points, retire E6, drop the threshold to 4 | Your risk control currently can't turn red |
| 3 | Tighten A3 and A5 or drop them from the score | Removes ~1.7 free points and restores spread across the middle 65% |
| 4 | Add the index's own stage as a regime gate on the Shortlist | Stops you buying breakouts into a falling market |
| 5 | Convert `RS %` to a cross-sectional percentile | Makes "market leader" a measurable claim rather than a directional one |
| 6 | Rank sectors by relative strength, not delivery-band counts | Aligns the sector sheet with what the method actually asks for |

Items 2 and 3 are an afternoon's work and would materially improve the ranking. Item 1 is the one that tells you whether any of it is worth doing.

---

## Bottom line

As an instrument for **finding candidates**, this is now good. The filters encode real Weinstein logic, the entry and stop levels are correct, the data integrity issues are resolved, and the output is a short ranked list rather than a wall of numbers.

As an instrument for **deciding between candidates**, it's weaker than it looks. The scores that drive the ordering are unweighted sums with near-constant components on the buy side and triple-counted components on the sell side, and the sell side's strongest warning never fires.

**How I'd use it today:** treat the Shortlist as a weekly candidate list — roughly 25 names, of which the 5 or so tagged `AtPivot` with a stop under 10% are worth pulling up a weekly chart for. Trust the *filters* (stage, RS sign, liquidity, corp-action exclusion, pivot and stop levels). Be sceptical of the *ordering*. Don't rely on the exit score to tell you when to sell — use the `Cross↓ WMA` column and the stop level, which are the real Weinstein triggers.

And run the forward test once you have two years of data. That's the difference between a well-built screener and a screener you know works.
