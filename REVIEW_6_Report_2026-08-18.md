# Review — Delivery_Report_2026-08-18

First report built on the full two-year cache. Reviewed against the previous 192-row run.

---

## Headline

**The backfill worked. Everything I said would come back online did.**

But the run surfaced one problem I couldn't see before, and it's the most important finding in this review: **the Shortlist ranking is pointing at the worst entries.** The names at the top are the most extended with the widest stops; the one genuinely clean setup is ranked 43rd.

---

## 1. What the backfill fixed — confirmed

Cache: **1,060 stocks, median 499 rows, `high`/`low` present**, RELIANCE spanning 19-Aug-2024 → 14-Aug-2026.

| Column | Before (192 rows) | Now (499 rows) |
|---|---|---|
| `Wks Above` max | **12** (capped) | **66** |
| stocks pinned at exactly 12 | 97 of 296 (33%) | **18 of 1,060 (1.7%)** |
| `52W High %` | 9-month, close-based | true 252-day from intraday, 1,060/1,060 populated, median −18.3% |
| `vs 200DMA` | fake (<200 days) | real, median +3.4% |
| `Sqz Ratio` | close-to-close TR | Wilder TR, median 0.98 |
| `Base Wks` max | 36 (capped) | **52** |

`Wks Above` now ranges 0 → 66 and the 421 stocks reading 0 are exactly the 420 currently below their 30WMA (Stage 1 + 4 + Pullback). That's correct behaviour, not a bug.

Also working as intended: `Vol Conf` now shows **36 of 116** crosses passing the 2× volume bar (31%), down from 63% at the old 1.0× threshold. The tightened gate is doing its job.

---

## 2. The ranking is upside down — fix this first

The composite ranks by `accum_score` percentile + `rs_ratio` percentile. The problem is that **relative strength is close to a proxy for "has already run"**:

```
corr(RS %, →Pivot %)  = +0.75
```

That's not a subtle relationship. High RS almost mechanically means the stock is already well past its breakout point. Since RS is half the ranking, the consequence is direct:

| | mean `→Pivot %` | mean `→Stop %` |
|---|---|---|
| **Rank 1–10** | **+11.1%** (extended) | **21.8%** (wide) |
| **Rank 30+** | +5.7% | 16.4% |

```
corr(rank, →Stop %)  = -0.28
corr(rank, →Pivot %) = -0.21
```

Both negative — better-ranked names have *worse* risk. Concretely, from this report:

- **Rank 1, SUNDRMFAST** — RS +41%, but **15.4% past its pivot with a 26.3% stop.** The worst risk/reward on the sheet is ranked first.
- **Rank 43, EICHERMOT** — −1.5% from its pivot with a **9.8% stop**. The only name on the entire sheet that is both at a buy point and inside 10% risk, and it's near the bottom.

Across all 50: **median stop 16.0%**, only **2 of 50 inside 10%**, 17 of 50 inside 15%.

**Fix:** add a risk term to the composite. Something like

```
composite = 0.4 × accum_pct + 0.3 × rs_pct + 0.3 × risk_pct
```

where `risk_pct` rewards small `→Stop %` and proximity to the pivot. Or simply demote anything with `→Pivot % > 10%` or `→Stop % > 15%`. Either way, stop letting RS alone drive the top of the sheet.

**Until then:** ignore the Rank column and sort the Shortlist by `→Stop %` ascending.

---

## 3. Other findings from this run

### `top_n: 50` is truncating a lot
**129 stocks** passed stage + RS + exit + delivery + no-corp-action, before the liquidity filter. The sheet shows 50. You're seeing well under half of what qualified — and because of §2, you're seeing the *most extended* half. Raise `top_n` to 100+ or tighten the filters so the cap stops binding.

### 11 of 50 have no identifiable base
STYLEBAAZA, SUDARSCHEM, POONAWALLA, COSMOFIRST, GLAXO, POLYMED, HUHTAMAKI, ASKAUTOLTD, STLTECH, NILKAMAL, FIVESTAR — blank `Pivot`, `Stop`, `Base Wks`. Honest (no base was found), but they occupy slots at ranks 3, 11, 15 and can't be acted on with a level. Consider requiring a base for shortlist entry, or sorting them last.

