# Code Review — NSE Weinstein Screener

**Reviewed:** `main.py`, `calculations.py`, `excel_generator.py`, `data_cache.py`, `nse_data_fetcher.py`
**Date:** 17 Aug 2026
**Evidence base:** static read of all five modules, re-running `StockCalculator` over 120 cached tickers, and auditing the 1,053 rows of the delivered `Delivery_Report_2026-08-15.xlsx`.

---

## Executive summary

The pipeline is well organised and the recent hardening (atomic cache writes, retry sessions, LRU bhavcopy cache, look-ahead guard on the NSE 52-week snapshot) shows real care. The problems are not structural — they are in **signal fidelity**.

Three issues are severe enough that the current Excel output should not be traded from as-is:

1. **Prices are never adjusted for splits/bonuses.** 4 of 120 sampled tickers (~3%, so roughly 35 stocks in the 1,053-name universe) carry a fake ±25%+ one-day gap that corrupts the 30WMA, stage, ROC, 52W distance and volume ratio.
2. **Only ~192 trading days of history exist**, so "52W High %", "Price vs 200DMA" and "Wks Above WMA" are all mislabelled — they measure a ~9-month window, not what the header says.
3. **The volume-confirmation bar is 1.0× average, not Weinstein's 2×.** In the delivered report 72 of 114 crosses get the green "✓ Vol" BUY highlight; on my sample only ~24% of cross weeks would clear a genuine 2× test.

---

## Severity 1 — will produce wrong buy/sell calls

### 1.1 No corporate-action adjustment (whole pipeline)
`nse_data_fetcher.py:178-183, 827-832` take `CLOSE_PRICE` straight from `sec_bhavdata_full`, which is **unadjusted**. Nothing anywhere back-adjusts for splits, bonuses or demergers.

Observed in the cache:

| Ticker | Date | Apparent 1-day move | Close before → after |
|---|---|---|---|
| HDFCAMC | 2025-11-26 | −49.8% | 5336.5 → 2679.0 |
| JLHL | 2026-07-24 | −79.5% | 1574.5 → 323.2 |
| TRENT | 2026-06-04 | −33.4% | 4257.6 → 2837.6 |
| GUJALKALI | 2026-03-23 | +26.4% | 486.5 → 615.1 |

Running the real calculator on HDFCAMC produces:

```
stage            Stage 1        <- basing candidate
price_vs_wma     Below -5.2%
52w_high_pct     -54.8%         <- pure artifact of the bonus
near_52w_high    No
cross_below      9 phantom events
vol_ratio (max)  4.8x           <- share count doubled, not real interest
```

A stock trading near its adjusted highs is being surfaced as a Stage 1 accumulation candidate. This single issue also feeds false `Stage 4`, false `SELL` on Cross Below WMA, false `Coiling` squeeze, and inflated `Vol Ratio`.

**Fix:** detect adjustment events (a >20% overnight gap with no matching gap in NIFTYBEES, or pull `/api/corporate-actions`) and back-adjust `close`, `traded_quantity` and `delivery_quantity` before any calculation. At minimum, add a `CA Flag` column so affected rows are visibly quarantined.

### 1.2 History window is far shorter than the indicator names claim
`main.py:129-135` fetches `max(lookback+volume_ma+30, (30+10)*7) = 280` **calendar** days ≈ **192 trading days**. Verified: every cached ticker spans 2025-11-07 → 2026-08-14, 192 rows.

Consequences:

| Column | Code | Reality on 192 rows |
|---|---|---|
| `52W High %` / `52W Low %` | `rolling(252, min_periods=126)` (`calculations.py:457-458`) | ~9-month extreme, labelled 52-week |
| `Price vs 200DMA` | `rolling(200, min_periods=100)` (`calculations.py:971`) | never a true 200DMA |
| `Wks Above WMA` | consecutive counter (`calculations.py:116-131`) | **capped at 12** — confirmed max across all 1,053 report rows |
| `weekly_wma30` | needs 30 weekly closes | only ~59 of 192 daily rows have a value (median across sample) |

"Wks Above WMA" is your stage-maturity read. Right now a stock two years into Stage 2 and one twelve weeks in both read `12`.

**Fix:** raise the initial fetch to ~500 trading days (≈730 calendar days). This is the cheapest high-impact change; the bhavcopy LRU already handles the extra dates.

### 1.3 Volume confirmation threshold is far too low
`calculations.py:149-150`:
```python
df['cross_above_confirmed'] = df['cross_above'] & (df['week_avg_vol_ratio'] > 1.0)
```
Weinstein requires breakout-week volume at **≥2× the average**. At 1.0× the test is "volume was merely average or better".

