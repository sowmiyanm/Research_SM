# Column Reliability Guide

Which columns to trust, which to discount, and why. Based on measured behaviour, not opinion.

---

## QUICK REFERENCE — after the first full run

Once `--mode initial` has given you ~490 rows per stock with intraday high/low.

### Trust these (18)

**Screen with them**
`STAGE` · `Price vs WMA` · `30WMA Slope`\* · `Wks Above` · `Wks Below`
`Cross↑` · `Vol Conf` · `Vol Ratio`
`52W High %` · `52W Low %` · `Near 52WH` · `vs 200DMA`
`RS vs NIFTY` (sign only) · `Dlv 30d` · `Dlv 10d` · `ADV cr`

**Act on them**
`Pivot` · `→Pivot %` · `Stop` · `→Stop %` · **`Cross↓ WMA`**

**Always check**
`As Of` — greys out when the row is stale

### Supporting, useful but secondary (7)
`ROC 1W/1M/3M` · `Momentum` · `RSI (14)` · `RSI Signal` · `Base Wks` · `Squeeze` / `Sqz Ratio` · the `N≥50%` / `N≥40%` count columns · `Why`

### Still ignore after the run (14)
`PE Ratio` · `Sector PE` · `Promoter %` · `Profit Growth YoY` — API failures, not a depth issue
`Exit Score` · `Accum Score` 3–5 band · `Dlv Trend` — mis-calibrated
`Dlv Momentum` · `vs 10MA` — redundant
`Divergence` · `Vol Spike↓` — single-day
`Stage 1 Alert` · `Stg1 Str` · `RS Trend` — construction issues

\* `30WMA Slope` reads *Flat* for anything moving less than ±2% over 4 weeks. Tighten via `wma_slope_threshold_pct` if you want it more sensitive.

**Verify the depth actually landed before relying on the first group:**

```bash
python3 -c "import pandas as pd; d=pd.read_excel('data_cache/excel/RELIANCE_historical.xlsx'); print(len(d), list(d.columns))"
```

Want ~490 rows with `high` and `low` present. Then check `Wks Above` on the Report spreads across the range instead of piling up at 12.

---

## Ignore entirely — these columns are empty

Fill rate in your last real run (`Delivery_Report_2026-08-15.xlsx`, 1,053 stocks):

| Column | Populated |
|---|---|
| PE Ratio | **0.0%** |
| Sector PE | **0.0%** |
| Promoter % | **0.0%** |
| Profit Growth YoY | **3.1%** |

These come from three NSE endpoints — `quote-equity`, `corp-info?corpType=shp`, and the XBRL filings — and all three failed for essentially the entire universe. The code handles them correctly; the fetches simply aren't returning data. Likely a cookie/rate-limit/blocking issue against NSE.

**Action:** ignore these four completely. They're not unreliable, they're blank. If you want them, the fetch needs debugging — start by calling `fetch_52week_batch` on 5 tickers and printing the raw response.

Note this also means **Near 52WH and the 52W columns fall back entirely to the rolling calculation**, since the NSE 52-week snapshot arrives through the same failed call.

---

## Ignore until you run the backfill

These are wrong *right now* purely because the cache holds 192 days instead of ~490. All become reliable after `--mode initial`.

| Column | What's wrong today |
|---|---|
| **Wks Above** / **Wks Below** | Hard-capped at 12. Measured: 94 of 296 stocks read 0, **97 read exactly 12**. Carries almost no information |
| **52W High %** / **52W Low %** | It's a ~9-month high, computed from closing prices, not a 52-week high from intraday extremes |
| **Near 52WH** | Derived from the above, so inherits the error |
| **vs 200DMA** | Shown for every stock, computed from under 200 days (`min_periods=100` lets it through) |
| **Squeeze** / **Sqz Ratio** | ATR uses close-to-close only — no intraday range, which is the thing a squeeze actually measures |
| **Base Wks** | Capped near 36 weeks; should reach 52 |

---

## Discount as signals — mis-calibrated