### 38 tickers are stale — several are dead
`As Of` is doing its job. Oldest:

```
GENSOL     18-Mar-2025      ZOMATO   08-Apr-2025      ADORWELD  09-Apr-2025
ISEC       21-Mar-2025      HIL      08-Apr-2025      SUVENPHAR 16-May-2025
```

These aren't data failures — they're **delisted, suspended or renamed** (ZOMATO became ETERNAL; GENSOL was suspended; ISEC delisted after its buyback). Clean them out of `tickers.txt`; they're consuming fetch time and cache space for nothing.

### Fundamentals: still 0.0% on all four
`PE`, `Sector PE`, `Promoter %`, `Profit Gr. YoY` — confirmed dead on a fresh run, matching the `0/1061` you saw in the log. Not transient. Ignore these four until the API fetch is debugged.

### Exit score: red alert fired zero times out of 1,060
```
exit_score distribution: 0:66  1:206  2:283  3:285  4:179  5:41
maximum observed: 5        red alert threshold: >= 6
```
Exactly as predicted. The column is labelled "of 10", the practical ceiling is 5, and the red highlight is unreachable. **Do not use it as a sell trigger** — use `Cross↓ WMA` and your stop.

### Accum score clustering confirmed at full scale
```
0:4  1:57  2:110  3:202  4:361  5:239  6:73  7:14
```
**57% at 4 or 5.** The two near-constant factors are still flattening the middle. The 6–7 band (87 stocks) is meaningful; 3–5 isn't a ranking.

### Two RS outliers worth a manual look
- **STLTECH: +153% in 52 days**, largest single day +29.4% — that sits just under the 30% corp-action threshold, so it wasn't flagged. Could be genuine (the stock has had news) or an unadjusted action. Check the chart before trusting its RS.
- **HUHTAMAKI: +66% in 52 days**, largest day 12.6% — no gap, so probably genuine, but that RS is an outlier driving its rank-30 placement on `Acc4` alone.

---

## 4. How to use *this* report today

1. Open **Shortlist**, ignore `Rank`, **sort by `→Stop %` ascending**
2. Keep rows where `→Pivot %` is between −2% and +5% — that's your entry window
3. Check `As Of` reads 14-Aug-2026
4. Prefer `Base Wks` ≥ 10 and a `Why` containing `3xConfirm` or `Cross↑Vol`
5. Skip anything tagged `Ext__%` or `Risk__%` — those tags exist to warn you off

On this report that process yields a very short list. **EICHERMOT** (−1.5% from pivot, 9.8% stop, Acc6, Dlv 56%, 45-week base) is the standout. **MAHLOG** has the tightest stop at 7.5% but sits 8.4% *below* its pivot, so it hasn't triggered. **JSWINFRA, NYKAA, CHOLAFIN, MEDANTA, HAL, SUPRAJIT** are at their pivots with 13–14% stops — acceptable if you size for it.

---

## 5. Priority fixes

| # | Fix | Effort |
|---|---|---|
| 1 | Add a risk term to the shortlist composite (§2) | ~20 lines |
| 2 | Raise `top_n` to 100, or require a base for entry | 1 line |
| 3 | Remove the 38 dead tickers from `tickers.txt` | 5 min |
| 4 | Re-weight the exit score; drop the alert threshold to 4 | ~20 lines |
| 5 | Debug the NSE fundamental fetch (headers/Referer) | 30 min |
| 6 | Tighten or drop the two near-constant accum factors | ~10 lines |

Item 1 matters most. Right now the sheet's own ranking is steering you toward the trades with the worst reward-to-risk, and the columns that would tell you so — `→Pivot %` and `→Stop %` — sit at the far right where they're easy to miss.

---

## Bottom line

The data foundation is now genuinely solid: two years of intraday-accurate history, 1,060 stocks, every depth-dependent column working, dates clean, corporate actions quarantined. That was the hard part and it's done.

What's left is that the **ranking hasn't caught up with the risk columns we added.** The system knows how to compute a good entry — it just isn't sorting by it yet. Fix the composite and this becomes a genuinely reliable weekly screen. Until then it's reliable *as a filter* and misleading *as a ranking*, which is a much easier thing to work around: sort by `→Stop %` yourself.