Measured on 60 tickers: 38 cross-above weeks, only **9 (24%)** had weekly average volume ≥2.0×. In the delivered report, **72 of 114** crosses carry the green `✓ Vol` BUY styling.

**Fix:** raise to 2.0 (make it a config key), and surface `week_avg_vol_ratio` as a visible column so the bar is auditable rather than hidden behind a tick mark.

### 1.4 Weekly cross flags are broadcast onto days before the week has closed
`calculations.py:134-139` merges the weekly `cross_above`/`cross_below` flags onto **every daily row of that week**. A cross is only defined by the **Friday** close, yet it appears on Monday's row.

Measured: **44 of 118 tickers** have `cross_above == True` on a row that is not the week's last trading day. Re-computing with only mid-week data available changes the answer in **2.5% of weeks** — i.e. the signal you act on Tuesday is provisional and sometimes vanishes by Friday.

Two distinct problems: (a) any backtest over this cache is look-ahead biased; (b) live, a mid-week "✓" is a provisional signal displayed identically to a settled one.

**Fix:** attach cross flags only to the week's last row; add an `is_week_complete` flag and label mid-week crosses "Provisional".

### 1.5 Stage 2 assigned to stocks trading *below* the 30WMA
`calculations.py:346-351` deliberately maps `price < WMA` + `WMA rising` → Stage 2. The comment justifies it as "pullback within an established uptrend", but Weinstein's Stage 2 definition requires price **above** a rising 30WMA — trading below it is precisely the stage-2-failure condition he tells you to exit on.

In the sample, 2 of 53 Stage 2 stocks were below their WMA. Low frequency, but these are exactly the names most likely to break down.

**Fix:** introduce a distinct `Stage 2 (Pullback)` label rather than folding it into Stage 2, so it can be filtered separately. The stated reason for the change — spurious "new Stage 1" alerts from counter resets — is better solved with a confirmation requirement (e.g. 2 consecutive weeks) on the stage transition itself.

### 1.6 The `wma_slope` deadband is wide enough to hide real trends
`calculations.py:326-331` calls the slope `Flat` unless the WMA moved more than ±2% over 4 weeks. A steady 0.4%/week advance (≈23%/year) reads as **Flat**, which routes an advancing stock into Stage 1 (if below) or Stage 3 (if above). Stage 3 is your exit trigger.

**Fix:** make the band a config value and tighten it (±0.5–1%), or scale it by the stock's own volatility.

### 1.7 The screening row mixes two different 52-week definitions
`calculations.py:457-472`: history uses `rolling(252).max()` of **closing** prices; the final row is overwritten with NSE's snapshot, which is an **intraday** high/low. The last row is the only row the Excel report reads.

So `52W High %` and the gold `Near 52W High` highlight are computed on a different basis from every historical row, and systematically understate proximity to the high (intraday high ≥ closing high). 221 of 1,053 rows are flagged Yes; the true count on a consistent basis differs.

**Fix:** pick one basis. Either fetch intraday high/low into the cache, or drop the NSE overwrite and label the column by its actual (closing-price, N-day) definition.

### 1.8 The report has no per-ticker "as of" date
`excel_generator.py:348` — `latest_data = df.iloc[-1]`. If a ticker's fetch fails, `main.py:174-180 / 194-201` silently falls back to cache and the row is rendered with **no indication that it is stale**. A ticker frozen three weeks ago shows its old Stage, RSI and Cross Above as if current, in the same visual style as fresh rows.

Right now all caches happen to be current (2026-08-14), so this is latent — but the fallback paths make it inevitable.

**Fix:** add an `As Of` column from `df['date'].iloc[-1]` and grey/strike any row older than the report's max date.

### 1.9 Cache dates carry a time-of-day stamp
Every cached row stores e.g. `2026-08-14T21:19:19.687191` — the wall-clock time of the run, because `_get_trading_dates` (`nse_data_fetcher.py:350-357`) iterates from a `datetime.now()`-derived `from_date` and `_fetch_combined_bhavcopy:256` assigns that datetime directly.

`DataCache.merge_new_data:184` de-duplicates on the exact `date` value. Two runs at different clock times produce **different timestamps for the same trading day**, so the dedupe silently fails and the day is double-counted — which shifts every rolling window and MA.

**Fix:** `date.normalize()` (or `datetime.combine(d, time.min)`) at ingestion in both `get_stock_data` and `get_stock_data_batch`, plus a one-off normalise-and-dedupe pass over the existing cache.

