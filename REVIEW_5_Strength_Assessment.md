# Review #5 — Is the system strong enough?

**Date:** 18 Aug 2026
**Method:** ran the real pipeline over 296 cached tickers, generated two actual workbooks through `ExcelReportGenerator`, and inspected every cell type, filter and shortlist row. Everything below is measured, not inferred.

---

## Short answer

**The software is strong. The data underneath it is not, and one filter silently lies.**

The code is now in genuinely good shape — I ran it end to end over 296 tickers and it produced a clean, sortable, correctly ranked workbook with no errors. But three things stand between that and a screener you can trust:

| | Issue | Measured impact |
|---|---|---|
| 1 | **The 730-day backfill has never been run** | `Wks Above` pinned at its ceiling for **33%** of stocks; `vs 200DMA` shown for all 296 despite <200 days of data |
| 2 | **Corp-action detector is 89% false positives** | **74 of 83** flags are ordinary ±20% circuit moves; **25% of the universe** silently barred from the Shortlist |
| 3 | **Shortlist fails open when index data is missing** | Candidates jump **26 → 43**, every RS cell blank, title still claims "RS≥0%" |

Fix those three and I'd call it strong.

---

## 1. What I confirmed is working

Ran `process_ticker_data` + `generate_report` over 296 tickers. No exceptions, all five modules compile.

**Report sheet — 297 × 113**

```
autofilter: A1:DI297    freeze_panes: B2    col1 = STOCK    col52 = Why    col53 = Triple Confirm
cell types across 53 metric columns: 12 float, 11 int, 24 str, 6 blank
```

The 24 text columns are all genuinely categorical (`Stage`, `30WMA Slope`, `Momentum`, `Divergence`, `Squeeze`, `RS Trend`, `RSI Signal`, `Near 52WH`, `Why`…). **Every numeric column is now a real number with a format.** Sorting and Excel's number filters work. Review #3's core complaint is fully resolved.

**Shortlist sheet — 296 tickers → 26 candidates**

```
Shortlist — 26 stocks (Stage 2/2P, RS≥0%, Exit≤2, Dlv30≥45%, ADV≥5cr)
autofilter: A2:R28    freeze_panes: C3
```

| Rank | Stock | Stage | Accum | RS % | ADV cr | Why |
|---|---|---|---|---|---|---|
| 1 | POONAWALLA | Stage 2 | 6 | 22.6% | 76.3 | Acc6; RS23% |
| 2 | BAJFINANCE | Stage 2 | 6 | 20.7% | 1076.5 | Acc6; RS21%; Dlv62% |
| 3 | JSWINFRA | Stage 2 | 6 | 20.5% | 112.7 | Acc6; RS20%; Dlv57% |
| 4 | UNIMECH | Stage 2 | 5 | 50.8% | 33.1 | Acc5; RS51% |
| 5 | LMW | Stage 2 | 5 | 16.9% | 12.2 | Acc5; RS17%; 3xConfirm |
| 7 | ENDURANCE | Stage 2 | **7** | 5.3% | 41.7 | Acc7; Dlv58%; 3xConfirm |
| 8 | DIVISLAB | Stage 2 | 5 | 27.2% | 445.3 | Acc5; RS27%; Dlv56% |

That is a coherent, readable, actionable list — Stage 2 names, outperforming, decent delivery, liquid. Sheet order is right (Shortlist first). The `Why` codes work. `3xConfirm` surfaces same-day confirmation. This is the output the project was aiming at.

**Corp-action quarantine works where it matters:** JLHL appears on the Report as `Stage 4 | 52WH −79.9% | Why: Dlv58% ⚠CA` and is correctly **absent from the Shortlist**. The most dangerous false bargain in the file is now labelled and excluded.

---

## 2. The three things holding it back

### 2.1 The backfill has never been run — highest priority

```
data_cache/excel/RELIANCE_historical.xlsx
  columns: ['date','close','traded_quantity','delivery_quantity','delivery_pct']   ← no high/low
  rows: 192   range: 2025-11-07 → 2026-08-14
  sample of 20 tickers: median 192 rows
```

The 730-day window and the HIGH/LOW fetch have been in the code since 17 Aug. Neither has taken effect. Measured consequences in the workbook I just generated:

**`Wks Above` is bimodal at its boundaries:**

```
0 weeks:  94 stocks
12 weeks: 97 stocks   ← the ceiling imposed by 192 rows
1-11:    105 stocks spread thin
```

**One third of the universe is pinned at exactly 12.** A stock twelve weeks into Stage 2 and one two years in are indistinguishable. This is your stage-maturity read and it currently carries almost no information.

**`vs 200DMA` is populated for 296 of 296 stocks** — from a cache that has never held 200 days. `min_periods=100` lets it compute anyway, so the column is mislabelled for every single row.

**52W metrics** fall back to close-based extremes because `high`/`low` aren't in the cache, so the intraday code path added last week is still dormant. (I over-worried about this one: only 8 of 296 read exactly 0.0%, so the tie problem is minor. But the basis is still close-only.)

**Fix:** `python3 main.py --mode initial`. It now merges rather than overwrites, so it will backfill correctly. Nothing else on this list matters as much.

