# Review #3 — Can this Excel actually help you pick stocks?

**Date:** 17 Aug 2026
**Question asked:** forget the institutional framing — does the spreadsheet help me choose stocks, and what should change?
**Answer:** the calculations are largely fine. **The spreadsheet itself is the bottleneck.** Almost none of it can be sorted or filtered, and there is no shortlist — so you are eyeballing 1,053 rows across 110 columns to find maybe 20 names.

Fix the six things in Part 5 and this becomes a genuinely fast picking tool. Most of them are 20–40 lines in `excel_generator.py`.

---

## Part 1 — The blocking problem: you can't sort or filter it

I opened `Delivery_Report_2026-08-15.xlsx` and inspected every cell type in a data row.

| Property | Current state |
|---|---|
| Size | 1,063 rows × 110 columns |
| Cell types across the 52 metric columns | **42 text, 8 numbers, 2 blank** |
| AutoFilter | **None** |
| Freeze panes | **None** |
| Conditional formatting rules | **0** (all colour is baked into static fills) |
| Header row | Row 10 (nine rows of band totals sit above it) |
| `STOCK` column | **Column 50** |

### 1.1 Percentages, ratios and scores are stored as text

These are all strings, not numbers:

```
52W High %      "-20.0%"        RS vs NIFTY     "+4.7%"
52W Low %       "+30.2%"        RSI (14)        "52.3"
Price vs 200DMA "+7.1%"         Vol Ratio       "0.7x"
ROC 1W/1M/3M    "+13.2%"        Squeeze Ratio   "1.43"
Deliv Avg 10/30d "49.4%"        Accum Score     "3/6"
Profit Growth   "+1.0%"         Exit Score      "1/7"
```

Because they're text, Excel gives you **no** number filters — no "Greater Than", no "Top 10", no "Between". You cannot ask "show me everything more than 5% above its 200DMA" or "RS above 10%". Those are exactly the questions you'd want to ask.

### 1.2 Worse — a text sort silently returns the wrong stocks

Text sorts character by character. On `52W High %` the actual order Excel produces is:

```
-0.1%, -0.2%, ... -0.9%, -1.0%, -10.0%, -10.1%, ... -19.9%, -2.0%, -2.1%
                            ^^^^^^^^^^^^^^^^^^^^^^^^
                       -10% to -19% land between -1% and -2%
```

So "sort by closest to 52-week high" puts a stock 19% off its high above one that's 2% off. Every percentage column in the report behaves this way. **This is worse than not being able to sort — it looks like it worked.**

### 1.3 The new 0–10 Exit Score sorts backwards

Now that `Exit Score` prints `/10`, a text sort orders it:

```
0/10, 1/10, 10/10, 2/10, 3/10, ... 9/10
             ^^^^^
```

`10/10` — the strongest sell signal in the book — sorts third from the top ascending, i.e. it gets **buried in the middle** of a descending sort. The same will happen to `Accum Score` if it ever reaches 10.

### 1.4 The ticker is in column 50 and nothing is frozen

To read STAGE (col 3) you're at the far left; the ticker is 47 columns to the right. Scroll to the ticker and every metric is off-screen. Scroll to the date grid (cols 51–110) and you've lost both. With no freeze panes there is no way to keep the name visible.

### 1.5 The daily cells pack two facts into one string

Each date cell reads `"58.8% | No"` — delivery percent and the volume flag concatenated. Neither is usable in a formula, a sparkline, or conditional formatting. You can see the colour, but you can't compute with it.

### 1.6 The header is on row 10

Nine rows of band totals plus a merged "Commentary" row sit above the header, so even after adding a filter you'd have to select the range by hand every time, and Excel's "Format as Table" will guess wrong.

---

## Part 2 — There's no shortlist, so the report never finishes the job

The report tells you the state of 1,053 stocks. It never says *which ones to look at*. That last step is the whole point, and it's the one you're doing manually.

Here's what the data you already compute can do. I ran the real calculator over a random 250-ticker sample and applied a Weinstein-faithful funnel:

| Filter | Names left |
|---|---|
| Universe sampled | 244 |
| Drop suspected corporate actions | 183 |
| Traded volume ≥ Rs 5 crore/day | 138 |
| Stage 2 or Stage 2 (Pullback) | 66 |
| Outperforming the index (RS > 0) | 58 |
| Exit score ≤ 2 | 39 |
| 30-day delivery ≥ 45% | **24** |

**244 rows → 24 candidates.** Scaled to your full universe that's roughly 100 names, ranked. Then the top of that list:

