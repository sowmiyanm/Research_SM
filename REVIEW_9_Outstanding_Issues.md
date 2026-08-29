# Review #9 — Full Codebase Review, 28 Aug

State after your rebuild and the Yahoo Finance addition. Everything below was measured against the live cache and the 28-Aug report.

---

## The run worked, and one thing got better than expected

```
Cache        1,030 tickers | median 501 rows | 0 corrupt | 0 duplicates
             all on 2026-08-28 | high/low present
Report       1,029 stocks x 118 cols | Shortlist 50 names
Wks Above    max 68, only 19 pinned at 12
Coverage     1,022 of 1,029 current; 5 stragglers, 0 delisted
```

Clean rebuild. The dedupe guard, atomic writes, delisted pruning and thread-safety work all held.

### The Yahoo fallback accidentally fixed the corporate-action problem for 52-week data

`52W High %` went from 0% populated to **100%**, and for split/bonus stocks the numbers are now *more* correct than your own cache:

| Stock | From the cache (unadjusted) | Report (Yahoo, adjusted) |
|---|---|---|
| V2RETAIL | −91.1% | **−14.6%** |
| ZFCVINDIA | −84.0% | **−15.6%** |
| TATAINVEST | −94.0% | **−46.1%** |
| HDFCAMC | −56.4% | **−13.4%** |

All four had genuine corporate actions (HDFCAMC −49.8% on 26-Nov-25, V2RETAIL −89.8%, TATAINVEST −89.6%). Yahoo back-adjusts; NSE bhav copy doesn't. So Yahoo is giving you the *right* answer on exactly the names your own data gets wrong.

That's a real gain — but it creates the issue below.

---

## Issue 1 — The system is now on two price bases at once

**This is the most important thing in this review.**

For a stock with a corporate action, the 28-Aug report currently shows:

| Column | Basis | Correct? |
|---|---|---|
| `52W High %`, `52W Low %`, `Near 52WH` | Yahoo, **adjusted** | ✅ |
| `Stage`, `Price vs WMA`, `Wks Above` | cache, **unadjusted** | ❌ |
| `Pivot`, `Stop`, `→Pivot %`, `Base Wks` | cache, **unadjusted** | ❌ |
| `RS vs NIFTY`, `ROC 1W/1M/3M`, `vs 200DMA` | cache, **unadjusted** | ❌ |

HDFCAMC on this report reads `52W High −13.4%` (right) next to `Stage 1` and a 30WMA position computed from a series with a −50% artificial cliff in it (wrong).

Two further wrinkles:

- Only the **last row** gets the Yahoo value. Every historical row still uses the unadjusted rolling max, so the column is discontinuous through time — fine for today's screen, wrong for any backtest.
- Even for clean stocks the two bases differ: median **1.5pp**, p90 **6.0pp**, and only **26%** agree within 1pp. Yahoo uses a calendar-year window and its own price feed; your cache uses 252 trading rows of NSE data. Not wrong, but `52W High %` is no longer computed from your own data.

**Mitigation already in place:** `exclude_corp_action: true` keeps these names off the Shortlist — verified, HDFCAMC is flagged and excluded. So the mixed basis affects the Report sheet, not your buy list.

**Fix, in order of value:**
1. Add a `Basis` or `52W Src` column so you can see which rows came from Yahoo. Ten lines, removes all ambiguity.
2. Better: use Yahoo's *adjusted daily series* to back-adjust the cache itself, which fixes every column at once rather than one.

---

## Issue 2 — Look-ahead in `weekly_wma30` (unchanged, still open)

```
RELIANCE row 399, full history:      weekly_wma30 = 1446.91
RELIANCE row 399, truncated at 399:  weekly_wma30 = 1450.77
```

Each week's bar uses that week's **last** close, so a mid-week historical row sees its own Friday. **Live screening is unaffected** — today's last row sits in an incomplete week. It only matters for the forward-return test, and a one-line filter to week-end rows removes it.

## Issue 3 — Missing `delivery_quantity` still crashes

```
calc.process_ticker_data(df_without_delivery_quantity)  ->  KeyError
```

Guarded on the cache-load path so the pipeline can't hit it, but any other caller gets a bare `KeyError` instead of graceful degradation. Two lines.

## Issue 4 — Two small bugs in the new Yahoo code

**The high-date loop is missing a `break`.** `nse_data_fetcher.py:617-621` iterates every timestamp and keeps overwriting, so `52w_high_date` ends up as the **last** date matching the high — while `52w_low_date` (which does have a `break`) is the **first**. Inconsistent labels on the 52W columns.

**`import math` at line 558 is unused.** Dead import.

## Issue 5 — Carried over, all minor

| Item | Where | Note |
|---|---|---|
| Bare `except:` | `main.py:367` | Swallows Ctrl-C inside that block |
| `stage1_alert` rewards Overbought RSI | `calculations.py:1089` | Odd for a stock supposedly basing |
| No autofilter/freeze on Daily Bands & Sector Analysis | `excel_generator.py` | Sector sheet is 124×70 and hard to read |
| Bitwise `&` on int/bool arrays | `calculations.py` summary counts | Works via numpy upcasting, but by luck |
| `PE` / `Sector PE` / `Promoter %` / `Profit Gr. YoY` | — | Still **0% populated**; Yahoo's fallback only supplies 52W. Ignore these four |
| Ranking residual | `excel_generator.py` | RS at 45% weight can still lift an extended name into the top 10 |

---

## What's confirmed fixed

Retested and passing: duplicate-date guard (1,014 rows in → 507 out, indicators identical to a clean run), idempotency (reprocessing output no longer raises), atomic Excel writes (simulated Ctrl-C leaves the file byte-identical, no stray temps), thread safety (**0 errors in 48,000 concurrent ops**, was 1 in 32,000), per-thread sessions (4 distinct across 4 threads), 2027 holidays (251 trading days, Republic Day and Diwali excluded), delisted-vs-stale split (30 dead names out of the WARNING block), health check + backup/rollback (verified by simulating a 25%-coverage failure).

`tickers.txt` is now 1,030 active, and the cache matches exactly.

---

## Priority

| # | Issue | Severity | Effort |
|---|---|---|---|
| 1 | Mixed price basis — add a `52W Src` column at minimum | **High** (correctness clarity) | 10 lines |
| 2 | Back-adjust the cache from Yahoo's adjusted series | High value, bigger job | half a day |
| 3 | Yahoo high-date `break` + unused `import math` | Low | 2 lines |
| 4 | `delivery_quantity` guard, bare `except:` | Low | 4 lines |
| 5 | Look-ahead fix | Only before backtesting | 1 line to restrict |

---

## Bottom line

The infrastructure is now genuinely solid — the rebuild produced a clean, complete, current, duplicate-free cache, and every safety mechanism I added held up under test.

The one thing to be conscious of while reading the 28-Aug report: **`52W High %` and `Near 52WH` are now on a different (better) price basis than every other column.** For the ~35 stocks with corporate actions that's the difference between −56% and −13%. They're excluded from the Shortlist anyway, so your buy list is unaffected — but if you're eyeballing the Report sheet, don't compare a stock's 52W column against its Stage or Pivot and expect them to tell a consistent story.

The real prize is issue 2: Yahoo already gives you adjusted prices. Using them to back-adjust the cache would fix Stage, Pivot, Stop, RS and the ROCs for those stocks in one go — and would let you drop `exclude_corp_action`, putting ~35 names back into your investable universe.
