# Review #7 — After your 28-Aug changes

Ran the current code end-to-end over the full-depth cache (499 rows/stock) and measured the same statistics as Review #6 so the two are directly comparable.

---

## Verdict

**Three good changes, one significant regression.**

Retiring the Exit Score was the right call and was done cleanly. But changing the Shortlist ranking to **100% RS percentile** made the problem I flagged in Review #6 substantially worse, not better.

```
                          Review #6      Now        Direction
corr(rank, →Stop %)         -0.28       -0.82       much worse
corr(rank, →Pivot %)        -0.21       -0.78       much worse
corr(RS, →Pivot %)          +0.75       +0.79       unchanged
```

Negative correlations mean better-ranked names have *worse* entries. It has gone from a mild bias to an almost perfect inverse ranking.

---

## 1. What you changed — and what it did

### Exit Score retired — good call, cleanly done

`calculate_exit_score` is now a documented no-op stub, and both `Exit (of 10)` and `Accum (of 7)` are gone from the Report. No orphan columns left behind, and the individual exit signals (`Cross↓ WMA`, `Distrib Alert`, `Stage 3 Alert`, `Trend Break`, `Dlv Momentum`, `Vol Spike↓`) are still rendered together where you can read them.

This directly addresses my Review #6 finding that the score maxed at 5 while its red alert fired at ≥6 — it never triggered once across 1,060 stocks. Reading the individual columns is more honest than a composite that hid which risk was actually firing.

### `max_exit_score` filter removed — no contamination, verified

Dropping the Exit Score meant losing the `max_exit_score: 2` shortlist filter. I checked whether names with active sell signals now leak onto the buy list:

```
names on the shortlist with Cross↓ WMA = SELL or Stage 3 Alert = Exit Signal:  none
```

Clean. A cross below the 30WMA moves a stock out of Stage 2 in practice, so the stage filter covers it. No action needed.

### `trend_break` Lower High threshold 2% → 5%

Sensible. A 2% lower high over a 20-day window fires on routine intra-Stage-2 consolidation. Your comment explains the reasoning and it's right.

### Shortlist columns improved

`Accum` and `Exit` replaced with `Cross` and `Diverge`. Better — those are observable facts rather than opaque composites.

---

## 2. The regression: ranking is now an almost perfect inverse

The composite became:

```python
composite = rank_rs                      # RS percentile, 0-100
if cross_confirmed:  composite += 12
elif cross_above:    composite += 8
if triple_confirm:   composite += 5
```

The logic is defensible in isolation — RS is Weinstein's core "buy market leaders" rule, and a fresh confirmed cross deserves a bump. **But relative strength correlates +0.79 with "has already run past its pivot."** Previously RS was only half the composite and `accum_score` partially decorrelated it. Making RS the sole base removed that dampening.

Measured on the current code (n=20 shortlisted names with levels):

| | mean `→Pivot %` | mean `→Stop %` |
|---|---|---|
| **Rank 1–10** | **+10.3%** (extended) | **18.4%** (wide) |

The top of the sheet:

```
 1 ENTERO      RS 58%   →Pivot +29.5%   →Stop 29.5%   Ext29%; Risk30%
 2 OPTIEMUS    RS 37%   no base
 3 PRICOLLTD   RS 36%   →Pivot +13.7%   →Stop 19.3%   Risk19%
 4 GLAND       RS 32%   →Pivot +12.7%   →Stop 20.9%   Risk21%
 5 ALIVUS      RS 31%   →Pivot +16.2%   →Stop 17.5%   Ext16%; Risk17%
...
 9 SHRIPISTON  RS 22%   →Pivot  +0.5%   →Stop 14.9%   AtPivot
10 ARMANFIN    RS 21%   →Pivot  -1.4%   →Stop 11.7%   AtPivot
```

**Rank 1 is 29.5% past its buy point with a 29.5% stop** — the worst reward-to-risk on the sheet, listed first. The two names actually sitting at their pivots are ranked 9th and 10th. Only 6 of 20 have a stop inside 10%.

The bonuses aren't rescuing it: no top-10 name has `Cross↑` or `3xConfirm` in its `Why`, so in practice the ranking is a near-pure sort by RS.

**Fix — add a risk term back, and make it the tiebreaker RS can't override:**