| STOCK | Stage | Acc | RS % | 52WH % | Wks | Dlv30 | ADV cr | Exit |
|---|---|---|---|---|---|---|---|---|
| CHOLAFIN | Stage 2 | 5 | 25.5 | −2.4 | 9 | 58.0% | 265.3 | 1 |
| UNIPARTS | Stage 2 | 4 | 33.9 | −1.1 | 12 | 52.4% | 10.6 | 0 |
| POONAWALLA | Stage 2 | 5 | 22.9 | −1.0 | 9 | 48.8% | 55.2 | 0 |
| ALIVUS | Stage 2 | 4 | 30.1 | −0.5 | 12 | 50.7% | 10.8 | 0 |
| JSWINFRA | Stage 2 | 5 | 20.8 | −3.4 | 12 | 57.2% | 101.9 | 0 |
| NAUKRI | Stage 2 | 4 | 30.0 | −3.8 | 7 | 52.2% | 182.9 | 1 |
| SHRIPISTON | Stage 2 | 4 | 27.9 | −0.7 | 12 | 52.1% | 24.4 | 0 |
| GLAXO | Stage 2 | 5 | 20.6 | −0.4 | 7 | 56.5% | 15.9 | 0 |
| AUROPHARMA | Stage 2 | 6 | 11.3 | −2.7 | 12 | 46.8% | 147.0 | 1 |
| NESTLEIND | Stage 2 | 6 | 4.9 | −2.7 | 12 | 59.2% | 296.8 | 2 |

Every one of those numbers already exists in your pipeline. This is a **presentation** gap, not a calculation gap — which is good news, because it's the cheap kind to fix.

