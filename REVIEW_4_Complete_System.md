# Review #4 — Complete System Review

**Date:** 17 Aug 2026
**Scope:** all five modules, config, cache layer, Excel output path, end to end
**Method note — please read:** the project folder was **not mounted into my execution sandbox** this round, so unlike Reviews #1–#3 I could not run the pipeline or open a generated workbook. Everything below is from reading the current source. Measured figures I quote are carried over from earlier rounds and labelled as such. Section 6 lists the checks I would have run so you can confirm them yourself.

---

## 1. Verdict

**The system has gone from "several silent correctness bugs" to "solid, with six specific defects."** Essentially every recommendation from Reviews #1–#3 has been implemented, and implemented well — not worked around. The Excel output in particular is now built the way a screening tool should be.

Six defects remain, one of which I'd treat as important because it degrades silently:

| # | Defect | Severity |
|---|---|---|
| 4.1 | `data_cache` drops `high`/`low` from the Excel backup → silent fallback to close-only 52W and TR | **High** |
| 4.2 | Shortlist F&O greying uses a leaked loop variable — greys all rows or none | Medium |
| 4.3 | Shortlist filters fail *open* on NaN — a failed NIFTY fetch silently disables the RS filter | Medium |
| 4.4 | Corp-action exclusion is over-broad (~25% of universe dropped, measured earlier) | Medium |
| 4.5 | ADV filter uses mean, not median — one spike day passes an illiquid stock | Low |
| 4.6 | Still detection-not-adjustment for corporate actions; no Pivot/Stop columns | By design, open |

---

## 2. The system as it now stands

```
tickers.txt (1,053)  fno_tickers.txt  ticker_metadata.json
        │
        ▼
nse_data_fetcher.py
  • sec_bhavdata_full per date → date/close/HIGH/LOW/qty/delivery
    - dates normalised at ingestion, pd.to_numeric(errors='coerce')
    - MTO fallback fixed to record type '20'
    - retry/backoff sessions, per-fetch isolated sessions, 500-entry LRU bhavcopy cache
  • quote-equity   → 52W high/low, PE, sector PE
  • corp-info      → promoter %, QoQ change
  • XBRL           → quarterly PAT, YoY growth (context-filtered)
  • NIFTYBEES      → index proxy for RS
        │
        ▼
data_cache.py   pickle (atomic write) + Excel backup, schema-validated,
                merge_new_data on BOTH paths → no more truncation
        │
        ▼
calculations.py  ~25 indicator passes, in dependency order:
   corp-action detect → delivery% → vol MA → weekly WMA30 (+ weekly slope,
   cross flags keyed to week-end) → colour band → stage → triple confirm →
   delivery trends → RSI → 52W → RS → divergence → squeeze (Wilder TR) →
   ROC → 200DMA → accum score → exit signals → exit score → Stage 1 alert
        │
        ▼
excel_generator.py  4 sheets: Shortlist (first) │ Report │ Daily Bands │ Sector Analysis
```

The pipeline order is now correct throughout — including the two ordering bugs I flagged (`vol_spike_down` before `distribution_alert`, corp-action detection before any price-dependent indicator).

---

## 3. Scorecard — everything raised across four reviews

### Fixed and verified by inspection

**Data integrity**

- Dates normalised at ingestion *and* `to_date` normalised in `main._calculate_fetch_window` — the duplicate-trading-day risk is closed at source
- `pd.to_numeric(errors='coerce')` on close/high/low/quantities — one `-` cell can no longer kill a 50-ticker batch
- HIGH/LOW now fetched and used
- MTO delivery parser record type corrected to `'20'`; missing delivery no longer coerced to a misleading `0`
- `merge_new_data` on both the batch and single-ticker paths — `--mode initial` extends history instead of truncating it
- History window 730 calendar days (~500 trading days)
- `load_ticker_data(required_columns=...)` lets index data validate against a smaller schema

**Weinstein logic**

- `wma_slope` computed at the **weekly** level (holiday-shortened weeks no longer distort it), threshold exposed as `wma_slope_threshold_pct`
- Cross flags merged on `week_end_date`, not `week` — the look-ahead bias in historical rows is gone
- `Stage 2 (Pullback)` separated from clean Stage 2
- `breakout_volume_multiplier: 2.0` now applied to `cross_above_confirmed`/`cross_below_confirmed`, and `volume_ma_multiplier` back to `1.0` for daily delivery — **the misapplied gate from Review #2 is correctly split**
- PE / sector PE written to the last row only (no look-ahead into historical rows)
- 52W high/low from intraday high/low when present
- Wilder-style TR in `calculate_squeeze`
- Bullish divergence floored at −10%
- `stage_3_alert` persists 10 days *and* now requires an `observed_transition` — the spurious first-10-rows firing is fixed
- `vol_spike_down` moved to step 3, ahead of `distribution_alert` at step 4 — Pattern B can now actually fire
- `accum_score` Factor 1 reuses `roc_1m` for consistency with the displayed column
- New `calculate_triple_confirm` — price above 30WMA **and** volume above average **and** delivery ≥50% on the same day. This is a genuinely good addition: it's the first signal in the system that requires price direction and delivery quality to agree.