```python
# risk_pct: 100 = at pivot with a tight stop, 0 = extended with a wide stop
entry_score = 0.0
if pd.notna(c['dist_pivot']):
    entry_score += max(0, 100 - abs(c['dist_pivot'] - 1.5) * 8)   # peak near +1.5%
if pd.notna(c['dist_stop']):
    entry_score += max(0, 100 - c['dist_stop'] * 5)               # 20% stop -> 0
    entry_score /= 2

c['composite'] = 0.45 * c['rank_rs'] + 0.55 * entry_score
```

Names with no base should score 0 on the entry term rather than being ranked on RS alone — 5 of 25 currently have no `Pivot`/`Stop` at all yet occupy ranks 2 and 8.

---

## 3. New finding: NIFTY_50 has no working backup

`save_ticker_data` unconditionally computes `delivery_pct` from `traded_quantity` / `delivery_quantity`. Index data has neither, so the Excel write throws and is swallowed by the `except`:

```
Error saving Excel cache for NIFTY_50: 'traded_quantity'
excel written: False
```

Confirmed on disk — `data_cache/NIFTY_50.pkl` exists, `data_cache/excel/NIFTY_50_historical.xlsx` does not.

That makes the index series a **single point of failure with no fallback**. And it matters more now than it used to: with the ranking based entirely on RS, losing NIFTY doesn't just blank one column — every candidate gets `rank_rs = 50` and the entire ordering collapses to insertion order plus bonuses. I hit exactly this in my first run here (the pickle wouldn't load in my sandbox) and the top 10 came out effectively arbitrary, with `RS 0%` on every row.

The red banner does fire, so it's visible. But the fix is three lines:

```python
if 'traded_quantity' in df_excel.columns and 'delivery_quantity' in df_excel.columns:
    df_excel['delivery_pct'] = ...
else:
    df_excel['delivery_pct'] = np.nan
```

---

## 4. Performance note

Measured **0.67 s per ticker** for `process_ticker_data` at 499 rows — about **12 minutes of pure calculation** for 1,061 stocks, before any network time.

The cause is ~15 separate `for i in range(len(df))` loops, each doing `df.iloc[i]` reads and `df.loc[i, col]` writes — roughly 7,500 row-wise pandas operations per ticker. Most are vectorisable (`np.where`, `.shift()`, boolean masks). Not urgent, but if run time starts bothering you, that's where it all is.

---

## 5. Everything else still holds

Re-verified as working: cache at 499 rows with high/low, dates normalised, corporate-action quarantine at 30%, fail-closed shortlist filters, RS-outage banner, median ADV, stop-below-price invariant, sheet order, autofilter and freeze panes on both sheets, numeric cells throughout.

Still open from earlier reviews, unchanged:
- Four fundamental columns still empty (NSE API fetch)
- 38 dead tickers in `tickers.txt` (GENSOL, ZOMATO, ISEC, HIL…)
- `top_n: 50` truncating (129 passed the filters on the 18-Aug run)
- No market-regime gate, no cross-sectional RS percentile, no forward-return test

---

## Priority

| # | Action | Effort |
|---|---|---|
| 1 | Add the entry/risk term back into the shortlist composite (§2) | ~15 lines |
| 2 | Guard `delivery_pct` in `save_ticker_data` so NIFTY gets a backup (§3) | 3 lines |
| 3 | Rank names with no base last rather than on RS alone | 2 lines |
| 4 | Raise `top_n`, clean the 38 dead tickers | 5 min |

Item 1 matters most. Right now, if you sort the Shortlist by Rank you are systematically looking at the worst entries first — more so than before the change. **Until it's fixed, ignore Rank and sort by `→Stop %` ascending**, which is the same workaround as Review #6 but now more necessary.

---

## Bottom line

Retiring the Exit Score was correct and well executed — you removed a composite that provably never fired rather than patching it, and the columns it left behind are more informative than the number it replaced.

The ranking change went the wrong way. The instinct — "RS is Weinstein's core rule, so rank by it" — is sound Weinstein but wrong as a *sort key*, because by the time a stock has high RS it has usually already moved. RS belongs in the **filter** (which it is, at `min_rs: 0`) and entry quality belongs in the **sort**. Put the risk term back and this becomes the best version of the system so far.