### 1.10 `--mode initial` truncates the cache
`main.py:243` — the batch path calls `self.cache.save_ticker_data(ticker, df)`, overwriting the cache with only the freshly fetched window. `_process_single_ticker:182-186` carries an explicit comment warning against exactly this and uses `merge_new_data` instead; the batch path does the opposite.

Re-running `--mode initial` therefore discards any history longer than 280 days — which directly re-creates issue 1.2 even after you fix the fetch window.

**Fix:** use `merge_new_data` in `_process_batch_optimized` too.

### 1.11 The MTO delivery fallback almost certainly parses nothing
`nse_data_fetcher.py:312` gates on `parts[0].upper() in ['1','2','3']`. NSE's `MTO_*.DAT` uses record type **`20`** for security rows. When `DELIV_QTY` is absent from the bhavcopy, this fallback returns an empty frame, the left-merge yields NaN, and `:280` fills it with **0** — so `delivery_pct` becomes **0%**, not `N/A`.

A silent 0% pushes those days to `white`/`cream`, zeroes every delivery count, and drags `deliv_avg_30d` down — the exact opposite of a missing-data marker.

**Fix:** accept `'20'`, and on parse failure leave `DELIV_QTY` as NaN rather than 0 so `calculate_delivery_percentage` correctly produces NaN.

### 1.12 One bad cell can kill a whole 50-ticker batch
`nse_data_fetcher.py:831` — `combined_df['DELIV_QTY'].astype(float)` is outside any try/except. NSE writes `-` for rows with no reported delivery; a single one raises `ValueError`, which `main.py:369-371` catches at the batch level and marks all 50 tickers failed. Use `pd.to_numeric(..., errors='coerce')`.

### 1.13 "Stage 3 Alert → Exit Signal" is unreachable in practice
`calculations.py:788-796` sets `Exit Signal` only on the exact day of a Stage 2→3 transition, but the report reads only the last row. Confirmed in the delivered report: **0 of 1,053 rows** show `Exit Signal` (199 show `Stage 3`, 854 show `-`). The red exit highlight can effectively never fire.

Same shape of problem affects `Distribution Alert`, `Vol Spike Down` and `Divergence` — all single-day states shown next to 45-day counts, so a one-day blip reads like a regime.

**Fix:** report "transition occurred within last N days" rather than "on the last row", and label single-day columns explicitly (e.g. `Vol Spike Down (1d)`).

### 1.14 Bullish divergence has no floor on the price decline
`calculations.py:613` — `price_roc < 2 and deliv_change > 3` labels a stock **Bullish** even if it fell 40% over the 20-day window. Heavy delivery into a collapse is distribution/pledge unwind, not accumulation. Add a floor (e.g. `-8% < price_roc < 2%`).

### 1.15 Fundamentals are shown with no vintage
`profit_growth_yoy` and `promoter_pct` are rendered as current facts. `latest_quarter` and the promoter `quarter` **are** fetched but never written to the sheet (`excel_generator.py` never references them). An eight-month-old quarter and a fresh one look identical. Surface the quarter label next to both.

### 1.16 Sector Analysis silently drops unmapped tickers
`excel_generator.py:1001-1002` — `sectors` is built only from `ticker_metadata` values, and any ticker whose sector isn't in that set is `continue`d. Tickers missing from `ticker_metadata.json` vanish from the sector counts and from the grand total, with no warning. Add an explicit `Unknown` bucket and log the count.

### 1.17 The report in the folder is stale relative to the code
`Delivery_Report_2026-08-15.xlsx` shows `Accum Score x/6` and `Exit Score x/7`. The current code emits `/7` and `/10` (`excel_generator.py:629, 652`) because factors were added (`rs_ratio` to accumulation, `rs_trend`/`divergence`/`momentum_align` to exit). **Any conclusion drawn from the current file reflects the old scoring.** Regenerate before use.

Also note the exit-score colour cut-points (`>=6` red, `>=3` yellow, `:684-688`) were set for the 0–7 scale. On the observed distribution the old max was 4/7 — worth re-checking that `>=6` on the new 0–10 scale isn't now effectively unreachable too.

---

## Severity 2 — weakens discrimination