**Excel output**

- `STOCK` in column 1, header on row 1, band totals moved to their own sheet
- Numeric cells with `number_format` throughout (`_pct` / `_num_cell` / `_int_cell` helpers), `None` rather than `"N/A"` for blanks — sorting and number filters now work correctly
- Scores written as integers with the denominator in the header (`Accum (of 7)`, `Exit (of 10)`) — the `10/10`-sorts-before-`1/10` trap is gone
- `auto_filter` + `freeze_panes` on both Shortlist and Report
- `As Of` column with `stale_days_threshold` greying
- `Why` column with reason codes
- **`Shortlist` sheet, first in the workbook**, with ADV filter, config-driven thresholds, percentile-composite ranking, and a `+5` bump for same-day triple confirm
- Corp-action flag now reaches the Report as `⚠CA` in `Why`, using the correct `(df[...]=='Yes').any()` check rather than the last row
- Sector Analysis now has an explicit `Unknown` bucket — unmapped tickers are no longer silently dropped

**Dead code removed:** `is_fno_stock`, `is_weekstart`/`weekstart_cross`, `dma_200_signal`, `face_value`, the unreachable `else: 'Stage 1'`, the ignored `series` parameter, and the stale `exchange`/`weekstart_day`/`delivery_bins.*.max` config keys.

That is a lot of correct work. The remaining items are narrower.

---

## 4. New findings this round

### 4.1 The Excel cache silently strips `high` and `low` — **highest priority**

`data_cache.py:149-150`:

```python
cols = ['date', 'close', 'traded_quantity', 'delivery_quantity', 'delivery_pct']
df_excel = df_excel[cols]
```

`high` and `low` are dropped from the Excel backup. Three consequences, in increasing order of nastiness:

1. The Excel backup can never restore intraday data — it's no longer a faithful backup.
2. `load_ticker_data` falls back to Excel whenever the pickle is missing or unreadable. The returned frame has no `high`/`low`, so `calculate_52week_metrics` and `calculate_squeeze` take their close-only fallback branches. `_has_required_columns` doesn't check for `high`/`low`, so **nothing warns you**. You get a 52W high computed from closes and a close-to-close ATR, labelled identically to the correct version.
3. Worse: `merge_new_data` concatenates an Excel-loaded `cached_df` (no high/low) with a fresh `new_df` (with high/low). The result has `NaN` high/low on all older rows. `rolling(252, min_periods=126).max()` skips NaN, so `52w_high` gets computed from **whatever intraday data happens to exist** — a silently mixed basis that varies per ticker.

**Fix:**

```python
cols = ['date', 'close', 'high', 'low', 'traded_quantity', 'delivery_quantity', 'delivery_pct']
cols = [c for c in cols if c in df_excel.columns]
df_excel = df_excel[cols]
```

And in `calculations.py`, log a warning when the close-only fallback is taken so degradation is visible rather than silent.

### 4.2 Shortlist F&O greying uses a leaked loop variable

`excel_generator.py:1009`:

```python
for rank, c in enumerate(candidates, start=1):
    ...
    if ticker in fno_tickers:        # ← `ticker` is not defined in this loop
        for ci in range(3, 18):
            ws.cell(row=r, column=ci).fill = self.colors['grey']
```

`ticker` is left over from the candidate-collection loop at line 826, so it holds **the last ticker in `ticker_data_dict`** for every row. Depending on whether that one arbitrary ticker happens to be in F&O, either every shortlist row is greyed out or none is. Should be `if c['ticker'] in fno_tickers:`.

This is the kind of bug that looks like a styling quirk and gets ignored — but a fully-greyed shortlist reads as "nothing here is cash-market eligible", which is misleading.

### 4.3 Shortlist filters fail open on missing data

`excel_generator.py:855-860`:

```python
if pd.notna(rs_ratio) and rs_ratio < min_rs:      continue
if pd.notna(exit_score) and exit_score > max_exit: continue
if pd.notna(deliv_30d) and deliv_30d < min_deliv:  continue
```

A `NaN` value **passes** the filter. So:

- A ticker with fewer than 52 rows has `rs_ratio = NaN` and clears the "must be outperforming" test
- If the NIFTY/NIFTYBEES fetch fails, `rs_ratio` is `NaN` for the *entire universe* — the market-leadership requirement, which is the most Weinstein-faithful filter in the set, silently becomes a no-op. The title still prints "RS≥0%". I hit exactly this failure mode in my own harness in Review #2, which is how I know it's reachable.

These stocks then rank last (`rs_ratio` is coerced to `-999` at line 888) but still occupy shortlist slots with a blank RS cell.