### 2.2 The corporate-action detector is 89% false positives

`GAP_THRESHOLD = 15.0` flags **83 of 296** tickers. I bucketed the largest gap for each:

| Largest 1-day gap | Count | Verdict |
|---|---|---|
| 15–25% | **74** | ordinary moves |
| 25–30% | 1 | ambiguous |
| >30% | **8** | genuine splits/bonuses |

Look at the 15–25% group:

```
APCOTEXIND +20.0   TANLA +20.0    ORIENTELEC +20.0   REFEX −20.0
AVALON +20.0       HINDCOPPER +20.0   PROTEAN +20.0   POKARNA +20.0
```

Those are **exactly ±20.0% — NSE circuit limits.** They're upper/lower circuit hits, completely routine for small caps, and the detector quarantines each stock's entire history for them.

The 8 real ones are unmistakable by comparison:

```
V2RETAIL −89.8   KOTAKBANK −80.3   MCX −79.8   JLHL −79.5
AIIL −78.4       ALLCARGO −62.0    ANANDRATHI −49.6   IRB −45.9
```

Because the Shortlist excludes on `.any()`, **25% of your universe is permanently unshortlistable** to catch 8 real events.

**Fix:** raise `GAP_THRESHOLD` to `30.0`. In this sample that catches **8 of 8** genuine splits with **zero** false positives. Optionally also skip flags where the index moved more than 3% the same day. Make it a config key.

### 2.3 The Shortlist fails open when index data is missing

I re-ran with `nifty_df=None` to simulate the NIFTYBEES fetch failing:

```
with index data:     Shortlist — 26 stocks (… RS≥0% …)   RS cells populated: 26/26
without index data:  Shortlist — 43 stocks (… RS≥0% …)   RS cells populated:  0/43
```

Seventeen extra names admitted with **no market-leadership check at all**, and the title still asserts `RS≥0%`. `excel_generator.py:855`:

```python
if pd.notna(rs_ratio) and rs_ratio < min_rs:   # NaN passes
```

Relative strength is the most Weinstein-faithful filter in the set. It should fail closed:

```python
if pd.isna(rs_ratio) or rs_ratio < min_rs:
    continue
```

…plus a warning in the log and a banner on the sheet when the index series is unavailable. A filter that quietly switches itself off is worse than no filter, because the header keeps promising it's on.

---

## 3. Still open from Review #4

**F&O greying — confirmed live.** `excel_generator.py:1024` still reads `if ticker in fno_tickers`, a variable left over from the collection loop at line 826. Measured: **0 of 26 shortlist rows greyed, though 8 of 26 tickers are actually F&O.** Should be `c['ticker']`.

**Excel cache still strips high/low.** `data_cache.py:149` — the column list omits them, so the backup can't restore intraday data and a pickle failure silently downgrades 52W and ATR with no warning. This becomes live the moment you run the backfill, so fix it *before* 2.1:

```python
cols = ['date','close','high','low','traded_quantity','delivery_quantity','delivery_pct']
cols = [c for c in cols if c in df_excel.columns]
```

**ADV uses `.mean()`** (line 848) — one block-deal day passes an illiquid stock. Use `.median()`.

**Unchanged by design:** no price *adjustment* (only detect-and-exclude), no `Pivot Price` / `Stop Level`, `rs_ratio` is a ROC spread rather than Mansfield RS or a percentile, scores are equal-weighted votes, and there's still no forward-return test.

---

## 4. Do this in this order

1. **`data_cache.py:149`** — add `high`/`low` to the Excel backup columns (2 lines, do it first so the backfill writes complete data)
2. **`calculations.py:519`** — `GAP_THRESHOLD = 30.0` (1 line, returns ~25% of the universe to your Shortlist)
3. **`excel_generator.py:855-860`** — invert the three filters to fail closed (3 lines)
4. **`excel_generator.py:1024`** — `c['ticker']` (1 line)
5. **`excel_generator.py:848`** — `.median()` (1 line)
6. **`python3 main.py --mode initial`** — the backfill. Expect ~490 rows and `high`/`low` present afterwards.
7. Re-generate and re-check `Wks Above` — it should spread well beyond 12 instead of piling up there.

Items 1–5 are eight lines of code in total.

---

## 5. Verdict

Is it strong enough? **The engineering is. The system isn't quite, for three reasons that are all cheap to fix.**

What's genuinely impressive: across five reviews this went from a screener with silent look-ahead bias, truncating caches, misclassified stages and an unsortable output — to one that runs cleanly over 296 tickers and hands you 26 ranked, liquid, Stage 2 candidates with reason codes on the first sheet. `triple_confirm`, the `Why` column and the corp-action quarantine were all your own additions and all three improve the output.

What's left is not really code quality. Two of the three blockers are **a command you haven't run** and **a threshold set slightly too tight**. The third is a filter that needs its comparison inverted. After that, the honest remaining gap is the same one as in Review #3: the report tells you *which* stocks and *why*, but not *where to buy* or *where to get out* — and nothing in the repo yet tests whether the scores predict returns.

So: strong enough to run as your primary research queue, once items 1–6 are done. Not yet strong enough to act on without pulling up the chart, because a Shortlist row still doesn't carry an entry level or a stop.