- **Accumulation score has no weighting.** `calculations.py:1001-1050` sums 7 equal binary factors. In the delivered report 410 of 1,053 stocks (39%) sit at exactly the middle bucket. Weinstein's own hierarchy would weight *price above a rising 30WMA* and *positive RS* far above *delivery trend stable*.
- **`rs_ratio` is not Mansfield RS**, despite the docstring (`calculations.py:509`). It's a 52-day ROC difference. Fine as a metric, but the `Improving`/`Weakening` bands use a fixed ±1 percentage-point threshold against its own MA — far too tight for small caps, too loose for large caps.
- **ATR uses close-to-close only** (`calculations.py:638`) because high/low aren't fetched. The `Coiling` squeeze signal therefore misses intraday range compression entirely — the thing a squeeze actually is. `sec_bhavdata_full` contains `HIGH_PRICE`/`LOW_PRICE`; fetching them fixes this *and* issue 1.7.
- **NIFTYBEES as the NIFTY proxy** (`nse_data_fetcher.py:399`) is itself unadjusted and carries tracking error/dividend drag, so every RS number has a small systematic bias.
- **`calculate_weekly_wma` is not idempotent.** If handed a DataFrame that already contains `cross_above`/`weekly_wma30`, the merge at `:134` silently produces `_x`/`_y` columns and downstream reads break. Currently safe only because raw frames are cached — a latent trap.
- **Redundant recomputation:** `excel_generator.py:631-634` instantiates a second `StockCalculator` and re-runs `calculate_summary_counts` per ticker, work already done in the pipeline.
- **First row treated as an up day.** `calculations.py:231` — `.diff().fillna(0) >= 0` counts row 0 as price-up-or-flat.

---

## Dead code

| Location | Item | Note |
|---|---|---|
| `nse_data_fetcher.py:361-384` | `is_fno_stock()` | Never called; F&O comes from `fno_tickers.txt` |
| `calculations.py:156-164` | `is_weekstart`, `weekstart_cross` | Computed every run, read by nothing |
| `calculations.py:981-984` | `dma_200_signal` | Computed, never rendered (only `price_vs_200dma` is) |
| `calculations.py:354-355` | `else: 'Stage 1'` | **Unreachable** — the five preceding branches cover every (sign × slope) combination |
| `excel_generator.py:965-967` | `day_header.font = _FONT_BOLD_SIZE12` | Overwritten on the very next line |
| `main.py:16` | `from pathlib import Path` | Unused (only appears in a docstring) |
| `nse_data_fetcher.py:124,755` | `series` parameter | Accepted and documented but ignored; `'EQ'` is hardcoded at `:236` |
| `config.json` | `exchange`, `weekstart_day` | Zero references in code |
| `config.json` | `delivery_bins.*.max` | Only `min` is read (`calculations.py:203-211`) |
| `config.json` | no `cream` entry | Band exists in code with a hardcoded colour (`excel_generator.py:74`) |
| fetched, never shown | `face_value`, `promoter_pct_prev`, `latest_profit`, `yoy_prev_profit`, `latest_quarter` | `latest_quarter` is broadcast onto every DataFrame row and then discarded |
| repo root | `update_ticker_files.py` | Referenced by no script, shell file or doc |
| repo root | `tickers_backup_20251226.txt` | Orphan snapshot |
| repo root | `stock_screener.log` | 0 bytes, committed |
| `run_screener.sh` | — | Hardcodes `python3 main.py`; silently ignores `--mode`, `--batch-size`, `--skip-financials` |

`weekstart_day: "Monday"` in config is worse than unused — it's actively misleading, since `calculations.py:84` hardcodes `to_period('W-FRI')`.

---

## Suggested order of work

**Do first — these change which stocks you buy:**

1. Corporate-action adjustment, or at minimum a quarantine flag (1.1)
2. Extend history to ~500 trading days (1.2) **and** fix `_process_batch_optimized` so `--mode initial` stops truncating it (1.10)
3. Raise volume confirmation to 2× (1.3)
4. Attach cross flags to week-end rows only; mark mid-week crosses provisional (1.4)

**Do next — data integrity:**

5. Normalise dates at ingestion + one-off cache cleanup (1.9)
6. `pd.to_numeric(errors='coerce')` on quantity columns (1.12); fix MTO record type and stop coercing missing delivery to 0 (1.11)
7. Add an `As Of` column and grey stale rows (1.8)

**Then — signal quality:**

8. Fetch `HIGH_PRICE`/`LOW_PRICE` — fixes both the squeeze calculation and the 52W basis mismatch (1.7, Sev-2)
9. Split `Stage 2 (Pullback)` out (1.5); make the slope deadband configurable and tighter (1.6)
10. Make alert columns window-based rather than last-row-only (1.13)
11. Weight the accumulation score (Sev-2)

**Housekeeping:** delete the dead code above, and regenerate the report so its scoring matches the code (1.17).
