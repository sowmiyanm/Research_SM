# Review #2 — Weinstein Screener: Code Delta + PMS Fitness Assessment

**Date:** 17 Aug 2026
**Perspective:** code reviewer + portfolio manager evaluating whether this can drive real allocation decisions
**Method:** re-read all five modules; re-ran `StockCalculator` across 55–300 cached tickers; measured the effect of each change against the prior baseline.

---

## Part 1 — Verdict

**Code quality: materially improved. Investment readiness: not yet.**

Nine of my seventeen severity-1 findings are properly fixed. But three things stand in the way of using this to run money:

1. **A change was applied to the wrong gate**, and it has gutted the report's core signal. Setting `volume_ma_multiplier = 2.0` changed `is_high_vol` — the daily delivery/accumulation machinery — instead of the breakout-confirmation gate that Weinstein's 2× rule actually governs. That gate is still at 1.0×. Measured effect below; this is the single most urgent item.
2. **The corporate-action work is disconnected on both ends.** The detector runs, but its flag is `'No'` on the exact row the report reads, and the column is not in the Excel output at all. HDFCAMC still prints as a Stage 1 basing candidate at "−54.8% from 52W high".
3. **None of the data fixes have taken effect yet**, because the cache was never rebuilt. Still 192 rows, still no high/low columns.

Beyond the code, the system is missing the parts of Weinstein's method that make it *tradeable* rather than *descriptive* — no stop levels, no breakout pivot, no market-regime filter, no cross-sectional ranking, no liquidity screen, no evidence any of it predicts returns. Detail in Part 3.

---

## Part 2 — Code delta

### 2.1 Properly fixed — good work

| # | Finding | What was done |
|---|---|---|
| 1.2 | History window | `history_calendar_days = 730` (~500 trading days). Correct. |
| 1.4 | Weekly cross flags broadcast to every daily row | Cross flags now merged on `week_end_date` instead of `week`, so they fire only on the week's last row. This removes the look-ahead bias from historical rows — the cleanest fix in the set. |
| 1.5 | Stage 2 assigned below the 30WMA | Now labelled `Stage 2 (Pullback)`, distinct and filterable. |
| 1.6 | Slope deadband hardcoded | Moved to weekly level (fixes the holiday/repeated-value problem) and exposed as `wma_slope_threshold_pct`. |
| 1.8 | No as-of date | `As Of` column added at col 50, with grey styling for stale rows. |
| 1.9 | Timestamps in cached dates | `.dt.normalize()` at both ingestion points. |
| 1.10 | `--mode initial` truncating cache | Batch path now uses `merge_new_data`. |
| 1.11 | MTO parser record type | `parts[0] == '20'`. Correct. |
| 1.12 | One bad cell killing a 50-ticker batch | `pd.to_numeric(..., errors='coerce')` throughout. |
| 1.13 | "Exit Signal" unreachable | 10-day persistence window. |
| 1.14 | Bullish divergence with no floor | Now `-10 <= price_roc < 2`. |
| 1.15 | Fundamentals with no vintage | Header now reads `Profit Growth YoY (Qtr)`. |
| — | PE/sector PE look-ahead | Now written only to the last row — a bias I hadn't flagged. Good catch. |
| — | Dead code | `is_fno_stock`, `is_weekstart`/`weekstart_cross`, `dma_200_signal`, `face_value`, unreachable `else: 'Stage 1'`, the `series` parameter, and stale config keys all removed. |
| — | HIGH/LOW now fetched | True Wilder-style TR in `calculate_squeeze`, with a close-to-close fallback. |

### 2.2 The 2× multiplier — applied to the wrong gate

`calculations.py:63-68` now requires daily volume **> 2 × the 36-day MA** for `is_high_vol == 'Yes'`. That flag feeds the colour grid, all six delivery counts, `accum_score` Factor 6, `stage1_alert` Criteria 1 and 3, and `vol_spike_down`.

Measured across 53 tickers, same data, only the multiplier changed:

| Metric | 1.0× (before) | 2.0× (now) |
|---|---|---|
| Coloured cells in the 60-day grid | 17.8% | **4.5%** |
| White (non-actionable) cells | 73.1% | **91.1%** |
| `Accum` Factor 6 met (5 of last 10 high-vol days) | 12 / 53 | **0 / 53** |
| `Count (≥50% + HighVol)/45` — mean / max | 3.21 / 12 | **0.70 / 4** |
| `Vol Spike Down` seen in last 60d | 52 / 53 | 37 / 53 |
| Tickers with ≥1 volume-confirmed cross | 15 / 53 | **15 / 53 (unchanged)** |

Three consequences:

- **The delivery heat-map — the report's centrepiece — is now 91% blank.** The colour-band grid, the daily band totals, and the entire Sector Analysis sheet all key off `color_band`, which is `'white'` whenever `is_high_vol != 'Yes'`.
- **`accum_score` Factor 6 is structurally dead.** Requiring 5 of 10 days at >2× a 36-day average is close to arithmetically self-defeating — that much volume drags the MA up. The score is now effectively out of 6 while the report still prints `/7`, so the top bucket is unreachable.
- **The gate you actually wanted to tighten did not move.** `cross_above_confirmed` / `cross_below_confirmed` (`calculations.py:196-197`) still test `week_avg_vol_ratio > 1.0`, hardcoded. Identical count before and after.

Weinstein's 2× rule is specifically about **breakout-week volume**. "Above average daily volume" is the correct, conventional bar for the delivery/accumulation overlay.

**Fix:** revert `volume_ma_multiplier` to `1.0` (or split into `volume_ma_multiplier` for daily and a new `breakout_volume_multiplier: 2.0`), and apply 2.0 to lines 196-197. Also: `vol_spike_down` weakening is a *safety* regression — you get fewer distribution warnings, not more.

### 2.3 Corporate actions — detector disconnected at both ends

`detect_corporate_actions` (`calculations.py:460`) is called at line 1189. Three problems:

1. **The flag is `'No'` on the row the report reads.** Line 510 marks rows *before* the earliest gap as suspect. `_add_ticker_row` reads `df.iloc[-1]`, which is after the gap. Verified:

   | Ticker | `corp_action_suspected` (last row) | any row | Stage reported | 52W High % |
   |---|---|---|---|---|
   | HDFCAMC | **No** | Yes | Stage 1 | −54.8% |
   | TRENT | **No** | Yes | Stage 4 | −35.6% |
   | JLHL | **No** | Yes | Stage 4 | −79.9% |

2. **The columns are not rendered.** `corp_action_suspected`, `corp_action_gap_dates` and `corp_action_gap_info` appear nowhere in `excel_generator.py`. Even a correct flag would be invisible.

3. **Detection is not adjustment.** The 30WMA, stage, ROC, 52W distance and volume ratios are still computed on unadjusted prices. HDFCAMC is unchanged from review #1: a stock near its adjusted highs, reported as a basing candidate.

Also, the 15% threshold is too tight for Indian mid/small caps — a legitimate 16% earnings move will trip it, and line 510 then quarantines that stock's *entire prior history*. Raise to ~20% and cross-check against NIFTYBEES moving the same day.

**Minimum viable fix:** compute a cumulative adjustment factor from detected gaps and divide historical `close`/`high`/`low` (and multiply quantities) before any indicator runs. Short of that, propagate the flag to the last row and render it as a `Corp Action` column so affected names are visibly quarantined.

### 2.4 Still open from review #1

- **1.3 Breakout volume confirmation** — still `> 1.0` (see 2.2).
- **1.7 52W basis mismatch** — `calculations.py:534-539` now uses `high`/`low` when present, which is right, but the last row is still overwritten with NSE's snapshot. Once the cache has high/low the two bases agree; until then they don't.
- **1.16 Sector Analysis drops unmapped tickers** — `metadata.get('department', 'Unknown')` is still `continue`d when not in the `sectors` set. Silent omission from counts and totals.
- **Sev-2** — `rs_ratio` still isn't Mansfield RS despite the docstring; equal-weighted scores; first row counted as an up day; `calculate_weekly_wma` still not idempotent.

### 2.5 New bugs introduced