*(Note: I used a stand-in index for RS because the NIFTY pickle wouldn't load in my sandbox. Ranking mechanics are what matters here, not the exact RS values.)*

---

## Part 3 — Things that would put the wrong names on your list

Carried forward from review #2, kept short. These matter here because each one corrupts the shortlist.

### 3.1 Your delivery grid is 91% blank — and it's a one-line fix

`volume_ma_multiplier = 2.0` in `config.json` made `is_high_vol` require **twice** the 36-day average volume. That flag drives the colour grid and every delivery count. Measured on 53 tickers:

| | 1.0× | 2.0× (now) |
|---|---|---|
| Coloured cells in the 60-day grid | 17.8% | **4.5%** |
| `Count (≥50% + HighVol)/45` mean | 3.21 | **0.70** |
| `Accum` Factor 6 met | 12 / 53 | **0 / 53** |

Weinstein's 2× rule is about *breakout-week* volume, not daily delivery. Set it back to `1.0` and put 2.0 on `cross_above_confirmed` (`calculations.py:196`), which is still at 1.0.

### 3.2 Corporate-action stocks look like clean buys

`detect_corporate_actions` runs but flags rows *before* the gap — and the report reads the **last** row, so the flag is `'No'`. The columns aren't rendered anywhere either. Result:

| Ticker | Reported | Reality |
|---|---|---|
| HDFCAMC | Stage 1, −54.8% from 52W high | 1:1 bonus; near adjusted highs |
| JLHL | Stage 4, −79.9% | unadjusted split |
| TRENT | Stage 4, −35.6% | unadjusted split |

**These are the most attractive-looking "deep value basing" names in your report and all three are illusions.** For picking stocks this is the most dangerous single defect. Even before proper price adjustment, propagate the flag to the last row and add a `Corp Action` column so you can filter them out.

### 3.3 The cache hasn't been rebuilt, so three columns still lie

`data_cache` is still 192 rows with no high/low. Until you run `python3 main.py --mode initial`:

- `52W High %` is really a 9-month high
- `Price vs 200DMA` isn't a 200DMA
- `Wks Above WMA` is capped at 12 for every stock — so it can't distinguish a fresh Stage 2 from a mature one

Incremental mode only fetches forward; this will not self-heal.

### 3.4 Two silent failures worth knowing about

- **`distribution_alert` Pattern B can never fire.** It reads `vol_spike_down` at `calculations.py:860`, but that column is created at line 919 — later in the same function. Move step 6 above step 3.
- **If the NIFTY fetch fails, RS dies silently for the whole universe.** `rs_ratio` becomes NaN, `RS vs NIFTY` shows `N/A` everywhere, and `accum_score` Factor 7 scores 0 for every stock — so the score is quietly out of 6 while still printing `/7`. Nothing in the report warns you. I hit this in my own harness, which is how I noticed. Log a loud warning and print the index status in the Commentary row.

---

## Part 4 — Two columns that would change how you use this

You have plenty of *description*. What's missing is the two numbers you need to act:

**Where do I buy?** Weinstein buys the breakout through a base's resistance line. Add `Pivot Price` (highest close of the base) and `Distance to Pivot %`. Then "which stocks are within 3% of triggering" becomes a filter instead of a chart-by-chart review.

**Where do I get out?** Add `Stop Level` (below the base, or the 30WMA for a held position) and `Distance to Stop %`. This isn't position-sizing theory — it's so you can reject a setup where the sensible stop is 18% away before you buy it.

Two more that cost almost nothing:

- **`Why`** — a short reason string per row, e.g. `"Cross↑ + RS 25% + Dlv 58%"`. Turns a wall of numbers into something you can scan.
- **`New This Week`** — flag signals that appeared since the last report. Most weeks you only care about what changed, not the standing state of 1,053 stocks.

---

## Part 5 — Concrete fixes, in priority order

### Fix 1 — Write numbers as numbers (biggest single win)

In `_add_ticker_row`, replace the f-string cells with real values plus a display format:

```python
# BEFORE — text, unsortable
ws.cell(row=row, column=11, value=f"{high_52w_pct:+.1f}%")

# AFTER — number that sorts and filters correctly
c = ws.cell(row=row, column=11,
            value=round(high_52w_pct / 100, 4) if pd.notna(high_52w_pct) else None)
c.number_format = '+0.0%;-0.0%'
```

Apply to: 52W High/Low %, RS vs NIFTY, RSI, Vol Ratio, Price vs 200DMA, Profit Growth, ROC 1W/1M/3M, Squeeze Ratio, Deliv Avg 10d/30d.

For the scores, write the integer and put the denominator in the header:

```python
ws.cell(row=header_row, column=summary_col_start + 3, value="Accum Score (of 7)")
ws.cell(row=row, column=summary_col_start + 3, value=int(accum_score))   # 5, not "5/7"
```

Use `None` rather than the string `"N/A"` for missing values — blanks sort and filter cleanly; `"N/A"` poisons a numeric column back into text.

### Fix 2 — Make it navigable

```python
ws.auto_filter.ref = f"A{header_row}:{get_column_letter(last_col)}{last_row}"
ws.freeze_panes = ws.cell(row=header_row + 1, column=2)   # ticker + header always visible
```

And move `STOCK` to **column 1**, shifting everything right by one. Ten minutes of column-index arithmetic, and it fixes the single most annoying thing about using the file.

Move the nine band-total rows to their own small sheet so the header sits on row 1.

### Fix 3 — Add a `Shortlist` sheet

New method in `ExcelReportGenerator`, called from `generate_report`, implementing the Part 2 funnel with thresholds from `config.json`:

```json
"shortlist": {
  "min_adv_crore": 5,
  "stages": ["Stage 2", "Stage 2 (Pullback)"],
  "min_rs": 0,
  "max_exit_score": 2,
  "min_deliv_30d": 45,
  "exclude_corp_action": true,
  "top_n": 50
}
```

Rank by `accum_score` percentile + `rs_ratio` percentile. Put this sheet **first** so it opens on the shortlist, not on 1,053 rows. Add a matching `Watch - Sell` sheet for holdings with `exit_score >= 6` or a confirmed cross below.

### Fix 4 — Split the date cells

Delivery % as a number in the cell, volume flag as **bold** or a cell border rather than concatenated text. Then a colour scale can be a real conditional-formatting rule and the grid becomes computable.

### Fix 5 — Add the decision columns

`ADV (20d) Rs cr`, `Corp Action`, `Pivot Price`, `Distance to Pivot %`, `Stop Level`, `Distance to Stop %`, `Why`.

To make room, retire columns that aren't carrying weight for picking: `Sector PE` (mostly `N/A`), `Squeeze Ratio` (keep the label, drop the number), `Face Value`, and one of the four near-identical 45-day delivery counts.

### Fix 6 — The calculation fixes from Part 3

`volume_ma_multiplier` → 1.0 and 2.0 onto the cross confirmation; corp-action flag onto the last row; reorder `vol_spike_down` before `distribution_alert`; then one `--mode initial` run.

---

## Suggested sequence

| When | Do |
|---|---|
| Next 30 min | `volume_ma_multiplier` → 1.0; 2.0 onto `cross_above_confirmed`; reorder `vol_spike_down` |
| Then | `python3 main.py --mode initial` (backfills 730 days + high/low) |
| Half a day | Fix 1 (numeric cells) + Fix 2 (autofilter, freeze, ticker to col A) |
| Half a day | Fix 3 (Shortlist sheet) — the change you'll feel most |
| After that | Corp Action column, ADV, Pivot/Stop, `Why` |

---

## Bottom line

The analysis engine is in decent shape — the numbers behind this report are mostly right, and after review #2's fixes the data integrity is solid. The problem is that the output is built like a **printed archive**: static colours, text labels, everything visible at once, nothing sortable.

For picking stocks you want the opposite: a short ranked list that opens first, numeric columns you can filter, the ticker always on screen, and a clear reason each name is there. That's Fixes 1–3, and none of it requires touching the calculations.

One caution regardless of what you fix: until corporate actions are properly adjusted, **treat any stock showing a very large negative "52W High %" with suspicion** rather than as a bargain. HDFCAMC, JLHL and TRENT are the three most tempting-looking names in the current file and all three are artifacts.

Happy to implement any of these — I'd suggest Fixes 1–3 together, since they're the ones that change how the file feels to use.