**Fix:** invert to fail closed — `if pd.isna(rs_ratio) or rs_ratio < min_rs: continue` — and log a loud warning plus a banner on the Shortlist sheet if the index series is unavailable.

### 4.4 Corp-action exclusion is over-broad

`detect_corporate_actions` uses a **15%** single-day threshold and flags every row before the earliest gap; the shortlist then excludes on `.any()`. Measured in Review #3: this removed **61 of 244 sampled names (25%)**.

For Indian mid- and small-caps a 15% single-day move is common — earnings surprises, upper circuits, block deals. So you are excluding roughly a quarter of the universe, most of it legitimately traded, to avoid a handful of genuine splits.

**Fix:** raise to ~20%, and cross-check the same day's index move (a real split moves the stock and not the index; a sector-wide selloff moves both). Better still, adjust rather than exclude — see 4.6.

### 4.5 ADV uses mean rather than median

`excel_generator.py:848` — `(recent['traded_quantity'] * recent['close']).mean()` over 20 days. One block-deal day can lift a ₹1 crore/day stock above a ₹5 crore threshold. Use `.median()`, which is what my Review #3 liquidity table was based on.

### 4.6 Open by design

- **Corporate actions are detected and excluded, never adjusted.** This is safe but costs you names: a stock that split 18 months ago is permanently unshortlistable even though its recent price history is perfectly clean. A cumulative back-adjustment factor applied to `close`/`high`/`low` (and the inverse to quantities) before indicators run would both fix the signals and return those names to the universe.
- **No `Pivot Price` / `Distance to Pivot %` / `Stop Level` / `Distance to Stop %`.** The report now tells you *which* stocks and *why*, but still not *where to buy* or *where to get out*. These were Review #3 Part 4 and remain the largest functional gap for a stock picker.
- **`rs_ratio` is still a 52-day ROC spread, not Mansfield RS**, despite the docstring, and it's an absolute value rather than a cross-sectional percentile — so you can't distinguish a top-decile leader from a marginal outperformer.
- **Scores are still equal-weighted votes**, and there is still no backtest anywhere in the repo. Both composites remain unvalidated hypotheses.

---

## 5. Two smaller notes

- `calculate_weekly_wma` is still **not idempotent** — handed a frame that already contains `cross_above`/`weekly_wma30`, the merges produce `_x`/`_y` suffixed columns and downstream reads break. Currently safe because only raw frames are cached, but it's a live trap for anyone who caches processed output. A one-line guard (`df = df.drop(columns=[...], errors='ignore')` at entry) removes the risk.
- `calculate_summary_counts` still treats row 0 as an up day (`.diff().fillna(0) >= 0`). Immaterial over 45-day windows; noted for completeness.

---

## 6. What I could not verify — please run these

Because the folder wasn't mounted I could not execute anything. These are the checks that would confirm the system is behaving, in the order I'd run them:

1. **Has the backfill run?** `python3 -c "import pandas as pd; d=pd.read_excel('data_cache/excel/RELIANCE_historical.xlsx'); print(len(d), list(d.columns), d['date'].min(), d['date'].max())"` — you want **~490 rows** and `high`/`low` present. If it still shows 192 rows, run `python3 main.py --mode initial` before trusting `52W High %`, `vs 200DMA` or `Wks Above`.
2. **Does the workbook open on a populated Shortlist?** If it shows "No stocks pass the shortlist filters", the thresholds are too tight for current market conditions — loosen `min_deliv_30d` first.
3. **Are the shortlist rows greyed?** If all or none are, that confirms 4.2.
4. **Is `RS %` populated on the Shortlist?** All blanks means the NIFTY fetch failed and 4.3 has silently disabled the RS filter.
5. **Spot-check a numeric sort** — sort `Report` by `52W High %` descending and confirm the top rows really are closest to their highs.
6. **HDFCAMC / JLHL / TRENT** — confirm they carry `⚠CA` in `Why` on the Report sheet and are absent from the Shortlist.

---

## 7. Bottom line

The engineering is in good shape. Across four rounds the data layer went from silently corrupting on several paths to correct-by-construction, the Weinstein logic went from three genuine misclassifications to faithful, and the Excel went from an unsortable archive to a filterable tool that opens on a ranked shortlist. `triple_confirm` and the `Why` column are additions I didn't ask for and both improve the output.

Fix 4.1 first — it's the only remaining defect that degrades **silently**, and silent degradation is what makes a screener untrustworthy rather than merely imperfect. 4.2 and 4.3 are quick and both affect the Shortlist, which is now the sheet you'll actually use.

After that, the honest assessment is that the *code* is no longer the limiting factor. What's left is method: buy/stop levels so a shortlist row becomes an actionable trade, and a forward-return test so the scores stop being educated guesses. Until that test exists, treat the Shortlist as a well-constructed research queue — the names worth spending your chart time on — rather than a list of decisions.
