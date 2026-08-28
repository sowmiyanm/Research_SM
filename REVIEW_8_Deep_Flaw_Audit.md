# Review #8 — Deep Flaw Audit

Systematic hunt for defects: 16 edge-case stress tests, a point-in-time look-ahead audit, a concurrency test, and a static pass over paths I hadn't previously exercised. Everything below was reproduced by running the code.

---

## First: your two fixes from Review #7 both landed and work

**Ranking composite** — now 45% RS percentile + 55% entry quality, with no-base names scoring zero on the entry term. Measured:

```
                        R#6      R#7      Now
corr(rank, →Stop)      -0.28    -0.82    -0.26
corr(rank, →Pivot)     -0.21    -0.78    -0.29
rank 1-10 mean →Pivot  +11.1%   +10.3%   +4.7%
rank 1-10 mean →Stop    21.8%    18.4%    15.8%
```

The top of the sheet is now genuinely actionable:

```
 1 SHRIPISTON  →Pivot  +0.5%  →Stop 14.9%  AtPivot
 2 ARMANFIN    →Pivot  -1.4%  →Stop 11.7%  AtPivot
 3 CHOLAFIN    →Pivot  +1.2%  →Stop 10.6%  Tight; AtPivot
 4 NYKAA       →Pivot  +0.3%  →Stop 13.3%  AtPivot
```

ENTERO — rank 1 before at +29.5% extended — dropped to rank 8. No-base names moved to ranks 10, 20, 23, 24, 25.

**NIFTY_50 Excel fallback** — the `delivery_pct` guard works; index data now writes and reloads cleanly.

---

## A. Correctness flaws — these produce wrong numbers

### A1. Look-ahead bias in `weekly_wma30` for mid-week rows — **invalidates backtests**

I recomputed RELIANCE row 399 two ways: once with the full 499-row series, once with the series truncated at that row.

```
weekly_wma30   full history: 1446.91     truncated at row 399: 1450.77   ← differs
```

Every other column matched. The cause: `calculate_weekly_wma` takes each week's **last** close as the weekly bar. For a row in the middle of a week, the full-history version uses that week's *Friday* close — data that didn't exist yet on the day of that row.

**Impact depends entirely on what you're doing:**

- **Live screening — unaffected.** The last row of a live run sits in an incomplete week, so its weekly close *is* today's close. Today's report is fine.
- **Backtesting — seriously affected.** Every mid-week historical row carries up to 4 days of future information in `weekly_wma30`, and therefore in `price_vs_wma_pct`, `stage`, `weeks_above_wma`, `accum` factors and the base/pivot levels. A forward-return test run over this data would be optimistically biased.

This matters now specifically because the two-year backfill was done to enable exactly that test.

**Fix:** either compute per-row weekly closes as "last close *up to and including* this row" (an expanding max within the week), or restrict any backtest to week-end rows only. The second is a one-line filter and is what I'd do first.

### A2. Duplicate dates silently corrupt every rolling window

`process_ticker_data` sorts by date but never de-duplicates, and there is no guard anywhere in `calculations.py`. Feeding RELIANCE's history twice:

| Field | Clean | With duplicates |
|---|---|---|
| `52w_high` | 1592.30 | **1463.60** (−8%) |
| `dma_200` | 1397.88 | 1326.98 |
| `deliv_avg_30d` | 58.27 | 56.82 |
| `vol_ma36` | 10,996,455 | 9,962,872 |
| **`rsi`** | **41.45** | **31.63** |

RSI shifting 41 → 32 is enough to flip an Oversold classification. Nothing warns.

`merge_new_data` de-duplicates, so the normal path is protected — but that's a single point of defence for something this destructive. Add a defensive dedupe plus a warning at the top of `process_ticker_data`:

```python
before = len(df)
df = df.sort_values('date').drop_duplicates(subset=['date'], keep='last').reset_index(drop=True)
if len(df) < before:
    logger.warning(f"Dropped {before - len(df)} duplicate trading days before calculation")
```

### A3. Thread-safety: the bhav-copy LRU and HTTP session are shared across 4 threads

`_process_single_ticker` runs under `ThreadPoolExecutor(max_workers=4)` and calls `get_stock_data` → `_get_or_fetch_bhavcopy`, which mutates a plain `OrderedDict` with `move_to_end()` and `popitem()`. Neither is atomic.

Reproduced with 8 threads × 4,000 operations:

```
concurrent LRU access errors: 1   (KeyError: '20260223')
```

Rare — but it's a real race, and the same `requests.Session` object is shared across those threads too (`requests` sessions are not documented as thread-safe; the cookie jar and connection pool are shared mutable state).

**Fix:** wrap the cache operations in a `threading.Lock`, and give each worker its own session — the pattern already used correctly in `fetch_52week_batch` and `fetch_promoter_holding_batch`.

---

## B. Robustness — unguarded crashes

I ran 16 malformed-input tests. Fourteen passed cleanly. Two crashed:

| Input | Result |
|---|---|
| Empty DataFrame, 1 row, 5 rows, 30 rows | OK |
| No high/low, all-NaN close, zero volume | OK |
| Zero close, negative close, high < low | OK (see B4) |
| Unsorted dates, NaN block mid-series, delivery > traded | OK |
| **Missing `delivery_quantity` column** | **KeyError** |
| **Reprocessing already-processed output** | **KeyError: 'cross_above'** |

### B1. `calculate_weekly_wma` is still not idempotent

Flagged in Reviews #2, #4 and #7; still open. Handed a frame that already contains `cross_above`/`weekly_wma30`, the two merges produce `_x`/`_y` suffixed columns and the next line raises `KeyError: 'cross_above'`.