| Location | Issue |
|---|---|
| `calculations.py:860` | `distribution_alert` Pattern B reads `vol_spike_down`, but that column is created at line 919 — **later in the same function**. `.get()` returns the `'No'` default, so Pattern B can never fire. Move step 6 above step 3. |
| `calculations.py:908-910` | If the series *starts* in Stage 3 with no preceding Stage 2, `days_since_transition` is 0, so `Exit Signal` fires spuriously for the first 10 rows. Require an observed transition. |
| `calculations.py:505` | `corp_action_gap_info` is assigned inside the `if gap_mask.any()` block only, so the column is absent for clean stocks — an inconsistent schema that will bite any code doing `df['corp_action_gap_info']`. |
| — | `config.json` still lists `cream.min` and `white.min`, neither of which is read (`get_delivery_color_band` decides cream in `get_color_with_volume`, and white is the `else`). Cosmetic, but it's the same class of misleading config as the old `weekstart_day`. |

### 2.6 The fixes have not taken effect yet

`data_cache/RELIANCE.pkl` is dated 14 Aug, and the Excel cache still shows **192 rows, columns `[date, close, traded_quantity, delivery_quantity]`** — no high/low.

So right now, in the live output: 52W metrics still fall back to close-based, squeeze still falls back to close-to-close, `Price vs 200DMA` is still not a 200DMA, and `Wks Above WMA` still caps at 12.

Incremental mode only fetches *forward* from the last cached date, so this will never self-heal. You need one **`python3 main.py --mode initial`** run — which now merges rather than overwrites, so it will correctly backfill to 730 days.

---

## Part 3 — PMS fitness: what's missing from the method itself

The code review above is about correctness. This section is about whether a correct version of this system could size a position. Today it cannot. Ranked by what I'd need before allocating.

### 3.1 No stop-loss, therefore no position sizing — the binding constraint

Weinstein's method is inseparable from stop placement: initial stop below the base (or below the breakout pivot), then trailed up, with the 30WMA as the long-term line in the sand. The report has no stop price, no distance-to-stop, and no R-multiple.

Without distance-to-stop you cannot size a position on risk, which means you cannot construct a portfolio from this output — only a watchlist. **Add:** `Stop Level`, `Distance to Stop %`, and `Risk-Adjusted Score` (signal strength ÷ distance to stop). This is the highest-value addition in this document.

### 3.2 No base identification and no breakout pivot

Weinstein's Stage 1 is a *visible horizontal base* with a definable resistance line; the buy is the breakout **through that line** on expanding volume. Here Stage 1 is approximated as "price below a flat 30WMA" — which admits stocks in orderly decline that happen to have a flat MA, and has no concept of the price you'd actually buy above.

**Add:** base detection (e.g. N weeks where the high-low range stays inside X%), the resulting `Pivot Price`, `Base Length (wks)`, `Base Depth %`, and `Distance to Pivot %`. Base length and tightness are Weinstein's own quality filters — a 30-week tight base is a far better setup than a 6-week loose one, and today they score identically.

### 3.3 No market-regime filter

Weinstein's first instruction is to establish the *market's* stage before buying anything. NIFTYBEES is fetched here purely as an RS denominator; its own stage is never computed. Buying Stage 2 breakouts in a Stage 4 market is the classic way to lose money with this method.

**Add:** run the same stage logic on the index, print it in the Commentary row, and gate or discount buy signals when the index is in Stage 3/4.

### 3.4 No cross-sectional or sector ranking

"Buy the strongest stocks in the strongest groups" is central to the method. What exists:

- `rs_ratio` is a raw 52-day ROC spread, not a percentile — so you can't tell a top-decile leader from a marginal outperformer.
- The Sector Analysis sheet ranks sectors by *delivery colour-band counts*, not by sector relative strength.

**Add:** cross-sectional RS percentile (1–99) per stock, and a sector RS ranking computed from constituent price performance. Then filter to leaders in top-quartile sectors.

### 3.5 No liquidity or investability screen

For a PMS this is disqualifying on its own. Measured median 20-day turnover across 298 cached names:

| Percentile | Rs crore/day |
|---|---|
| p10 | 1.99 |
| p25 | 4.64 |
| p50 | 15.03 |
| p75 | 60.89 |
| p90 | 154.57 |

**26% of the universe trades under Rs 5 crore/day**; the thinnest names (BANARISUG Rs 0.11 cr, ROSSELLIND Rs 0.13 cr) cannot absorb a meaningful position without moving the price. There is no turnover filter anywhere in the code.

**Add:** an `ADV (20d)` column plus a configurable minimum, and a `Max Position at 10% of ADV` figure so you can see capacity before you get attached to a name.

### 3.6 No evidence of predictive power

There is no backtest, no forward-return measurement, no hit-rate or expectancy calculation anywhere in the repo. `accum_score` and `exit_score` are unvalidated equal-weight sums of plausible-sounding factors.

For allocation you need, at minimum: forward 3/6/12-month returns bucketed by `accum_score` and by stage at signal date, plus hit rate and average win/loss for the cross-above signal. Two years of history is thin for this, but it would at least distinguish "this discriminates" from "this is a nicely formatted opinion". **Until this exists, treat every score in the report as a hypothesis.**

### 3.7 Scores are unweighted votes

Both composites give one point per factor. In Weinstein's hierarchy, *price above a rising 30WMA on 2× volume* and *positive relative strength* dominate; *delivery trend stable* is a minor confirmation. Equal weighting lets four weak confirmations outvote the two that matter. Weight them, and ideally let the backtest set the weights.

### 3.8 Delivery-% overlay needs to be positioned honestly

The delivery analysis is a genuine India-specific edge and the most original part of this system — NSE delivery data has real information that US-based Weinstein practitioners don't get. But it is *not* Weinstein, and right now it carries roughly equal weight with the actual stage criteria in both composites. Keep it, but report it as a separate confirmation score rather than blending it into the stage signal.

### 3.9 Two years is thin for weekly stage analysis

730 days ≈ 100 weekly bars, of which the first 30 are consumed by the WMA. Weinstein works on weekly charts where you want to see a full cycle — 3–5 years. Consider 1,500 calendar days once the pipeline is stable; the bhavcopy LRU already handles the extra dates and it's a one-time backfill cost.

---

## Part 4 — Recommended order

**Before the next report run (hours):**

1. Revert `volume_ma_multiplier` to 1.0; move 2.0 onto `cross_above_confirmed`/`cross_below_confirmed` (§2.2)
2. Move `vol_spike_down` (step 6) above `distribution_alert` (step 3) (§2.5)
3. Run `python3 main.py --mode initial` to backfill 730 days with high/low (§2.6)

**This week:**

4. Back-adjust prices for corporate actions; propagate the flag to the last row and render a `Corp Action` column (§2.3)
5. Add `ADV (20d)` + minimum turnover filter (§3.5)
6. Add `Stop Level` and `Distance to Stop %` (§3.1)
7. Fix the spurious first-10-row `Exit Signal`; add an `Unknown` sector bucket (§2.5, §2.4)

**Before this drives any allocation:**

8. Base detection, `Pivot Price`, `Distance to Pivot %`, base length/depth (§3.2)
9. Index stage as a market-regime gate (§3.3)
10. Cross-sectional RS percentile + sector RS ranking (§3.4)
11. A forward-return backtest — then re-weight both composites from its output (§3.6, §3.7)

---

## Bottom line

The engineering has gone from "several silent correctness bugs" to "mostly correct, with one high-impact misapplied change". That's real progress and the hard data-integrity work (date normalisation, numeric coercion, week-end cross keying, cache merging) is done properly.

What remains is a different kind of gap. The system currently produces a **well-instrumented description of where each stock sits** — and that is genuinely useful for generating a watchlist. It does not yet produce a **decision**: no stop, no pivot, no capacity, no regime gate, no ranking, and no evidence the scores predict anything.

My recommendation: run it in parallel as a watchlist generator, and paper-track the signals it produces for two to three quarters while items 8–11 get built. That gives you the forward-return sample you need anyway — and it costs nothing but patience.