| Column | Measured problem |
|---|---|
| **Exit Score** | Mis-weighted. Three of ten factors all measure "delivery is falling" (correlations +0.61, +0.47, +0.44). Being below a 10-day MA (true 61% of the time) scores the same as a confirmed close below the 30WMA (6.5%) — the primary Weinstein sell trigger. And the red alert fires at ≥6 when the maximum ever observed across 197 stocks' full history was 6, reached by 9 of them. **Do not use as a sell trigger.** |
| **Accum Score** (middle range) | Two factors fire for ~85% of stocks, so everything starts at ~1.7 points. **65% of the universe lands on 4 or 5** — reading 5 as better than 4 isn't supported. The 6–7 band is meaningful; 3–5 is mush |
| **Dlv Trend** | In your real run: 555 Stable, 311 Increasing, 183 Decreasing. **82% read Increasing-or-Stable**, so it barely discriminates |

---

## Don't count twice — redundant

| Column | Overlaps with |
|---|---|
| **Dlv Momentum** | **Divergence** — correlate **+0.61**. Both reduce to "delivery is falling". Pick one |
| **vs 10MA** | True 61% of the time. It's a fact about today, not a signal. Fine as context, don't weight it |

---

## Read as one day, not a trend

These describe a single trading day. They sit next to 45-day counts, which invites reading them as a regime.

- **Divergence** — one 20-day comparison, evaluated today only
- **Vol Spike↓** — literally yesterday-to-today
- **Triple Confirm** — genuinely useful, but it means "all three aligned *today*". A blank tomorrow doesn't mean the setup broke

---

## Treat with caution — construction issues

| Column | Concern |
|---|---|
| **Stage 1 Alert** / **Stg1 Str** | Fires for **20% of the universe** (209 of 1,053) — too broad for a "special situation" flag. Its RSI criterion awards a point when RSI is *Overbought*, which is strange for a stock supposedly still basing |
| **30WMA Slope** | The ±2% band is measured over 4 weeks. A steady 0.4%/week advance (~23%/yr) reads as **Flat**, which routes an advancing stock into Stage 1 or Stage 3. Configurable via `wma_slope_threshold_pct` if you want it tighter |
| **RS Trend** | Improving/Weakening uses a fixed ±1 percentage-point band against its own MA — too tight for small caps, too loose for large caps |
| **RS vs NIFTY** | The **sign** is trustworthy (outperforming or not). The **magnitude is not comparable across stocks** — it's an absolute 52-day ROC spread, not a percentile, so +12% doesn't tell you whether that's top-decile. Also benchmarked against NIFTYBEES (an ETF), not the index itself |

---

## The reliable core — use these

Everything below is measured-sound and, where relevant, verified by invariant checks.

**Identity & freshness**
`STOCK` · `MCAP` · `SEGMENT` · **`As Of`** (greys out when stale — always check it)

**Trend / stage — the backbone**
`STAGE` · `Price vs WMA` · `Cross↑` · `Vol Conf` (2× confirmed) · `Vol Ratio`

**Entry & exit — the actionable pair**
`Pivot` · `→Pivot %` · `Stop` · `→Stop %`
Verified across 146 stocks: zero cases of a stop above the entry price, median risk 10%.

**The real sell signal**
**`Cross↓ WMA`** — this, and your stop being hit. Not the exit score.

**Momentum & participation**
`ROC 1W/1M/3M` · `Momentum` · `RSI (14)` · `RSI Signal` · `Dlv 10d` · `Dlv 30d` · the `N≥50%`/`N≥40%` count columns

**Shortlist-only**
`Rank` · `ADV cr` (median-based, so a single block deal can't inflate it) · `Why`

---

## One-line workflow

Open the **Shortlist**. The filters that got a name onto it — stage, RS sign, exit ≤ 2, delivery, liquidity, corp-action exclusion — are trustworthy. Sort by **`→Pivot %`** and look at names between −2% and +5% with **`→Stop %`** under 10%. Check **`As Of`** is current. Pull up a weekly chart before buying. Sell on **`Cross↓ WMA`** or your stop.

Ignore the four fundamental columns, discount the exit score, and don't read Accum 4 vs 5 as a difference.