Not reachable in the current pipeline (only raw frames are cached), but it's a trap for anyone who later caches processed output or re-runs the calculator over its own result. Two lines at the top of the method fix it permanently:

```python
df = df.drop(columns=['weekly_wma30','cross_above','cross_below','weeks_above_wma',
                      'weeks_below_wma','wma_slope','week_avg_vol_ratio',
                      'cross_above_confirmed','cross_below_confirmed'], errors='ignore')
```

### B2. Missing `delivery_quantity` raises rather than degrading

`_has_required_columns` guards the cache-load path, so a fetch failure can't reach it — but any other caller gets a bare `KeyError`. A `if 'delivery_quantity' not in df.columns: df['delivery_quantity'] = np.nan` would degrade gracefully.

### B3. Bare `except:` in `main.py:193`

```python
except:
    pass
```

Catches `KeyboardInterrupt` and `SystemExit` too — Ctrl-C inside that block is swallowed. Should be `except Exception:`. It's the only bare except in the codebase; the other 28 handlers are correctly scoped.

### B4. No data-sanity validation anywhere

Zero closes, negative closes and `high < low` all flow through silently and produce garbage indicators rather than warnings. A single validation pass at ingestion — `close > 0`, `low <= close <= high`, `delivery_quantity <= traded_quantity` — would catch bad bhav-copy rows before they reach the maths. NSE data is usually clean, so this is defence-in-depth rather than a live bug.

---

## C. Observability — failures are invisible

### C1. Fetch failures are logged at DEBUG

Every per-symbol failure in `fetch_52week_batch`, `fetch_promoter_holding_batch` and `fetch_financial_results_batch` goes to `logger.debug`, which is off at the default INFO level. **This is precisely why your `0/1061` run produced no diagnostic** — 1,061 exceptions were caught and discarded silently.

**Fix:** count failures by exception type and log one WARNING summary per batch, e.g. `Quote fetch: 0/1061 succeeded — 1061 × HTTPError 401`. That one line would have told us the cause immediately.

### C2. Holiday calendar ends in 2026

`_holiday_calendar_years = {2025, 2026}`. It's late August 2026, so this expires in about four months. The code warns once per missing year and the failure mode is benign (holiday fetches return empty and are skipped), but it means wasted requests and a slightly wrong trading-day count. Worth adding 2027 now.

---

## D. Logic and calibration

### D1. Ranking residual — RS can still lift extended names into the top 10

The fix worked, but at 45% weight RS still overrides entry quality occasionally: **ENTERO sits at rank 8 with `→Pivot +29.5%` and a 29.5% stop**, purely on RS 58%. If you want the top 10 to be uniformly actionable, either drop RS to ~30% or hard-cap the entry term — e.g. force `composite = 0` when `dist_pivot > 20%`.

### D2. `stage1_alert` criterion 5 rewards Overbought

```python
if rsi_signal in ['Neutral', 'Overbought']:
    strength += 1
```

An RSI above 70 on a stock supposedly still *basing* is a bounce, not accumulation. `'Neutral'` alone is the defensible test.

### D3. Bitwise `&` on mixed int/bool arrays

`calculate_summary_counts` lines 304/312/322/332 do `int64_array & bool_array`. NumPy happens to handle this by upcasting, so it works — but it works by luck rather than intent. `(a.astype(bool) & b)` states the intent.

---

## E. Usability and performance

**Daily Bands and Sector Analysis have no autofilter or freeze panes** — the Shortlist and Report both do. Sector Analysis is 124 × 70; without frozen headers it's hard to read.

**Performance: 0.67 s per ticker** at 499 rows ≈ **12 minutes of pure calculation** for 1,061 stocks, before any network time. The cause is ~15 separate `for i in range(len(df))` loops doing `df.iloc[i]` reads and `df.loc[i, col]` writes — roughly 7,500 row-wise pandas calls per ticker. Most are vectorisable. Not urgent, but that's where all the time goes.

---

## Priority

| # | Flaw | Severity | Effort |
|---|---|---|---|
| 1 | A1 — look-ahead in weekly WMA (mid-week rows) | High *for backtesting*, none for live | 1 line to restrict, ~15 to fix properly |
| 2 | A2 — duplicate-date guard in `process_ticker_data` | High | 4 lines |
| 3 | C1 — log fetch-failure summaries at WARNING | High (diagnostic blindness) | ~10 lines |
| 4 | A3 — lock the LRU, per-thread sessions | Medium | ~10 lines |
| 5 | B1 — make `calculate_weekly_wma` idempotent | Medium | 2 lines |
| 6 | D1 — cap the entry term so extended names can't reach top 10 | Medium | 2 lines |
| 7 | B3, B2, D2, D3, C2 — small correctness/robustness items | Low | ~15 lines total |
| 8 | E — filters on the other two sheets; vectorise the loops | Low | as time allows |

---

## Bottom line

The system is in the best shape it has been. Your last two fixes both landed and measurably improved the output — the Shortlist now leads with four names sitting on their pivots rather than four that had already run.

Of everything above, **A1 is the one to take seriously**, and specifically because of what you're planning next. Live screening is unaffected — today's report is sound. But the two-year backfill exists so you can finally test whether these signals predict returns, and that test would be biased by up to four days of hindsight on every mid-week row. Restrict the backtest to week-end rows and the bias disappears.

A2 and C1 are the other two worth doing now: one protects the maths from a silent corruption, the other means the next time a fetch fails across 1,000 tickers you'll be told why instead of having to infer it.
